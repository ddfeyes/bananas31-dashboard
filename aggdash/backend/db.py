"""SQLite schema and helper utilities for aggdash."""
import logging
import sqlite3
import time
from pathlib import Path

from config import DB_PATH

logger = logging.getLogger(__name__)

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS exchanges (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS price_feed (
    exchange_id TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    UNIQUE(exchange_id, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_price_feed ON price_feed(exchange_id, timestamp);

CREATE TABLE IF NOT EXISTS trades (
    exchange_id  TEXT NOT NULL,
    timestamp    REAL NOT NULL,
    side         TEXT,
    price        REAL,
    amount       REAL,
    buyer_maker  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_trades ON trades(exchange_id, timestamp);

CREATE TABLE IF NOT EXISTS oi (
    exchange_id   TEXT NOT NULL,
    timestamp     REAL NOT NULL,
    open_interest REAL,
    funding_rate  REAL
);
CREATE INDEX IF NOT EXISTS idx_oi ON oi(exchange_id, timestamp);

CREATE TABLE IF NOT EXISTS dex_price (
    timestamp     REAL NOT NULL,
    price         REAL,
    liquidity     REAL,
    deviation_pct REAL
);

CREATE TABLE IF NOT EXISTS funding_rates (
    exchange_id TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    rate_8h     REAL,
    rate_1h     REAL
);

CREATE TABLE IF NOT EXISTS liquidations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    source    TEXT,
    symbol    TEXT,
    side      TEXT,
    quantity  REAL,
    price     REAL
);

CREATE TABLE IF NOT EXISTS alerts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      REAL NOT NULL,
    kind           TEXT NOT NULL,  -- 'signal' | 'pattern'
    name           TEXT NOT NULL,
    severity       TEXT,
    message        TEXT,
    value          REAL,
    sent_telegram  INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp DESC);

CREATE TABLE IF NOT EXISTS signal_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    signal_id   TEXT NOT NULL,
    direction   TEXT,  -- 'short' | 'long' | null
    severity    TEXT,
    value       REAL,
    message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_signal_history_timestamp ON signal_history(timestamp DESC);

INSERT OR IGNORE INTO exchanges VALUES
    ('binance-spot',    'Binance Spot',        1),
    ('binance-perp',    'Binance Perp',        1),
    ('bybit-spot',      'Bybit Spot',          1),
    ('bybit-perp',      'Bybit Perp',          1),
    ('bsc-pancakeswap', 'BSC PancakeSwap V3',  1);
"""


def init_db() -> None:
    """Create schema if it doesn't exist."""
    conn = get_db()
    try:
        conn.executescript(DDL)
        conn.commit()
        logger.info("DB initialised at %s", Path(DB_PATH).resolve())
    finally:
        conn.close()


def get_db() -> sqlite3.Connection:
    """Return a new sqlite3 connection with row_factory set."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def record_signal_history(signal_id: str, direction: str | None, severity: str, value: float | None, message: str) -> None:
    """Record a signal event to signal_history table."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO signal_history (timestamp, signal_id, direction, severity, value, message) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), signal_id, direction, severity, value, message)
        )
        conn.commit()
    finally:
        conn.close()


def log_alert(
    kind: str, name: str, severity: str, message: str,
    value: float = None, sent_telegram: bool = False,
    dedup_window_secs: int = 1800,  # align with _ALERT_COOLDOWN_SECS in main.py
) -> bool:
    """Persist a fired alert to the alerts table.

    Deduplication: skip INSERT if an identical (kind, name) alert was already
    logged within `dedup_window_secs` seconds. Returns True if inserted, False if skipped.
    """
    import time as _time
    now = _time.time()
    conn = get_db()
    try:
        # Check for recent duplicate
        recent = conn.execute(
            "SELECT id FROM alerts WHERE kind=? AND name=? AND timestamp>=? LIMIT 1",
            (kind, name, now - dedup_window_secs),
        ).fetchone()
        if recent:
            return False  # duplicate suppressed

        conn.execute(
            "INSERT INTO alerts(timestamp, kind, name, severity, message, value, sent_telegram) VALUES (?,?,?,?,?,?,?)",
            (now, kind, name, severity, message, value, 1 if sent_telegram else 0),
        )
        conn.commit()
        return True
    except Exception as exc:
        logger.warning("log_alert failed: %s", exc)
        return False
    finally:
        conn.close()


def get_last_alert_ts(name: str, kind: str = None) -> float:
    """Return the timestamp of the most recent alert with this name, or 0 if none."""
    conn = get_db()
    try:
        if kind:
            row = conn.execute(
                "SELECT MAX(timestamp) FROM alerts WHERE name=? AND kind=?",
                (name, kind),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT MAX(timestamp) FROM alerts WHERE name=?",
                (name,),
            ).fetchone()
        return row[0] or 0.0
    except Exception:
        return 0.0
    finally:
        conn.close()


VALID_INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def get_latest_ohlcv(exchange_id: str, minutes: int = 60, interval: str = "1m") -> list:
    """Return recent OHLCV bars for the given exchange from price_feed.

    If interval != '1m', bars are resampled with SQL aggregation so that
    the response stays below ~1500 rows regardless of timeframe.
    """
    import time
    cutoff = time.time() - minutes * 60
    interval_secs = VALID_INTERVALS.get(interval, 60)

    conn = get_db()
    try:
        if interval_secs == 60:
            # Raw 1-minute bars — no resampling needed
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM price_feed "
                "WHERE exchange_id = ? AND timestamp > ? ORDER BY timestamp",
                (exchange_id, cutoff),
            ).fetchall()
            return [dict(r) for r in rows]

        # Resampled bars using a single-pass CTE with ROW_NUMBER() window functions.
        # This avoids O(n²) correlated subqueries and runs in O(n log n) via the index.
        # SQLite ≥ 3.25 supports window functions; production uses 3.46.1.
        sql = """
            WITH bucketed AS (
                SELECT
                    CAST(timestamp / :iv AS INTEGER) * :iv AS bucket,
                    open, high, low, close, volume,
                    ROW_NUMBER() OVER (
                        PARTITION BY CAST(timestamp / :iv AS INTEGER)
                        ORDER BY timestamp ASC
                    ) AS rn_first,
                    ROW_NUMBER() OVER (
                        PARTITION BY CAST(timestamp / :iv AS INTEGER)
                        ORDER BY timestamp DESC
                    ) AS rn_last
                FROM price_feed
                WHERE exchange_id = :eid
                  AND timestamp > :cutoff
            )
            SELECT
                bucket                                          AS ts,
                MAX(CASE WHEN rn_first = 1 THEN open  END)     AS open,
                MAX(high)                                       AS high,
                MIN(low)                                        AS low,
                MAX(CASE WHEN rn_last  = 1 THEN close END)     AS close,
                SUM(volume)                                     AS volume
            FROM bucketed
            GROUP BY bucket
            ORDER BY bucket
        """
        rows = conn.execute(sql, {"eid": exchange_id, "iv": interval_secs, "cutoff": cutoff}).fetchall()
        return [{"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
                for r in rows]
    finally:
        conn.close()


def get_latest_oi_history(exchange_id: str, limit: int = 200) -> list:
    """Return recent OI history for the given exchange from oi table."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT timestamp, open_interest AS oi FROM oi "
            "WHERE exchange_id = ? ORDER BY timestamp DESC LIMIT ?",
            (exchange_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()

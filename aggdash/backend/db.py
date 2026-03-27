"""SQLite schema and helper utilities for aggdash."""
import logging
import sqlite3
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

        # Resampled bars: bucket timestamps, aggregate OHLCV within each bucket.
        # open  = first close in bucket (SQLite has no FIRST aggregate; use MIN(rowid) subquery)
        # close = last close in bucket (MAX rowid)
        # SQLite doesn't have FIRST/LAST, so we use a correlated subquery trick.
        sql = """
            SELECT
                CAST(timestamp / :iv AS INTEGER) * :iv   AS ts,
                (SELECT p2.open FROM price_feed p2
                 WHERE p2.exchange_id = :eid
                   AND CAST(p2.timestamp / :iv AS INTEGER) * :iv = CAST(p.timestamp / :iv AS INTEGER) * :iv
                 ORDER BY p2.timestamp ASC LIMIT 1)       AS open,
                MAX(high)                                  AS high,
                MIN(low)                                   AS low,
                (SELECT p2.close FROM price_feed p2
                 WHERE p2.exchange_id = :eid
                   AND CAST(p2.timestamp / :iv AS INTEGER) * :iv = CAST(p.timestamp / :iv AS INTEGER) * :iv
                 ORDER BY p2.timestamp DESC LIMIT 1)       AS close,
                SUM(volume)                                AS volume
            FROM price_feed p
            WHERE exchange_id = :eid
              AND timestamp > :cutoff
            GROUP BY CAST(timestamp / :iv AS INTEGER)
            ORDER BY ts
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

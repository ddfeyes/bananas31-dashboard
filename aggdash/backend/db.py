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
    volume      REAL
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

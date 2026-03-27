"""
backfill.py — Historical OHLCV backfill for bananas31-dashboard.

Fetches 1-minute klines from Binance spot, Binance perp, Bybit perp
and inserts into price_feed table (INSERT OR IGNORE — safe to re-run).

Usage (inside container or directly):
    python3 backfill.py [--db /path/to/db] [--days 365] [--interval 1m]
    python3 backfill.py --days 7       # fast test
    python3 backfill.py --days 365     # full year

Sources:
    binance-spot  → https://api.binance.com/api/v3/klines
    binance-perp  → https://fapi.binance.com/fapi/v1/klines
    bybit-perp    → https://api.bybit.com/v5/market/kline

Rate limits respected:
    Binance: 1200 req/min → we sleep 0.05s between batches (500 bars/req)
    Bybit:   120 req/min  → we sleep 0.6s between batches (200 bars/req)
"""

import asyncio
import aiohttp
import sqlite3
import time
import logging
import argparse
import os
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [backfill] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")

SYMBOL = "BANANAS31USDT"
DB_PATH = os.environ.get("DB_PATH", "/app/data/bananas31.db")

INTERVAL_TO_SECS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


# ── Binance helpers ────────────────────────────────────────────────────

async def fetch_binance(session, url, symbol, interval, start_ms, end_ms, limit=1000):
    """Fetch one page of Binance klines. Returns list of (ts_sec, o, h, l, c, v)."""
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": limit,
    }
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        resp.raise_for_status()
        raw = await resp.json()
    return [
        (int(row[0]) / 1000.0, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]))
        for row in raw
    ]


async def backfill_binance(session, db_conn, exchange_id, url, interval, start_ts, end_ts):
    """Page through Binance REST and bulk-insert into price_feed."""
    interval_secs = INTERVAL_TO_SECS[interval]
    interval_ms = interval_secs * 1000
    limit = 1000

    cursor = db_conn.cursor()
    total = 0
    current_ms = int(start_ts * 1000)
    end_ms = int(end_ts * 1000)

    while current_ms < end_ms:
        page_end_ms = min(current_ms + limit * interval_ms, end_ms)
        try:
            bars = await fetch_binance(session, url, SYMBOL, interval, current_ms, page_end_ms, limit)
        except Exception as e:
            log.warning("%s: fetch error at %s: %s — retrying in 2s", exchange_id, current_ms, e)
            await asyncio.sleep(2)
            continue

        if not bars:
            current_ms = page_end_ms
            continue

        cursor.executemany(
            "INSERT OR IGNORE INTO price_feed(exchange_id, timestamp, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(exchange_id, ts, o, h, l, c, v) for ts, o, h, l, c, v in bars],
        )
        db_conn.commit()
        total += len(bars)

        last_ts = bars[-1][0]
        pct = (last_ts - start_ts) / (end_ts - start_ts) * 100
        log.info(
            "%s: inserted %d bars (total %d) — up to %s (%.1f%%)",
            exchange_id,
            len(bars),
            total,
            datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            pct,
        )

        current_ms = int(last_ts * 1000) + interval_ms
        await asyncio.sleep(0.05)  # 20 req/s, well below 1200/min limit

    log.info("%s: DONE — %d bars total", exchange_id, total)
    return total


# ── Bybit helpers ──────────────────────────────────────────────────────

async def fetch_bybit(session, symbol, interval, start_ms, end_ms, limit=200):
    """Fetch one page of Bybit klines (linear). Returns list of (ts_sec, o, h, l, c, v)."""
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": interval,
        "start": start_ms,
        "end": end_ms,
        "limit": limit,
    }
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        resp.raise_for_status()
        data = await resp.json()
    rows = data.get("result", {}).get("list", [])
    # Bybit returns newest-first; reverse to chronological
    rows = list(reversed(rows))
    return [
        (int(row[0]) / 1000.0, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]))
        for row in rows
    ]


async def backfill_bybit(session, db_conn, exchange_id, interval, start_ts, end_ts):
    """Page through Bybit REST and bulk-insert into price_feed."""
    interval_secs = INTERVAL_TO_SECS.get(interval)
    if not interval_secs:
        raise ValueError(f"Unknown interval: {interval}")
    interval_ms = interval_secs * 1000
    limit = 200

    # Bybit interval labels: 1,3,5,15,30,60,120,240,360,720,D,W,M
    bybit_interval_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
    bybit_interval = bybit_interval_map.get(interval, interval)

    cursor = db_conn.cursor()
    total = 0
    current_ms = int(start_ts * 1000)
    end_ms = int(end_ts * 1000)

    while current_ms < end_ms:
        page_end_ms = min(current_ms + limit * interval_ms, end_ms)
        try:
            bars = await fetch_bybit(session, SYMBOL, bybit_interval, current_ms, page_end_ms, limit)
        except Exception as e:
            log.warning("%s: fetch error at %s: %s — retrying in 2s", exchange_id, current_ms, e)
            await asyncio.sleep(2)
            continue

        if not bars:
            current_ms = page_end_ms
            continue

        cursor.executemany(
            "INSERT OR IGNORE INTO price_feed(exchange_id, timestamp, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(exchange_id, ts, o, h, l, c, v) for ts, o, h, l, c, v in bars],
        )
        db_conn.commit()
        total += len(bars)

        last_ts = bars[-1][0]
        pct = (last_ts - start_ts) / (end_ts - start_ts) * 100
        log.info(
            "%s: inserted %d bars (total %d) — up to %s (%.1f%%)",
            exchange_id,
            len(bars),
            total,
            datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            pct,
        )

        current_ms = int(last_ts * 1000) + interval_ms
        await asyncio.sleep(0.6)  # ~1.7 req/s, well below 120/min limit

    log.info("%s: DONE — %d bars total", exchange_id, total)
    return total


# ── Main ───────────────────────────────────────────────────────────────

async def run(db_path: str, days: int, interval: str):
    now_ts = time.time()
    start_ts = now_ts - days * 86400

    log.info("Backfill: %.0f days back, interval=%s, db=%s", days, interval, db_path)
    log.info("From: %s  To: %s",
             datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             datetime.fromtimestamp(now_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    db = sqlite3.connect(db_path)
    # Ensure table exists (in case running standalone)
    db.execute("""
        CREATE TABLE IF NOT EXISTS price_feed (
            exchange_id TEXT NOT NULL,
            timestamp   REAL NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      REAL,
            UNIQUE(exchange_id, timestamp)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_price_feed ON price_feed(exchange_id, timestamp)")
    db.commit()

    async with aiohttp.ClientSession() as session:
        # Binance spot
        log.info("=== binance-spot ===")
        await backfill_binance(
            session, db, "binance-spot",
            "https://api.binance.com/api/v3/klines",
            interval, start_ts, now_ts,
        )

        # Binance perp
        log.info("=== binance-perp ===")
        await backfill_binance(
            session, db, "binance-perp",
            "https://fapi.binance.com/fapi/v1/klines",
            interval, start_ts, now_ts,
        )

        # Bybit perp
        log.info("=== bybit-perp ===")
        await backfill_bybit(
            session, db, "bybit-perp",
            interval, start_ts, now_ts,
        )

    # Summary
    cursor = db.cursor()
    cursor.execute("""
        SELECT exchange_id, count(*) as cnt,
               datetime(min(timestamp), 'unixepoch') as first,
               datetime(max(timestamp), 'unixepoch') as last
        FROM price_feed
        GROUP BY exchange_id
    """)
    log.info("=== FINAL DB SUMMARY ===")
    for row in cursor.fetchall():
        log.info("  %s: %d bars  [%s → %s]", *row)

    db.close()
    log.info("Backfill complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical OHLCV into bananas31 DB")
    parser.add_argument("--db", default=DB_PATH, help="Path to SQLite DB")
    parser.add_argument("--days", type=float, default=365, help="Days of history to fetch (default: 365)")
    parser.add_argument("--interval", default="1m", choices=list(INTERVAL_TO_SECS.keys()), help="Candle interval")
    args = parser.parse_args()

    asyncio.run(run(args.db, args.days, args.interval))

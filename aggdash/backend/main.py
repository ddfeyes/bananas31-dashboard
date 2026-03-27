"""Main FastAPI application for aggdash backend."""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import API_HOST, API_PORT, LOG_LEVEL, OHLCV_INTERVAL_SECS
from db import init_db, get_db
from ring_buffer import RingBuffer
from ohlcv_aggregator import OHLCVAggregator
from collectors import (
    BinancePerpCollector,
    BinanceSpotCollector,
    BybitPerpCollector,
    BSCPancakeSwapCollector,
    OIFundingPoller,
)
from analytics_engine import AnalyticsEngine
from signals import SignalEngine
from ws_manager import price_manager

# Configure structured JSON logging
from pythonjsonlogger import jsonlogger

_log_handler = logging.StreamHandler()
_formatter = jsonlogger.JsonFormatter(
    fmt='%(asctime)s %(name)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
    rename_fields={'asctime': 'timestamp', 'name': 'logger', 'levelname': 'level'},
)
_log_handler.setFormatter(_formatter)
logging.root.setLevel(getattr(logging, LOG_LEVEL))
logging.root.handlers = [_log_handler]
logger = logging.getLogger(__name__)

# Uvicorn log config for JSON output
UVICORN_LOG_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'fmt': '%(asctime)s %(name)s %(levelname)s %(message)s',
            'rename_fields': {'asctime': 'timestamp', 'name': 'logger', 'levelname': 'level'},
        }
    },
    'handlers': {
        'default': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
            'stream': 'ext://sys.stdout',
        }
    },
    'loggers': {
        'uvicorn': {'handlers': ['default'], 'level': 'INFO', 'propagate': False},
        'uvicorn.error': {'handlers': ['default'], 'level': 'INFO', 'propagate': False},
        'uvicorn.access': {'handlers': ['default'], 'level': 'INFO', 'propagate': False},
    },
}

# Track application start time for uptime reporting
_app_start_time = time.time()

# Global state
ring_buffer: RingBuffer = None
ohlcv_aggregator: OHLCVAggregator = None
analytics_engine: AnalyticsEngine = None
signal_engine: SignalEngine = None
collectors: list = []
oi_funding_poller: OIFundingPoller = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global ring_buffer, ohlcv_aggregator, analytics_engine, signal_engine, collectors, oi_funding_poller

    logger.info("Starting up aggdash backend...")

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Initialize ring buffer and aggregator
    ring_buffer = RingBuffer()
    ohlcv_aggregator = OHLCVAggregator(ring_buffer, OHLCV_INTERVAL_SECS)
    # Analytics engine wired in after oi_funding_poller is created

    # Create callbacks
    async def on_tick(tick):
        """Callback for new tick."""
        await ring_buffer.add_tick(tick)
        await ohlcv_aggregator.process_tick(tick)
        # Push latest prices to WebSocket subscribers (throttled to 1/sec)
        if price_manager.count > 0:
            latest = await ring_buffer.get_latest_prices()
            if latest:
                await price_manager.notify_tick(latest)

    async def on_liquidation(liq):
        """Callback for liquidation."""
        logger.debug("Liquidation: %s", liq)

    # Initialize collectors (BybitSpot removed — BANANAS31USDT only exists as perp on Bybit)
    collectors = [
        BinancePerpCollector(on_tick, on_liquidation),
        BinanceSpotCollector(on_tick),
        BybitPerpCollector(on_tick, on_liquidation),
        BSCPancakeSwapCollector(on_tick, get_cex_spot=ohlcv_aggregator.get_aggregated_spot_price),
    ]

    # Initialize OI + Funding poller
    oi_funding_poller = OIFundingPoller(oi_interval_secs=30, funding_interval_secs=60)

    # Initialize analytics engine (needs ring_buffer + poller)
    analytics_engine = AnalyticsEngine(ring_buffer, oi_funding_poller)
    signal_engine = SignalEngine(ring_buffer)

    # Wire OI updates into analytics engine for delta tracking
    _orig_poll_oi = oi_funding_poller._poll_oi if hasattr(oi_funding_poller, '_poll_oi') else None

    # Start all collectors
    [asyncio.create_task(c.start()) for c in collectors]
    asyncio.create_task(oi_funding_poller.start())

    # Backfill historical data if DB is sparse (Bug 6)
    asyncio.create_task(_backfill_historical_data())

    # Start OHLCV flush task
    async def flush_ohlcv_periodically():
        while True:
            try:
                await asyncio.sleep(OHLCV_INTERVAL_SECS)
                await ohlcv_aggregator.flush_incomplete_bars()
            except Exception as e:
                logger.error("Error flushing OHLCV: %s", e)

    asyncio.create_task(flush_ohlcv_periodically())

    # Start Telegram signal alert task (SPEC §4: post to topic 7135 every 5 min)
    asyncio.create_task(_telegram_signal_alert_loop())

    logger.info("All collectors started")

    yield

    # Shutdown
    logger.info("Shutting down...")
    for c in collectors:
        await c.stop()
    await oi_funding_poller.stop()

    await asyncio.sleep(1)  # Allow graceful shutdown
    logger.info("Shutdown complete")

# Create FastAPI app
app = FastAPI(
    title="aggdash - Multi-Exchange Aggregator",
    description="Real-time aggregated price data from multiple exchanges",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "ring_buffer_size": await ring_buffer.size(),
    }

@app.get("/api/prices")
async def get_prices():
    """Get current prices from all sources."""
    prices = {}

    for source in ["binance-spot", "binance-perp", "bybit-perp", "bsc-pancakeswap"]:
        latest = await ohlcv_aggregator.get_current_price(source)
        if latest is None:
            # Fallback: grab most recent tick from ring buffer (fixes #14: bybit-perp missing)
            ticks = await ring_buffer.get_ticks(source)
            if ticks:
                latest = ticks[-1].price
        if latest is not None:
            prices[source] = latest

    return {
        "timestamp": time.time(),
        "prices": prices,
    }

@app.get("/api/price-change")
async def get_price_change(window_secs: int = 86400):
    """
    Compute % price change over the given window (default 24h).

    Returns per-source: {change_pct, current, prev} for each exchange.
    Uses price_feed table: current = latest close, prev = closest close to (now - window_secs).
    """
    db = get_db()
    now = time.time()
    target_ts = now - window_secs
    tolerance = 1800  # ±30 min acceptable for 24h anchor

    sources = ["binance-spot", "binance-perp", "bybit-perp", "bsc-pancakeswap"]
    result: dict = {}

    for src in sources:
        # Current price
        row_cur = db.execute(
            "SELECT close FROM price_feed WHERE exchange_id = ? ORDER BY timestamp DESC LIMIT 1",
            (src,),
        ).fetchone()
        if not row_cur:
            continue
        current = row_cur[0]

        # Historical price closest to target_ts
        row_prev = db.execute(
            """
            SELECT close FROM price_feed
            WHERE exchange_id = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY ABS(timestamp - ?) ASC
            LIMIT 1
            """,
            (src, target_ts - tolerance, target_ts + tolerance, target_ts),
        ).fetchone()

        if not row_prev:
            result[src] = {"current": current, "prev": None, "change_pct": None}
            continue

        prev = row_prev[0]
        change_pct = (current - prev) / prev * 100 if prev else None
        result[src] = {"current": current, "prev": prev, "change_pct": change_pct}

    db.close()
    return {
        "timestamp": now,
        "window_secs": window_secs,
        "changes": result,
    }


@app.websocket("/ws/prices")
async def ws_prices(websocket: WebSocket):
    """
    WebSocket endpoint for real-time price streaming.

    Pushes JSON: {"type": "prices", "timestamp": <float>, "prices": {source: price, ...}}
    Rate-limited to 1 message/sec regardless of tick rate.
    Client can send any text to keep the connection alive (heartbeat).
    """
    await price_manager.connect(websocket)
    # Send the current prices immediately on connect
    try:
        initial_prices = await ring_buffer.get_latest_prices()
        if initial_prices:
            await websocket.send_json({
                "type": "prices",
                "timestamp": time.time(),
                "prices": initial_prices,
            })
    except Exception:
        pass

    try:
        while True:
            # Keep connection alive — wait for client heartbeat or disconnect
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send a keepalive ping
                try:
                    await websocket.send_json({"type": "ping", "timestamp": time.time()})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WS prices connection closed: %s", exc)
    finally:
        price_manager.disconnect(websocket)


@app.get("/api/aggregated-prices")
async def get_aggregated_prices():
    """Get aggregated prices."""
    spot_price = await ohlcv_aggregator.get_aggregated_spot_price()
    perp_price = await ohlcv_aggregator.get_aggregated_perp_price()

    return {
        "timestamp": time.time(),
        "spot_price": spot_price,
        "perp_price": perp_price,
        "basis": (perp_price - spot_price) if spot_price and perp_price else None,
    }

@app.get("/api/ticks")
async def get_ticks(source: str = None):
    """Get recent ticks from ring buffer."""
    ticks = await ring_buffer.get_ticks(source)
    return {
        "count": len(ticks),
        "ticks": [
            {
                "timestamp": t.timestamp,
                "source": t.source,
                "price": t.price,
                "volume": t.volume,
                "is_buy": t.is_buy,
            }
            for t in ticks
        ]
    }

@app.get("/api/oi")
async def get_oi():
    """Get aggregated Open Interest (Binance perp + Bybit perp)."""
    per_source = oi_funding_poller.get_latest_oi()
    aggregated = oi_funding_poller.get_aggregated_oi()
    total = aggregated if aggregated else None
    return {
        "timestamp": time.time(),
        "per_source": per_source,
        "aggregated": aggregated,
        # Aliases for frontend / tests
        "total_oi": total,
        "per_exchange": per_source,
    }

@app.get("/api/funding")
async def get_funding():
    """Get latest funding rates (Binance perp + Bybit perp)."""
    rates = oi_funding_poller.get_latest_funding()
    # Compute average_rate from nested dicts (fixes #13: frontend expects average_rate)
    rate_8h_values = [
        v["rate_8h"]
        for v in rates.values()
        if isinstance(v, dict) and v.get("rate_8h") is not None
    ]
    avg_rate = sum(rate_8h_values) / len(rate_8h_values) if rate_8h_values else None
    annualized = avg_rate * 3 * 365 * 100 if avg_rate is not None else None
    return {
        "timestamp": time.time(),
        "rates": rates,
        "average_rate": avg_rate,
        "annualized_pct": annualized,
    }

@app.get("/api/liquidations")
async def get_liquidations(limit: int = 100):
    """Get recent liquidation events."""
    from db import get_db
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        SELECT timestamp, source, symbol, side, quantity, price
        FROM liquidations ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
    return {"count": len(rows), "liquidations": rows}


@app.get("/api/liquidations/series")
async def get_liquidations_series(minutes: int = 60, bucket_secs: int = 60):
    """
    Liquidations aggregated by minute bucket.
    Returns per-side (SELL = long liquidation, BUY = short liquidation) bar data.
    """
    cutoff = time.time() - minutes * 60
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT
                CAST(timestamp / ? AS INTEGER) * ? AS bucket,
                side,
                COUNT(*) AS count,
                SUM(quantity * price) AS usd_value
            FROM liquidations
            WHERE timestamp > ?
            GROUP BY bucket, side
            ORDER BY bucket ASC
            """,
            (bucket_secs, bucket_secs, cutoff),
        ).fetchall()
    finally:
        conn.close()

    # Pivot into {timestamp, sell_usd, buy_usd, sell_count, buy_count}
    buckets: dict = {}
    for row in rows:
        bucket, side, count, usd = row
        if bucket not in buckets:
            buckets[bucket] = {
                "timestamp": bucket,
                "sell_usd": 0.0, "sell_count": 0,
                "buy_usd": 0.0, "buy_count": 0,
            }
        side_key = "sell" if side and side.upper() == "SELL" else "buy"
        buckets[bucket][f"{side_key}_usd"] += usd or 0.0
        buckets[bucket][f"{side_key}_count"] += count

    series = sorted(buckets.values(), key=lambda x: x["timestamp"])
    return {"series": series, "count": len(series), "bucket_secs": bucket_secs}

@app.get("/api/status")
async def get_status():
    """Get collector status."""
    return {
        "collectors": [
            {"name": c.__class__.__name__, "running": c.running}
            for c in collectors
        ],
        "ring_buffer_size": await ring_buffer.size(),
        "ohlcv_bars": sum(  # fixes #16: count bars from DB, not just in-progress current_bars
            1 for _ in ohlcv_aggregator.current_bars.values()
        ) + len(getattr(ohlcv_aggregator, "_completed_bars", {})),
    }


# ── /api/stats — concise health + stats snapshot ──────────────────────

@app.get("/api/stats")
async def get_stats():
    """Concise health and statistics snapshot for monitoring."""
    rb_size = await ring_buffer.size()
    now = time.time()
    since_24h = now - 86400

    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT count(*) FROM price_feed")
        price_feed_rows = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM oi")
        oi_rows_count = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM liquidations")
        liq_rows = cursor.fetchone()[0]

        # 24h volume per exchange
        vol_rows = cursor.execute(
            """
            SELECT exchange_id, SUM(volume) as vol_24h
            FROM price_feed
            WHERE timestamp >= ?
            GROUP BY exchange_id
            """,
            (since_24h,),
        ).fetchall()
        vol_map = {row[0]: row[1] or 0.0 for row in vol_rows}
        vol_24h = {
            "binance_spot": vol_map.get("binance-spot", 0.0),
            "binance_perp": vol_map.get("binance-perp", 0.0),
            "bybit_perp": vol_map.get("bybit-perp", 0.0),
        }
        vol_24h["total"] = sum(vol_24h.values())

        # OI 24h change % — latest row per exchange vs 24h-ago row per exchange
        oi_change_24h_pct = None
        try:
            # Latest OI per exchange (one row each)
            oi_now_rows = cursor.execute(
                """
                SELECT exchange_id, open_interest
                FROM oi
                WHERE (exchange_id, timestamp) IN (
                    SELECT exchange_id, MAX(timestamp) FROM oi GROUP BY exchange_id
                )
                """,
            ).fetchall()
            # OI per exchange closest to 24h ago (±30min window)
            oi_ago_rows = cursor.execute(
                """
                SELECT exchange_id, open_interest
                FROM oi
                WHERE timestamp BETWEEN ? AND ? + 1800
                ORDER BY timestamp ASC
                """,
                (since_24h, since_24h),
            ).fetchall()

            if oi_now_rows and oi_ago_rows:
                # Sum latest per exchange (deduplicated)
                seen = set()
                oi_now_total = 0.0
                for ex, oi in oi_now_rows:
                    if ex not in seen and oi:
                        oi_now_total += oi
                        seen.add(ex)
                # Sum 24h-ago per exchange (deduplicated — take first occurrence per exchange)
                seen = set()
                oi_ago_total = 0.0
                for ex, oi in oi_ago_rows:
                    if ex not in seen and oi:
                        oi_ago_total += oi
                        seen.add(ex)
                if oi_ago_total > 0:
                    oi_change_24h_pct = (oi_now_total - oi_ago_total) / oi_ago_total
        except Exception:
            pass

        db.close()
    except Exception:
        price_feed_rows = oi_rows_count = liq_rows = -1
        vol_24h = {"binance_spot": 0, "binance_perp": 0, "bybit_perp": 0, "total": 0}
        oi_change_24h_pct = None

    # Latest tick timestamp
    all_ticks = await ring_buffer.get_ticks()
    last_tick_ts = all_ticks[-1].timestamp if all_ticks else None

    # Signal count from signal engine
    try:
        snapshot = await analytics_engine.snapshot()
        active_signals = signal_engine.compute_signals(snapshot)
        signal_count = len(active_signals)
    except Exception:
        signal_count = 0

    return {
        "status": "ok",
        "uptime_secs": round(now - _app_start_time),
        "ring_buffer_size": rb_size,
        "signal_count": signal_count,
        "last_tick_ts": last_tick_ts,
        "ws_connections": price_manager.count,
        "collectors": [
            {"name": c.__class__.__name__, "running": c.running}
            for c in collectors
        ],
        "db": {
            "price_feed_rows": price_feed_rows,
            "oi_rows": oi_rows_count,
            "liquidations_rows": liq_rows,
        },
        "vol_24h": vol_24h,
        "oi_change_24h_pct": oi_change_24h_pct,
    }


# ── Analytics endpoints ────────────────────────────────────────────────

@app.get("/api/analytics/snapshot")
async def get_analytics_snapshot():
    """Full analytics snapshot: CVD, basis, spread, OI delta, funding."""
    return await analytics_engine.snapshot()


@app.get("/api/analytics/cvd")
async def get_cvd(source: str = None, window_secs: int = 3600):
    """Current CVD per source and aggregated."""
    return await analytics_engine.compute_cvd(source=source, window_secs=window_secs)


@app.get("/api/analytics/cvd/series")
async def get_cvd_series(
    interval_secs: int = 60,
    window_secs: int = 3600,
    source: str = None,
):
    """CVD time-series per source and aggregated."""
    return await analytics_engine.compute_cvd_series(
        interval_secs=interval_secs,
        window_secs=window_secs,
        source=source,
    )


@app.get("/api/analytics/basis")
async def get_basis():
    """Current basis (perp - spot) per exchange and aggregated."""
    return await analytics_engine.compute_basis()


@app.get("/api/analytics/basis/series")
async def get_basis_series(interval_secs: int = 60, window_secs: int = 3600):
    """Basis time-series per exchange and aggregated."""
    return await analytics_engine.compute_basis_series(
        interval_secs=interval_secs,
        window_secs=window_secs,
    )


@app.get("/api/analytics/basis/ma7d")
async def get_basis_ma7d():
    """
    7-day moving average of aggregated basis_pct.

    Uses 1-hour bucketed basis bars from price_feed (last 14 days to compute
    a full 7-day rolling MA). Returns [{timestamp, basis_pct, ma7d}] for all
    available points with window = 168 bars.
    SPEC §5: 'Basis trend: 7-day MA'.
    """
    from db import get_db
    db = get_db()
    window_secs = 14 * 86400  # 14 days of history
    since = time.time() - window_secs
    bucket = 3600  # 1-hour bars

    try:
        # Two fast GROUP BY queries — avoid self-JOIN on 1M+ rows (was timing out)
        spot_rows = db.execute(
            """
            SELECT CAST(timestamp / ? AS INTEGER) * ? AS ts, AVG(close)
            FROM price_feed
            WHERE exchange_id = 'binance-spot' AND timestamp >= ?
            GROUP BY ts ORDER BY ts ASC
            """,
            (bucket, bucket, since),
        ).fetchall()
        perp_rows = db.execute(
            """
            SELECT CAST(timestamp / ? AS INTEGER) * ? AS ts, AVG(close)
            FROM price_feed
            WHERE exchange_id = 'binance-perp' AND timestamp >= ?
            GROUP BY ts ORDER BY ts ASC
            """,
            (bucket, bucket, since),
        ).fetchall()
    finally:
        db.close()

    if not spot_rows or not perp_rows:
        return {"ma7d": [], "window_bars": 168}

    # Build lookup dicts and compute basis_pct where both sources have data
    spot_by_ts = {int(ts): close for ts, close in spot_rows if close}
    perp_by_ts = {int(ts): close for ts, close in perp_rows if close}
    all_ts = sorted(set(spot_by_ts) & set(perp_by_ts))

    series = []
    for ts in all_ts:
        spot = spot_by_ts[ts]
        perp = perp_by_ts[ts]
        if spot > 0:
            basis_pct = (perp - spot) / spot * 100
            series.append({"timestamp": ts, "basis_pct": basis_pct})

    # Compute rolling 7-day MA (168 hourly bars)
    MA_WINDOW = 168
    result = []
    for i, pt in enumerate(series):
        window_start = max(0, i - MA_WINDOW + 1)
        window_vals = [s["basis_pct"] for s in series[window_start:i + 1]]
        ma7d = sum(window_vals) / len(window_vals)
        result.append({
            "timestamp": pt["timestamp"],
            "basis_pct": pt["basis_pct"],
            "ma7d": ma7d,
            "window_used": len(window_vals),
        })

    return {"ma7d": result, "window_bars": MA_WINDOW, "count": len(result)}


@app.get("/api/analytics/dex-cex-spread")
async def get_dex_cex_spread():
    """Current DEX vs CEX spot spread."""
    return await analytics_engine.compute_dex_cex_spread()


@app.get("/api/analytics/dex-cex-spread/series")
async def get_dex_cex_spread_series(interval_secs: int = 60, window_secs: int = 3600):
    """DEX vs CEX spread time-series."""
    return await analytics_engine.compute_dex_cex_spread_series(
        interval_secs=interval_secs,
        window_secs=window_secs,
    )


@app.get("/api/analytics/oi-delta")
async def get_oi_delta():
    """Current OI delta (per source and aggregated)."""
    return await analytics_engine.compute_oi_delta()


@app.get("/api/analytics/oi-delta/series")
async def get_oi_delta_series(window_secs: int = 3600):
    """OI delta time-series from DB history."""
    return await analytics_engine.get_oi_delta_series(window_secs=window_secs)


@app.get("/api/analytics/funding")
async def get_funding_summary():
    """Aggregated funding rate summary."""
    return await analytics_engine.get_funding_summary()


@app.get("/api/analytics/funding/series")
async def get_funding_series(interval_secs: int = 300, window_secs: int = 86400):
    """
    Funding rate time series per exchange, bucketed by interval.

    Returns per_source: {exchange: [{timestamp, rate_8h, rate_1h}, ...]}
    Default: 24h window, 5-min buckets → 288 points per exchange.
    """
    db = get_db()
    now = time.time()
    since = now - window_secs
    sources = ["binance-perp", "bybit-perp"]
    result: dict = {}

    for src in sources:
        rows = db.execute(
            """
            SELECT CAST((timestamp / ?) AS INTEGER) * ? AS bucket,
                   rate_8h, rate_1h
            FROM funding_rates
            WHERE exchange_id = ? AND timestamp >= ?
            ORDER BY bucket ASC, timestamp DESC
            """,
            (interval_secs, interval_secs, src, since),
        ).fetchall()

        # Deduplicate buckets — keep the most recent reading per bucket
        seen: set = set()
        pts = []
        for bucket, r8, r1 in rows:
            if bucket not in seen:
                seen.add(bucket)
                pts.append({"timestamp": int(bucket), "rate_8h": r8, "rate_1h": r1})
        pts.sort(key=lambda x: x["timestamp"])
        result[src] = pts

    db.close()
    return {
        "per_source": result,
        "window_secs": window_secs,
        "interval_secs": interval_secs,
    }


@app.get("/api/analytics/volume/series")
async def get_volume_series(interval_secs: int = 60, window_secs: int = 3600):
    """Volume series per exchange over a time window, bucketed by interval."""
    from db import get_db
    now = __import__("time").time()
    since = now - window_secs
    bucket = interval_secs

    db = get_db()
    exchanges = ["binance-spot", "binance-perp", "bybit-perp"]
    result: dict = {}

    for exch in exchanges:
        rows = db.execute(
            """
            SELECT CAST((timestamp / ?) AS INTEGER) * ? AS ts,
                   SUM(volume) AS vol
            FROM price_feed
            WHERE exchange_id = ? AND timestamp >= ?
            GROUP BY ts
            ORDER BY ts ASC
            """,
            (bucket, bucket, exch, since),
        ).fetchall()
        result[exch] = [{"timestamp": r[0], "volume": r[1] or 0.0} for r in rows]

    return {
        "per_exchange": result,
        "interval_secs": interval_secs,
        "window_secs": window_secs,
    }


@app.get("/api/oi/delta")
async def get_oi_delta_snapshot():
    """Latest OI delta: current vs 30 min ago (from snapshot)."""
    snap = await analytics_engine.snapshot()
    return snap.get("oi_delta", {})


@app.get("/api/analytics/ohlcv")
async def get_ohlcv(exchange_id: str = "binance-spot", minutes: int = 1440, interval: str = "1m"):
    """Get OHLCV bars from the price_feed table for a given exchange and time range.

    interval: 1m (default), 5m, 15m, 30m, 1h, 4h, 1d
    For long timeframes pass a coarser interval to keep response size reasonable.
    """
    from db import get_latest_ohlcv, VALID_INTERVALS
    if interval not in VALID_INTERVALS:
        interval = "1m"
    bars = get_latest_ohlcv(exchange_id, minutes=minutes, interval=interval)
    return {"bars": bars, "count": len(bars), "exchange_id": exchange_id, "interval": interval}


@app.get("/api/dex")
async def get_dex():
    """Get latest DEX price, liquidity, and deviation from CEX spot."""
    # Latest from ring buffer
    bsc_collector = next(
        (c for c in collectors if c.__class__.__name__ == "BSCPancakeSwapCollector"), None
    )
    last_price = bsc_collector.last_price if bsc_collector else None
    last_liquidity = bsc_collector.last_liquidity if bsc_collector else None

    # Latest from DB
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT timestamp, price, liquidity, deviation_pct FROM dex_price ORDER BY timestamp DESC LIMIT 1"
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    cex_spot = await ohlcv_aggregator.get_aggregated_spot_price()
    deviation_pct = None
    if last_price and cex_spot and cex_spot > 0:
        deviation_pct = (last_price - cex_spot) / cex_spot * 100

    return {
        "timestamp": time.time(),
        "dex_price": last_price,
        "liquidity": last_liquidity,
        "cex_spot_avg": cex_spot,
        "deviation_pct": deviation_pct,
        "last_db_record": dict(row) if row else None,
    }


@app.get("/api/dex/history")
async def get_dex_history(limit: int = 100):
    """Get DEX price history from dex_price table."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT timestamp, price, liquidity, deviation_pct FROM dex_price ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
    return {"count": len(rows), "history": rows}


@app.get("/api/signals")
async def get_signals():
    """Get active real-time signals (squeeze risk, arb, OI accumulation, deleveraging)."""
    if analytics_engine is None or signal_engine is None:
        return {"timestamp": 0, "signals": [], "count": 0}
    snap = await analytics_engine.snapshot()
    sigs = signal_engine.compute_signals(snap)
    return {"timestamp": snap.get("timestamp", 0), "signals": sigs, "count": len(sigs)}


# ── /api/dex/price (Bug 2) ─────────────────────────────────────────────

@app.get("/api/dex/price")
async def get_dex_price():
    """Get latest DEX price from dex_price table."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT timestamp, price, liquidity, deviation_pct FROM dex_price ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "no data")

    # Compute liquidity_usd (fix #15): V3 liquidity L is in sqrt(token0*token1) units.
    # Approximate TVL using infinite-range formula: amount1_usd ≈ L * sqrtP / 1e18 * bnb_usd * 2
    bsc_coll = next(
        (c for c in collectors if c.__class__.__name__ == "BSCPancakeSwapCollector"), None
    )
    liquidity_usd = None
    if bsc_coll and bsc_coll.last_sqrt_price_x96 and bsc_coll.last_bnb_usd and row[2]:
        try:
            L = row[2]
            sqrtP = bsc_coll.last_sqrt_price_x96 / (2 ** 96)
            # amount1 (WBNB in 18 decimals) ≈ L * sqrtP / 1e18 (infinite-range approx)
            amount1_wbnb = L * sqrtP / 1e18
            # Total TVL ≈ 2× one-sided (symmetric pool)
            liquidity_usd = amount1_wbnb * bsc_coll.last_bnb_usd * 2
        except Exception:
            pass

    return {
        "timestamp": row[0],
        "price": row[1],
        "liquidity": row[2],          # raw L (Q128-based, for reference)
        "liquidity_usd": liquidity_usd,  # estimated USD TVL
        "deviation_pct": row[3],
    }


# ── /api/oi/series (Bug 3) ────────────────────────────────────────────

@app.get("/api/oi/series")
async def get_oi_series(minutes: int = 60):
    """Get OI time-series from the oi DB table."""
    cutoff = time.time() - minutes * 60
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT exchange_id, timestamp, open_interest FROM oi WHERE timestamp > ? ORDER BY timestamp",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    per_source: dict = {}
    for row in rows:
        src = row[0]
        if src not in per_source:
            per_source[src] = []
        per_source[src].append({"timestamp": row[1], "open_interest": row[2]})

    # Build aggregated series using neighbor-join: for each Binance point,
    # find the nearest Bybit point within MAX_JOIN_SECS and sum them.
    # This is robust to any fixed-boundary edge cases with rounding.
    MAX_JOIN_SECS = 5.0  # polls arrive within ~0.5s; 5s window is very safe
    all_sources = sorted(per_source.keys())  # deterministic order
    aggregated = []
    if len(all_sources) == 0:
        pass
    elif len(all_sources) == 1:
        # Only one source: emit directly
        src = all_sources[0]
        aggregated = [
            {"timestamp": pt["timestamp"], "open_interest": pt["open_interest"]}
            for pt in per_source[src]
        ]
    else:
        # Multi-source: join on nearest timestamp within MAX_JOIN_SECS
        # Use first source as anchor, find nearest in each other source
        anchor_src = all_sources[0]
        other_srcs = all_sources[1:]
        # Build sorted arrays for each other source
        other_sorted = {s: sorted(per_source[s], key=lambda x: x["timestamp"]) for s in other_srcs}
        # Pointer per source for O(n) scan
        ptrs = {s: 0 for s in other_srcs}
        for anchor_pt in sorted(per_source[anchor_src], key=lambda x: x["timestamp"]):
            ts_anchor = anchor_pt["timestamp"]
            total = anchor_pt["open_interest"]
            valid = True
            for s in other_srcs:
                arr = other_sorted[s]
                if not arr:
                    valid = False
                    break
                ptr = ptrs[s]
                # Advance pointer to nearest
                while ptr + 1 < len(arr) and abs(arr[ptr + 1]["timestamp"] - ts_anchor) < abs(arr[ptr]["timestamp"] - ts_anchor):
                    ptr += 1
                ptrs[s] = ptr
                nearest = arr[ptr]
                if abs(nearest["timestamp"] - ts_anchor) > MAX_JOIN_SECS:
                    valid = False
                    break
                total += nearest["open_interest"]
            if valid:
                aggregated.append({"timestamp": ts_anchor, "open_interest": total})

    return {"per_source": per_source, "aggregated": aggregated}


# ── /api/patterns — calibrated thresholds for BANANAS31 (low-cap) ────
# OI_ACCUMULATION: >1.5% OI rise in 4h with flat price (was 5%)
_PAT_OI_ACCUM_PCT = 1.5
# DEX_PREMIUM: dex > cex * (1 + threshold) i.e. >0.3% (was 1%)
_PAT_DEX_PREMIUM_PCT = 0.3
# BASIS_SQUEEZE: basis > 0.1% with positive funding (was 0.3%)
_PAT_BASIS_SQUEEZE_PCT = 0.1
# LIQUIDATION_CASCADE: >5 liqs in 5-min window (unchanged — event-based)
_PAT_LIQ_CASCADE_COUNT = 5
# VOLUME_DIVERGENCE: spot/perp ratio >3x in 1h (unchanged)

@app.get("/api/patterns")
async def get_patterns():
    """Detect structural patterns in current DB data."""
    patterns = []
    now = time.time()
    conn = get_db()
    try:
        # 1. OI_ACCUMULATION: last 4h OI rose >5% while price change <0.5%
        oi_rows = conn.execute(
            "SELECT open_interest FROM oi WHERE exchange_id='binance-perp' AND timestamp > ? ORDER BY timestamp",
            (now - 4 * 3600,),
        ).fetchall()
        if len(oi_rows) >= 2:
            oi_first = oi_rows[0][0]
            oi_last = oi_rows[-1][0]
            if oi_first and oi_first > 0:
                oi_change_pct = (oi_last - oi_first) / oi_first * 100
                # Check price change
                price_rows = conn.execute(
                    "SELECT close FROM price_feed WHERE exchange_id='binance-spot' AND timestamp > ? ORDER BY timestamp",
                    (now - 4 * 3600,),
                ).fetchall()
                price_change_pct = 0
                if len(price_rows) >= 2:
                    p_first = price_rows[0][0]
                    p_last = price_rows[-1][0]
                    if p_first and p_first > 0:
                        price_change_pct = abs((p_last - p_first) / p_first * 100)
                if oi_change_pct > _PAT_OI_ACCUM_PCT and price_change_pct < 0.5:
                    patterns.append({
                        "name": "OI_ACCUMULATION",
                        "confidence": min(oi_change_pct / 10, 1.0),
                        "description": f"OI rose {oi_change_pct:.1f}% in 4h while price moved only {price_change_pct:.2f}%",
                        "severity": "high" if oi_change_pct > _PAT_OI_ACCUM_PCT * 3 else "medium",
                        "detected_at": now,
                    })

        # 2. LIQUIDATION_CASCADE: >5 liquidations in any 5-min window in last 1h
        liq_rows = conn.execute(
            "SELECT timestamp FROM liquidations WHERE timestamp > ? ORDER BY timestamp",
            (now - 3600,),
        ).fetchall()
        if liq_rows:
            liq_times = [r[0] for r in liq_rows]
            max_in_window = 0
            for i, t in enumerate(liq_times):
                count = sum(1 for t2 in liq_times[i:] if t2 - t <= 300)
                max_in_window = max(max_in_window, count)
            if max_in_window > _PAT_LIQ_CASCADE_COUNT:
                patterns.append({
                    "name": "LIQUIDATION_CASCADE",
                    "confidence": min(max_in_window / 15, 1.0),
                    "description": f"{max_in_window} liquidations in a 5-min window (last 1h)",
                    "severity": "high" if max_in_window > 10 else "medium",
                    "detected_at": now,
                })

        # 3. DEX_PREMIUM: current dex_price > avg(binance-spot last 5min) * 1.01
        dex_row = conn.execute(
            "SELECT price FROM dex_price ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        spot_avg_row = conn.execute(
            "SELECT AVG(close) FROM price_feed WHERE exchange_id='binance-spot' AND timestamp > ?",
            (now - 300,),
        ).fetchone()
        if dex_row and spot_avg_row and dex_row[0] and spot_avg_row[0] and spot_avg_row[0] > 0:
            dex_p = dex_row[0]
            spot_avg = spot_avg_row[0]
            threshold_factor = 1.0 + _PAT_DEX_PREMIUM_PCT / 100.0
            if dex_p > spot_avg * threshold_factor:
                prem_pct = (dex_p - spot_avg) / spot_avg * 100
                patterns.append({
                    "name": "DEX_PREMIUM",
                    "confidence": min(prem_pct / 5, 1.0),
                    "description": f"DEX price {prem_pct:.2f}% above CEX spot average",
                    "severity": "medium",
                    "detected_at": now,
                })

        # 4. VOLUME_DIVERGENCE: spot_volume_1h / perp_volume_1h > 3
        spot_vol_row = conn.execute(
            "SELECT SUM(volume) FROM price_feed WHERE exchange_id='binance-spot' AND timestamp > ?",
            (now - 3600,),
        ).fetchone()
        perp_vol_row = conn.execute(
            "SELECT SUM(volume) FROM price_feed WHERE exchange_id='binance-perp' AND timestamp > ?",
            (now - 3600,),
        ).fetchone()
        spot_vol = (spot_vol_row[0] or 0) if spot_vol_row else 0
        perp_vol = (perp_vol_row[0] or 0) if perp_vol_row else 0
        if perp_vol > 0 and spot_vol / perp_vol > 3:
            ratio = spot_vol / perp_vol
            patterns.append({
                "name": "VOLUME_DIVERGENCE",
                "confidence": min(ratio / 10, 1.0),
                "description": f"Spot/Perp volume ratio {ratio:.1f}x in last 1h",
                "severity": "medium",
                "detected_at": now,
            })

        # 5. BASIS_SQUEEZE: basis > 0.3% AND funding_rate > 0
        spot_price_row = conn.execute(
            "SELECT close FROM price_feed WHERE exchange_id='binance-spot' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        perp_price_row = conn.execute(
            "SELECT close FROM price_feed WHERE exchange_id='binance-perp' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        funding_row = conn.execute(
            "SELECT rate_8h FROM funding_rates WHERE exchange_id='binance-perp' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if spot_price_row and perp_price_row and spot_price_row[0] and spot_price_row[0] > 0:
            basis_pct = (perp_price_row[0] - spot_price_row[0]) / spot_price_row[0] * 100
            funding_rate = funding_row[0] if funding_row else 0
            if basis_pct > _PAT_BASIS_SQUEEZE_PCT and funding_rate and funding_rate > 0:
                patterns.append({
                    "name": "BASIS_SQUEEZE",
                    "confidence": min(basis_pct / 1.0, 1.0),
                    "description": f"Basis {basis_pct:.3f}% with positive funding {funding_rate*100:.4f}% — squeeze risk",
                    "severity": "high" if basis_pct > 0.5 else "medium",
                    "detected_at": now,
                })
    finally:
        conn.close()

    return {"patterns": patterns}


# ── Telegram signal alerts (SPEC §4) ─────────────────────────────────

# Alterlain bot token + target chat/topic
_TELEGRAM_BOT_TOKEN = "8630691278:AAHKwfY24KVBCudTJWbwb-E5qKbArNSPw5c"
_TELEGRAM_CHAT_ID = "-1003844426893"
_TELEGRAM_THREAD_ID = 7135
_ALERT_INTERVAL_SECS = 300        # check every 5 min
_ALERT_COOLDOWN_SECS = 1800       # don't resend same signal within 30 min

# In-memory dedup: {signal_id: last_sent_ts}
_alert_sent_at: dict = {}


async def _send_telegram_alert(text: str) -> bool:
    """Send a message to Telegram topic 7135 via alterlain bot."""
    url = f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": _TELEGRAM_CHAT_ID,
        "message_thread_id": _TELEGRAM_THREAD_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if data.get("ok"):
                    logger.info("Telegram alert sent: %s", text[:80])
                    return True
                else:
                    logger.warning("Telegram alert failed: %s", data)
                    return False
    except Exception as exc:
        logger.warning("Telegram alert error: %s", exc)
        return False


async def _telegram_signal_alert_loop():
    """Background task: check signals every 5 min and post to Telegram when new ones fire."""
    # Wait for data collection to warm up before first check
    await asyncio.sleep(120)

    while True:
        try:
            snap = await analytics_engine.snapshot()
            sigs = signal_engine.compute_signals(snap)
            now = time.time()

            for sig in sigs:
                sig_id = sig.get("id", "unknown")
                last_sent = _alert_sent_at.get(sig_id, 0)
                if now - last_sent < _ALERT_COOLDOWN_SECS:
                    continue  # still in cooldown

                severity = sig.get("severity", "info")
                icon = {"alert": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "📊")
                name = sig.get("name", sig_id)
                msg_text = sig.get("message", "")
                ts_str = __import__("datetime").datetime.utcfromtimestamp(now).strftime("%H:%M UTC")

                text = (
                    f"{icon} <b>{name}</b>\n"
                    f"{msg_text}\n"
                    f"<i>{ts_str} · bananas31-dashboard.111miniapp.com</i>"
                )
                ok = await _send_telegram_alert(text)
                if ok:
                    _alert_sent_at[sig_id] = now

        except Exception as exc:
            logger.warning("Telegram alert loop error: %s", exc)

        await asyncio.sleep(_ALERT_INTERVAL_SECS)


# ── Historical backfill (Bug 6) ───────────────────────────────────────

async def _backfill_historical_data():
    """Fetch last 7 days of Binance data if DB is sparse."""
    try:
        conn = get_db()
        spot_count = conn.execute(
            "SELECT COUNT(*) FROM price_feed WHERE exchange_id='binance-spot'"
        ).fetchone()[0]
        perp_count = conn.execute(
            "SELECT COUNT(*) FROM price_feed WHERE exchange_id='binance-perp'"
        ).fetchone()[0]
        conn.close()

        async with aiohttp.ClientSession() as session:
            # Binance spot klines (7 days, 1m interval — max 1500 per request)
            if spot_count < 1000:
                logger.info("Backfilling Binance spot klines...")
                for start_offset in range(0, 10080, 1500):
                    limit = min(1500, 10080 - start_offset)
                    start_time = int((time.time() - 7 * 86400 + start_offset * 60) * 1000)
                    try:
                        async with session.get(
                            "https://api.binance.com/api/v3/klines",
                            params={"symbol": "BANANAS31USDT", "interval": "1m", "startTime": start_time, "limit": limit},
                            timeout=aiohttp.ClientTimeout(total=15),
                        ) as resp:
                            klines = await resp.json()
                            if isinstance(klines, list) and klines:
                                conn = get_db()
                                for k in klines:
                                    conn.execute(
                                        "INSERT OR IGNORE INTO price_feed(exchange_id,timestamp,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)",
                                        ("binance-spot", k[0] / 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])),
                                    )
                                conn.commit()
                                conn.close()
                                logger.info("Backfilled %d spot klines (batch %d)", len(klines), start_offset // 1500)
                    except Exception as exc:
                        logger.warning("Spot kline backfill error: %s", exc)
                    await asyncio.sleep(0.5)

            # Binance perp klines
            if perp_count < 1000:
                logger.info("Backfilling Binance perp klines...")
                try:
                    async with session.get(
                        "https://fapi.binance.com/fapi/v1/klines",
                        params={"symbol": "BANANAS31USDT", "interval": "1m", "limit": 1500},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        klines = await resp.json()
                        if isinstance(klines, list) and klines:
                            conn = get_db()
                            for k in klines:
                                conn.execute(
                                    "INSERT OR IGNORE INTO price_feed(exchange_id,timestamp,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)",
                                    ("binance-perp", k[0] / 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])),
                                )
                            conn.commit()
                            conn.close()
                            logger.info("Backfilled %d perp klines", len(klines))
                except Exception as exc:
                    logger.warning("Perp kline backfill error: %s", exc)

            # Binance OI history
            oi_count = get_db().execute("SELECT COUNT(*) FROM oi").fetchone()[0]
            if oi_count < 100:
                logger.info("Backfilling Binance OI history...")
                try:
                    async with session.get(
                        "https://fapi.binance.com/futures/data/openInterestHist",
                        params={"symbol": "BANANAS31USDT", "period": "5m", "limit": 500},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        data = await resp.json()
                        if isinstance(data, list) and data:
                            conn = get_db()
                            for item in data:
                                conn.execute(
                                    "INSERT OR IGNORE INTO oi(exchange_id,timestamp,open_interest) VALUES(?,?,?)",
                                    ("binance-perp", item["timestamp"] / 1000, float(item["sumOpenInterest"])),
                                )
                            conn.commit()
                            conn.close()
                            logger.info("Backfilled %d OI records", len(data))
                except Exception as exc:
                    logger.warning("OI backfill error: %s", exc)

            # Binance funding history
            funding_count = get_db().execute("SELECT COUNT(*) FROM funding_rates").fetchone()[0]
            if funding_count < 50:
                logger.info("Backfilling Binance funding history...")
                try:
                    async with session.get(
                        "https://fapi.binance.com/fapi/v1/fundingRate",
                        params={"symbol": "BANANAS31USDT", "limit": 100},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        data = await resp.json()
                        if isinstance(data, list) and data:
                            conn = get_db()
                            for item in data:
                                rate = float(item["fundingRate"])
                                conn.execute(
                                    "INSERT OR IGNORE INTO funding_rates(exchange_id,timestamp,rate_8h,rate_1h) VALUES(?,?,?,?)",
                                    ("binance-perp", item["fundingTime"] / 1000, rate, rate / 8),
                                )
                            conn.commit()
                            conn.close()
                            logger.info("Backfilled %d funding records", len(data))
                except Exception as exc:
                    logger.warning("Funding backfill error: %s", exc)

        logger.info("Historical backfill complete")
    except Exception as exc:
        logger.error("Backfill error: %s", exc)


# ── Static frontend serving ────────────────────────────────────────────

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if FRONTEND_DIR.exists():
    # Mount static assets (js, css)
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")

    @app.get("/")
    async def serve_index():
        """Serve the dashboard frontend."""
        return FileResponse(str(FRONTEND_DIR / "index.html"))
else:
    @app.get("/")
    async def serve_index_placeholder():
        return {"message": "aggdash backend running. Frontend not found."}


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting server on %s:%d", API_HOST, API_PORT)
    uvicorn.run(app, host=API_HOST, port=API_PORT, workers=1, log_config=UVICORN_LOG_CONFIG)

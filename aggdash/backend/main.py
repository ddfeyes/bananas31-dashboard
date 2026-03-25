"""Main FastAPI application for aggdash backend."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
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
    BybitSpotCollector,
    BSCPancakeSwapCollector,
    OIFundingPoller,
)
from analytics_engine import AnalyticsEngine
from signals import SignalEngine

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

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

    async def on_liquidation(liq):
        """Callback for liquidation."""
        logger.debug("Liquidation: %s", liq)

    # Initialize collectors
    collectors = [
        BinancePerpCollector(on_tick, on_liquidation),
        BinanceSpotCollector(on_tick),
        BybitPerpCollector(on_tick, on_liquidation),
        BybitSpotCollector(on_tick),
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

    # Start OHLCV flush task
    async def flush_ohlcv_periodically():
        while True:
            try:
                await asyncio.sleep(OHLCV_INTERVAL_SECS)
                await ohlcv_aggregator.flush_incomplete_bars()
            except Exception as e:
                logger.error("Error flushing OHLCV: %s", e)

    asyncio.create_task(flush_ohlcv_periodically())

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

    for source in ["binance-spot", "binance-perp", "bybit-spot", "bybit-perp", "bsc-pancakeswap"]:
        latest = await ohlcv_aggregator.get_current_price(source)
        if latest:
            prices[source] = latest

    return {
        "timestamp": asyncio.get_event_loop().time(),
        "prices": prices,
    }

@app.get("/api/aggregated-prices")
async def get_aggregated_prices():
    """Get aggregated prices."""
    spot_price = await ohlcv_aggregator.get_aggregated_spot_price()
    perp_price = await ohlcv_aggregator.get_aggregated_perp_price()

    return {
        "timestamp": asyncio.get_event_loop().time(),
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
    return {
        "timestamp": asyncio.get_event_loop().time(),
        "per_source": per_source,
        "aggregated": aggregated,
    }

@app.get("/api/funding")
async def get_funding():
    """Get latest funding rates (Binance perp + Bybit perp)."""
    return {
        "timestamp": asyncio.get_event_loop().time(),
        "rates": oi_funding_poller.get_latest_funding(),
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

@app.get("/api/status")
async def get_status():
    """Get collector status."""
    return {
        "collectors": [
            {"name": c.__class__.__name__, "running": c.running}
            for c in collectors
        ],
        "ring_buffer_size": await ring_buffer.size(),
        "ohlcv_bars": len(ohlcv_aggregator.current_bars),
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
        "timestamp": asyncio.get_event_loop().time(),
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
    uvicorn.run(app, host=API_HOST, port=API_PORT, workers=1)

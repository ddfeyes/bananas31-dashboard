"""FastAPI REST endpoints."""
import time
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from storage import (
    get_latest_orderbook,
    get_recent_trades,
    get_oi_history,
    get_funding_history,
    get_recent_liquidations,
)
from metrics import (
    compute_cvd,
    compute_volume_imbalance,
    compute_oi_momentum,
    classify_market_phase,
)

router = APIRouter(prefix="/api")


@router.get("/orderbook/latest")
async def orderbook_latest(exchange: Optional[str] = None, limit: int = Query(default=1, le=20)):
    data = await get_latest_orderbook(exchange=exchange, limit=limit)
    return {"status": "ok", "data": data, "count": len(data)}


@router.get("/trades/recent")
async def trades_recent(
    limit: int = Query(default=100, le=1000),
    since: Optional[float] = None
):
    data = await get_recent_trades(limit=limit, since=since)
    return {"status": "ok", "data": data, "count": len(data)}


@router.get("/oi/history")
async def oi_history(
    limit: int = Query(default=300, le=2000),
    since: Optional[float] = None
):
    data = await get_oi_history(limit=limit, since=since)
    return {"status": "ok", "data": data, "count": len(data)}


@router.get("/funding/history")
async def funding_history(
    limit: int = Query(default=100, le=1000),
    since: Optional[float] = None
):
    data = await get_funding_history(limit=limit, since=since)
    return {"status": "ok", "data": data, "count": len(data)}


@router.get("/liquidations/recent")
async def liquidations_recent(
    limit: int = Query(default=50, le=500),
    since: Optional[float] = None
):
    data = await get_recent_liquidations(limit=limit, since=since)
    return {"status": "ok", "data": data, "count": len(data)}


@router.get("/cvd/history")
async def cvd_history(window: int = Query(default=3600, le=86400)):
    data = await compute_cvd(window_seconds=window)
    return {"status": "ok", "data": data, "count": len(data)}


@router.get("/metrics/summary")
async def metrics_summary():
    phase_task = classify_market_phase()
    vol_task = compute_volume_imbalance(window_seconds=60)
    oi_task = compute_oi_momentum(window_seconds=300)

    import asyncio
    phase, vol_imb, oi_mom = await asyncio.gather(phase_task, vol_task, oi_task)

    # Latest price from orderbook
    ob = await get_latest_orderbook(limit=1)
    price = ob[0].get("mid_price") if ob else None
    spread = ob[0].get("spread") if ob else None
    imbalance = ob[0].get("imbalance") if ob else None

    # Latest funding
    funding = await get_funding_history(limit=2)
    latest_funding = {}
    for row in funding:
        latest_funding[row["exchange"]] = row["rate"]

    return {
        "status": "ok",
        "ts": time.time(),
        "price": price,
        "spread": spread,
        "orderbook_imbalance": imbalance,
        "phase": phase,
        "volume_imbalance": vol_imb,
        "oi_momentum": oi_mom,
        "funding_rates": latest_funding,
    }

"""Performance optimization tests — TDD (issue #170).

Covers:
  1. Timing middleware exports _timing_middleware and adds X-Response-Time header
  2. DB has proper indexes on pattern_history and phase_snapshots after init_db()
  3. SQLite open_db() applies cache_size and temp_store PRAGMAs
  4. Expensive endpoints populate the in-memory cache on first call
"""

import os
import sys
import tempfile

import aiosqlite
import httpx
import pytest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_perf.db"))
os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
os.environ.setdefault("SYMBOL_BYBIT", "BANANAS31USDT")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage import init_db, DB_PATH  # noqa: E402

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_app():
    """Test app: router + timing middleware imported from production main.py."""
    from fastapi import FastAPI
    from starlette.middleware.base import BaseHTTPMiddleware
    from api import router
    from main import _timing_middleware  # fails if middleware not exported from main

    app = FastAPI()
    app.add_middleware(BaseHTTPMiddleware, dispatch=_timing_middleware)
    app.include_router(router)
    return app


def _client(app=None):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app or _make_app()),
        base_url="http://test",
    )


# ── 1. Timing middleware ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timing_middleware_header_on_symbols():
    """X-Response-Time header must be present on every response."""
    await init_db()
    async with _client() as c:
        r = await c.get("/api/symbols")
    assert r.status_code == 200
    assert "x-response-time" in r.headers, "Missing X-Response-Time header"


@pytest.mark.asyncio
async def test_timing_middleware_header_on_health():
    """X-Response-Time header must appear on /api/health."""
    await init_db()
    async with _client() as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    assert "x-response-time" in r.headers


@pytest.mark.asyncio
async def test_timing_middleware_format():
    """X-Response-Time must be formatted as '<float>ms'."""
    await init_db()
    async with _client() as c:
        r = await c.get("/api/symbols")
    val = r.headers.get("x-response-time", "")
    assert val.endswith("ms"), f"Expected '<float>ms', got: {val!r}"
    elapsed = float(val[:-2])
    assert elapsed >= 0.0, f"Elapsed time must be non-negative, got {elapsed}"


# ── 2. DB indexes ─────────────────────────────────────────────────────────────


async def _index_names(table: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,),
        ) as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


@pytest.mark.asyncio
async def test_init_db_creates_pattern_history_index():
    """init_db must create an index on pattern_history(symbol, ts)."""
    await init_db()
    names = await _index_names("pattern_history")
    assert names, f"No indexes on pattern_history; found: {names}"
    assert any(
        "sym" in n.lower() or "pattern" in n.lower() for n in names
    ), f"Expected a symbol-based index on pattern_history; found: {names}"


@pytest.mark.asyncio
async def test_init_db_creates_phase_snapshots_index():
    """init_db must create an index on phase_snapshots(symbol, ts)."""
    await init_db()
    names = await _index_names("phase_snapshots")
    assert names, f"No indexes on phase_snapshots; found: {names}"
    assert any(
        "sym" in n.lower() or "phase" in n.lower() or "snap" in n.lower() for n in names
    ), f"Expected a symbol-based index on phase_snapshots; found: {names}"


@pytest.mark.asyncio
async def test_core_tables_have_indexes():
    """Core tables must have (symbol, ts) indexes."""
    await init_db()
    for table in ("trades", "open_interest", "funding_rate", "liquidations"):
        names = await _index_names(table)
        assert names, f"No indexes on {table}"


# ── 3. SQLite PRAGMAs ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_db_uses_wal_mode():
    """open_db() must use WAL journal mode."""
    from storage import open_db

    async with open_db() as db:
        async with db.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()
    assert row[0].lower() == "wal"


@pytest.mark.asyncio
async def test_open_db_sets_large_cache():
    """open_db() must set cache_size significantly above the SQLite default (−2000)."""
    from storage import open_db

    async with open_db() as db:
        async with db.execute("PRAGMA cache_size") as cur:
            row = await cur.fetchone()
    # Default is −2000 (2 MB). We require at least −8000 (8 MB).
    assert (
        abs(row[0]) >= 8000
    ), f"cache_size {row[0]} is not much larger than default −2000"


@pytest.mark.asyncio
async def test_open_db_sets_temp_store_memory():
    """open_db() must configure temp_store=MEMORY (value=2) for faster temp tables."""
    from storage import open_db

    async with open_db() as db:
        async with db.execute("PRAGMA temp_store") as cur:
            row = await cur.fetchone()
    # 0=default, 1=FILE, 2=MEMORY
    assert row[0] == 2, f"temp_store expected 2 (MEMORY), got {row[0]}"


# ── 4. Cache population ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_summary_populates_cache():
    """/api/stats/summary must populate the cache so repeated calls are cheap."""
    from cache import cache_clear, cache_size

    await init_db()
    cache_clear()
    async with _client() as c:
        await c.get("/api/stats/summary")
    assert (
        cache_size() > 0
    ), "/api/stats/summary did not populate cache — @cache_result decorator missing?"


@pytest.mark.asyncio
async def test_correlations_populates_cache():
    """/api/correlations must populate cache on first call."""
    from cache import cache_clear, cache_size

    await init_db()
    cache_clear()
    async with _client() as c:
        await c.get("/api/correlations")
    assert (
        cache_size() > 0
    ), "/api/correlations did not populate cache — @cache_result decorator missing?"


@pytest.mark.asyncio
async def test_market_regime_populates_cache():
    """/api/market-regime must populate cache on first call."""
    from cache import cache_clear, cache_size

    await init_db()
    cache_clear()
    async with _client() as c:
        await c.get("/api/market-regime?symbol=BANANAS31USDT")
    assert (
        cache_size() > 0
    ), "/api/market-regime did not populate cache — @cache_result decorator missing?"


@pytest.mark.asyncio
async def test_cvd_history_populates_cache():
    """/api/cvd/history must populate cache on first call."""
    from cache import cache_clear, cache_size

    await init_db()
    cache_clear()
    async with _client() as c:
        await c.get("/api/cvd/history?symbol=BANANAS31USDT")
    assert (
        cache_size() > 0
    ), "/api/cvd/history did not populate cache — @cache_result decorator missing?"


@pytest.mark.asyncio
async def test_multi_summary_populates_cache():
    """/api/multi-summary must populate cache on first call."""
    from cache import cache_clear, cache_size

    await init_db()
    cache_clear()
    async with _client() as c:
        await c.get("/api/multi-summary")
    assert (
        cache_size() > 0
    ), "/api/multi-summary did not populate cache — @cache_result decorator missing?"


@pytest.mark.asyncio
async def test_tape_speed_populates_cache():
    """/api/tape-speed must populate cache on first call."""
    from cache import cache_clear, cache_size

    await init_db()
    cache_clear()
    async with _client() as c:
        await c.get("/api/tape-speed?symbol=BANANAS31USDT")
    assert (
        cache_size() > 0
    ), "/api/tape-speed did not populate cache — @cache_result decorator missing?"

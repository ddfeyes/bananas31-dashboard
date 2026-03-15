"""Tests for backend/cache.py — TTL cache behaviour."""

import asyncio
import os
import sys
import time
import tempfile

import pytest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_cache.db"))
os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
os.environ.setdefault("SYMBOL_BYBIT", "BANANAS31USDT")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cache import (
    cache_clear,
    cache_get,
    cache_set,
    cache_size,
    cache_result,
    make_cache_key,
    _cache,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_between_tests():
    """Ensure a clean cache state before every test."""
    cache_clear()
    yield
    cache_clear()


# ── Unit: make_cache_key ──────────────────────────────────────────────────────


def test_make_cache_key_no_kwargs():
    assert make_cache_key("foo") == "foo"


def test_make_cache_key_with_kwargs():
    key = make_cache_key("ep", symbol="BTC", limit=300)
    assert key == "ep|limit=300|symbol=BTC"


def test_make_cache_key_sorted_kwargs():
    """Key must be identical regardless of kwarg insertion order."""
    k1 = make_cache_key("ep", b=2, a=1)
    k2 = make_cache_key("ep", a=1, b=2)
    assert k1 == k2


def test_make_cache_key_unique_per_symbol():
    k1 = make_cache_key("oi_history", symbol="BANANAS31USDT")
    k2 = make_cache_key("oi_history", symbol="COSUSDT")
    assert k1 != k2


def test_make_cache_key_unique_per_param_value():
    k1 = make_cache_key("volume_profile", window=3600, bins=50)
    k2 = make_cache_key("volume_profile", window=7200, bins=50)
    assert k1 != k2


# ── Unit: cache_get / cache_set ───────────────────────────────────────────────


def test_cache_miss_on_empty():
    hit, value = cache_get("missing_key", ttl_seconds=60)
    assert hit is False
    assert value is None


def test_cache_hit_after_set():
    cache_set("k1", {"data": [1, 2, 3]})
    hit, value = cache_get("k1", ttl_seconds=60)
    assert hit is True
    assert value == {"data": [1, 2, 3]}


def test_cache_miss_after_ttl_expires():
    cache_set("k_short", "hello")
    # Manually backdate the entry so it looks expired
    _cache["k_short"] = (time.time() - 61, "hello")
    hit, value = cache_get("k_short", ttl_seconds=60)
    assert hit is False
    assert value is None


def test_expired_entry_is_evicted():
    cache_set("stale", "data")
    _cache["stale"] = (time.time() - 61, "data")
    cache_get("stale", ttl_seconds=60)  # triggers eviction
    assert "stale" not in _cache


def test_cache_set_overwrites_existing():
    cache_set("k", "old")
    cache_set("k", "new")
    hit, value = cache_get("k", ttl_seconds=60)
    assert hit is True
    assert value == "new"


def test_cache_clear_removes_all():
    cache_set("a", 1)
    cache_set("b", 2)
    assert cache_size() == 2
    cache_clear()
    assert cache_size() == 0


def test_cache_size_tracks_entries():
    assert cache_size() == 0
    cache_set("x", 1)
    assert cache_size() == 1
    cache_set("y", 2)
    assert cache_size() == 2


# ── Unit: cache_result decorator ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decorator_caches_result():
    call_count = 0

    @cache_result(ttl_seconds=60)
    async def fake_endpoint(symbol: str = "BTC"):
        nonlocal call_count
        call_count += 1
        return {"symbol": symbol, "value": call_count}

    r1 = await fake_endpoint(symbol="BTC")
    r2 = await fake_endpoint(symbol="BTC")

    assert r1 == r2
    assert call_count == 1  # only computed once


@pytest.mark.asyncio
async def test_decorator_different_keys_for_different_params():
    call_count = 0

    @cache_result(ttl_seconds=60)
    async def fake_endpoint(symbol: str = "BTC"):
        nonlocal call_count
        call_count += 1
        return {"symbol": symbol, "n": call_count}

    r_btc = await fake_endpoint(symbol="BTC")
    r_eth = await fake_endpoint(symbol="ETH")

    assert r_btc["symbol"] == "BTC"
    assert r_eth["symbol"] == "ETH"
    assert call_count == 2  # each symbol is a separate cache entry


@pytest.mark.asyncio
async def test_decorator_recomputes_after_ttl():
    call_count = 0

    @cache_result(ttl_seconds=60)
    async def fake_endpoint():
        nonlocal call_count
        call_count += 1
        return {"n": call_count}

    await fake_endpoint()
    # Manually expire the cache entry
    key = "fake_endpoint"
    _cache[key] = (time.time() - 61, _cache[key][1])

    await fake_endpoint()
    assert call_count == 2  # recomputed because TTL expired


@pytest.mark.asyncio
async def test_decorator_preserves_function_name():
    @cache_result(ttl_seconds=60)
    async def my_special_endpoint():
        return {}

    assert my_special_endpoint.__name__ == "my_special_endpoint"


@pytest.mark.asyncio
async def test_concurrent_requests_return_same_cached_value():
    """Concurrent requests after cache warm-up all get the cached value."""
    call_count = 0

    @cache_result(ttl_seconds=60)
    async def slow_endpoint(symbol: str = "BTC"):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0)  # yield to event loop
        return {"n": call_count}

    # First call warms the cache
    await slow_endpoint(symbol="BTC")
    # Subsequent concurrent calls should all get the cached value
    results = await asyncio.gather(*[slow_endpoint(symbol="BTC") for _ in range(5)])

    # All 5 results should be identical (cached)
    assert all(r == results[0] for r in results)
    # Only 1 actual computation happened (initial warm-up)
    assert call_count == 1


@pytest.mark.asyncio
async def test_decorator_caches_none_symbol():
    """Endpoints with symbol=None (default) should be cached separately from named symbols."""
    call_count = 0

    @cache_result(ttl_seconds=60)
    async def ep(symbol=None):
        nonlocal call_count
        call_count += 1
        return {"symbol": symbol, "n": call_count}

    await ep(symbol=None)
    await ep(symbol="BANANAS31USDT")

    # Two different cache keys → two calls
    assert call_count == 2

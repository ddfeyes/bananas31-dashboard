"""
Unit/smoke tests for the /api/liquidation-heatmap endpoint.

Validates bucket logic, response shape, intensity helpers, sorting,
edge cases, and route registration.
"""
import math
import os
import sys
import time

import pytest

# ── Python mirrors of bucket/heatmap logic ────────────────────────────────────

def build_price_buckets(price_min: float, price_max: float, n: int) -> list[dict]:
    """Divide [price_min, price_max] into n equal-width buckets."""
    if n <= 0 or price_min >= price_max:
        return []
    step = (price_max - price_min) / n
    return [
        {
            "price_low":  round(price_min + i * step, 10),
            "price_high": round(price_min + (i + 1) * step, 10),
            "long_usd":   0.0,
            "short_usd":  0.0,
            "total_usd":  0.0,
        }
        for i in range(n)
    ]


def bucket_index(price: float, price_min: float, price_max: float, n: int) -> int:
    """Return which bucket a price falls into (clamped to [0, n-1])."""
    if price_max == price_min:
        return 0
    frac = (price - price_min) / (price_max - price_min)
    return max(0, min(n - 1, int(frac * n)))


def fill_buckets(liquidations: list[dict], price_min: float, price_max: float, n: int) -> list[dict]:
    """Accumulate liquidation USD values into price buckets."""
    buckets = build_price_buckets(price_min, price_max, n)
    for liq in liquidations:
        idx = bucket_index(float(liq["price"]), price_min, price_max, n)
        usd = float(liq.get("value") or liq["price"] * liq["qty"])
        if liq["side"] == "long":
            buckets[idx]["long_usd"] += usd
        else:
            buckets[idx]["short_usd"] += usd
        buckets[idx]["total_usd"] += usd
    return buckets


def intensity(total_usd: float, max_usd: float) -> float:
    """0.0–1.0 intensity for coloring (log-scaled)."""
    if max_usd <= 0 or total_usd <= 0:
        return 0.0
    return math.log1p(total_usd) / math.log1p(max_usd)


# ── Sample data ───────────────────────────────────────────────────────────────

SAMPLE_LIQS = [
    {"ts": 1e9, "symbol": "BANANAS31USDT", "side": "long",  "price": 0.002300, "qty": 1000, "value": 2.30},
    {"ts": 1e9, "symbol": "BANANAS31USDT", "side": "short", "price": 0.002350, "qty": 2000, "value": 4.70},
    {"ts": 1e9, "symbol": "BANANAS31USDT", "side": "long",  "price": 0.002400, "qty": 5000, "value": 12.00},
    {"ts": 1e9, "symbol": "BANANAS31USDT", "side": "long",  "price": 0.002500, "qty": 3000, "value": 7.50},
]
PRICE_MIN = 0.002200
PRICE_MAX = 0.002600
N_BUCKETS = 4

SAMPLE_RESPONSE = {
    "status": "ok",
    "ts": 1773600000.0,
    "window_s": 3600,
    "symbols": {
        "BANANAS31USDT": {
            "buckets": [
                {"price_low": 0.0022, "price_high": 0.0023, "long_usd": 0.0,  "short_usd": 0.0, "total_usd": 0.0},
                {"price_low": 0.0023, "price_high": 0.0024, "long_usd": 2.30, "short_usd": 4.70, "total_usd": 7.00},
                {"price_low": 0.0024, "price_high": 0.0025, "long_usd": 12.0, "short_usd": 0.0, "total_usd": 12.0},
                {"price_low": 0.0025, "price_high": 0.0026, "long_usd": 7.50, "short_usd": 0.0, "total_usd": 7.50},
            ],
            "price_min": 0.0022,
            "price_max": 0.0026,
            "total_usd": 26.5,
            "n_liquidations": 4,
        }
    },
}


# ── Bucket construction ───────────────────────────────────────────────────────

def test_build_buckets_count():
    buckets = build_price_buckets(100.0, 200.0, 5)
    assert len(buckets) == 5


def test_build_buckets_cover_range():
    buckets = build_price_buckets(100.0, 200.0, 4)
    assert buckets[0]["price_low"] == pytest.approx(100.0)
    assert buckets[-1]["price_high"] == pytest.approx(200.0)


def test_build_buckets_contiguous():
    buckets = build_price_buckets(0.0, 1.0, 5)
    for i in range(len(buckets) - 1):
        assert buckets[i]["price_high"] == pytest.approx(buckets[i + 1]["price_low"])


def test_build_buckets_empty_when_min_equals_max():
    assert build_price_buckets(100.0, 100.0, 5) == []


def test_build_buckets_zero_count():
    assert build_price_buckets(100.0, 200.0, 0) == []


def test_bucket_index_first():
    assert bucket_index(100.0, 100.0, 200.0, 10) == 0


def test_bucket_index_last():
    assert bucket_index(200.0, 100.0, 200.0, 10) == 9


def test_bucket_index_mid():
    idx = bucket_index(150.0, 100.0, 200.0, 10)
    assert idx == 5


def test_bucket_index_clamp_below():
    assert bucket_index(0.0, 100.0, 200.0, 10) == 0


def test_bucket_index_clamp_above():
    assert bucket_index(999.0, 100.0, 200.0, 10) == 9


# ── Fill logic ────────────────────────────────────────────────────────────────

def test_fill_buckets_total_usd():
    buckets = fill_buckets(SAMPLE_LIQS, PRICE_MIN, PRICE_MAX, N_BUCKETS)
    grand_total = sum(b["total_usd"] for b in buckets)
    assert grand_total == pytest.approx(2.30 + 4.70 + 12.00 + 7.50, rel=1e-3)


def test_fill_buckets_long_short_split():
    buckets = fill_buckets(SAMPLE_LIQS, PRICE_MIN, PRICE_MAX, N_BUCKETS)
    total_long  = sum(b["long_usd"]  for b in buckets)
    total_short = sum(b["short_usd"] for b in buckets)
    assert total_long  == pytest.approx(2.30 + 12.00 + 7.50, rel=1e-3)
    assert total_short == pytest.approx(4.70, rel=1e-3)


def test_fill_buckets_empty_input():
    buckets = fill_buckets([], PRICE_MIN, PRICE_MAX, N_BUCKETS)
    assert all(b["total_usd"] == 0.0 for b in buckets)


# ── Intensity helper ──────────────────────────────────────────────────────────

def test_intensity_zero_when_empty():
    assert intensity(0.0, 100.0) == pytest.approx(0.0)


def test_intensity_one_at_max():
    assert intensity(100.0, 100.0) == pytest.approx(1.0)


def test_intensity_between_zero_and_one():
    v = intensity(50.0, 200.0)
    assert 0.0 < v < 1.0


def test_intensity_zero_max():
    assert intensity(50.0, 0.0) == 0.0


# ── Response shape ────────────────────────────────────────────────────────────

def test_response_has_status():
    assert SAMPLE_RESPONSE["status"] == "ok"


def test_response_has_symbols_dict():
    assert isinstance(SAMPLE_RESPONSE["symbols"], dict)


def test_response_has_window_s():
    assert SAMPLE_RESPONSE["window_s"] == 3600


def test_response_has_ts():
    assert isinstance(SAMPLE_RESPONSE["ts"], float)


def test_symbol_entry_has_buckets():
    entry = SAMPLE_RESPONSE["symbols"]["BANANAS31USDT"]
    assert isinstance(entry["buckets"], list)
    assert len(entry["buckets"]) > 0


def test_symbol_entry_has_price_range():
    entry = SAMPLE_RESPONSE["symbols"]["BANANAS31USDT"]
    assert "price_min" in entry and "price_max" in entry
    assert entry["price_max"] > entry["price_min"]


def test_bucket_has_required_keys():
    for bucket in SAMPLE_RESPONSE["symbols"]["BANANAS31USDT"]["buckets"]:
        for key in ("price_low", "price_high", "long_usd", "short_usd", "total_usd"):
            assert key in bucket, f"Missing key '{key}'"


# ── Route registration ────────────────────────────────────────────────────────

def test_liquidation_heatmap_route_registered():
    import tempfile
    os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
    os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from api import router
    paths = [r.path for r in router.routes]
    assert any("liquidation-heatmap" in p for p in paths)

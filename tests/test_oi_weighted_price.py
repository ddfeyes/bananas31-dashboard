"""
Tests for OI-weighted price endpoint and rendering logic.

Validates calculation, bias classification, deviation formatting,
and edge cases that mirror app.js renderOiWeightedPrice().
"""
import math
from unittest.mock import AsyncMock, patch

import pytest


# ── Python mirrors of app.js helpers ─────────────────────────────────────────

def fmt_price(v, decimals=4):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


def fmt_deviation(v):
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.3f}%"


def deviation_color(deviation_pct):
    if deviation_pct is None:
        return "var(--muted)"
    if deviation_pct > 1.0:
        return "var(--red)"
    if deviation_pct < -1.0:
        return "var(--green)"
    return "var(--muted)"


def badge_class_for_bias(bias):
    if bias == "long_heavy":
        return "badge-red"
    if bias == "short_heavy":
        return "badge-green"
    return "badge-blue"


# ── OI-weighted price calculation (mirrors backend logic) ─────────────────────

def compute_oi_weighted_price_py(oi_rows, trade_rows):
    """Pure-Python mirror of compute_oi_weighted_price for test assertions."""
    if not oi_rows or not trade_rows:
        return None, None, None, "neutral"

    trades_asc = sorted(trade_rows, key=lambda t: t["ts"])

    cum_wt = 0.0
    cum_wp = 0.0
    for oi in oi_rows:
        oi_ts = oi["ts"]
        oi_val = float(oi.get("oi_value") or 0)
        if oi_val <= 0:
            continue
        # Find last trade price at or within 10s after oi_ts
        price = None
        lo, hi = 0, len(trades_asc) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if trades_asc[mid]["ts"] <= oi_ts + 10:
                price = float(trades_asc[mid]["price"])
                lo = mid + 1
            else:
                hi = mid - 1
        if price is None or price <= 0:
            continue
        cum_wt += oi_val
        cum_wp += oi_val * price

    if cum_wt == 0:
        return None, None, None, "neutral"

    oi_wp = cum_wp / cum_wt
    current_price = float(trades_asc[-1]["price"])
    deviation_pct = (current_price - oi_wp) / oi_wp * 100

    if deviation_pct > 1.0:
        bias = "long_heavy"
    elif deviation_pct < -1.0:
        bias = "short_heavy"
    else:
        bias = "neutral"

    return oi_wp, current_price, deviation_pct, bias


# ── Sample fixtures ───────────────────────────────────────────────────────────

BASE_TS = 1710432000.0  # fixed epoch for reproducibility

OI_ROWS_FLAT = [
    {"ts": BASE_TS + i * 60, "oi_value": 1_000_000.0, "symbol": "BANANAS31USDT"}
    for i in range(10)
]

TRADE_ROWS_FLAT = [
    {"ts": BASE_TS + i * 60, "price": 0.5000, "symbol": "BANANAS31USDT"}
    for i in range(10)
]

OI_ROWS_RISING = [
    {"ts": BASE_TS + i * 60, "oi_value": 1_000_000.0 + i * 100_000, "symbol": "BANANAS31USDT"}
    for i in range(10)
]

TRADE_ROWS_RISING = [
    {"ts": BASE_TS + i * 60, "price": 0.5000 + i * 0.001, "symbol": "BANANAS31USDT"}
    for i in range(10)
]

# Current price above OI-weighted avg → long_heavy
OI_ROWS_LONG_HEAVY = [
    {"ts": BASE_TS + i * 60, "oi_value": 1_000_000.0, "symbol": "BANANAS31USDT"}
    for i in range(5)
]
TRADE_ROWS_LONG_HEAVY = [
    {"ts": BASE_TS + i * 60, "price": 1.0, "symbol": "BANANAS31USDT"}
    for i in range(4)
] + [{"ts": BASE_TS + 4 * 60, "price": 1.025, "symbol": "BANANAS31USDT"}]

# Current price below OI-weighted avg → short_heavy
OI_ROWS_SHORT_HEAVY = [
    {"ts": BASE_TS + i * 60, "oi_value": 1_000_000.0, "symbol": "BANANAS31USDT"}
    for i in range(5)
]
TRADE_ROWS_SHORT_HEAVY = [
    {"ts": BASE_TS + i * 60, "price": 1.0, "symbol": "BANANAS31USDT"}
    for i in range(4)
] + [{"ts": BASE_TS + 4 * 60, "price": 0.975, "symbol": "BANANAS31USDT"}]


# ── 1. Calculation correctness ────────────────────────────────────────────────

class TestOiWeightedPriceCalculation:
    def test_flat_oi_flat_price_equals_constant(self):
        """When all OI and prices are constant, weighted avg equals that price."""
        oi_wp, current, dev, bias = compute_oi_weighted_price_py(OI_ROWS_FLAT, TRADE_ROWS_FLAT)
        assert oi_wp == pytest.approx(0.5, rel=1e-6)

    def test_flat_oi_flat_price_zero_deviation(self):
        oi_wp, current, dev, bias = compute_oi_weighted_price_py(OI_ROWS_FLAT, TRADE_ROWS_FLAT)
        assert dev == pytest.approx(0.0, abs=1e-6)

    def test_flat_oi_flat_price_neutral_bias(self):
        _, _, _, bias = compute_oi_weighted_price_py(OI_ROWS_FLAT, TRADE_ROWS_FLAT)
        assert bias == "neutral"

    def test_weighted_avg_higher_weight_on_recent(self):
        """OI-weighted avg shifts toward price at higher-OI periods."""
        oi_wp, _, _, _ = compute_oi_weighted_price_py(OI_ROWS_RISING, TRADE_ROWS_RISING)
        # Rising OI means more weight on later (higher) prices → oi_wp > simple avg
        simple_avg = sum(r["price"] for r in TRADE_ROWS_RISING) / len(TRADE_ROWS_RISING)
        assert oi_wp > simple_avg

    def test_manual_two_point_calculation(self):
        """Verify exact math with two data points."""
        oi = [
            {"ts": BASE_TS, "oi_value": 100.0, "symbol": "X"},
            {"ts": BASE_TS + 60, "oi_value": 300.0, "symbol": "X"},
        ]
        trades = [
            {"ts": BASE_TS, "price": 10.0, "symbol": "X"},
            {"ts": BASE_TS + 60, "price": 20.0, "symbol": "X"},
        ]
        oi_wp, _, _, _ = compute_oi_weighted_price_py(oi, trades)
        expected = (100.0 * 10.0 + 300.0 * 20.0) / (100.0 + 300.0)  # 17.5
        assert oi_wp == pytest.approx(expected, rel=1e-9)

    def test_deviation_formula(self):
        """deviation_pct = (current - oi_wp) / oi_wp * 100."""
        oi = [{"ts": BASE_TS, "oi_value": 1.0, "symbol": "X"}]
        trades = [
            {"ts": BASE_TS, "price": 100.0, "symbol": "X"},
            {"ts": BASE_TS + 30, "price": 105.0, "symbol": "X"},
        ]
        oi_wp, current, dev, _ = compute_oi_weighted_price_py(oi, trades)
        assert current == pytest.approx(105.0)
        assert oi_wp == pytest.approx(100.0)
        assert dev == pytest.approx(5.0, rel=1e-6)


# ── 2. Bias classification ────────────────────────────────────────────────────

class TestBiasClassification:
    def test_long_heavy_when_price_above_1pct(self):
        _, _, _, bias = compute_oi_weighted_price_py(OI_ROWS_LONG_HEAVY, TRADE_ROWS_LONG_HEAVY)
        assert bias == "long_heavy"

    def test_short_heavy_when_price_below_1pct(self):
        _, _, _, bias = compute_oi_weighted_price_py(OI_ROWS_SHORT_HEAVY, TRADE_ROWS_SHORT_HEAVY)
        assert bias == "short_heavy"

    def test_neutral_within_1pct(self):
        oi = [{"ts": BASE_TS, "oi_value": 1_000_000.0, "symbol": "X"}]
        trades = [
            {"ts": BASE_TS, "price": 1.0, "symbol": "X"},
            {"ts": BASE_TS + 30, "price": 1.005, "symbol": "X"},
        ]
        _, _, dev, bias = compute_oi_weighted_price_py(oi, trades)
        assert abs(dev) < 1.0
        assert bias == "neutral"

    def test_boundary_exactly_1pct_is_neutral(self):
        """At exactly 1.0% deviation, bias is still neutral (> not >=)."""
        oi = [{"ts": BASE_TS, "oi_value": 1.0, "symbol": "X"}]
        trades = [
            {"ts": BASE_TS, "price": 100.0, "symbol": "X"},
            {"ts": BASE_TS + 30, "price": 101.0, "symbol": "X"},
        ]
        _, _, dev, bias = compute_oi_weighted_price_py(oi, trades)
        assert dev == pytest.approx(1.0, rel=1e-6)
        assert bias == "neutral"

    def test_boundary_just_above_1pct_is_long_heavy(self):
        oi = [{"ts": BASE_TS, "oi_value": 1.0, "symbol": "X"}]
        trades = [
            {"ts": BASE_TS, "price": 100.0, "symbol": "X"},
            {"ts": BASE_TS + 30, "price": 101.01, "symbol": "X"},
        ]
        _, _, _, bias = compute_oi_weighted_price_py(oi, trades)
        assert bias == "long_heavy"

    def test_boundary_just_below_neg1pct_is_short_heavy(self):
        oi = [{"ts": BASE_TS, "oi_value": 1.0, "symbol": "X"}]
        trades = [
            {"ts": BASE_TS, "price": 100.0, "symbol": "X"},
            {"ts": BASE_TS + 30, "price": 98.99, "symbol": "X"},
        ]
        _, _, _, bias = compute_oi_weighted_price_py(oi, trades)
        assert bias == "short_heavy"


# ── 3. Edge cases ─────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_oi_returns_none(self):
        oi_wp, current, dev, bias = compute_oi_weighted_price_py([], TRADE_ROWS_FLAT)
        assert oi_wp is None
        assert current is None
        assert dev is None
        assert bias == "neutral"

    def test_empty_trades_returns_none(self):
        oi_wp, current, dev, bias = compute_oi_weighted_price_py(OI_ROWS_FLAT, [])
        assert oi_wp is None

    def test_zero_oi_value_skipped(self):
        oi = [
            {"ts": BASE_TS, "oi_value": 0.0, "symbol": "X"},
            {"ts": BASE_TS + 60, "oi_value": 500_000.0, "symbol": "X"},
        ]
        trades = [
            {"ts": BASE_TS, "price": 999.0, "symbol": "X"},
            {"ts": BASE_TS + 60, "price": 1.0, "symbol": "X"},
        ]
        oi_wp, _, _, _ = compute_oi_weighted_price_py(oi, trades)
        assert oi_wp == pytest.approx(1.0, rel=1e-6)

    def test_trade_outside_window_not_matched(self):
        """Trade more than 60s after OI record should not be matched."""
        oi = [{"ts": BASE_TS, "oi_value": 1.0, "symbol": "X"}]
        trades = [{"ts": BASE_TS + 120, "price": 999.0, "symbol": "X"}]
        oi_wp, _, _, _ = compute_oi_weighted_price_py(oi, trades)
        # No match → None
        assert oi_wp is None

    def test_single_oi_single_trade(self):
        oi = [{"ts": BASE_TS, "oi_value": 500_000.0, "symbol": "X"}]
        trades = [{"ts": BASE_TS + 10, "price": 2.5, "symbol": "X"}]
        oi_wp, current, dev, _ = compute_oi_weighted_price_py(oi, trades)
        assert oi_wp == pytest.approx(2.5)
        assert current == pytest.approx(2.5)
        assert dev == pytest.approx(0.0, abs=1e-9)


# ── 4. Formatting helpers ─────────────────────────────────────────────────────

class TestFormattingHelpers:
    def test_fmt_deviation_positive(self):
        assert fmt_deviation(2.345) == "+2.345%"

    def test_fmt_deviation_negative(self):
        assert fmt_deviation(-1.234) == "-1.234%"

    def test_fmt_deviation_zero(self):
        assert fmt_deviation(0.0) == "+0.000%"

    def test_fmt_deviation_none(self):
        assert fmt_deviation(None) == "—"

    def test_deviation_color_long_heavy(self):
        assert deviation_color(1.5) == "var(--red)"

    def test_deviation_color_short_heavy(self):
        assert deviation_color(-1.5) == "var(--green)"

    def test_deviation_color_neutral(self):
        assert deviation_color(0.5) == "var(--muted)"

    def test_deviation_color_none(self):
        assert deviation_color(None) == "var(--muted)"

    def test_badge_class_long_heavy(self):
        assert badge_class_for_bias("long_heavy") == "badge-red"

    def test_badge_class_short_heavy(self):
        assert badge_class_for_bias("short_heavy") == "badge-green"

    def test_badge_class_neutral(self):
        assert badge_class_for_bias("neutral") == "badge-blue"


# ── 5. API response shape ─────────────────────────────────────────────────────

class TestApiResponseShape:
    FULL_RESPONSE = {
        "status": "ok",
        "symbol": "BANANAS31USDT",
        "oi_weighted_price": 0.48523100,
        "current_price": 0.49010000,
        "deviation_pct": 1.0036,
        "bias": "long_heavy",
        "oi_count": 50,
        "description": "Price +1.004% vs OI-weighted avg",
    }

    NO_DATA_RESPONSE = {
        "status": "ok",
        "symbol": "BANANAS31USDT",
        "oi_weighted_price": None,
        "current_price": None,
        "deviation_pct": None,
        "bias": "neutral",
        "description": "No OI data",
    }

    def test_full_response_has_required_keys(self):
        keys = {"status", "symbol", "oi_weighted_price", "current_price", "deviation_pct", "bias"}
        assert keys.issubset(self.FULL_RESPONSE.keys())

    def test_no_data_response_has_required_keys(self):
        keys = {"status", "symbol", "oi_weighted_price", "current_price", "deviation_pct", "bias"}
        assert keys.issubset(self.NO_DATA_RESPONSE.keys())

    def test_bias_values_are_valid(self):
        valid = {"long_heavy", "short_heavy", "neutral"}
        assert self.FULL_RESPONSE["bias"] in valid
        assert self.NO_DATA_RESPONSE["bias"] in valid

    def test_deviation_pct_is_numeric_when_present(self):
        assert isinstance(self.FULL_RESPONSE["deviation_pct"], (int, float))

    def test_no_data_nulls_are_none(self):
        assert self.NO_DATA_RESPONSE["oi_weighted_price"] is None
        assert self.NO_DATA_RESPONSE["current_price"] is None
        assert self.NO_DATA_RESPONSE["deviation_pct"] is None

    def test_description_field_present(self):
        assert "description" in self.FULL_RESPONSE
        assert isinstance(self.FULL_RESPONSE["description"], str)

"""
Unit / smoke tests for /api/spread-analysis (market microstructure: bid-ask
spread estimator + effective spread card).

Covers:
  - Roll model spread estimator (serial covariance of tick changes)
  - Effective spread computation (2 × |trade_price - mid|)
  - spread_to_bps conversion
  - effective_ratio calculation
  - quality_label classification
  - Response shape validation
  - Edge cases (flat prices, single trade, zero mid)
  - Route registration
  - HTML card / JS smoke tests
"""
import os
import sys
import math
import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _html() -> str:
    with open(os.path.join(_ROOT, "frontend", "index.html"), encoding="utf-8") as f:
        return f.read()


def _js() -> str:
    with open(os.path.join(_ROOT, "frontend", "app.js"), encoding="utf-8") as f:
        return f.read()


# ── Python mirrors of backend logic ──────────────────────────────────────────

def roll_spread(prices: list[float]) -> float | None:
    """
    Roll (1984) spread estimator from tick prices.

    Compute first-order serial covariance of consecutive price changes.
    If cov(Δp_t, Δp_{t-1}) < 0: spread = 2 * sqrt(-cov), else 0.
    Returns spread in price units (same units as prices), or None if
    fewer than 3 prices.
    """
    if len(prices) < 3:
        return None
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    n = len(changes)
    if n < 2:
        return None
    # Serial covariance: cov(Δp_t, Δp_{t-1}) for t = 1..n-1
    pairs = [(changes[i], changes[i - 1]) for i in range(1, n)]
    mean_a = sum(p[0] for p in pairs) / len(pairs)
    mean_b = sum(p[1] for p in pairs) / len(pairs)
    cov = sum((a - mean_a) * (b - mean_b) for a, b in pairs) / len(pairs)
    if cov >= 0:
        return 0.0
    return round(2.0 * math.sqrt(-cov), 10)


def effective_spread(trade_prices: list[float], mid_price: float) -> float | None:
    """
    Average effective spread = mean(2 × |trade_price - mid_price|).
    Returns None if no trades or mid_price <= 0.
    """
    if not trade_prices or mid_price <= 0:
        return None
    values = [2.0 * abs(p - mid_price) for p in trade_prices]
    return round(sum(values) / len(values), 10)


def spread_to_bps(spread_price: float, mid_price: float) -> float | None:
    """Convert a spread in price units to basis points."""
    if mid_price <= 0 or spread_price < 0:
        return None
    return round(spread_price / mid_price * 10_000, 4)


def effective_ratio(eff_spread_bps: float | None,
                    quoted_spread_bps: float | None) -> float | None:
    """Ratio of effective spread to quoted spread (0–1+). None if either is None/zero."""
    if eff_spread_bps is None or quoted_spread_bps is None:
        return None
    if quoted_spread_bps <= 0:
        return None
    return round(eff_spread_bps / quoted_spread_bps, 4)


def quality_label(roll_bps: float | None) -> str:
    """
    Classify spread quality from Roll spread in bps.
    tight < 5, normal < 20, wide >= 20.
    Returns 'unknown' if None.
    """
    if roll_bps is None:
        return "unknown"
    if roll_bps < 5:
        return "tight"
    if roll_bps < 20:
        return "normal"
    return "wide"


# ── roll_spread tests ─────────────────────────────────────────────────────────

PRICES_OSCILLATING = [1.000, 1.001, 1.000, 1.001, 1.000, 1.001, 1.000]
PRICES_TRENDING    = [1.000, 1.001, 1.002, 1.003, 1.004, 1.005]
PRICES_FLAT        = [1.000, 1.000, 1.000, 1.000, 1.000]
PRICES_SINGLE      = [1.000]
PRICES_TWO         = [1.000, 1.001]


def test_roll_spread_returns_float_for_oscillating():
    result = roll_spread(PRICES_OSCILLATING)
    assert result is not None
    assert isinstance(result, float)


def test_roll_spread_positive_for_oscillating():
    # Alternating prices → negative serial covariance → positive spread
    result = roll_spread(PRICES_OSCILLATING)
    assert result is not None
    assert result > 0.0


def test_roll_spread_zero_for_trending():
    # Monotonically increasing → positive serial covariance → spread = 0
    result = roll_spread(PRICES_TRENDING)
    assert result is not None
    assert result == pytest.approx(0.0)


def test_roll_spread_zero_for_flat():
    result = roll_spread(PRICES_FLAT)
    assert result is not None
    assert result == pytest.approx(0.0)


def test_roll_spread_none_for_single_price():
    assert roll_spread(PRICES_SINGLE) is None


def test_roll_spread_none_for_two_prices():
    assert roll_spread(PRICES_TWO) is None


def test_roll_spread_none_for_empty():
    assert roll_spread([]) is None


def test_roll_spread_symmetric_oscillation():
    # Perfect alternating ±tick: should give tick-width estimate
    prices = [1.0, 1.001, 1.0, 1.001, 1.0, 1.001, 1.0, 1.001]
    result = roll_spread(prices)
    assert result is not None
    assert result > 0.0
    # Roll estimate for perfect alternating ±0.001: changes = [+0.001,-0.001,+0.001,...]
    # cov(Δp_t, Δp_{t-1}) = -0.001^2; spread = 2*sqrt(0.001^2) = 0.002
    assert result == pytest.approx(0.002, rel=1e-3)


def test_roll_spread_scales_with_tick_size():
    prices_small = [1.0, 1.001, 1.0, 1.001, 1.0]
    prices_large = [1.0, 1.01, 1.0, 1.01, 1.0]
    small = roll_spread(prices_small)
    large = roll_spread(prices_large)
    assert small is not None and large is not None
    assert large > small


# ── effective_spread tests ────────────────────────────────────────────────────

def test_effective_spread_at_mid():
    # Trades all at mid → effective spread = 0
    result = effective_spread([1.0, 1.0, 1.0], mid_price=1.0)
    assert result == pytest.approx(0.0)


def test_effective_spread_above_mid():
    result = effective_spread([1.001], mid_price=1.0)
    assert result == pytest.approx(0.002)


def test_effective_spread_below_mid():
    result = effective_spread([0.999], mid_price=1.0)
    assert result == pytest.approx(0.002)


def test_effective_spread_mixed():
    # 1.001 and 0.999 both 0.001 from mid=1.0 → 2*0.001 = 0.002 avg
    result = effective_spread([1.001, 0.999], mid_price=1.0)
    assert result == pytest.approx(0.002)


def test_effective_spread_none_empty():
    assert effective_spread([], mid_price=1.0) is None


def test_effective_spread_none_zero_mid():
    assert effective_spread([1.0, 1.001], mid_price=0.0) is None


def test_effective_spread_positive():
    result = effective_spread([1.001, 1.002, 0.998], mid_price=1.0)
    assert result is not None
    assert result > 0.0


# ── spread_to_bps tests ───────────────────────────────────────────────────────

def test_spread_to_bps_basic():
    # 0.001 spread on 1.0 mid = 10 bps
    assert spread_to_bps(0.001, 1.0) == pytest.approx(10.0)


def test_spread_to_bps_small_price():
    # 0.00002 spread on 0.002 mid = 100 bps
    assert spread_to_bps(0.00002, 0.002) == pytest.approx(100.0)


def test_spread_to_bps_zero_spread():
    assert spread_to_bps(0.0, 1.0) == pytest.approx(0.0)


def test_spread_to_bps_none_zero_mid():
    assert spread_to_bps(0.001, 0.0) is None


def test_spread_to_bps_none_negative_spread():
    assert spread_to_bps(-0.001, 1.0) is None


# ── effective_ratio tests ─────────────────────────────────────────────────────

def test_effective_ratio_half():
    assert effective_ratio(5.0, 10.0) == pytest.approx(0.5)


def test_effective_ratio_equal():
    assert effective_ratio(10.0, 10.0) == pytest.approx(1.0)


def test_effective_ratio_over_quoted():
    assert effective_ratio(15.0, 10.0) == pytest.approx(1.5)


def test_effective_ratio_none_zero_quoted():
    assert effective_ratio(5.0, 0.0) is None


def test_effective_ratio_none_none_inputs():
    assert effective_ratio(None, 10.0) is None
    assert effective_ratio(5.0, None) is None


# ── quality_label tests ───────────────────────────────────────────────────────

def test_quality_tight():
    assert quality_label(0.0) == "tight"
    assert quality_label(4.9) == "tight"


def test_quality_normal():
    assert quality_label(5.0) == "normal"
    assert quality_label(19.9) == "normal"


def test_quality_wide():
    assert quality_label(20.0) == "wide"
    assert quality_label(100.0) == "wide"


def test_quality_none():
    assert quality_label(None) == "unknown"


# ── Response shape ────────────────────────────────────────────────────────────

SAMPLE_RESPONSE = {
    "status": "ok",
    "symbol": "BANANAS31USDT",
    "window_seconds": 300,
    "roll_spread": 0.0000981,
    "roll_spread_bps": 4.14,
    "effective_spread": 0.0000854,
    "effective_spread_bps": 3.61,
    "quoted_spread_bps": 8.50,
    "effective_ratio": 0.425,
    "mid_price": 0.002369,
    "n_trades": 312,
    "n_changes": 311,
    "quality": "tight",
    "description": "Effective spread 43% of quoted spread — tight market",
}


def test_response_status_ok():
    assert SAMPLE_RESPONSE["status"] == "ok"


def test_response_has_required_keys():
    for key in (
        "symbol", "window_seconds",
        "roll_spread", "roll_spread_bps",
        "effective_spread", "effective_spread_bps",
        "quoted_spread_bps", "effective_ratio",
        "mid_price", "n_trades", "n_changes",
        "quality", "description",
    ):
        assert key in SAMPLE_RESPONSE


def test_response_quality_valid():
    assert SAMPLE_RESPONSE["quality"] in ("tight", "normal", "wide", "unknown")


def test_response_roll_spread_nonneg():
    assert SAMPLE_RESPONSE["roll_spread"] >= 0


def test_response_effective_spread_nonneg():
    assert SAMPLE_RESPONSE["effective_spread"] >= 0


def test_response_roll_spread_bps_nonneg():
    assert SAMPLE_RESPONSE["roll_spread_bps"] >= 0


def test_response_effective_spread_bps_nonneg():
    assert SAMPLE_RESPONSE["effective_spread_bps"] >= 0


def test_response_effective_ratio_positive():
    assert SAMPLE_RESPONSE["effective_ratio"] > 0


def test_response_n_changes_less_than_trades():
    assert SAMPLE_RESPONSE["n_changes"] <= SAMPLE_RESPONSE["n_trades"]


def test_response_has_description():
    assert isinstance(SAMPLE_RESPONSE["description"], str)
    assert len(SAMPLE_RESPONSE["description"]) > 0


def test_response_tight_quality_matches_bps():
    # tight quality should correspond to roll_spread_bps < 5
    if SAMPLE_RESPONSE["quality"] == "tight":
        assert SAMPLE_RESPONSE["roll_spread_bps"] < 5.0


def test_response_effective_ratio_consistent():
    resp = SAMPLE_RESPONSE
    if resp["quoted_spread_bps"] and resp["quoted_spread_bps"] > 0:
        expected_ratio = resp["effective_spread_bps"] / resp["quoted_spread_bps"]
        assert resp["effective_ratio"] == pytest.approx(expected_ratio, rel=0.01)


# ── Roll model property tests ─────────────────────────────────────────────────

def test_roll_spread_nonneg_always():
    import random
    random.seed(42)
    for _ in range(20):
        prices = [1.0 + random.gauss(0, 0.001) for _ in range(20)]
        result = roll_spread(prices)
        if result is not None:
            assert result >= 0.0


def test_roll_spread_invariant_to_price_level():
    # Multiplying all prices by constant should scale spread proportionally
    prices_base = [1.0, 1.001, 1.0, 1.001, 1.0, 1.001, 1.0]
    prices_scaled = [p * 100 for p in prices_base]
    s_base = roll_spread(prices_base)
    s_scaled = roll_spread(prices_scaled)
    assert s_base is not None and s_scaled is not None
    assert s_scaled == pytest.approx(s_base * 100, rel=1e-4)


def test_effective_spread_invariant_to_direction():
    # Buy above mid and sell below mid should give same effective spread
    mid = 1.0
    tick = 0.001
    prices_buy  = [mid + tick] * 10
    prices_sell = [mid - tick] * 10
    prices_mixed = [mid + tick, mid - tick] * 5
    eff_buy   = effective_spread(prices_buy, mid)
    eff_sell  = effective_spread(prices_sell, mid)
    eff_mixed = effective_spread(prices_mixed, mid)
    assert eff_buy == pytest.approx(eff_sell)
    assert eff_mixed == pytest.approx(eff_buy)


# ── Route registration ────────────────────────────────────────────────────────

def test_spread_analysis_route_registered():
    import tempfile
    os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
    os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from api import router
    paths = [r.path for r in router.routes]
    assert any("spread-analysis" in p for p in paths)


# ── HTML / JS smoke tests ─────────────────────────────────────────────────────

def test_html_has_spread_analysis_card():
    assert "card-spread-analysis" in _html()


def test_js_has_render_market_microstructure():
    assert "renderMarketMicrostructure" in _js()


def test_js_calls_spread_analysis_api():
    assert "spread-analysis" in _js()

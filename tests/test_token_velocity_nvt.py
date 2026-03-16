"""
Unit / smoke tests for /api/token-velocity-nvt.

Token velocity + NVT ratio card — on-chain signal for BTC valuation.

Key metrics:
  velocity    = tx_volume_usd / circulating_supply_usd (proxy)
              = tx_volume_usd / market_cap_usd  (when supply proxy = market cap)
  NVT ratio   = market_cap_usd / tx_volume_usd
  NVT signal  = market_cap_usd / (28-day MA of tx_volume_usd)

Thresholds:
  NVT signal > 150  → overbought  (price exceeds on-chain utility)
  NVT signal < 45   → oversold    (price undervalues on-chain utility)
  45–90             → fair_value
  90–150            → neutral

Velocity trend:
  7d avg > 30d avg × 1.05  → accelerating
  7d avg < 30d avg × 0.95  → decelerating
  otherwise                → stable

Covers:
  - _tv_velocity
  - _tv_nvt_ratio
  - _tv_nvt_signal
  - _tv_nvt_label
  - _tv_moving_average
  - _tv_velocity_trend
  - _tv_zscore
  - Response shape / key validation
  - Structural: route, HTML card, JS function, JS API call
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import (
    _tv_velocity,
    _tv_nvt_ratio,
    _tv_nvt_signal,
    _tv_nvt_label,
    _tv_moving_average,
    _tv_velocity_trend,
    _tv_zscore,
)

# ---------------------------------------------------------------------------
# Sample response fixture
# ---------------------------------------------------------------------------

SAMPLE_RESPONSE = {
    "velocity": {
        "current":      0.082,
        "trend":        "accelerating",
        "velocity_7d":  0.079,
        "velocity_30d": 0.072,
    },
    "nvt": {
        "ratio":                 98.5,
        "signal":               112.3,
        "label":                "neutral",
        "zscore":                0.45,
        "overbought_threshold": 150,
        "oversold_threshold":    45,
    },
    "history": [
        {"date": "2024-11-14", "velocity": 0.075, "nvt_ratio": 95.2,  "nvt_signal": 108.1},
        {"date": "2024-11-15", "velocity": 0.078, "nvt_ratio": 97.1,  "nvt_signal": 109.4},
        {"date": "2024-11-16", "velocity": 0.071, "nvt_ratio": 103.0, "nvt_signal": 110.0},
        {"date": "2024-11-17", "velocity": 0.080, "nvt_ratio": 96.8,  "nvt_signal": 110.8},
        {"date": "2024-11-18", "velocity": 0.082, "nvt_ratio": 98.5,  "nvt_signal": 112.3},
    ],
    "market_cap_usd":     1_200_000_000_000.0,
    "tx_volume_24h_usd":     98_400_000_000.0,
    "description": "NVT neutral: ratio 98.5 — fair value zone",
}


# ===========================================================================
# 1. _tv_velocity
# ===========================================================================

class TestTvVelocity:
    def test_typical_returns_ratio(self):
        # tx_vol=100B, market_cap=1T → velocity = 0.1
        vel = _tv_velocity(100_000_000_000.0, 1_000_000_000_000.0)
        assert vel == pytest.approx(0.1, rel=1e-4)

    def test_zero_supply_returns_zero(self):
        assert _tv_velocity(1_000_000.0, 0.0) == pytest.approx(0.0, abs=1e-9)

    def test_zero_tx_volume_returns_zero(self):
        assert _tv_velocity(0.0, 1_000_000_000_000.0) == pytest.approx(0.0, abs=1e-9)

    def test_both_zero_returns_zero(self):
        assert _tv_velocity(0.0, 0.0) == pytest.approx(0.0, abs=1e-9)

    def test_higher_volume_higher_velocity(self):
        v_low  = _tv_velocity(50_000_000_000.0,  1_000_000_000_000.0)
        v_high = _tv_velocity(200_000_000_000.0, 1_000_000_000_000.0)
        assert v_high > v_low

    def test_returns_float(self):
        assert isinstance(_tv_velocity(1e11, 1e12), float)

    def test_velocity_equals_tx_over_supply(self):
        tx, supply = 7_500_000_000.0, 100_000_000_000.0
        assert _tv_velocity(tx, supply) == pytest.approx(tx / supply, rel=1e-6)


# ===========================================================================
# 2. _tv_nvt_ratio
# ===========================================================================

class TestTvNvtRatio:
    def test_typical_nvt(self):
        # mktcap=1T, tx_vol=10B → NVT=100
        nvt = _tv_nvt_ratio(1_000_000_000_000.0, 10_000_000_000.0)
        assert nvt == pytest.approx(100.0, rel=1e-4)

    def test_zero_tx_volume_returns_zero(self):
        assert _tv_nvt_ratio(1_000_000_000_000.0, 0.0) == pytest.approx(0.0, abs=1e-9)

    def test_zero_market_cap_returns_zero(self):
        assert _tv_nvt_ratio(0.0, 10_000_000_000.0) == pytest.approx(0.0, abs=1e-9)

    def test_higher_mktcap_higher_nvt(self):
        nvt_low  = _tv_nvt_ratio(500_000_000_000.0,  10_000_000_000.0)
        nvt_high = _tv_nvt_ratio(2_000_000_000_000.0, 10_000_000_000.0)
        assert nvt_high > nvt_low

    def test_higher_tx_volume_lower_nvt(self):
        nvt_low_vol  = _tv_nvt_ratio(1_000_000_000_000.0, 5_000_000_000.0)
        nvt_high_vol = _tv_nvt_ratio(1_000_000_000_000.0, 20_000_000_000.0)
        assert nvt_low_vol > nvt_high_vol

    def test_returns_float(self):
        assert isinstance(_tv_nvt_ratio(1e12, 1e10), float)


# ===========================================================================
# 3. _tv_nvt_signal
# ===========================================================================

class TestTvNvtSignal:
    def test_typical_nvt_signal(self):
        # mktcap=1T, ma28=10B → signal=100
        sig = _tv_nvt_signal(1_000_000_000_000.0, 10_000_000_000.0)
        assert sig == pytest.approx(100.0, rel=1e-4)

    def test_zero_ma_returns_zero(self):
        assert _tv_nvt_signal(1_000_000_000_000.0, 0.0) == pytest.approx(0.0, abs=1e-9)

    def test_zero_market_cap_returns_zero(self):
        assert _tv_nvt_signal(0.0, 10_000_000_000.0) == pytest.approx(0.0, abs=1e-9)

    def test_higher_ma_lower_signal(self):
        sig_low_ma  = _tv_nvt_signal(1_000_000_000_000.0, 5_000_000_000.0)
        sig_high_ma = _tv_nvt_signal(1_000_000_000_000.0, 20_000_000_000.0)
        assert sig_low_ma > sig_high_ma

    def test_same_as_nvt_ratio_when_ma_equals_current(self):
        # When 28d MA equals today's volume, NVT signal == NVT ratio
        mktcap = 1_200_000_000_000.0
        vol    = 12_000_000_000.0
        assert _tv_nvt_signal(mktcap, vol) == pytest.approx(
            _tv_nvt_ratio(mktcap, vol), rel=1e-6
        )

    def test_returns_float(self):
        assert isinstance(_tv_nvt_signal(1e12, 1e10), float)


# ===========================================================================
# 4. _tv_nvt_label
# ===========================================================================

class TestTvNvtLabel:
    def test_above_150_is_overbought(self):
        assert _tv_nvt_label(160.0) == "overbought"

    def test_exactly_150_is_overbought(self):
        assert _tv_nvt_label(150.0) == "overbought"

    def test_between_90_and_150_is_neutral(self):
        assert _tv_nvt_label(120.0) == "neutral"

    def test_between_45_and_90_is_fair_value(self):
        assert _tv_nvt_label(65.0) == "fair_value"

    def test_below_45_is_oversold(self):
        assert _tv_nvt_label(30.0) == "oversold"

    def test_exactly_45_is_fair_value(self):
        assert _tv_nvt_label(45.0) == "fair_value"

    def test_exactly_90_is_neutral(self):
        assert _tv_nvt_label(90.0) == "neutral"

    def test_returns_valid_string(self):
        for v in (20.0, 50.0, 100.0, 200.0):
            result = _tv_nvt_label(v)
            assert result in ("overbought", "neutral", "fair_value", "oversold")


# ===========================================================================
# 5. _tv_moving_average
# ===========================================================================

class TestTvMovingAverage:
    def test_empty_returns_zero(self):
        assert _tv_moving_average([], 28) == pytest.approx(0.0, abs=1e-9)

    def test_single_value_returns_that_value(self):
        assert _tv_moving_average([42.0], 28) == pytest.approx(42.0, rel=1e-6)

    def test_window_equals_len(self):
        vals = [10.0, 20.0, 30.0]
        assert _tv_moving_average(vals, 3) == pytest.approx(20.0, rel=1e-6)

    def test_window_larger_than_len_uses_all(self):
        vals = [10.0, 20.0, 30.0]
        assert _tv_moving_average(vals, 100) == pytest.approx(20.0, rel=1e-6)

    def test_window_smaller_uses_last_n(self):
        vals = [100.0, 200.0, 10.0, 20.0, 30.0]
        # last 3: 10, 20, 30 → avg=20
        assert _tv_moving_average(vals, 3) == pytest.approx(20.0, rel=1e-6)

    def test_returns_float(self):
        assert isinstance(_tv_moving_average([1.0, 2.0, 3.0], 3), float)


# ===========================================================================
# 6. _tv_velocity_trend
# ===========================================================================

class TestTvVelocityTrend:
    def test_7d_much_higher_than_30d_is_accelerating(self):
        assert _tv_velocity_trend(0.12, 0.08) == "accelerating"

    def test_7d_much_lower_than_30d_is_decelerating(self):
        assert _tv_velocity_trend(0.06, 0.10) == "decelerating"

    def test_similar_values_is_stable(self):
        assert _tv_velocity_trend(0.10, 0.10) == "stable"

    def test_zero_both_is_stable(self):
        assert _tv_velocity_trend(0.0, 0.0) == "stable"

    def test_returns_valid_string(self):
        result = _tv_velocity_trend(0.08, 0.09)
        assert result in ("accelerating", "decelerating", "stable")

    def test_just_above_threshold_is_accelerating(self):
        # 7d = 30d * 1.06 → above 1.05 threshold
        v30 = 0.10
        v7  = v30 * 1.06
        assert _tv_velocity_trend(v7, v30) == "accelerating"


# ===========================================================================
# 7. _tv_zscore
# ===========================================================================

class TestTvZscore:
    def test_empty_history_returns_zero(self):
        assert _tv_zscore(100.0, []) == 0.0

    def test_single_history_returns_zero(self):
        assert _tv_zscore(100.0, [100.0]) == 0.0

    def test_current_at_mean_returns_near_zero(self):
        history = [80.0, 90.0, 100.0, 110.0, 120.0]
        assert abs(_tv_zscore(100.0, history)) < 0.01

    def test_above_mean_returns_positive(self):
        history = [80.0, 90.0, 95.0, 100.0]
        assert _tv_zscore(200.0, history) > 0

    def test_below_mean_returns_negative(self):
        history = [100.0, 110.0, 120.0, 130.0]
        assert _tv_zscore(0.0, history) < 0

    def test_uniform_history_returns_zero(self):
        history = [100.0] * 10
        assert _tv_zscore(100.0, history) == pytest.approx(0.0, abs=0.01)


# ===========================================================================
# 8. SAMPLE_RESPONSE structure
# ===========================================================================

class TestSampleResponseShape:
    def test_has_velocity_dict(self):
        assert isinstance(SAMPLE_RESPONSE["velocity"], dict)

    def test_velocity_has_required_keys(self):
        for key in ("current", "trend", "velocity_7d", "velocity_30d"):
            assert key in SAMPLE_RESPONSE["velocity"], f"velocity missing '{key}'"

    def test_velocity_trend_is_valid(self):
        assert SAMPLE_RESPONSE["velocity"]["trend"] in (
            "accelerating", "decelerating", "stable"
        )

    def test_has_nvt_dict(self):
        assert isinstance(SAMPLE_RESPONSE["nvt"], dict)

    def test_nvt_has_required_keys(self):
        for key in ("ratio", "signal", "label", "zscore",
                    "overbought_threshold", "oversold_threshold"):
            assert key in SAMPLE_RESPONSE["nvt"], f"nvt missing '{key}'"

    def test_nvt_label_is_valid(self):
        assert SAMPLE_RESPONSE["nvt"]["label"] in (
            "overbought", "neutral", "fair_value", "oversold"
        )

    def test_nvt_thresholds_correct(self):
        assert SAMPLE_RESPONSE["nvt"]["overbought_threshold"] == 150
        assert SAMPLE_RESPONSE["nvt"]["oversold_threshold"]   == 45

    def test_has_history_list(self):
        assert isinstance(SAMPLE_RESPONSE["history"], list)

    def test_history_items_have_required_keys(self):
        for item in SAMPLE_RESPONSE["history"]:
            for key in ("date", "velocity", "nvt_ratio", "nvt_signal"):
                assert key in item, f"history item missing '{key}'"

    def test_has_market_cap(self):
        assert "market_cap_usd" in SAMPLE_RESPONSE
        assert SAMPLE_RESPONSE["market_cap_usd"] > 0

    def test_has_tx_volume(self):
        assert "tx_volume_24h_usd" in SAMPLE_RESPONSE
        assert SAMPLE_RESPONSE["tx_volume_24h_usd"] > 0

    def test_has_description(self):
        assert isinstance(SAMPLE_RESPONSE["description"], str)


# ===========================================================================
# 9. Structural tests
# ===========================================================================

class TestStructural:
    def test_route_registered_in_api_py(self):
        api_path = os.path.join(os.path.dirname(__file__), "..", "backend", "api.py")
        content = open(api_path).read()
        assert "/token-velocity-nvt" in content, "/token-velocity-nvt route missing"

    def test_html_card_exists(self):
        html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
        content = open(html_path).read()
        assert "card-token-velocity-nvt" in content, "card-token-velocity-nvt missing"

    def test_js_render_function_exists(self):
        js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
        content = open(js_path).read()
        assert "renderTokenVelocityNvt" in content, "renderTokenVelocityNvt missing"

    def test_js_api_call_to_endpoint(self):
        js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
        content = open(js_path).read()
        assert "/token-velocity-nvt" in content, "/token-velocity-nvt call missing"

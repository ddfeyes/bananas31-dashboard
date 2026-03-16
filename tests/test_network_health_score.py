"""
Unit / smoke tests for /api/network-health-score.

Composite network health score — combines four on-chain signals into a
single 0-100 gauge for Bitcoin network vitality.

Components (equal 25% weight each):
  hash_rate       — 7d vs 30d hash rate trend (security & miner commitment)
  mempool         — tx backlog congestion (inverted: low congestion = high score)
  active_addresses— 7d vs 30d MA of unique active addresses (demand proxy)
  fee_pressure    — current sat/vbyte vs 30d median (inverted: low fees = high score)

Labels:
  90–100  excellent
  70–89   healthy
  50–69   neutral
  30–49   stressed
  0–29    critical

Trend:
  improving — score rising  (last half avg > first half avg + threshold)
  declining — score falling (last half avg < first half avg - threshold)
  stable    — otherwise

Covers:
  - _nh_hash_rate_score
  - _nh_mempool_score
  - _nh_address_score
  - _nh_fee_score
  - _nh_composite
  - _nh_health_label
  - _nh_trend
  - _nh_normalize
  - Response shape / key validation
  - Structural: route, HTML card, JS function, JS API call
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import (
    _nh_hash_rate_score,
    _nh_mempool_score,
    _nh_address_score,
    _nh_fee_score,
    _nh_composite,
    _nh_health_label,
    _nh_trend,
    _nh_normalize,
)

# ---------------------------------------------------------------------------
# Sample response fixture
# ---------------------------------------------------------------------------

SAMPLE_RESPONSE = {
    "score": 72.4,
    "label": "healthy",
    "trend": "improving",
    "components": {
        "hash_rate": {
            "score":      80.0,
            "weight":     0.25,
            "current_eh": 650.5,
            "ma_30d_eh":  620.0,
            "trend":      "improving",
        },
        "mempool": {
            "score":       65.0,
            "weight":      0.25,
            "tx_count":    12_000,
            "congestion":  "moderate",
        },
        "active_addresses": {
            "score":    70.0,
            "weight":   0.25,
            "current":  850_000,
            "ma_30d":   820_000,
            "trend":    "stable",
        },
        "fee_pressure": {
            "score":         74.0,
            "weight":        0.25,
            "sat_per_vbyte": 15.0,
            "level":         "moderate",
        },
    },
    "history": [
        {"date": "2024-11-14", "score": 65.1, "label": "neutral"},
        {"date": "2024-11-15", "score": 67.3, "label": "neutral"},
        {"date": "2024-11-16", "score": 69.0, "label": "neutral"},
        {"date": "2024-11-17", "score": 70.8, "label": "healthy"},
        {"date": "2024-11-18", "score": 71.5, "label": "healthy"},
        {"date": "2024-11-19", "score": 72.0, "label": "healthy"},
        {"date": "2024-11-20", "score": 72.4, "label": "healthy"},
    ],
    "description": "Healthy: composite network score 72/100 — hash rate rising",
}


# ===========================================================================
# 1. _nh_hash_rate_score
# ===========================================================================

class TestNhHashRateScore:
    def test_7d_above_30d_returns_above_50(self):
        assert _nh_hash_rate_score(700.0, 600.0) > 50

    def test_7d_below_30d_returns_below_50(self):
        assert _nh_hash_rate_score(500.0, 600.0) < 50

    def test_equal_returns_50(self):
        assert _nh_hash_rate_score(600.0, 600.0) == pytest.approx(50.0, abs=1.0)

    def test_zero_ma_returns_50(self):
        # No baseline → neutral
        assert _nh_hash_rate_score(600.0, 0.0) == pytest.approx(50.0, abs=1.0)

    def test_result_in_0_100(self):
        for h7, h30 in [(1000.0, 100.0), (100.0, 1000.0), (500.0, 500.0)]:
            s = _nh_hash_rate_score(h7, h30)
            assert 0.0 <= s <= 100.0

    def test_returns_float(self):
        assert isinstance(_nh_hash_rate_score(600.0, 580.0), float)

    def test_large_improvement_approaches_100(self):
        s = _nh_hash_rate_score(2000.0, 100.0)
        assert s > 80.0


# ===========================================================================
# 2. _nh_mempool_score
# ===========================================================================

class TestNhMempoolScore:
    def test_zero_txs_returns_100(self):
        assert _nh_mempool_score(0, 100_000) == pytest.approx(100.0, abs=0.1)

    def test_full_mempool_returns_near_zero(self):
        assert _nh_mempool_score(100_000, 100_000) == pytest.approx(0.0, abs=0.1)

    def test_half_full_returns_near_50(self):
        s = _nh_mempool_score(50_000, 100_000)
        assert s == pytest.approx(50.0, abs=1.0)

    def test_above_max_clamped_to_zero(self):
        assert _nh_mempool_score(200_000, 100_000) == pytest.approx(0.0, abs=0.1)

    def test_result_in_0_100(self):
        for cnt in (0, 10_000, 50_000, 100_000, 200_000):
            s = _nh_mempool_score(cnt, 100_000)
            assert 0.0 <= s <= 100.0

    def test_returns_float(self):
        assert isinstance(_nh_mempool_score(20_000, 100_000), float)


# ===========================================================================
# 3. _nh_address_score
# ===========================================================================

class TestNhAddressScore:
    def test_current_above_ma_returns_above_50(self):
        assert _nh_address_score(900_000, 800_000) > 50

    def test_current_below_ma_returns_below_50(self):
        assert _nh_address_score(700_000, 800_000) < 50

    def test_equal_returns_50(self):
        assert _nh_address_score(800_000, 800_000) == pytest.approx(50.0, abs=1.0)

    def test_zero_ma_returns_50(self):
        assert _nh_address_score(800_000, 0) == pytest.approx(50.0, abs=1.0)

    def test_result_in_0_100(self):
        for curr, ma in [(1_000_000, 500_000), (300_000, 800_000), (800_000, 800_000)]:
            s = _nh_address_score(curr, ma)
            assert 0.0 <= s <= 100.0

    def test_returns_float(self):
        assert isinstance(_nh_address_score(850_000, 820_000), float)


# ===========================================================================
# 4. _nh_fee_score
# ===========================================================================

class TestNhFeeScore:
    def test_fee_below_avg_returns_above_50(self):
        # Low fees → healthy → higher score
        assert _nh_fee_score(5.0, 20.0) > 50

    def test_fee_above_avg_returns_below_50(self):
        # High fees → stressed → lower score
        assert _nh_fee_score(50.0, 20.0) < 50

    def test_fee_equals_avg_returns_50(self):
        assert _nh_fee_score(20.0, 20.0) == pytest.approx(50.0, abs=1.0)

    def test_zero_avg_returns_50(self):
        assert _nh_fee_score(15.0, 0.0) == pytest.approx(50.0, abs=1.0)

    def test_result_in_0_100(self):
        for curr, avg in [(1.0, 20.0), (100.0, 20.0), (20.0, 20.0)]:
            s = _nh_fee_score(curr, avg)
            assert 0.0 <= s <= 100.0

    def test_returns_float(self):
        assert isinstance(_nh_fee_score(15.0, 20.0), float)


# ===========================================================================
# 5. _nh_composite
# ===========================================================================

class TestNhComposite:
    def test_equal_weights_equal_scores_returns_that_score(self):
        scores  = {"a": 70.0, "b": 70.0, "c": 70.0, "d": 70.0}
        weights = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}
        assert _nh_composite(scores, weights) == pytest.approx(70.0, rel=1e-4)

    def test_weighted_average(self):
        scores  = {"a": 100.0, "b": 0.0}
        weights = {"a": 0.75,  "b": 0.25}
        assert _nh_composite(scores, weights) == pytest.approx(75.0, rel=1e-4)

    def test_empty_returns_zero(self):
        assert _nh_composite({}, {}) == pytest.approx(0.0, abs=1e-6)

    def test_result_in_0_100(self):
        scores  = {"a": 80.0, "b": 60.0, "c": 40.0, "d": 90.0}
        weights = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}
        s = _nh_composite(scores, weights)
        assert 0.0 <= s <= 100.0

    def test_returns_float(self):
        scores  = {"a": 70.0}
        weights = {"a": 1.0}
        assert isinstance(_nh_composite(scores, weights), float)

    def test_missing_weight_key_ignored(self):
        # Score key not in weights → ignored (weight 0)
        scores  = {"a": 80.0, "b": 60.0}
        weights = {"a": 1.0}
        assert _nh_composite(scores, weights) == pytest.approx(80.0, rel=1e-4)


# ===========================================================================
# 6. _nh_health_label
# ===========================================================================

class TestNhHealthLabel:
    def test_100_is_excellent(self):
        assert _nh_health_label(100.0) == "excellent"

    def test_90_is_excellent(self):
        assert _nh_health_label(90.0) == "excellent"

    def test_80_is_healthy(self):
        assert _nh_health_label(80.0) == "healthy"

    def test_60_is_neutral(self):
        assert _nh_health_label(60.0) == "neutral"

    def test_40_is_stressed(self):
        assert _nh_health_label(40.0) == "stressed"

    def test_20_is_critical(self):
        assert _nh_health_label(20.0) == "critical"

    def test_returns_valid_string(self):
        for v in (5.0, 35.0, 55.0, 75.0, 95.0):
            assert _nh_health_label(v) in (
                "excellent", "healthy", "neutral", "stressed", "critical"
            )


# ===========================================================================
# 7. _nh_trend
# ===========================================================================

class TestNhTrend:
    def test_empty_returns_stable(self):
        assert _nh_trend([]) == "stable"

    def test_single_returns_stable(self):
        assert _nh_trend([72.0]) == "stable"

    def test_rising_series_is_improving(self):
        assert _nh_trend([60.0, 62.0, 65.0, 68.0, 72.0, 75.0]) == "improving"

    def test_falling_series_is_declining(self):
        assert _nh_trend([75.0, 72.0, 68.0, 65.0, 62.0, 58.0]) == "declining"

    def test_flat_series_is_stable(self):
        assert _nh_trend([70.0] * 7) == "stable"

    def test_returns_valid_string(self):
        assert _nh_trend([65.0, 67.0, 69.0]) in ("improving", "declining", "stable")


# ===========================================================================
# 8. _nh_normalize
# ===========================================================================

class TestNhNormalize:
    def test_at_min_returns_0(self):
        assert _nh_normalize(0.0, 0.0, 100.0) == pytest.approx(0.0, abs=0.1)

    def test_at_max_returns_100(self):
        assert _nh_normalize(100.0, 0.0, 100.0) == pytest.approx(100.0, abs=0.1)

    def test_midpoint_returns_50(self):
        assert _nh_normalize(50.0, 0.0, 100.0) == pytest.approx(50.0, abs=0.1)

    def test_clamps_below_min(self):
        assert _nh_normalize(-10.0, 0.0, 100.0) == pytest.approx(0.0, abs=0.1)

    def test_clamps_above_max(self):
        assert _nh_normalize(150.0, 0.0, 100.0) == pytest.approx(100.0, abs=0.1)

    def test_zero_range_returns_50(self):
        assert _nh_normalize(5.0, 5.0, 5.0) == pytest.approx(50.0, abs=0.1)


# ===========================================================================
# 9. SAMPLE_RESPONSE structure
# ===========================================================================

class TestSampleResponseShape:
    def test_has_score(self):
        assert 0 <= SAMPLE_RESPONSE["score"] <= 100

    def test_has_label(self):
        assert SAMPLE_RESPONSE["label"] in (
            "excellent", "healthy", "neutral", "stressed", "critical"
        )

    def test_has_trend(self):
        assert SAMPLE_RESPONSE["trend"] in ("improving", "declining", "stable")

    def test_has_components_dict(self):
        assert isinstance(SAMPLE_RESPONSE["components"], dict)

    def test_all_four_components_present(self):
        for key in ("hash_rate", "mempool", "active_addresses", "fee_pressure"):
            assert key in SAMPLE_RESPONSE["components"], f"missing component '{key}'"

    def test_each_component_has_score_and_weight(self):
        for name, comp in SAMPLE_RESPONSE["components"].items():
            assert "score"  in comp, f"{name} missing 'score'"
            assert "weight" in comp, f"{name} missing 'weight'"

    def test_component_scores_in_range(self):
        for name, comp in SAMPLE_RESPONSE["components"].items():
            assert 0 <= comp["score"] <= 100, f"{name} score out of range"

    def test_weights_sum_to_one(self):
        total = sum(c["weight"] for c in SAMPLE_RESPONSE["components"].values())
        assert total == pytest.approx(1.0, rel=1e-4)

    def test_has_history_list(self):
        assert isinstance(SAMPLE_RESPONSE["history"], list)

    def test_history_items_have_required_keys(self):
        for item in SAMPLE_RESPONSE["history"]:
            for key in ("date", "score", "label"):
                assert key in item, f"history item missing '{key}'"

    def test_has_description(self):
        assert isinstance(SAMPLE_RESPONSE["description"], str)


# ===========================================================================
# 10. Structural tests
# ===========================================================================

class TestStructural:
    def test_route_registered_in_api_py(self):
        api_path = os.path.join(os.path.dirname(__file__), "..", "backend", "api.py")
        content = open(api_path).read()
        assert "/network-health-score" in content, "/network-health-score route missing"

    def test_html_card_exists(self):
        html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
        content = open(html_path).read()
        assert "card-network-health-score" in content, "card-network-health-score missing"

    def test_js_render_function_exists(self):
        js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
        content = open(js_path).read()
        assert "renderNetworkHealthScore" in content, "renderNetworkHealthScore missing"

    def test_js_api_call_to_endpoint(self):
        js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
        content = open(js_path).read()
        assert "/network-health-score" in content, "/network-health-score call missing"

"""
Unit / smoke tests for /api/cross-chain-bridge-monitor.

Cross-chain bridge monitor — tracks bridge activity and flows across
ETH/BSC/ARB/OP/BASE chains with anomaly detection.

Covers:
  - _cb_net_flow
  - _cb_flow_label
  - _cb_chain_dominance
  - _cb_utilization_rate
  - _cb_anomaly_flag
  - _cb_bridge_rank
  - _cb_volume_zscore
  - _cb_congestion_label
  - Response shape / key validation
  - Structural: route, HTML card, JS function, JS API call
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import (
    _cb_net_flow,
    _cb_flow_label,
    _cb_chain_dominance,
    _cb_utilization_rate,
    _cb_anomaly_flag,
    _cb_bridge_rank,
    _cb_volume_zscore,
    _cb_congestion_label,
)

# ---------------------------------------------------------------------------
# Sample response fixture
# ---------------------------------------------------------------------------

SAMPLE_RESPONSE = {
    "chains": {
        "ETH":  {"inflow_24h": 450.2, "outflow_24h": 380.1, "net_flow": 70.1,  "flow_label": "inflow"},
        "BSC":  {"inflow_24h": 210.5, "outflow_24h": 245.0, "net_flow": -34.5, "flow_label": "outflow"},
        "ARB":  {"inflow_24h": 320.0, "outflow_24h": 290.0, "net_flow": 30.0,  "flow_label": "inflow"},
        "OP":   {"inflow_24h": 180.0, "outflow_24h": 175.0, "net_flow": 5.0,   "flow_label": "balanced"},
        "BASE": {"inflow_24h":  95.0, "outflow_24h":  80.0, "net_flow": 15.0,  "flow_label": "inflow"},
    },
    "bridges": [
        {"name": "Stargate", "volume_24h": 520.0, "rank": 1},
        {"name": "Across",   "volume_24h": 310.0, "rank": 2},
        {"name": "Hop",      "volume_24h": 205.0, "rank": 3},
        {"name": "Synapse",  "volume_24h": 140.0, "rank": 4},
        {"name": "CCTP",     "volume_24h":  80.0, "rank": 5},
    ],
    "dominance": {"chain": "ETH", "inflow_pct": 35.2},
    "congestion": {"label": "moderate", "avg_wait_seconds": 180},
    "anomalies": [
        {"chain": "ETH", "inflow_24h": 450.2, "avg_7d": 210.0, "ratio": 2.14},
    ],
    "utilization": {"ETH": 72.5, "ARB": 58.0},
    "total_volume_24h": 1255.7,
    "zscore": 1.6,
    "description": "ETH dominant bridge inflow 35% — Stargate leads volume — moderate congestion",
}


# ===========================================================================
# 1. _cb_net_flow
# ===========================================================================

class TestCbNetFlow:
    def test_inflow_greater_than_outflow(self):
        assert _cb_net_flow(500.0, 300.0) == pytest.approx(200.0, abs=1e-4)

    def test_outflow_greater_than_inflow(self):
        assert _cb_net_flow(300.0, 500.0) == pytest.approx(-200.0, abs=1e-4)

    def test_equal_returns_zero(self):
        assert _cb_net_flow(400.0, 400.0) == pytest.approx(0.0, abs=1e-6)

    def test_zero_inflow(self):
        assert _cb_net_flow(0.0, 100.0) == pytest.approx(-100.0, abs=1e-4)

    def test_zero_outflow(self):
        assert _cb_net_flow(100.0, 0.0) == pytest.approx(100.0, abs=1e-4)

    def test_both_zero(self):
        assert _cb_net_flow(0.0, 0.0) == pytest.approx(0.0, abs=1e-6)

    def test_returns_float(self):
        assert isinstance(_cb_net_flow(100.0, 80.0), float)


# ===========================================================================
# 2. _cb_flow_label
# ===========================================================================

class TestCbFlowLabel:
    def test_positive_net_is_inflow(self):
        assert _cb_flow_label(50.0) == "inflow"

    def test_negative_net_is_outflow(self):
        assert _cb_flow_label(-50.0) == "outflow"

    def test_zero_is_balanced(self):
        assert _cb_flow_label(0.0) == "balanced"

    def test_small_positive_below_threshold_is_balanced(self):
        assert _cb_flow_label(0.1) == "balanced"

    def test_small_negative_above_threshold_is_balanced(self):
        assert _cb_flow_label(-0.1) == "balanced"

    def test_large_inflow(self):
        assert _cb_flow_label(1000.0) == "inflow"

    def test_large_outflow(self):
        assert _cb_flow_label(-1000.0) == "outflow"

    def test_returns_valid_string(self):
        for net in [-100.0, -1.0, 0.0, 1.0, 100.0]:
            assert _cb_flow_label(net) in ("inflow", "outflow", "balanced")


# ===========================================================================
# 3. _cb_chain_dominance
# ===========================================================================

class TestCbChainDominance:
    def test_empty_returns_unknown(self):
        assert _cb_chain_dominance({}) == "unknown"

    def test_single_chain_returns_that_chain(self):
        assert _cb_chain_dominance({"ETH": 500.0}) == "ETH"

    def test_returns_chain_with_highest_inflow(self):
        flows = {"ETH": 450.0, "BSC": 210.0, "ARB": 320.0}
        assert _cb_chain_dominance(flows) == "ETH"

    def test_arb_dominance(self):
        flows = {"ETH": 100.0, "BSC": 50.0, "ARB": 800.0}
        assert _cb_chain_dominance(flows) == "ARB"

    def test_handles_equal_values(self):
        flows = {"ETH": 100.0, "BSC": 100.0}
        result = _cb_chain_dominance(flows)
        assert result in ("ETH", "BSC")

    def test_returns_string(self):
        assert isinstance(_cb_chain_dominance({"ETH": 500.0}), str)


# ===========================================================================
# 4. _cb_utilization_rate
# ===========================================================================

class TestCbUtilizationRate:
    def test_zero_volume_returns_zero(self):
        assert _cb_utilization_rate(0.0, 1000.0) == pytest.approx(0.0, abs=1e-6)

    def test_full_capacity_returns_100(self):
        assert _cb_utilization_rate(1000.0, 1000.0) == pytest.approx(100.0, abs=1e-4)

    def test_half_capacity_returns_50(self):
        assert _cb_utilization_rate(500.0, 1000.0) == pytest.approx(50.0, abs=1e-4)

    def test_over_capacity_clamped_to_100(self):
        assert _cb_utilization_rate(1500.0, 1000.0) == pytest.approx(100.0, abs=1e-4)

    def test_zero_capacity_returns_zero(self):
        assert _cb_utilization_rate(500.0, 0.0) == pytest.approx(0.0, abs=1e-6)

    def test_result_in_0_100_range(self):
        for vol, cap in [(0, 1000), (250, 1000), (500, 1000), (1000, 1000), (2000, 1000)]:
            result = _cb_utilization_rate(float(vol), float(cap))
            assert 0.0 <= result <= 100.0

    def test_returns_float(self):
        assert isinstance(_cb_utilization_rate(500.0, 1000.0), float)


# ===========================================================================
# 5. _cb_anomaly_flag
# ===========================================================================

class TestCbAnomalyFlag:
    def test_exactly_2x_is_flagged(self):
        assert _cb_anomaly_flag(200.0, 100.0) is True

    def test_above_2x_is_flagged(self):
        assert _cb_anomaly_flag(300.0, 100.0) is True

    def test_below_2x_not_flagged(self):
        assert _cb_anomaly_flag(150.0, 100.0) is False

    def test_equal_to_average_not_flagged(self):
        assert _cb_anomaly_flag(100.0, 100.0) is False

    def test_zero_average_not_flagged(self):
        assert _cb_anomaly_flag(100.0, 0.0) is False

    def test_zero_current_not_flagged(self):
        assert _cb_anomaly_flag(0.0, 100.0) is False

    def test_returns_bool(self):
        assert isinstance(_cb_anomaly_flag(300.0, 100.0), bool)


# ===========================================================================
# 6. _cb_bridge_rank
# ===========================================================================

class TestCbBridgeRank:
    def test_empty_returns_empty_list(self):
        assert _cb_bridge_rank({}) == []

    def test_single_bridge_rank_1(self):
        result = _cb_bridge_rank({"Stargate": 500.0})
        assert result[0]["name"] == "Stargate"
        assert result[0]["rank"] == 1

    def test_sorted_by_volume_descending(self):
        volumes = {"Hop": 100.0, "Stargate": 500.0, "Across": 300.0}
        result = _cb_bridge_rank(volumes)
        assert result[0]["name"] == "Stargate"
        assert result[1]["name"] == "Across"
        assert result[2]["name"] == "Hop"

    def test_ranks_are_sequential(self):
        volumes = {"A": 300.0, "B": 200.0, "C": 100.0}
        result = _cb_bridge_rank(volumes)
        assert [r["rank"] for r in result] == [1, 2, 3]

    def test_top_5_limit(self):
        volumes = {f"Bridge{i}": float(100 - i) for i in range(10)}
        result = _cb_bridge_rank(volumes, top_n=5)
        assert len(result) == 5

    def test_each_entry_has_required_keys(self):
        result = _cb_bridge_rank({"Stargate": 500.0, "Across": 300.0})
        for entry in result:
            assert "name" in entry
            assert "volume_24h" in entry
            assert "rank" in entry

    def test_returns_list(self):
        assert isinstance(_cb_bridge_rank({"Stargate": 500.0}), list)


# ===========================================================================
# 7. _cb_volume_zscore
# ===========================================================================

class TestCbVolumeZscore:
    def test_empty_history_returns_zero(self):
        assert _cb_volume_zscore(100.0, []) == pytest.approx(0.0, abs=1e-6)

    def test_single_history_returns_zero(self):
        assert _cb_volume_zscore(100.0, [100.0]) == pytest.approx(0.0, abs=1e-6)

    def test_at_mean_returns_near_zero(self):
        history = [80.0, 100.0, 120.0, 100.0, 80.0]
        mean = sum(history) / len(history)
        assert abs(_cb_volume_zscore(mean, history)) < 0.01

    def test_above_mean_positive(self):
        history = [100.0, 110.0, 90.0, 100.0]
        assert _cb_volume_zscore(200.0, history) > 0

    def test_below_mean_negative(self):
        history = [100.0, 110.0, 90.0, 100.0]
        assert _cb_volume_zscore(0.0, history) < 0

    def test_uniform_history_returns_zero(self):
        history = [100.0] * 7
        assert _cb_volume_zscore(100.0, history) == pytest.approx(0.0, abs=0.01)

    def test_returns_float(self):
        assert isinstance(_cb_volume_zscore(100.0, [80.0, 100.0, 120.0]), float)


# ===========================================================================
# 8. _cb_congestion_label
# ===========================================================================

class TestCbCongestionLabel:
    def test_very_fast_is_low(self):
        assert _cb_congestion_label(30) == "low"

    def test_moderate_wait(self):
        assert _cb_congestion_label(180) == "moderate"

    def test_high_wait(self):
        assert _cb_congestion_label(600) == "high"

    def test_severe_wait(self):
        assert _cb_congestion_label(1800) == "severe"

    def test_zero_seconds_is_low(self):
        assert _cb_congestion_label(0) == "low"

    def test_returns_valid_string(self):
        for secs in [0, 60, 300, 900, 3600]:
            assert _cb_congestion_label(secs) in ("low", "moderate", "high", "severe")

    def test_returns_string(self):
        assert isinstance(_cb_congestion_label(120), str)


# ===========================================================================
# 9. SAMPLE_RESPONSE structure
# ===========================================================================

class TestSampleResponseShape:
    def test_has_chains_dict(self):
        assert isinstance(SAMPLE_RESPONSE["chains"], dict)

    def test_chains_has_all_five(self):
        for chain in ("ETH", "BSC", "ARB", "OP", "BASE"):
            assert chain in SAMPLE_RESPONSE["chains"], f"chains missing '{chain}'"

    def test_each_chain_has_required_keys(self):
        for chain, data in SAMPLE_RESPONSE["chains"].items():
            for key in ("inflow_24h", "outflow_24h", "net_flow", "flow_label"):
                assert key in data, f"{chain} missing '{key}'"

    def test_flow_label_values_valid(self):
        for chain, data in SAMPLE_RESPONSE["chains"].items():
            assert data["flow_label"] in ("inflow", "outflow", "balanced")

    def test_has_bridges_list(self):
        assert isinstance(SAMPLE_RESPONSE["bridges"], list)

    def test_bridges_count_is_5(self):
        assert len(SAMPLE_RESPONSE["bridges"]) == 5

    def test_each_bridge_has_required_keys(self):
        for b in SAMPLE_RESPONSE["bridges"]:
            for key in ("name", "volume_24h", "rank"):
                assert key in b, f"bridge missing '{key}'"

    def test_bridge_ranks_sequential(self):
        ranks = sorted(b["rank"] for b in SAMPLE_RESPONSE["bridges"])
        assert ranks == [1, 2, 3, 4, 5]

    def test_has_dominance_dict(self):
        assert isinstance(SAMPLE_RESPONSE["dominance"], dict)

    def test_dominance_has_required_keys(self):
        for key in ("chain", "inflow_pct"):
            assert key in SAMPLE_RESPONSE["dominance"], f"dominance missing '{key}'"

    def test_dominance_inflow_pct_in_range(self):
        pct = SAMPLE_RESPONSE["dominance"]["inflow_pct"]
        assert 0.0 <= pct <= 100.0

    def test_has_congestion_dict(self):
        assert isinstance(SAMPLE_RESPONSE["congestion"], dict)

    def test_congestion_has_required_keys(self):
        for key in ("label", "avg_wait_seconds"):
            assert key in SAMPLE_RESPONSE["congestion"], f"congestion missing '{key}'"

    def test_has_anomalies_list(self):
        assert isinstance(SAMPLE_RESPONSE["anomalies"], list)

    def test_anomaly_items_have_required_keys(self):
        for a in SAMPLE_RESPONSE["anomalies"]:
            for key in ("chain", "inflow_24h", "avg_7d", "ratio"):
                assert key in a, f"anomaly missing '{key}'"

    def test_has_total_volume(self):
        assert "total_volume_24h" in SAMPLE_RESPONSE
        assert SAMPLE_RESPONSE["total_volume_24h"] > 0

    def test_has_zscore(self):
        assert "zscore" in SAMPLE_RESPONSE
        assert isinstance(SAMPLE_RESPONSE["zscore"], float)

    def test_has_description(self):
        assert isinstance(SAMPLE_RESPONSE["description"], str)


# ===========================================================================
# 10. Structural tests
# ===========================================================================

class TestStructural:
    def test_route_registered_in_api_py(self):
        api_path = os.path.join(os.path.dirname(__file__), "..", "backend", "api.py")
        content = open(api_path).read()
        assert "/cross-chain-bridge-monitor" in content, "/cross-chain-bridge-monitor route missing"

    def test_html_card_exists(self):
        html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
        content = open(html_path).read()
        assert "card-cross-chain-bridge" in content, "card-cross-chain-bridge missing"

    def test_js_render_function_exists(self):
        js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
        content = open(js_path).read()
        assert "renderCrossChainBridge" in content, "renderCrossChainBridge missing"

    def test_js_api_call_to_endpoint(self):
        js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
        content = open(js_path).read()
        assert "/cross-chain-bridge-monitor" in content, "/cross-chain-bridge-monitor call missing"

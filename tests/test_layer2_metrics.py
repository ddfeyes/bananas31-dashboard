"""
Unit / smoke tests for /api/layer2-metrics.

Layer 2 Metrics Aggregator — TVL by L2 chain, bridge inflow/outflow 24h,
transaction count comparison, gas savings vs L1, and growth momentum score.

L2 chains covered: Arbitrum, Optimism, Base, Polygon, zkSync

Approach:
  - TVL per chain from DeFi Llama free API (no key)
  - Bridge flows: 24h delta in TVL used as inflow/outflow proxy
  - Transaction counts: relative throughput vs Ethereum L1
  - Gas savings: (L1 avg gas cost - L2 avg gas cost) / L1 avg gas cost
  - Growth momentum: composite score combining TVL change + tx growth

Signal:
  strong_growth  — momentum >= 70
  growing        — momentum >= 50
  neutral        — momentum >= 30
  declining      — momentum < 30

Covers:
  - _l2_tvl_share
  - _l2_bridge_flow_direction
  - _l2_gas_savings_pct
  - _l2_momentum_score
  - _l2_growth_label
  - _l2_rank_chains
  - _l2_tvl_change_pct
  - Response shape / key validation
  - Structural: route, HTML card, JS function, JS API call
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import (
    _l2_tvl_share,
    _l2_bridge_flow_direction,
    _l2_gas_savings_pct,
    _l2_momentum_score,
    _l2_growth_label,
    _l2_rank_chains,
    _l2_tvl_change_pct,
)

# ---------------------------------------------------------------------------
# Sample response fixture
# ---------------------------------------------------------------------------

SAMPLE_RESPONSE = {
    "chains": {
        "Arbitrum": {
            "tvl_usd":          18_500_000_000,
            "tvl_change_24h_pct":  1.2,
            "tvl_change_7d_pct":   4.5,
            "bridge_flow_24h_usd": 120_000_000,
            "bridge_direction":    "inflow",
            "tx_count_24h":        950_000,
            "avg_gas_usd":            0.04,
            "gas_savings_pct":       97.3,
            "momentum":              72.0,
        },
        "Optimism": {
            "tvl_usd":           7_200_000_000,
            "tvl_change_24h_pct":  0.8,
            "tvl_change_7d_pct":   2.1,
            "bridge_flow_24h_usd":  45_000_000,
            "bridge_direction":    "inflow",
            "tx_count_24h":        420_000,
            "avg_gas_usd":            0.05,
            "gas_savings_pct":       96.7,
            "momentum":              61.0,
        },
        "Base": {
            "tvl_usd":           4_800_000_000,
            "tvl_change_24h_pct":  2.5,
            "tvl_change_7d_pct":   8.2,
            "bridge_flow_24h_usd":  85_000_000,
            "bridge_direction":    "inflow",
            "tx_count_24h":        680_000,
            "avg_gas_usd":            0.03,
            "gas_savings_pct":       98.0,
            "momentum":              78.0,
        },
        "Polygon": {
            "tvl_usd":           1_100_000_000,
            "tvl_change_24h_pct": -0.5,
            "tvl_change_7d_pct":  -1.2,
            "bridge_flow_24h_usd": -15_000_000,
            "bridge_direction":   "outflow",
            "tx_count_24h":        310_000,
            "avg_gas_usd":            0.02,
            "gas_savings_pct":       98.7,
            "momentum":              38.0,
        },
        "zkSync": {
            "tvl_usd":             820_000_000,
            "tvl_change_24h_pct":   0.3,
            "tvl_change_7d_pct":    1.0,
            "bridge_flow_24h_usd":   8_000_000,
            "bridge_direction":    "inflow",
            "tx_count_24h":         95_000,
            "avg_gas_usd":            0.06,
            "gas_savings_pct":       96.0,
            "momentum":              44.0,
        },
    },
    "aggregate": {
        "total_tvl_usd":         32_420_000_000,
        "total_tvl_change_24h_pct": 1.1,
        "total_bridge_inflow_24h":  258_000_000,
        "total_tx_count_24h":     2_455_000,
        "l1_vs_l2_tx_ratio":          0.18,
        "avg_gas_savings_pct":       97.3,
        "top_chain":            "Arbitrum",
    },
    "momentum": {
        "score":        62.5,
        "label":        "growing",
        "leader":       "Base",
        "laggard":      "Polygon",
    },
    "history_7d": [
        {"date": "2024-11-14", "total_tvl_usd": 30_500_000_000, "momentum": 55.0},
        {"date": "2024-11-15", "total_tvl_usd": 31_000_000_000, "momentum": 58.0},
        {"date": "2024-11-16", "total_tvl_usd": 30_800_000_000, "momentum": 56.0},
        {"date": "2024-11-17", "total_tvl_usd": 31_500_000_000, "momentum": 60.0},
        {"date": "2024-11-18", "total_tvl_usd": 32_000_000_000, "momentum": 61.0},
        {"date": "2024-11-19", "total_tvl_usd": 32_100_000_000, "momentum": 62.0},
        {"date": "2024-11-20", "total_tvl_usd": 32_420_000_000, "momentum": 62.5},
    ],
    "description": "Growing: L2 total TVL $32.4B — Arbitrum leads, Base momentum strongest",
}


# ===========================================================================
# 1. _l2_tvl_share
# ===========================================================================

class TestL2TvlShare:
    def test_equal_tvls_returns_equal_shares(self):
        chains = {"A": 500, "B": 500}
        shares = _l2_tvl_share(chains)
        assert shares["A"] == pytest.approx(50.0, abs=0.01)
        assert shares["B"] == pytest.approx(50.0, abs=0.01)

    def test_shares_sum_to_100(self):
        chains = {"A": 100, "B": 200, "C": 300, "D": 400}
        shares = _l2_tvl_share(chains)
        assert sum(shares.values()) == pytest.approx(100.0, abs=0.1)

    def test_dominant_chain_over_50_pct(self):
        chains = {"Big": 800, "Small": 200}
        shares = _l2_tvl_share(chains)
        assert shares["Big"] > 50.0

    def test_empty_returns_empty(self):
        assert _l2_tvl_share({}) == {}

    def test_zero_total_returns_zero_shares(self):
        chains = {"A": 0, "B": 0}
        shares = _l2_tvl_share(chains)
        for v in shares.values():
            assert v == pytest.approx(0.0, abs=1e-6)

    def test_returns_floats(self):
        shares = _l2_tvl_share({"A": 300, "B": 700})
        assert all(isinstance(v, float) for v in shares.values())

    def test_single_chain_is_100(self):
        shares = _l2_tvl_share({"Only": 1_000_000})
        assert shares["Only"] == pytest.approx(100.0, abs=0.01)


# ===========================================================================
# 2. _l2_bridge_flow_direction
# ===========================================================================

class TestL2BridgeFlowDirection:
    def test_positive_flow_is_inflow(self):
        assert _l2_bridge_flow_direction(50_000_000) == "inflow"

    def test_negative_flow_is_outflow(self):
        assert _l2_bridge_flow_direction(-30_000_000) == "outflow"

    def test_zero_is_neutral(self):
        assert _l2_bridge_flow_direction(0) == "neutral"

    def test_small_positive_below_threshold_is_neutral(self):
        assert _l2_bridge_flow_direction(500_000, threshold=1_000_000) == "neutral"

    def test_above_threshold_is_inflow(self):
        assert _l2_bridge_flow_direction(1_500_000, threshold=1_000_000) == "inflow"

    def test_returns_valid_string(self):
        result = _l2_bridge_flow_direction(100_000_000)
        assert result in ("inflow", "outflow", "neutral")


# ===========================================================================
# 3. _l2_gas_savings_pct
# ===========================================================================

class TestL2GasSavingsPct:
    def test_zero_l1_gas_returns_zero(self):
        assert _l2_gas_savings_pct(0.0, 0.05) == pytest.approx(0.0, abs=1e-6)

    def test_free_l2_returns_100(self):
        assert _l2_gas_savings_pct(1.50, 0.0) == pytest.approx(100.0, abs=0.01)

    def test_typical_l2_savings_high(self):
        # L1: $1.50, L2: $0.04 → ~97.3% savings
        savings = _l2_gas_savings_pct(1.50, 0.04)
        assert savings > 90.0

    def test_same_cost_is_zero_savings(self):
        assert _l2_gas_savings_pct(1.50, 1.50) == pytest.approx(0.0, abs=0.01)

    def test_l2_more_expensive_clamps_to_zero(self):
        assert _l2_gas_savings_pct(1.00, 2.00) == pytest.approx(0.0, abs=0.01)

    def test_returns_float(self):
        assert isinstance(_l2_gas_savings_pct(1.50, 0.05), float)

    def test_result_in_0_100_range(self):
        for l1, l2 in [(1.50, 0.04), (1.50, 1.50), (1.50, 0.0), (0.5, 2.0)]:
            result = _l2_gas_savings_pct(l1, l2)
            assert 0.0 <= result <= 100.0


# ===========================================================================
# 4. _l2_momentum_score
# ===========================================================================

class TestL2MomentumScore:
    def test_positive_changes_high_score(self):
        score = _l2_momentum_score(tvl_change_24h=3.0, tvl_change_7d=10.0, tx_growth=0.25)
        assert score > 60.0

    def test_negative_changes_low_score(self):
        score = _l2_momentum_score(tvl_change_24h=-3.0, tvl_change_7d=-8.0, tx_growth=-0.2)
        assert score < 40.0

    def test_flat_returns_near_50(self):
        score = _l2_momentum_score(tvl_change_24h=0.0, tvl_change_7d=0.0, tx_growth=0.0)
        assert 40.0 <= score <= 60.0

    def test_result_in_0_100_range(self):
        for tc24, tc7, txg in [
            (5.0, 20.0, 0.5), (-5.0, -15.0, -0.3), (0.0, 0.0, 0.0)
        ]:
            score = _l2_momentum_score(tc24, tc7, txg)
            assert 0.0 <= score <= 100.0

    def test_returns_float(self):
        assert isinstance(_l2_momentum_score(1.0, 3.0, 0.1), float)

    def test_higher_growth_higher_score(self):
        low  = _l2_momentum_score(0.5, 1.0, 0.02)
        high = _l2_momentum_score(3.0, 9.0, 0.3)
        assert high > low


# ===========================================================================
# 5. _l2_growth_label
# ===========================================================================

class TestL2GrowthLabel:
    def test_high_momentum_is_strong_growth(self):
        assert _l2_growth_label(75.0) == "strong_growth"

    def test_mid_high_is_growing(self):
        assert _l2_growth_label(55.0) == "growing"

    def test_mid_is_neutral(self):
        assert _l2_growth_label(40.0) == "neutral"

    def test_low_is_declining(self):
        assert _l2_growth_label(20.0) == "declining"

    def test_boundary_70_is_strong_growth(self):
        assert _l2_growth_label(70.0) == "strong_growth"

    def test_boundary_50_is_growing(self):
        assert _l2_growth_label(50.0) == "growing"

    def test_returns_valid_string(self):
        result = _l2_growth_label(50.0)
        assert result in ("strong_growth", "growing", "neutral", "declining")


# ===========================================================================
# 6. _l2_rank_chains
# ===========================================================================

class TestL2RankChains:
    def test_empty_returns_empty(self):
        assert _l2_rank_chains({}) == []

    def test_sorted_by_tvl_descending(self):
        chains = {
            "A": {"tvl_usd": 1_000},
            "B": {"tvl_usd": 5_000},
            "C": {"tvl_usd": 3_000},
        }
        ranked = _l2_rank_chains(chains)
        assert ranked[0][0] == "B"
        assert ranked[1][0] == "C"
        assert ranked[2][0] == "A"

    def test_returns_list_of_tuples(self):
        chains = {"A": {"tvl_usd": 100}, "B": {"tvl_usd": 200}}
        result = _l2_rank_chains(chains)
        assert isinstance(result, list)
        assert all(isinstance(item, tuple) and len(item) == 2 for item in result)

    def test_preserves_all_chains(self):
        chains = {k: {"tvl_usd": float(i * 100)} for i, k in enumerate("ABCDE", 1)}
        assert len(_l2_rank_chains(chains)) == 5

    def test_zero_tvl_last(self):
        chains = {"Rich": {"tvl_usd": 1_000_000}, "Zero": {"tvl_usd": 0}}
        ranked = _l2_rank_chains(chains)
        assert ranked[-1][0] == "Zero"


# ===========================================================================
# 7. _l2_tvl_change_pct
# ===========================================================================

class TestL2TvlChangePct:
    def test_positive_change_is_positive(self):
        assert _l2_tvl_change_pct(1_100, 1_000) > 0

    def test_negative_change_is_negative(self):
        assert _l2_tvl_change_pct(900, 1_000) < 0

    def test_no_change_is_zero(self):
        assert _l2_tvl_change_pct(1_000, 1_000) == pytest.approx(0.0, abs=1e-6)

    def test_zero_previous_returns_zero(self):
        assert _l2_tvl_change_pct(1_000, 0) == pytest.approx(0.0, abs=1e-6)

    def test_returns_float(self):
        assert isinstance(_l2_tvl_change_pct(1_100, 1_000), float)

    def test_correct_magnitude(self):
        # 1100 vs 1000 → +10%
        assert _l2_tvl_change_pct(1_100, 1_000) == pytest.approx(10.0, abs=0.01)


# ===========================================================================
# 8. SAMPLE_RESPONSE structure
# ===========================================================================

class TestSampleResponseShape:
    CHAINS = ("Arbitrum", "Optimism", "Base", "Polygon", "zkSync")

    def test_has_chains_dict(self):
        assert isinstance(SAMPLE_RESPONSE["chains"], dict)

    def test_has_all_five_chains(self):
        for chain in self.CHAINS:
            assert chain in SAMPLE_RESPONSE["chains"], f"{chain} missing"

    def test_each_chain_has_required_keys(self):
        for name, ch in SAMPLE_RESPONSE["chains"].items():
            for key in (
                "tvl_usd", "tvl_change_24h_pct", "tvl_change_7d_pct",
                "bridge_flow_24h_usd", "bridge_direction",
                "tx_count_24h", "avg_gas_usd", "gas_savings_pct", "momentum",
            ):
                assert key in ch, f"{name} missing '{key}'"

    def test_bridge_direction_valid(self):
        for name, ch in SAMPLE_RESPONSE["chains"].items():
            assert ch["bridge_direction"] in ("inflow", "outflow", "neutral"), \
                f"{name} has invalid bridge_direction"

    def test_gas_savings_in_range(self):
        for name, ch in SAMPLE_RESPONSE["chains"].items():
            assert 0 <= ch["gas_savings_pct"] <= 100, f"{name} gas_savings_pct out of range"

    def test_has_aggregate_dict(self):
        assert isinstance(SAMPLE_RESPONSE["aggregate"], dict)

    def test_aggregate_has_required_keys(self):
        for key in (
            "total_tvl_usd", "total_tvl_change_24h_pct",
            "total_bridge_inflow_24h", "total_tx_count_24h",
            "l1_vs_l2_tx_ratio", "avg_gas_savings_pct", "top_chain",
        ):
            assert key in SAMPLE_RESPONSE["aggregate"], f"aggregate missing '{key}'"

    def test_top_chain_is_valid(self):
        assert SAMPLE_RESPONSE["aggregate"]["top_chain"] in self.CHAINS

    def test_has_momentum_dict(self):
        assert isinstance(SAMPLE_RESPONSE["momentum"], dict)

    def test_momentum_has_required_keys(self):
        for key in ("score", "label", "leader", "laggard"):
            assert key in SAMPLE_RESPONSE["momentum"], f"momentum missing '{key}'"

    def test_momentum_label_valid(self):
        assert SAMPLE_RESPONSE["momentum"]["label"] in (
            "strong_growth", "growing", "neutral", "declining"
        )

    def test_has_history_7d_list(self):
        assert isinstance(SAMPLE_RESPONSE["history_7d"], list)

    def test_history_items_have_required_keys(self):
        for item in SAMPLE_RESPONSE["history_7d"]:
            for key in ("date", "total_tvl_usd", "momentum"):
                assert key in item, f"history_7d item missing '{key}'"

    def test_has_description(self):
        assert isinstance(SAMPLE_RESPONSE["description"], str)


# ===========================================================================
# 9. Structural tests
# ===========================================================================

class TestStructural:
    def test_route_registered_in_api_py(self):
        api_path = os.path.join(os.path.dirname(__file__), "..", "backend", "api.py")
        content = open(api_path).read()
        assert "/layer2-metrics" in content, "/layer2-metrics route missing"

    def test_html_card_exists(self):
        html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
        content = open(html_path).read()
        assert "card-layer2-metrics" in content, "card-layer2-metrics missing"

    def test_js_render_function_exists(self):
        js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
        content = open(js_path).read()
        assert "renderLayer2Metrics" in content, "renderLayer2Metrics missing"

    def test_js_api_call_to_endpoint(self):
        js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
        content = open(js_path).read()
        assert "/layer2-metrics" in content, "/layer2-metrics call missing"

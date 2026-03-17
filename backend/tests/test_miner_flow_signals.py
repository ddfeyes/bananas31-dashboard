"""Tests for compute_miner_flow_signals() — Wave 25, Task 5.

50+ tests covering all required keys, value ranges, structural invariants,
determinism, historical drawdowns, sell pressure forecast, and structural checks.
"""
import asyncio
import re
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from metrics import compute_miner_flow_signals

REQUIRED_KEYS = {
    "outflow_rate_btc",
    "outflow_rate_7d_avg",
    "outflow_trend",
    "reserve_ratio",
    "reserve_btc",
    "reserve_trend",
    "price_correlation_90d",
    "historical_drawdowns",
    "sell_pressure_forecast_30d",
    "sell_pressure_trend",
    "miner_capitulation_risk",
    "timestamp",
}

OUTFLOW_TRENDS = {"increasing", "decreasing", "stable"}
RESERVE_TRENDS = {"accumulating", "depleting", "stable"}
SELL_PRESSURE_TRENDS = {"rising", "falling", "neutral"}
CAPITULATION_RISKS = {"low", "medium", "high"}
DRAWDOWN_KEYS = {"date", "outflow_spike", "price_drawdown_pct"}


def run(coro):
    return asyncio.run(coro)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def result():
    return run(compute_miner_flow_signals())


@pytest.fixture(scope="module")
def result2():
    return run(compute_miner_flow_signals())


# ── Return type ────────────────────────────────────────────────────────────────


def test_returns_dict(result):
    assert isinstance(result, dict)


# ── Required keys ──────────────────────────────────────────────────────────────


def test_has_outflow_rate_btc(result):
    assert "outflow_rate_btc" in result


def test_has_outflow_rate_7d_avg(result):
    assert "outflow_rate_7d_avg" in result


def test_has_outflow_trend(result):
    assert "outflow_trend" in result


def test_has_reserve_ratio(result):
    assert "reserve_ratio" in result


def test_has_reserve_btc(result):
    assert "reserve_btc" in result


def test_has_reserve_trend(result):
    assert "reserve_trend" in result


def test_has_price_correlation_90d(result):
    assert "price_correlation_90d" in result


def test_has_historical_drawdowns(result):
    assert "historical_drawdowns" in result


def test_has_sell_pressure_forecast_30d(result):
    assert "sell_pressure_forecast_30d" in result


def test_has_sell_pressure_trend(result):
    assert "sell_pressure_trend" in result


def test_has_miner_capitulation_risk(result):
    assert "miner_capitulation_risk" in result


def test_has_timestamp(result):
    assert "timestamp" in result


def test_all_required_keys_present(result):
    assert REQUIRED_KEYS.issubset(result.keys())


# ── outflow_rate_btc ───────────────────────────────────────────────────────────


def test_outflow_rate_btc_positive(result):
    assert result["outflow_rate_btc"] > 0


def test_outflow_rate_btc_is_float(result):
    assert isinstance(result["outflow_rate_btc"], float)


def test_outflow_rate_btc_reasonable_range(result):
    assert 100.0 <= result["outflow_rate_btc"] <= 2000.0


# ── outflow_rate_7d_avg ────────────────────────────────────────────────────────


def test_outflow_rate_7d_avg_positive(result):
    assert result["outflow_rate_7d_avg"] > 0


def test_outflow_rate_7d_avg_is_float(result):
    assert isinstance(result["outflow_rate_7d_avg"], float)


def test_outflow_rate_7d_avg_reasonable_range(result):
    assert 100.0 <= result["outflow_rate_7d_avg"] <= 2000.0


# ── outflow_trend ──────────────────────────────────────────────────────────────


def test_outflow_trend_valid(result):
    assert result["outflow_trend"] in OUTFLOW_TRENDS


def test_outflow_trend_is_str(result):
    assert isinstance(result["outflow_trend"], str)


# ── reserve_ratio ──────────────────────────────────────────────────────────────


def test_reserve_ratio_in_range(result):
    assert 0.0 <= result["reserve_ratio"] <= 1.0


def test_reserve_ratio_is_float(result):
    assert isinstance(result["reserve_ratio"], float)


def test_reserve_ratio_positive(result):
    assert result["reserve_ratio"] > 0


# ── reserve_btc ────────────────────────────────────────────────────────────────


def test_reserve_btc_positive(result):
    assert result["reserve_btc"] > 0


def test_reserve_btc_is_float(result):
    assert isinstance(result["reserve_btc"], float)


def test_reserve_btc_reasonable_range(result):
    assert 1_000.0 <= result["reserve_btc"] <= 1_000_000.0


# ── reserve_trend ──────────────────────────────────────────────────────────────


def test_reserve_trend_valid(result):
    assert result["reserve_trend"] in RESERVE_TRENDS


def test_reserve_trend_is_str(result):
    assert isinstance(result["reserve_trend"], str)


# ── price_correlation_90d ──────────────────────────────────────────────────────


def test_price_correlation_90d_in_range(result):
    assert -1.0 <= result["price_correlation_90d"] <= 1.0


def test_price_correlation_90d_is_float(result):
    assert isinstance(result["price_correlation_90d"], float)


# ── historical_drawdowns ───────────────────────────────────────────────────────


def test_historical_drawdowns_is_list(result):
    assert isinstance(result["historical_drawdowns"], list)


def test_historical_drawdowns_length_10(result):
    assert len(result["historical_drawdowns"]) == 10


def test_historical_drawdowns_items_are_dicts(result):
    for item in result["historical_drawdowns"]:
        assert isinstance(item, dict)


def test_historical_drawdowns_have_required_keys(result):
    for item in result["historical_drawdowns"]:
        assert DRAWDOWN_KEYS.issubset(item.keys()), f"Missing keys in {item}"


def test_historical_drawdowns_date_is_str(result):
    for item in result["historical_drawdowns"]:
        assert isinstance(item["date"], str)


def test_historical_drawdowns_date_nonempty(result):
    for item in result["historical_drawdowns"]:
        assert len(item["date"]) > 0


def test_historical_drawdowns_date_iso_format(result):
    iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for item in result["historical_drawdowns"]:
        assert iso_re.match(item["date"]), f"Date not ISO: {item['date']}"


def test_historical_drawdowns_outflow_spike_positive(result):
    for item in result["historical_drawdowns"]:
        assert item["outflow_spike"] > 0


def test_historical_drawdowns_price_drawdown_nonpositive(result):
    for item in result["historical_drawdowns"]:
        assert item["price_drawdown_pct"] <= 0


def test_historical_drawdowns_outflow_spike_is_float(result):
    for item in result["historical_drawdowns"]:
        assert isinstance(item["outflow_spike"], float)


def test_historical_drawdowns_price_drawdown_is_float(result):
    for item in result["historical_drawdowns"]:
        assert isinstance(item["price_drawdown_pct"], float)


# ── sell_pressure_forecast_30d ────────────────────────────────────────────────


def test_sell_pressure_forecast_is_list(result):
    assert isinstance(result["sell_pressure_forecast_30d"], list)


def test_sell_pressure_forecast_length_30(result):
    assert len(result["sell_pressure_forecast_30d"]) == 30


def test_sell_pressure_forecast_all_positive(result):
    for v in result["sell_pressure_forecast_30d"]:
        assert v > 0


def test_sell_pressure_forecast_values_are_floats(result):
    for v in result["sell_pressure_forecast_30d"]:
        assert isinstance(v, float)


def test_sell_pressure_forecast_reasonable_range(result):
    for v in result["sell_pressure_forecast_30d"]:
        assert 100.0 <= v <= 2000.0


# ── sell_pressure_trend ────────────────────────────────────────────────────────


def test_sell_pressure_trend_valid(result):
    assert result["sell_pressure_trend"] in SELL_PRESSURE_TRENDS


def test_sell_pressure_trend_is_str(result):
    assert isinstance(result["sell_pressure_trend"], str)


# ── miner_capitulation_risk ────────────────────────────────────────────────────


def test_miner_capitulation_risk_valid(result):
    assert result["miner_capitulation_risk"] in CAPITULATION_RISKS


def test_miner_capitulation_risk_is_str(result):
    assert isinstance(result["miner_capitulation_risk"], str)


# ── timestamp ─────────────────────────────────────────────────────────────────


def test_timestamp_is_str(result):
    assert isinstance(result["timestamp"], str)


def test_timestamp_nonempty(result):
    assert len(result["timestamp"]) > 0


def test_timestamp_iso_format(result):
    ts = result["timestamp"]
    assert "T" in ts, f"Timestamp missing 'T': {ts}"


# ── Determinism (seeded random fields) ────────────────────────────────────────


def test_determinism_outflow_rate_btc(result, result2):
    assert result["outflow_rate_btc"] == result2["outflow_rate_btc"]


def test_determinism_outflow_rate_7d_avg(result, result2):
    assert result["outflow_rate_7d_avg"] == result2["outflow_rate_7d_avg"]


def test_determinism_outflow_trend(result, result2):
    assert result["outflow_trend"] == result2["outflow_trend"]


def test_determinism_reserve_btc(result, result2):
    assert result["reserve_btc"] == result2["reserve_btc"]


def test_determinism_reserve_ratio(result, result2):
    assert result["reserve_ratio"] == result2["reserve_ratio"]


def test_determinism_reserve_trend(result, result2):
    assert result["reserve_trend"] == result2["reserve_trend"]


def test_determinism_price_correlation(result, result2):
    assert result["price_correlation_90d"] == result2["price_correlation_90d"]


def test_determinism_forecast_first_value(result, result2):
    assert result["sell_pressure_forecast_30d"][0] == result2["sell_pressure_forecast_30d"][0]


def test_determinism_sell_pressure_trend(result, result2):
    assert result["sell_pressure_trend"] == result2["sell_pressure_trend"]


def test_determinism_capitulation_risk(result, result2):
    assert result["miner_capitulation_risk"] == result2["miner_capitulation_risk"]


def test_determinism_drawdown_dates(result, result2):
    dates1 = [d["date"] for d in result["historical_drawdowns"]]
    dates2 = [d["date"] for d in result2["historical_drawdowns"]]
    assert dates1 == dates2


def test_determinism_drawdown_spikes(result, result2):
    spikes1 = [d["outflow_spike"] for d in result["historical_drawdowns"]]
    spikes2 = [d["outflow_spike"] for d in result2["historical_drawdowns"]]
    assert spikes1 == spikes2


# ── Async / function shape ─────────────────────────────────────────────────────


def test_function_is_async():
    import inspect
    assert inspect.iscoroutinefunction(compute_miner_flow_signals)


def test_asyncio_run_works():
    data = asyncio.run(compute_miner_flow_signals())
    assert isinstance(data, dict)


# ── Structural tests ───────────────────────────────────────────────────────────


def test_route_registered_in_api_py():
    api_path = os.path.join(os.path.dirname(__file__), "..", "api.py")
    content = open(api_path).read()
    assert "/miner-flow-signals" in content, "/miner-flow-signals route missing from api.py"


def test_html_card_exists():
    html_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "frontend", "index.html"
    )
    content = open(html_path).read()
    assert "miner-flow-signals-card" in content, "miner-flow-signals-card missing from index.html"


def test_js_render_function_exists():
    js_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "frontend", "app.js"
    )
    content = open(js_path).read()
    assert "renderMinerFlowSignals" in content, "renderMinerFlowSignals missing from app.js"


def test_js_api_call_exists():
    js_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "frontend", "app.js"
    )
    content = open(js_path).read()
    assert "/miner-flow-signals" in content, "/miner-flow-signals call missing from app.js"

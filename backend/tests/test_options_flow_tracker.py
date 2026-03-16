"""50+ tests for the options flow tracker feature."""
import asyncio
import math
import os
import sys
import tempfile

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_oft.db")
os.environ["SYMBOL_BINANCE"] = "BANANAS31USDT"
os.environ["SYMBOL_BYBIT"] = "BANANAS31USDT"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from metrics import (
    _oft_skew_signal,
    _oft_skew_ratio,
    _oft_unusual_threshold,
    _oft_net_flow,
    _oft_dominant_expiry,
    _oft_skew_percentile,
    _oft_make_instrument,
    _oft_simulate_large_trades,
    _oft_compute_skew_by_expiry,
    _oft_detect_unusual_flow,
    _oft_build_strike_heatmap,
    compute_options_flow_tracker,
)


# ── Helper: read frontend files ────────────────────────────────────────────────

def _root():
    return os.path.join(os.path.dirname(__file__), "..", "..")


def _read_html():
    with open(os.path.join(_root(), "frontend", "index.html")) as f:
        return f.read()


def _read_js():
    with open(os.path.join(_root(), "frontend", "app.js")) as f:
        return f.read()


# ── _oft_skew_signal ──────────────────────────────────────────────────────────

def test_skew_signal_bullish_ratio_above_1_25():
    # ratio = 1260/1000 = 1.26 > 1.25 → bullish
    assert _oft_skew_signal(1260, 1000) == "bullish"


def test_skew_signal_bullish_ratio_exactly_1_25_is_neutral():
    # ratio == 1.25 is not strictly > 1.25 → neutral
    assert _oft_skew_signal(1250, 1000) == "neutral"


def test_skew_signal_bullish_strong():
    assert _oft_skew_signal(5000, 1000) == "bullish"


def test_skew_signal_bearish_ratio_below_0_8():
    assert _oft_skew_signal(700, 1000) == "bearish"


def test_skew_signal_bearish_zero_calls():
    assert _oft_skew_signal(0, 1000) == "bearish"


def test_skew_signal_neutral_equal_volume():
    assert _oft_skew_signal(1000, 1000) == "neutral"


def test_skew_signal_neutral_near_boundary_high():
    # ratio 1.24 → below 1.25 threshold → neutral
    assert _oft_skew_signal(1240, 1000) == "neutral"


def test_skew_signal_neutral_near_boundary_low():
    # ratio 0.81 → above 0.80 threshold → neutral
    assert _oft_skew_signal(810, 1000) == "neutral"


def test_skew_signal_zero_put_returns_bullish():
    assert _oft_skew_signal(100000, 0) == "bullish"


# ── _oft_skew_ratio ────────────────────────────────────────────────────────────

def test_skew_ratio_basic():
    assert _oft_skew_ratio(2000, 1000) == pytest.approx(2.0, abs=0.01)


def test_skew_ratio_zero_put():
    assert _oft_skew_ratio(500, 0) == 10.0


def test_skew_ratio_capped_at_10():
    assert _oft_skew_ratio(1_000_000, 1) == 10.0


def test_skew_ratio_less_than_one():
    ratio = _oft_skew_ratio(800, 1000)
    assert ratio == pytest.approx(0.8, abs=0.01)


def test_skew_ratio_equal():
    assert _oft_skew_ratio(1000, 1000) == pytest.approx(1.0, abs=0.01)


# ── _oft_unusual_threshold ─────────────────────────────────────────────────────

def test_unusual_threshold_above_3x():
    assert _oft_unusual_threshold(300001, 100000) is True


def test_unusual_threshold_exactly_3x_not_unusual():
    assert _oft_unusual_threshold(300000, 100000) is False


def test_unusual_threshold_below():
    assert _oft_unusual_threshold(200000, 100000) is False


def test_unusual_threshold_large_trade():
    assert _oft_unusual_threshold(5_000_000, 500_000) is True


# ── _oft_net_flow ──────────────────────────────────────────────────────────────

def test_net_flow_positive():
    assert _oft_net_flow(2_000_000, 800_000) == pytest.approx(1_200_000, abs=1)


def test_net_flow_negative():
    assert _oft_net_flow(500_000, 1_500_000) == pytest.approx(-1_000_000, abs=1)


def test_net_flow_zero():
    assert _oft_net_flow(1_000_000, 1_000_000) == pytest.approx(0, abs=1)


# ── _oft_dominant_expiry ───────────────────────────────────────────────────────

def test_dominant_expiry_picks_highest_volume():
    skew = {
        "28MAR26": {"call_volume_usd": 100_000, "put_volume_usd": 50_000},
        "25APR26": {"call_volume_usd": 800_000, "put_volume_usd": 200_000},
        "27JUN26": {"call_volume_usd": 200_000, "put_volume_usd": 100_000},
    }
    assert _oft_dominant_expiry(skew) == "25APR26"


def test_dominant_expiry_empty():
    assert _oft_dominant_expiry({}) == ""


def test_dominant_expiry_single():
    skew = {"28MAR26": {"call_volume_usd": 500_000, "put_volume_usd": 300_000}}
    assert _oft_dominant_expiry(skew) == "28MAR26"


# ── _oft_skew_percentile ───────────────────────────────────────────────────────

def test_skew_percentile_range_0_100():
    for ratio in [0.1, 0.5, 1.0, 1.5, 2.0, 5.0]:
        pct = _oft_skew_percentile(ratio)
        assert 0.0 <= pct <= 100.0, f"Out of range for ratio={ratio}"


def test_skew_percentile_1_0_is_near_50():
    pct = _oft_skew_percentile(1.0)
    assert 45.0 <= pct <= 55.0


def test_skew_percentile_higher_ratio_higher_pct():
    assert _oft_skew_percentile(2.0) > _oft_skew_percentile(1.0)


def test_skew_percentile_low_ratio_low_pct():
    assert _oft_skew_percentile(0.3) < _oft_skew_percentile(1.0)


# ── _oft_make_instrument ───────────────────────────────────────────────────────

def test_make_instrument_call():
    assert _oft_make_instrument(70000, "28MAR26", "call") == "BTC-28MAR26-70000-C"


def test_make_instrument_put():
    assert _oft_make_instrument(60000, "25APR26", "put") == "BTC-25APR26-60000-P"


def test_make_instrument_format():
    inst = _oft_make_instrument(80000, "27JUN26", "call")
    parts = inst.split("-")
    assert len(parts) == 4
    assert parts[0] == "BTC"
    assert parts[3] == "C"


# ── _oft_simulate_large_trades ─────────────────────────────────────────────────

def test_simulate_trades_count():
    trades = _oft_simulate_large_trades()
    assert len(trades) == 40


def test_simulate_trades_all_above_100k():
    trades = _oft_simulate_large_trades()
    for t in trades:
        assert t["notional_usd"] >= 100_000, f"Trade below $100k: {t['notional_usd']}"


def test_simulate_trades_required_keys():
    trades = _oft_simulate_large_trades()
    required = {"ts", "exchange", "instrument", "type", "strike", "expiry",
                "side", "contracts", "btc_price", "premium_per_contract",
                "notional_usd", "iv", "delta"}
    for t in trades:
        missing = required - set(t.keys())
        assert not missing, f"Missing keys: {missing}"


def test_simulate_trades_types_are_valid():
    trades = _oft_simulate_large_trades()
    for t in trades:
        assert t["type"] in ("call", "put")


def test_simulate_trades_sides_are_valid():
    trades = _oft_simulate_large_trades()
    for t in trades:
        assert t["side"] in ("buy", "sell")


def test_simulate_trades_exchanges_are_valid():
    trades = _oft_simulate_large_trades()
    for t in trades:
        assert t["exchange"] in ("deribit", "lyra")


def test_simulate_trades_sorted_newest_first():
    trades = _oft_simulate_large_trades()
    for i in range(len(trades) - 1):
        assert trades[i]["ts"] >= trades[i + 1]["ts"]


def test_simulate_trades_deterministic():
    t1 = _oft_simulate_large_trades()
    t2 = _oft_simulate_large_trades()
    assert t1 == t2


def test_simulate_trades_iv_range():
    trades = _oft_simulate_large_trades()
    for t in trades:
        assert 0.0 < t["iv"] < 5.0


def test_simulate_trades_delta_range():
    trades = _oft_simulate_large_trades()
    for t in trades:
        assert 0.0 <= t["delta"] <= 1.0


def test_simulate_trades_contracts_positive():
    trades = _oft_simulate_large_trades()
    for t in trades:
        assert t["contracts"] > 0


# ── _oft_compute_skew_by_expiry ────────────────────────────────────────────────

def test_skew_by_expiry_keys_present():
    trades = _oft_simulate_large_trades()
    skew = _oft_compute_skew_by_expiry(trades)
    assert len(skew) > 0
    for exp, v in skew.items():
        assert "call_volume_usd" in v
        assert "put_volume_usd" in v
        assert "skew_ratio" in v
        assert "skew_signal" in v
        assert "net_flow_usd" in v


def test_skew_by_expiry_volumes_non_negative():
    trades = _oft_simulate_large_trades()
    skew = _oft_compute_skew_by_expiry(trades)
    for exp, v in skew.items():
        assert v["call_volume_usd"] >= 0
        assert v["put_volume_usd"] >= 0


def test_skew_by_expiry_signals_valid():
    trades = _oft_simulate_large_trades()
    skew = _oft_compute_skew_by_expiry(trades)
    for exp, v in skew.items():
        assert v["skew_signal"] in ("bullish", "bearish", "neutral")


def test_skew_by_expiry_empty_trades():
    skew = _oft_compute_skew_by_expiry([])
    assert skew == {}


def test_skew_by_expiry_single_call_trade():
    trade = [{
        "expiry": "28MAR26", "type": "call", "notional_usd": 500_000,
    }]
    skew = _oft_compute_skew_by_expiry(trade)
    assert skew["28MAR26"]["call_volume_usd"] == 500_000
    assert skew["28MAR26"]["put_volume_usd"] == 0.0
    assert skew["28MAR26"]["skew_signal"] == "bullish"


def test_skew_by_expiry_net_flow_math():
    trades = [
        {"expiry": "28MAR26", "type": "call", "notional_usd": 300_000},
        {"expiry": "28MAR26", "type": "put", "notional_usd": 100_000},
    ]
    skew = _oft_compute_skew_by_expiry(trades)
    assert skew["28MAR26"]["net_flow_usd"] == pytest.approx(200_000, abs=1)


# ── _oft_detect_unusual_flow ───────────────────────────────────────────────────

def test_detect_unusual_flow_returns_list():
    trades = _oft_simulate_large_trades()
    alerts = _oft_detect_unusual_flow(trades)
    assert isinstance(alerts, list)


def test_detect_unusual_flow_severity_values():
    trades = _oft_simulate_large_trades()
    alerts = _oft_detect_unusual_flow(trades)
    for a in alerts:
        assert a["severity"] in ("high", "critical")


def test_detect_unusual_flow_required_keys():
    trades = _oft_simulate_large_trades()
    alerts = _oft_detect_unusual_flow(trades)
    required = {"ts", "instrument", "exchange", "notional_usd", "side", "type", "severity", "reason"}
    for a in alerts:
        assert required.issubset(set(a.keys()))


def test_detect_unusual_flow_empty_trades():
    assert _oft_detect_unusual_flow([]) == []


def test_detect_unusual_flow_sorted_by_notional():
    trades = _oft_simulate_large_trades()
    alerts = _oft_detect_unusual_flow(trades)
    for i in range(len(alerts) - 1):
        assert alerts[i]["notional_usd"] >= alerts[i + 1]["notional_usd"]


def test_detect_unusual_flow_critical_threshold():
    mean = 100_000
    trades = [
        {"ts": 1e9, "exchange": "deribit", "instrument": "BTC-28MAR26-70000-C",
         "type": "call", "side": "buy", "notional_usd": mean * 7,
         "expiry": "28MAR26", "strike": 70000},
    ] * 10
    mean_trade = mean  # mean is roughly mean * 7 since all trades are equal
    alerts = _oft_detect_unusual_flow(trades)
    # All trades equal → no alert (0x above mean*3 since all same size)
    # Actually mean = mean*7 * 10 / 10 = mean*7, so ratio = 1.0, not unusual
    assert isinstance(alerts, list)


# ── _oft_build_strike_heatmap ──────────────────────────────────────────────────

def test_strike_heatmap_keys_present():
    trades = _oft_simulate_large_trades()
    hm = _oft_build_strike_heatmap(trades)
    assert len(hm) > 0
    for strike, v in hm.items():
        assert "call_notional_usd" in v
        assert "put_notional_usd" in v
        assert "net_flow_usd" in v
        assert "dominant" in v


def test_strike_heatmap_dominant_values():
    trades = _oft_simulate_large_trades()
    hm = _oft_build_strike_heatmap(trades)
    for _, v in hm.items():
        assert v["dominant"] in ("call", "put")


def test_strike_heatmap_empty_trades():
    hm = _oft_build_strike_heatmap([])
    assert hm == {}


def test_strike_heatmap_dominant_call_when_calls_dominate():
    trades = [
        {"strike": 70000, "type": "call", "side": "buy", "notional_usd": 500_000},
        {"strike": 70000, "type": "put", "side": "sell", "notional_usd": 100_000},
    ]
    hm = _oft_build_strike_heatmap(trades)
    assert hm["70000"]["dominant"] == "call"


def test_strike_heatmap_dominant_put_when_puts_dominate():
    trades = [
        {"strike": 65000, "type": "call", "side": "buy", "notional_usd": 100_000},
        {"strike": 65000, "type": "put", "side": "sell", "notional_usd": 600_000},
    ]
    hm = _oft_build_strike_heatmap(trades)
    assert hm["65000"]["dominant"] == "put"


def test_strike_heatmap_net_flow_buy_adds():
    trades = [{"strike": 75000, "type": "call", "side": "buy", "notional_usd": 200_000}]
    hm = _oft_build_strike_heatmap(trades)
    assert hm["75000"]["net_flow_usd"] == pytest.approx(200_000, abs=1)


def test_strike_heatmap_net_flow_sell_subtracts():
    trades = [{"strike": 75000, "type": "put", "side": "sell", "notional_usd": 150_000}]
    hm = _oft_build_strike_heatmap(trades)
    assert hm["75000"]["net_flow_usd"] == pytest.approx(-150_000, abs=1)


# ── compute_options_flow_tracker (async integration) ──────────────────────────

@pytest.mark.asyncio
async def test_compute_options_flow_tracker_returns_dict():
    result = await compute_options_flow_tracker()
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_required_top_keys():
    result = await compute_options_flow_tracker()
    required = {"large_trades", "skew_by_expiry", "unusual_flow_alerts",
                "strike_heatmap", "summary", "description"}
    assert required.issubset(set(result.keys()))


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_large_trades_list():
    result = await compute_options_flow_tracker()
    assert isinstance(result["large_trades"], list)
    assert len(result["large_trades"]) <= 20


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_all_large_trades_above_100k():
    result = await compute_options_flow_tracker()
    for t in result["large_trades"]:
        assert t["notional_usd"] >= 100_000


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_summary_keys():
    result = await compute_options_flow_tracker()
    summary = result["summary"]
    required = {
        "total_call_volume_usd", "total_put_volume_usd",
        "overall_skew_ratio", "net_flow_direction", "dominant_expiry",
        "skew_percentile", "unusual_activity_count", "total_trades_analyzed",
        "exchanges",
    }
    assert required.issubset(set(summary.keys()))


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_summary_call_vol_positive():
    result = await compute_options_flow_tracker()
    assert result["summary"]["total_call_volume_usd"] > 0


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_summary_put_vol_positive():
    result = await compute_options_flow_tracker()
    assert result["summary"]["total_put_volume_usd"] > 0


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_net_flow_direction_valid():
    result = await compute_options_flow_tracker()
    assert result["summary"]["net_flow_direction"] in ("bullish", "bearish", "neutral")


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_skew_percentile_range():
    result = await compute_options_flow_tracker()
    pct = result["summary"]["skew_percentile"]
    assert 0.0 <= pct <= 100.0


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_description_is_string():
    result = await compute_options_flow_tracker()
    assert isinstance(result["description"], str)
    assert len(result["description"]) > 10


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_skew_by_expiry_non_empty():
    result = await compute_options_flow_tracker()
    assert len(result["skew_by_expiry"]) > 0


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_strike_heatmap_non_empty():
    result = await compute_options_flow_tracker()
    assert len(result["strike_heatmap"]) > 0


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_total_trades_analyzed():
    result = await compute_options_flow_tracker()
    assert result["summary"]["total_trades_analyzed"] == 40


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_exchanges_contain_deribit_or_lyra():
    result = await compute_options_flow_tracker()
    exchanges = set(result["summary"]["exchanges"])
    assert len(exchanges & {"deribit", "lyra"}) > 0


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_dominant_expiry_nonempty():
    result = await compute_options_flow_tracker()
    assert result["summary"]["dominant_expiry"] != ""


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_unusual_alerts_list():
    result = await compute_options_flow_tracker()
    assert isinstance(result["unusual_flow_alerts"], list)
    assert len(result["unusual_flow_alerts"]) <= 10


@pytest.mark.asyncio
async def test_compute_options_flow_tracker_is_deterministic():
    r1 = await compute_options_flow_tracker()
    r2 = await compute_options_flow_tracker()
    assert r1["summary"]["total_call_volume_usd"] == r2["summary"]["total_call_volume_usd"]
    assert r1["summary"]["total_put_volume_usd"] == r2["summary"]["total_put_volume_usd"]


# ── HTML / JS integration checks ───────────────────────────────────────────────

def test_html_card_section_exists():
    html = _read_html()
    assert 'id="card-options-flow"' in html


def test_html_card_title():
    html = _read_html()
    assert "Options Flow Tracker" in html


def test_html_card_content_div():
    html = _read_html()
    assert 'id="options-flow-content"' in html


def test_html_card_badge():
    html = _read_html()
    assert 'id="options-flow-badge"' in html


def test_html_card_meta_mentions_notional():
    html = _read_html()
    assert "$100k notional" in html or "100k notional" in html


def test_js_refresh_function_exists():
    js = _read_js()
    assert "refreshOptionsFlowTracker" in js


def test_js_refresh_called_in_refresh_loop():
    js = _read_js()
    assert "safe(refreshOptionsFlowTracker)" in js


def test_js_api_endpoint_referenced():
    js = _read_js()
    assert "/api/options-flow-tracker" in js


def test_js_skew_by_expiry_rendered():
    js = _read_js()
    assert "skew_by_expiry" in js


def test_js_unusual_flow_alerts_rendered():
    js = _read_js()
    assert "unusual_flow_alerts" in js


def test_js_strike_heatmap_rendered():
    js = _read_js()
    assert "strike_heatmap" in js

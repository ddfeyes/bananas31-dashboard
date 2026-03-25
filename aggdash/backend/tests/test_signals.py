"""Tests for SignalEngine."""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signals import SignalEngine, MIN_DATA_WINDOW_SECS


def make_engine(age_secs=MIN_DATA_WINDOW_SECS + 10):
    """Create a SignalEngine with _start_time adjusted so it's past the min data window."""
    engine = SignalEngine()
    engine._start_time = time.time() - age_secs
    return engine


def test_no_signals_before_data_window():
    """Signal engine returns empty list before minimum data window."""
    engine = SignalEngine()
    engine._start_time = time.time()  # just started
    snap = {
        "basis": {"agg_basis_pct": 0.03},
        "funding": {"per_exchange": {"binance": {"funding_rate": 0.001}}},
        "dex_cex_spread": {"deviation_pct": 0.02},
        "oi_delta": {"total_delta_pct": 0.10},
    }
    sigs = engine.compute_signals(snap)
    assert sigs == []


def test_squeeze_risk_fires():
    """Squeeze risk fires when basis > 2% and funding > 0."""
    engine = make_engine()
    snap = {
        "basis": {"agg_basis_pct": 0.03},  # 3% > 2%
        "funding": {"per_exchange": {"binance": {"funding_rate": 0.0005}}},  # positive
        "dex_cex_spread": {"deviation_pct": 0.0},
        "oi_delta": {"total_delta_pct": 0.01},
    }
    sigs = engine.compute_signals(snap)
    ids = [s["id"] for s in sigs]
    assert "squeeze_risk" in ids


def test_squeeze_risk_no_fire_low_basis():
    """Squeeze risk does NOT fire when basis < 2%."""
    engine = make_engine()
    snap = {
        "basis": {"agg_basis_pct": 0.01},  # 1% < 2%
        "funding": {"per_exchange": {"binance": {"funding_rate": 0.001}}},
        "dex_cex_spread": {"deviation_pct": 0.0},
        "oi_delta": {"total_delta_pct": 0.01},
    }
    sigs = engine.compute_signals(snap)
    ids = [s["id"] for s in sigs]
    assert "squeeze_risk" not in ids


def test_arb_opportunity_fires():
    """Arb opportunity fires when DEX deviation > 1%."""
    engine = make_engine()
    snap = {
        "basis": {},
        "funding": {},
        "dex_cex_spread": {"deviation_pct": 0.015},  # 1.5% > 1%
        "oi_delta": {},
    }
    sigs = engine.compute_signals(snap)
    ids = [s["id"] for s in sigs]
    assert "arb_opportunity" in ids


def test_arb_no_fire_small_deviation():
    """Arb does NOT fire when deviation < 1%."""
    engine = make_engine()
    snap = {
        "basis": {},
        "funding": {},
        "dex_cex_spread": {"deviation_pct": 0.005},  # 0.5% < 1%
        "oi_delta": {},
    }
    sigs = engine.compute_signals(snap)
    ids = [s["id"] for s in sigs]
    assert "arb_opportunity" not in ids


def test_oi_accumulation_no_fire_without_price_data():
    """OI accumulation does NOT fire when price data is absent (spec requirement)."""
    engine = make_engine()
    snap = {
        "basis": {},  # no spot_price_change_pct
        "funding": {},
        "dex_cex_spread": {},
        "oi_delta": {"total_delta_pct": 0.08},  # 8% OI spike
    }
    sigs = engine.compute_signals(snap)
    ids = [s["id"] for s in sigs]
    assert "oi_accumulation" not in ids, "Must not fire without price data"


def test_oi_accumulation_fires_flat_price():
    """OI accumulation fires when OI spike + price flat."""
    engine = make_engine()
    snap = {
        "basis": {"spot_price_change_pct": 0.001},  # flat
        "funding": {},
        "dex_cex_spread": {},
        "oi_delta": {"total_delta_pct": 0.08},  # 8% > 5%
    }
    sigs = engine.compute_signals(snap)
    ids = [s["id"] for s in sigs]
    assert "oi_accumulation" in ids


def test_deleveraging_fires():
    """Deleveraging fires when OI drops + price drops."""
    engine = make_engine()
    snap = {
        "basis": {"spot_price_change_pct": -0.02},  # -2% price drop
        "funding": {},
        "dex_cex_spread": {},
        "oi_delta": {"total_delta_pct": -0.08},  # -8% OI drop
    }
    sigs = engine.compute_signals(snap)
    ids = [s["id"] for s in sigs]
    assert "deleveraging" in ids


def test_signal_structure():
    """Every signal has required fields."""
    engine = make_engine()
    snap = {
        "basis": {"agg_basis_pct": 0.03},
        "funding": {"per_exchange": {"binance": {"funding_rate": 0.001}}},
        "dex_cex_spread": {"deviation_pct": 0.02},
        "oi_delta": {"total_delta_pct": 0.10},
    }
    sigs = engine.compute_signals(snap)
    for s in sigs:
        assert "id" in s
        assert "name" in s
        assert "severity" in s
        assert "message" in s
        assert s["severity"] in ("info", "warning", "alert")

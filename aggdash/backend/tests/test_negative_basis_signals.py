"""Tests for basis_flip and contango_flip signals."""
import pytest
import time
from aggdash.backend.signals import SignalEngine, CONTANGO_BASIS_THRESHOLD, CONTANGO_OI_STABLE_THRESHOLD


def make_snapshot(basis_pct, oi_delta_pct=0.0):
    """basis_pct in percent (e.g. 0.105), oi_delta_pct in fraction (e.g. 0.01)."""
    return {
        "basis": {
            "aggregated": {"basis_pct": basis_pct},
        },
        "funding": {"average_rate": 0.0001},
        "oi_delta": {"total_delta_pct": oi_delta_pct},
        "dex_cex_spread": {"spread_pct": 0.01},
    }


def test_negative_basis_signal_fires():
    """Negative basis (< -0.05%) fires the negative_basis signal."""
    se = SignalEngine()
    # Override start time so signal fires immediately
    se._start_time = 0

    snap = make_snapshot(basis_pct=-0.10)  # -0.10%
    signals = se.compute_signals(snap)

    neg = [s for s in signals if s["id"] == "negative_basis"]
    assert len(neg) == 1, f"expected negative_basis, got {[s['id'] for s in signals]}"
    assert neg[0]["direction"] == "long"


def test_negative_basis_silent_when_positive():
    """negative_basis does not fire for positive basis."""
    se = SignalEngine()
    se._start_time = 0

    snap = make_snapshot(basis_pct=0.10)
    signals = se.compute_signals(snap)

    neg = [s for s in signals if s["id"] == "negative_basis"]
    assert len(neg) == 0


def test_basis_flip_fires_positive_to_negative():
    """basis_flip fires when basis crosses from positive to negative."""
    se = SignalEngine()
    se._start_time = 0

    # First cycle: positive basis
    snap1 = make_snapshot(basis_pct=0.10)
    se.compute_signals(snap1)
    assert se._prev_agg_basis is not None
    assert se._prev_agg_basis > 0

    # Second cycle: negative basis → flip
    snap2 = make_snapshot(basis_pct=-0.10)
    signals = se.compute_signals(snap2)

    flips = [s for s in signals if s["id"] == "basis_flip"]
    assert len(flips) == 1, f"expected basis_flip, got {[s['id'] for s in signals]}"
    assert flips[0]["direction"] == "long"  # entering negative territory
    assert "positive" in flips[0]["message"]
    assert "negative" in flips[0]["message"]


def test_basis_flip_fires_negative_to_positive():
    """basis_flip fires when basis crosses from negative to positive."""
    se = SignalEngine()
    se._start_time = 0

    snap1 = make_snapshot(basis_pct=-0.10)
    se.compute_signals(snap1)

    snap2 = make_snapshot(basis_pct=0.20)
    signals = se.compute_signals(snap2)

    flips = [s for s in signals if s["id"] == "basis_flip"]
    assert len(flips) == 1
    assert flips[0]["direction"] == "short"  # entering positive territory


def test_basis_flip_silent_same_sign():
    """basis_flip does not fire when basis stays same sign."""
    se = SignalEngine()
    se._start_time = 0

    snap1 = make_snapshot(basis_pct=0.10)
    se.compute_signals(snap1)

    snap2 = make_snapshot(basis_pct=0.15)
    signals = se.compute_signals(snap2)

    flips = [s for s in signals if s["id"] == "basis_flip"]
    assert len(flips) == 0


def test_basis_flip_needs_history():
    """basis_flip requires previous cycle — silent on first cycle."""
    se = SignalEngine()
    se._start_time = 0

    snap = make_snapshot(basis_pct=-0.10)
    signals = se.compute_signals(snap)

    flips = [s for s in signals if s["id"] == "basis_flip"]
    assert len(flips) == 0  # no prev basis yet


def test_contango_flip_fires():
    """contango_flip fires when basis < -0.1% AND OI stable (±2%)."""
    se = SignalEngine()
    se._start_time = 0

    snap = make_snapshot(basis_pct=-0.15, oi_delta_pct=0.01)  # OI +1% = stable
    signals = se.compute_signals(snap)

    contango = [s for s in signals if s["id"] == "contango_flip"]
    assert len(contango) == 1, f"expected contango_flip, got {[s['id'] for s in signals]}"
    assert contango[0]["direction"] == "long"


def test_contango_flip_silent_oi_volatile():
    """contango_flip does not fire when OI is changing too much."""
    se = SignalEngine()
    se._start_time = 0

    # OI +5% = too volatile (> ±2%)
    snap = make_snapshot(basis_pct=-0.15, oi_delta_pct=0.05)
    signals = se.compute_signals(snap)

    contango = [s for s in signals if s["id"] == "contango_flip"]
    assert len(contango) == 0


def test_contango_flip_silent_above_threshold():
    """contango_flip does not fire when basis is not deeply negative."""
    se = SignalEngine()
    se._start_time = 0

    # -0.05% is above CONTANGO_BASIS_THRESHOLD of -0.1%
    snap = make_snapshot(basis_pct=-0.05, oi_delta_pct=0.01)
    signals = se.compute_signals(snap)

    contango = [s for s in signals if s["id"] == "contango_flip"]
    assert len(contango) == 0


def test_squeeze_thresholds_calibrated_from_issue_162():
    """
    squeeze_watch (0.1%) and squeeze_risk (0.2%) calibrated against
    real data from issue #162: Binance basis +0.1051%, Bybit -0.015%.
    Binance basis is right at the squeeze_watch boundary — correct.
    """
    from aggdash.backend.signals import SQUEEZE_WATCH_BASIS_THRESHOLD, SQUEEZE_BASIS_THRESHOLD

    # Binance basis 0.1051% → 0.001051 fraction → above 0.001 watch threshold
    binance_basis = 0.001051
    assert binance_basis > SQUEEZE_WATCH_BASIS_THRESHOLD
    # but below 0.002 squeeze risk threshold
    assert binance_basis <= SQUEEZE_BASIS_THRESHOLD

    # Bybit basis -0.015% → negative, separate regime (contango_flip)
    bybit_basis = -0.00015
    assert bybit_basis < 0
    assert bybit_basis >= CONTANGO_BASIS_THRESHOLD  # above contango threshold

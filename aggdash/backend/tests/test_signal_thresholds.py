"""
test_signal_thresholds.py — Verify calibrated signal thresholds fire on synthetic data.

Module 25: thresholds lowered for BANANAS31 (low-cap token, tight basis/spread).
"""
import pytest
from signals import (
    SignalEngine,
    SQUEEZE_BASIS_THRESHOLD,
    ARB_DEVIATION_THRESHOLD,
    OI_ACCUMULATION_THRESHOLD,
    OI_DELEVERAGE_THRESHOLD,
    PRICE_DOWN_THRESHOLD,
)


@pytest.fixture
def engine():
    eng = SignalEngine()
    # Skip warmup — set start time far in the past
    eng._start_time -= 3600
    return eng


# ── Threshold sanity checks ──────────────────────────────────────────

def test_squeeze_basis_threshold_calibrated():
    """SQUEEZE_BASIS_THRESHOLD must be ≤ 0.005 (0.5%) — realistic for BANANAS31."""
    assert SQUEEZE_BASIS_THRESHOLD <= 0.005, (
        f"SQUEEZE_BASIS_THRESHOLD={SQUEEZE_BASIS_THRESHOLD} is too high for BANANAS31 (max 0.5%)"
    )


def test_arb_threshold_calibrated():
    """ARB_DEVIATION_THRESHOLD must be ≤ 0.005 (0.5%)."""
    assert ARB_DEVIATION_THRESHOLD <= 0.005, (
        f"ARB_DEVIATION_THRESHOLD={ARB_DEVIATION_THRESHOLD} is too high for BANANAS31 (max 0.5%)"
    )


def test_oi_accumulation_threshold_calibrated():
    """OI_ACCUMULATION_THRESHOLD must be < 0.05 (5%)."""
    assert OI_ACCUMULATION_THRESHOLD < 0.05, (
        f"OI_ACCUMULATION_THRESHOLD={OI_ACCUMULATION_THRESHOLD} should be < 5%"
    )


def test_oi_deleverage_threshold_calibrated():
    """OI_DELEVERAGE_THRESHOLD must be > -0.05 (-5%)."""
    assert OI_DELEVERAGE_THRESHOLD > -0.05, (
        f"OI_DELEVERAGE_THRESHOLD={OI_DELEVERAGE_THRESHOLD} should be > -5%"
    )


# ── Signal firing tests ───────────────────────────────────────────────

def _make_snapshot(basis_pct=None, funding_rate=None, spread_pct=None,
                   oi_delta_pct=None, price_delta=None):
    """Build minimal snapshot dict with override values."""
    return {
        "basis": {
            "aggregated": {"basis_pct": basis_pct if basis_pct is not None else 0.05},
            "per_exchange": {},
        },
        "funding": {
            "per_source": {
                "binance-perp": {
                    "rate_8h": funding_rate if funding_rate is not None else 0.0001,
                    "rate_1h": (funding_rate if funding_rate is not None else 0.0001) / 8,
                },
            }
        },
        "dex_cex_spread": {
            "spread_pct": spread_pct if spread_pct is not None else 0.0,
        },
        "oi_delta": {
            "aggregated": {"delta_pct": oi_delta_pct if oi_delta_pct is not None else 0.0},
        },
    }


def test_squeeze_risk_fires_on_realistic_basis(engine):
    """
    Squeeze risk should fire when basis > SQUEEZE_BASIS_THRESHOLD % and funding > 0.
    0.25% basis and positive funding is realistic for BANANAS31.
    """
    # basis_pct in percent units (0.25 means 0.25%)
    basis_pct_above = SQUEEZE_BASIS_THRESHOLD * 100 * 1.5  # 1.5x above threshold
    snap = _make_snapshot(basis_pct=basis_pct_above, funding_rate=0.0001)
    sigs = engine.compute_signals(snap)
    sig_ids = [s["id"] for s in sigs]
    assert "squeeze_risk" in sig_ids, (
        f"squeeze_risk should fire at basis_pct={basis_pct_above:.4f}% "
        f"(threshold={SQUEEZE_BASIS_THRESHOLD * 100:.4f}%)"
    )


def test_squeeze_risk_silent_below_threshold(engine):
    """Squeeze risk should NOT fire when basis is below threshold."""
    basis_pct_below = SQUEEZE_BASIS_THRESHOLD * 100 * 0.5  # 0.5x below threshold
    snap = _make_snapshot(basis_pct=basis_pct_below, funding_rate=0.0001)
    sigs = engine.compute_signals(snap)
    sig_ids = [s["id"] for s in sigs]
    assert "squeeze_risk" not in sig_ids, (
        f"squeeze_risk should NOT fire at basis_pct={basis_pct_below:.5f}% "
        f"(threshold={SQUEEZE_BASIS_THRESHOLD * 100:.4f}%)"
    )


def test_arb_opportunity_fires(engine):
    """ARB signal should fire when DEX spread > ARB_DEVIATION_THRESHOLD %."""
    # spread_pct in percent units (0.5 means 0.5%)
    spread_above = ARB_DEVIATION_THRESHOLD * 100 * 2  # 2x threshold
    snap = _make_snapshot(spread_pct=spread_above)
    sigs = engine.compute_signals(snap)
    sig_ids = [s["id"] for s in sigs]
    assert "arb_opportunity" in sig_ids, (
        f"arb_opportunity should fire at spread={spread_above:.4f}% "
        f"(threshold={ARB_DEVIATION_THRESHOLD * 100:.4f}%)"
    )


def test_arb_opportunity_silent_below_threshold(engine):
    """ARB signal should NOT fire when spread is below threshold."""
    spread_below = ARB_DEVIATION_THRESHOLD * 100 * 0.3  # 0.3x threshold
    snap = _make_snapshot(spread_pct=spread_below)
    sigs = engine.compute_signals(snap)
    sig_ids = [s["id"] for s in sigs]
    assert "arb_opportunity" not in sig_ids


def test_oi_accumulation_fires_when_flat_price(engine):
    """OI accumulation fires when OI delta % > threshold AND price is flat."""
    oi_delta = OI_ACCUMULATION_THRESHOLD * 1.5  # fraction, e.g. 0.045
    snap = _make_snapshot(oi_delta_pct=oi_delta, price_delta=None)
    sigs = engine.compute_signals(snap)
    sig_ids = [s["id"] for s in sigs]
    assert "oi_accumulation" in sig_ids, (
        f"oi_accumulation should fire at oi_delta={oi_delta:.4f} "
        f"(threshold={OI_ACCUMULATION_THRESHOLD:.4f})"
    )


def test_deleveraging_fires(engine):
    """Deleveraging fires when OI drops and price drops."""
    oi_delta = OI_DELEVERAGE_THRESHOLD * 1.5  # fraction, more negative than threshold
    snap = _make_snapshot(oi_delta_pct=oi_delta)
    # Add price delta via basis override (basis has spot_price_change_pct)
    snap["basis"]["spot_price_change_pct"] = PRICE_DOWN_THRESHOLD * 2  # e.g. -0.01
    sigs = engine.compute_signals(snap)
    sig_ids = [s["id"] for s in sigs]
    assert "deleveraging" in sig_ids, (
        f"deleveraging should fire at oi_delta={oi_delta:.4f} "
        f"(threshold={OI_DELEVERAGE_THRESHOLD:.4f})"
    )


def test_no_signals_on_empty_snapshot(engine):
    """Engine returns empty list on a zeroed-out snapshot."""
    snap = _make_snapshot(basis_pct=0.0, funding_rate=0.0, spread_pct=0.0, oi_delta_pct=0.0)
    sigs = engine.compute_signals(snap)
    assert isinstance(sigs, list)
    # squeeze_risk: basis=0 → won't fire. arb: spread=0 → won't fire. etc.
    assert len(sigs) == 0, f"Expected no signals on zeroed snapshot, got: {sigs}"


def test_warmup_period_blocks_signals(engine):
    """Signals should not fire during warmup period (< MIN_DATA_WINDOW_SECS)."""
    import time
    eng = SignalEngine()
    # Reset start time to "just now" so warmup not complete
    eng._start_time = time.time()

    basis_pct_above = SQUEEZE_BASIS_THRESHOLD * 100 * 10  # well above threshold
    snap = _make_snapshot(basis_pct=basis_pct_above, funding_rate=0.001)
    sigs = eng.compute_signals(snap)
    assert sigs == [], "Signals should be blocked during warmup period"

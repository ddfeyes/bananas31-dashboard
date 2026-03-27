"""
test_perp_spot_ratio.py — Unit tests for perp/spot volume ratio.

Module 39: SPEC §2 perp/spot volume signal.
"""


def compute_perp_spot_ratio(spot_vol, perp_vol):
    """Mirror perp_spot_ratio computation from get_stats()."""
    return (perp_vol / spot_vol) if spot_vol and spot_vol > 0 else None


def test_perp_spot_ratio_speculation():
    """Ratio >3x indicates speculation-driven (perp >> spot)."""
    # Current state: 4.2x
    ratio = compute_perp_spot_ratio(spot_vol=526e6, perp_vol=2206e6)
    assert abs(ratio - 4.2) < 0.1, f"Expected ~4.2x, got {ratio:.1f}x"
    assert ratio > 3.0


def test_perp_spot_ratio_balanced():
    """Ratio ~1x indicates balanced volumes."""
    ratio = compute_perp_spot_ratio(spot_vol=1000, perp_vol=1000)
    assert abs(ratio - 1.0) < 0.01


def test_perp_spot_ratio_spot_dominant():
    """Ratio <1 indicates organic demand (spot >> perp)."""
    ratio = compute_perp_spot_ratio(spot_vol=1000, perp_vol=400)
    assert abs(ratio - 0.4) < 0.01
    assert ratio < 1.0


def test_perp_spot_ratio_zero_spot():
    """Zero spot volume → None (avoid div by zero)."""
    ratio = compute_perp_spot_ratio(spot_vol=0, perp_vol=1000)
    assert ratio is None


def test_perp_spot_ratio_zero_both():
    """Zero both → None."""
    ratio = compute_perp_spot_ratio(spot_vol=0, perp_vol=0)
    assert ratio is None

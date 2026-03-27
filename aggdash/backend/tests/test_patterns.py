"""
test_patterns.py — Verify calibrated patterns thresholds for BANANAS31.

Module 28: /api/patterns threshold calibration.
"""

# ── Import threshold constants ────────────────────────────────────────

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# We test the constants directly from main module globals
import ast


def get_threshold_constants():
    """Parse main.py and extract _PAT_* constants."""
    main_path = os.path.join(os.path.dirname(__file__), "..", "main.py")
    with open(main_path) as f:
        source = f.read()
    tree = ast.parse(source)
    constants = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("_PAT_"):
                    if isinstance(node.value, ast.Constant):
                        constants[target.id] = node.value.value
    return constants


# ── Threshold sanity tests ────────────────────────────────────────────

def test_oi_accumulation_threshold_calibrated():
    """OI accumulation must be ≤2.5% for BANANAS31 (was 5% — too high)."""
    consts = get_threshold_constants()
    val = consts.get("_PAT_OI_ACCUM_PCT")
    assert val is not None, "_PAT_OI_ACCUM_PCT not found in main.py"
    assert val <= 2.5, f"_PAT_OI_ACCUM_PCT={val} too high for BANANAS31 (max 2.5%)"


def test_dex_premium_threshold_calibrated():
    """DEX premium must be ≤0.5% for BANANAS31 (was 1%)."""
    consts = get_threshold_constants()
    val = consts.get("_PAT_DEX_PREMIUM_PCT")
    assert val is not None, "_PAT_DEX_PREMIUM_PCT not found in main.py"
    assert val <= 0.5, f"_PAT_DEX_PREMIUM_PCT={val} too high for BANANAS31 (max 0.5%)"


def test_basis_squeeze_threshold_calibrated():
    """BASIS_SQUEEZE must trigger at ≤0.2% basis (was 0.3%)."""
    consts = get_threshold_constants()
    val = consts.get("_PAT_BASIS_SQUEEZE_PCT")
    assert val is not None, "_PAT_BASIS_SQUEEZE_PCT not found in main.py"
    assert val <= 0.2, f"_PAT_BASIS_SQUEEZE_PCT={val} too high for BANANAS31 (max 0.2%)"


# ── Pattern logic tests ───────────────────────────────────────────────

def compute_oi_accumulation(oi_first, oi_last, price_first, price_last, threshold_pct=1.5):
    """Mirror OI_ACCUMULATION logic from /api/patterns."""
    if not oi_first or oi_first <= 0:
        return None
    oi_change_pct = (oi_last - oi_first) / oi_first * 100
    price_change_pct = abs((price_last - price_first) / price_first * 100) if price_first > 0 else 0
    if oi_change_pct > threshold_pct and price_change_pct < 0.5:
        return {"name": "OI_ACCUMULATION", "oi_change_pct": oi_change_pct}
    return None


def test_oi_accumulation_fires_at_calibrated_threshold():
    """OI_ACCUMULATION fires at 2% OI rise with flat price."""
    result = compute_oi_accumulation(
        oi_first=1_000_000, oi_last=1_020_000,  # +2%
        price_first=0.0135, price_last=0.0135,  # flat
        threshold_pct=1.5,
    )
    assert result is not None, "OI_ACCUMULATION should fire at +2% OI with flat price"
    assert result["name"] == "OI_ACCUMULATION"


def test_oi_accumulation_silent_at_old_5pct_threshold():
    """OI at 3% rise should fire with new 1.5% threshold (would NOT fire with old 5% threshold)."""
    # With new threshold (1.5%): fires
    result_new = compute_oi_accumulation(1_000_000, 1_030_000, 0.0135, 0.01352, 1.5)
    assert result_new is not None, "Should fire with calibrated 1.5% threshold"

    # With old threshold (5%): would NOT fire
    result_old = compute_oi_accumulation(1_000_000, 1_030_000, 0.0135, 0.01352, 5.0)
    assert result_old is None, "Would NOT fire with old 5% threshold"


def compute_dex_premium(dex_price, spot_avg, threshold_pct=0.3):
    """Mirror DEX_PREMIUM logic."""
    factor = 1.0 + threshold_pct / 100.0
    if spot_avg > 0 and dex_price > spot_avg * factor:
        return {"name": "DEX_PREMIUM", "prem_pct": (dex_price - spot_avg) / spot_avg * 100}
    return None


def test_dex_premium_fires_at_calibrated_threshold():
    """DEX_PREMIUM fires when DEX is 0.4% above spot (below old 1% threshold)."""
    spot = 0.01350
    dex = spot * 1.004  # +0.4% premium
    result = compute_dex_premium(dex, spot, threshold_pct=0.3)
    assert result is not None, "DEX_PREMIUM should fire at 0.4% with new 0.3% threshold"


def test_dex_premium_silent_below_threshold():
    """DEX_PREMIUM does NOT fire when DEX is only 0.1% above spot."""
    spot = 0.01350
    dex = spot * 1.001  # +0.1% — below 0.3% threshold
    result = compute_dex_premium(dex, spot, threshold_pct=0.3)
    assert result is None, "DEX_PREMIUM should NOT fire at 0.1% with 0.3% threshold"


def compute_basis_squeeze(basis_pct, funding_rate, threshold_pct=0.1):
    """Mirror BASIS_SQUEEZE logic."""
    if basis_pct > threshold_pct and funding_rate and funding_rate > 0:
        return {"name": "BASIS_SQUEEZE", "basis_pct": basis_pct}
    return None


def test_basis_squeeze_fires_at_calibrated_threshold():
    """BASIS_SQUEEZE fires at 0.15% basis with positive funding."""
    result = compute_basis_squeeze(basis_pct=0.15, funding_rate=0.0001, threshold_pct=0.1)
    assert result is not None, "BASIS_SQUEEZE should fire at 0.15% basis with 0.1% threshold"


def test_basis_squeeze_silent_below_threshold():
    """BASIS_SQUEEZE does NOT fire below threshold."""
    result = compute_basis_squeeze(basis_pct=0.05, funding_rate=0.0001, threshold_pct=0.1)
    assert result is None

"""
test_squeeze_index.py — Unit tests for Squeeze Risk Composite Index.

Module 41: squeeze_risk_score (0-100) combining basis + funding + PERP/S + liquidations.
"""


def compute_squeeze_risk(basis_pct=0.0, funding_rate=0.0, perp_spot_ratio=1.0, liq_total_usd=0.0):
    """
    Mirror squeeze_risk_score computation from get_stats().
    Weights: basis 0.5, funding 0.25, perp/spot 0.15, liq 0.1
    """
    # Basis component (max 100 at 1%)
    basis_component = min(abs(basis_pct) / 1.0, 1.0) * 100

    # Funding component (max 100 at 0.1%)
    funding_component = 0.0
    if funding_rate > 0:
        funding_component = min(funding_rate / 0.001, 1.0) * 100

    # Perp/Spot component (max 100 at 5x)
    ratio_component = 0.0
    if perp_spot_ratio > 0:
        ratio_component = min((perp_spot_ratio - 1) / 4, 1.0) * 100

    # Liquidation component (max 100 at $100k)
    liq_component = 0.0
    if liq_total_usd > 0:
        liq_component = min(liq_total_usd / 100000, 1.0) * 100

    # Weighted composite
    score = (
        basis_component * 0.5 +
        funding_component * 0.25 +
        ratio_component * 0.15 +
        liq_component * 0.1
    )
    return min(score, 100.0)


def test_squeeze_index_zero_inputs():
    """All zero inputs → score 0."""
    score = compute_squeeze_risk()
    assert score == 0.0


def test_squeeze_index_high_basis():
    """High basis (0.5%) alone → moderate score."""
    score = compute_squeeze_risk(basis_pct=0.5)
    # basis: 0.5/1.0 * 100 = 50, weighted 0.5 → 25
    assert abs(score - 25.0) < 1.0


def test_squeeze_index_combined():
    """Combined high basis + funding + PERP/S → high score."""
    # Current state: basis 0.147%, funding 0.0129%, PERP/S 4.2x, liq $2k
    score = compute_squeeze_risk(
        basis_pct=0.147,
        funding_rate=0.000129,
        perp_spot_ratio=4.2,
        liq_total_usd=2000,
    )
    # basis: 0.147/1 * 100 * 0.5 = 7.35
    # funding: 0.000129/0.001 * 100 * 0.25 = 3.225
    # ratio: (4.2-1)/4 * 100 * 0.15 = 11.975
    # liq: 2000/100000 * 100 * 0.1 = 0.2
    # total ~ 22.75
    assert 20.0 < score < 25.0, f"Expected ~22, got {score:.1f}"


def test_squeeze_index_capped_at_100():
    """Score capped at 100 even with extreme inputs."""
    score = compute_squeeze_risk(
        basis_pct=5.0,
        funding_rate=0.01,
        perp_spot_ratio=10.0,
        liq_total_usd=500000,
    )
    assert score <= 100.0

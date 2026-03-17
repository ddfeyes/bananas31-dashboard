"""
Leverage Ratio Heatmap — Wave 24 Task 5 (Issue #129).

Computes OI/MCap leverage ratios across major crypto assets (BTC, ETH, SOL, BNB),
assigns risk signals and heatmap colors, and returns 30-day history.

Data source: seeded mock (deterministic per symbol, no live API).
"""
import random
from typing import Dict, List, Optional

# Supported cross-market assets
ASSETS = ("BTC", "ETH", "SOL", "BNB")

# Valid risk signals
RISK_SIGNALS = ("high", "medium", "low")

# Valid trend values
TRENDS = ("rising", "falling", "stable")

# Valid heatmap colors
HEATMAP_COLORS = ("red", "orange", "yellow", "green")

# Leverage ratio thresholds for risk classification
HIGH_LEVERAGE_THRESHOLD = 1.4
MEDIUM_LEVERAGE_THRESHOLD = 1.0

# Heatmap color thresholds
RED_THRESHOLD = 1.5
ORANGE_THRESHOLD = 1.2
YELLOW_THRESHOLD = 0.9

# Base OI and market cap values (approximate real-world scale, USD)
_BASE_OI = {
    "BTC": 18_500_000_000,
    "ETH": 9_200_000_000,
    "SOL": 3_100_000_000,
    "BNB": 1_400_000_000,
}

_BASE_MCAP = {
    "BTC": 12_000_000_000,
    "ETH": 7_500_000_000,
    "SOL": 2_800_000_000,
    "BNB": 1_200_000_000,
}

_SECTOR = "crypto_perps"

_DESCRIPTION = (
    "Leverage Ratio (OI/MCap) measures open interest relative to market cap. "
    "High ratios signal elevated leverage and potential cascade risk. "
    "Values above 1.4 are high risk; above 1.0 are medium risk."
)


def _symbol_seed(symbol: str) -> int:
    """Deterministic seed from symbol string."""
    return sum(ord(c) * (i + 1) for i, c in enumerate(symbol))


def compute_asset_leverage(asset: str, rng: random.Random) -> Dict:
    """
    Compute leverage ratio data for a single asset.

    Returns dict with oi_usd, leverage_ratio, percentile_rank (placeholder 0),
    risk_signal, risk_score, trend, heatmap_color, history_30d.
    """
    base_oi = _BASE_OI.get(asset, 1_000_000_000)
    base_mcap = _BASE_MCAP.get(asset, 1_000_000_000)

    # Add seeded noise (±20%)
    oi_usd = round(base_oi * rng.uniform(0.80, 1.20))
    mcap_usd = round(base_mcap * rng.uniform(0.80, 1.20))

    leverage_ratio = round(oi_usd / mcap_usd, 3)

    risk_signal = _classify_risk_signal(leverage_ratio)
    risk_score = _compute_risk_score(leverage_ratio)
    trend = _classify_trend(rng)
    heatmap_color = _leverage_to_color(leverage_ratio)
    history_30d = _generate_history_30d(asset, leverage_ratio, rng)

    return {
        "oi_usd": oi_usd,
        "leverage_ratio": leverage_ratio,
        "percentile_rank": 0,  # filled in after ranking all assets
        "risk_signal": risk_signal,
        "risk_score": risk_score,
        "trend": trend,
        "heatmap_color": heatmap_color,
        "history_30d": history_30d,
    }


def _classify_risk_signal(leverage_ratio: float) -> str:
    """Classify risk signal from leverage ratio."""
    if leverage_ratio >= HIGH_LEVERAGE_THRESHOLD:
        return "high"
    if leverage_ratio >= MEDIUM_LEVERAGE_THRESHOLD:
        return "medium"
    return "low"


def _compute_risk_score(leverage_ratio: float) -> float:
    """
    Risk score 0–100 proportional to leverage ratio.
    Clamped: 0 at leverage=0, 100 at leverage>=2.0.
    """
    score = min(100.0, (leverage_ratio / 2.0) * 100.0)
    return round(max(0.0, score), 1)


def _classify_trend(rng: random.Random) -> str:
    """Seeded random trend selection."""
    return rng.choices(TRENDS, weights=[0.4, 0.3, 0.3])[0]


def _leverage_to_color(leverage_ratio: float) -> str:
    """Map leverage ratio to heatmap color."""
    if leverage_ratio >= RED_THRESHOLD:
        return "red"
    if leverage_ratio >= ORANGE_THRESHOLD:
        return "orange"
    if leverage_ratio >= YELLOW_THRESHOLD:
        return "yellow"
    return "green"


def _generate_history_30d(
    asset: str, current_ratio: float, rng: random.Random
) -> List[Dict]:
    """
    Generate 30-day leverage ratio history ending at current_ratio.

    Returns list of {date, leverage_ratio} dicts, oldest first.
    """
    from datetime import date, timedelta

    history = []
    today = date(2026, 3, 16)
    ratio = current_ratio * rng.uniform(0.85, 0.95)  # start slightly lower

    for day_offset in range(30, 0, -1):
        d = today - timedelta(days=day_offset)
        # Random walk toward current_ratio
        delta = rng.uniform(-0.03, 0.04)
        ratio = round(max(0.1, ratio + delta), 3)
        history.append({"date": str(d), "leverage_ratio": ratio})

    return history


def assign_percentile_ranks(assets_data: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Assign percentile_rank (0–100) to each asset based on leverage_ratio.

    Highest leverage_ratio gets rank 100, lowest gets 0.
    """
    sorted_assets = sorted(
        assets_data.keys(),
        key=lambda a: assets_data[a]["leverage_ratio"],
    )
    n = len(sorted_assets)
    for rank_idx, asset in enumerate(sorted_assets):
        if n == 1:
            pct = 100
        else:
            pct = round(rank_idx / (n - 1) * 100)
        assets_data[asset]["percentile_rank"] = pct
    return assets_data


def compute_leverage_ratio_heatmap(symbol: Optional[str] = None) -> Dict:
    """
    Main entry point: compute leverage ratio heatmap across BTC/ETH/SOL/BNB.

    Returns:
        assets: dict of asset -> {oi_usd, leverage_ratio, percentile_rank,
                                   risk_signal, risk_score, trend,
                                   heatmap_color, history_30d}
        sector: str
        description: str
    """
    seed = _symbol_seed(symbol or "BTCUSDT")
    rng = random.Random(seed)

    assets_data: Dict[str, Dict] = {}
    for asset in ASSETS:
        asset_rng = random.Random(seed + _symbol_seed(asset))
        assets_data[asset] = compute_asset_leverage(asset, asset_rng)

    assign_percentile_ranks(assets_data)

    return {
        "assets": assets_data,
        "sector": _SECTOR,
        "description": _DESCRIPTION,
    }
"""
TDD tests for Leverage Ratio Heatmap (Wave 24 Task 5, Issue #129).
8+ tests covering: compute functions, risk classification, color mapping,
history generation, percentile ranking, API structure, HTML/JS presence.
"""
import os
import sys
import tempfile

import pytest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
os.environ.setdefault("SYMBOL_BYBIT", "BANANAS31USDT")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from leverage_heatmap import (  # noqa: E402
    ASSETS,
    HEATMAP_COLORS,
    RISK_SIGNALS,
    TRENDS,
    assign_percentile_ranks,
    compute_asset_leverage,
    compute_leverage_ratio_heatmap,
    _classify_risk_signal,
    _compute_risk_score,
    _leverage_to_color,
)

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def btc_result():
    return compute_leverage_ratio_heatmap("BTCUSDT")


@pytest.fixture(scope="module")
def default_result():
    return compute_leverage_ratio_heatmap()


@pytest.fixture(scope="module")
def eth_result():
    return compute_leverage_ratio_heatmap("ETHUSDT")


# ── Top-level structure ───────────────────────────────────────────────────────

def test_result_is_dict(btc_result):
    assert isinstance(btc_result, dict)


def test_result_has_assets_key(btc_result):
    assert "assets" in btc_result


def test_result_has_sector(btc_result):
    assert "sector" in btc_result
    assert isinstance(btc_result["sector"], str)
    assert len(btc_result["sector"]) > 0


def test_result_has_description(btc_result):
    assert "description" in btc_result
    assert isinstance(btc_result["description"], str)
    assert len(btc_result["description"]) > 10


def test_all_four_assets_present(btc_result):
    for asset in ASSETS:
        assert asset in btc_result["assets"], f"Missing asset: {asset}"


def test_assets_is_dict(btc_result):
    assert isinstance(btc_result["assets"], dict)


# ── Per-asset field presence ──────────────────────────────────────────────────

def test_asset_has_oi_usd(btc_result):
    for asset in ASSETS:
        assert "oi_usd" in btc_result["assets"][asset]


def test_asset_has_leverage_ratio(btc_result):
    for asset in ASSETS:
        assert "leverage_ratio" in btc_result["assets"][asset]


def test_asset_has_percentile_rank(btc_result):
    for asset in ASSETS:
        assert "percentile_rank" in btc_result["assets"][asset]


def test_asset_has_risk_signal(btc_result):
    for asset in ASSETS:
        assert "risk_signal" in btc_result["assets"][asset]


def test_asset_has_risk_score(btc_result):
    for asset in ASSETS:
        assert "risk_score" in btc_result["assets"][asset]


def test_asset_has_trend(btc_result):
    for asset in ASSETS:
        assert "trend" in btc_result["assets"][asset]


def test_asset_has_heatmap_color(btc_result):
    for asset in ASSETS:
        assert "heatmap_color" in btc_result["assets"][asset]


def test_asset_has_history_30d(btc_result):
    for asset in ASSETS:
        assert "history_30d" in btc_result["assets"][asset]


# ── Field value validation ────────────────────────────────────────────────────

def test_leverage_ratio_positive(btc_result):
    for asset in ASSETS:
        lr = btc_result["assets"][asset]["leverage_ratio"]
        assert lr > 0, f"{asset} leverage_ratio must be positive"


def test_oi_usd_positive(btc_result):
    for asset in ASSETS:
        assert btc_result["assets"][asset]["oi_usd"] > 0


def test_risk_signal_valid_enum(btc_result):
    for asset in ASSETS:
        sig = btc_result["assets"][asset]["risk_signal"]
        assert sig in RISK_SIGNALS, f"{asset} risk_signal '{sig}' not in {RISK_SIGNALS}"


def test_heatmap_color_valid_enum(btc_result):
    for asset in ASSETS:
        color = btc_result["assets"][asset]["heatmap_color"]
        assert color in HEATMAP_COLORS, f"{asset} heatmap_color '{color}' not in {HEATMAP_COLORS}"


def test_trend_valid_enum(btc_result):
    for asset in ASSETS:
        trend = btc_result["assets"][asset]["trend"]
        assert trend in TRENDS, f"{asset} trend '{trend}' not in {TRENDS}"


def test_risk_score_range(btc_result):
    for asset in ASSETS:
        score = btc_result["assets"][asset]["risk_score"]
        assert 0 <= score <= 100, f"{asset} risk_score {score} out of range"


def test_percentile_rank_range(btc_result):
    for asset in ASSETS:
        rank = btc_result["assets"][asset]["percentile_rank"]
        assert 0 <= rank <= 100, f"{asset} percentile_rank {rank} out of range"


def test_percentile_ranks_include_0_and_100(btc_result):
    """With 4 assets, ranks must include 0 and 100."""
    ranks = [btc_result["assets"][a]["percentile_rank"] for a in ASSETS]
    assert 0 in ranks
    assert 100 in ranks


def test_history_30d_length(btc_result):
    for asset in ASSETS:
        history = btc_result["assets"][asset]["history_30d"]
        assert len(history) == 30, f"{asset} history_30d length {len(history)} != 30"


def test_history_30d_has_date_and_ratio(btc_result):
    for asset in ASSETS:
        history = btc_result["assets"][asset]["history_30d"]
        for entry in history:
            assert "date" in entry
            assert "leverage_ratio" in entry
            assert isinstance(entry["leverage_ratio"], float)


def test_history_30d_leverage_ratio_positive(btc_result):
    for asset in ASSETS:
        for entry in btc_result["assets"][asset]["history_30d"]:
            assert entry["leverage_ratio"] > 0


# ── _classify_risk_signal ─────────────────────────────────────────────────────

def test_classify_risk_signal_high():
    assert _classify_risk_signal(1.5) == "high"


def test_classify_risk_signal_medium():
    assert _classify_risk_signal(1.2) == "medium"


def test_classify_risk_signal_low():
    assert _classify_risk_signal(0.8) == "low"


def test_classify_risk_signal_boundary_high():
    assert _classify_risk_signal(1.4) == "high"


def test_classify_risk_signal_boundary_medium():
    assert _classify_risk_signal(1.0) == "medium"


def test_classify_risk_signal_just_below_medium():
    assert _classify_risk_signal(0.99) == "low"


# ── _compute_risk_score ───────────────────────────────────────────────────────

def test_risk_score_zero_at_zero():
    assert _compute_risk_score(0.0) == 0.0


def test_risk_score_100_at_two():
    assert _compute_risk_score(2.0) == 100.0


def test_risk_score_clamped_above_two():
    assert _compute_risk_score(5.0) == 100.0


def test_risk_score_fifty_at_one():
    assert _compute_risk_score(1.0) == 50.0


# ── _leverage_to_color ────────────────────────────────────────────────────────

def test_leverage_to_color_red():
    assert _leverage_to_color(1.6) == "red"


def test_leverage_to_color_orange():
    assert _leverage_to_color(1.3) == "orange"


def test_leverage_to_color_yellow():
    assert _leverage_to_color(1.0) == "yellow"


def test_leverage_to_color_green():
    assert _leverage_to_color(0.5) == "green"


# ── assign_percentile_ranks ───────────────────────────────────────────────────

def test_assign_percentile_ranks_single():
    data = {"BTC": {"leverage_ratio": 1.5}}
    result = assign_percentile_ranks(data)
    assert result["BTC"]["percentile_rank"] == 100


def test_assign_percentile_ranks_two_assets():
    data = {
        "BTC": {"leverage_ratio": 1.5},
        "ETH": {"leverage_ratio": 0.8},
    }
    result = assign_percentile_ranks(data)
    assert result["BTC"]["percentile_rank"] == 100
    assert result["ETH"]["percentile_rank"] == 0


def test_assign_percentile_ranks_consistent(btc_result):
    """Highest leverage_ratio asset has rank 100."""
    assets = btc_result["assets"]
    highest = max(assets, key=lambda a: assets[a]["leverage_ratio"])
    assert assets[highest]["percentile_rank"] == 100


# ── Determinism ───────────────────────────────────────────────────────────────

def test_deterministic_same_symbol():
    r1 = compute_leverage_ratio_heatmap("BTCUSDT")
    r2 = compute_leverage_ratio_heatmap("BTCUSDT")
    for asset in ASSETS:
        assert r1["assets"][asset]["leverage_ratio"] == r2["assets"][asset]["leverage_ratio"]


def test_different_symbols_may_differ(btc_result, eth_result):
    """Two different symbols should produce at least one different OI value."""
    diffs = sum(
        1 for a in ASSETS
        if btc_result["assets"][a]["oi_usd"] != eth_result["assets"][a]["oi_usd"]
    )
    assert diffs > 0


def test_default_symbol_returns_result(default_result):
    assert isinstance(default_result, dict)
    assert "assets" in default_result


# ── Integration: API + HTML + JS presence ────────────────────────────────────

def test_endpoint_in_api():
    api_path = os.path.join(_ROOT, "backend", "api.py")
    with open(api_path, encoding="utf-8") as f:
        content = f.read()
    assert "leverage-ratio-heatmap" in content


def test_compute_function_imported_in_api():
    api_path = os.path.join(_ROOT, "backend", "api.py")
    with open(api_path, encoding="utf-8") as f:
        content = f.read()
    assert "compute_leverage_ratio_heatmap" in content


def test_html_card_present():
    html_path = os.path.join(_ROOT, "frontend", "index.html")
    with open(html_path, encoding="utf-8") as f:
        content = f.read()
    assert "card-leverage-heatmap" in content


def test_html_badge_present():
    html_path = os.path.join(_ROOT, "frontend", "index.html")
    with open(html_path, encoding="utf-8") as f:
        content = f.read()
    assert "leverage-heatmap-badge" in content


def test_html_content_div_present():
    html_path = os.path.join(_ROOT, "frontend", "index.html")
    with open(html_path, encoding="utf-8") as f:
        content = f.read()
    assert "leverage-heatmap-content" in content


def test_js_render_function_present():
    js_path = os.path.join(_ROOT, "frontend", "app.js")
    with open(js_path, encoding="utf-8") as f:
        content = f.read()
    assert "renderLeverageHeatmap" in content


def test_js_wired_into_refresh():
    js_path = os.path.join(_ROOT, "frontend", "app.js")
    with open(js_path, encoding="utf-8") as f:
        content = f.read()
    assert "safe(renderLeverageHeatmap)" in content

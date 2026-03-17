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

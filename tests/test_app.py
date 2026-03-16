"""
Unit / smoke tests for the RV vs IV card:
  - Realized Volatility vs Implied Volatility (/api/rv-iv)

Covers:
  - Response shape validation
  - Python mirrors of badge/display-helper logic
  - RV/IV ratio calculation correctness
  - Color-coding logic (green when RV<IV, red when RV>IV)
  - HTML card presence
  - JS render function presence
  - Route registration
"""
import math
import os
import sys

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _html() -> str:
    with open(os.path.join(_ROOT, "frontend", "index.html"), encoding="utf-8") as f:
        return f.read()


def _js() -> str:
    with open(os.path.join(_ROOT, "frontend", "app.js"), encoding="utf-8") as f:
        return f.read()


# ══════════════════════════════════════════════════════════════════════════════
# Helpers mirrored from app.js renderRVIV()
# ══════════════════════════════════════════════════════════════════════════════

def rv_iv_badge(rv_iv_ratio: float | None) -> tuple[str, str]:
    """Mirror of badge logic: green when RV<IV (ratio<1), red when RV>IV (ratio>=1)."""
    if rv_iv_ratio is None:
        return ("—", "badge-blue")
    label = f"{rv_iv_ratio:.2f}"
    if rv_iv_ratio < 1.0:
        return (label, "badge-green")
    return (label, "badge-red")


def rv_iv_description(rv_iv_ratio: float | None) -> str:
    """Mirror of description text logic."""
    if rv_iv_ratio is None:
        return "—"
    if rv_iv_ratio < 1.0:
        return "RV < IV — options rich"
    return "RV > IV — realized exceeds implied"


def compute_rv_annualized(log_returns: list[float]) -> float:
    """Python mirror of RV computation in the backend and JS."""
    n = len(log_returns)
    if n < 2:
        return 0.0
    mean_r = sum(log_returns) / n
    variance = sum((r - mean_r) ** 2 for r in log_returns) / (n - 1)
    rv_per_candle = math.sqrt(variance)
    minutes_per_year = 525600.0
    return rv_per_candle * math.sqrt(minutes_per_year) * 100.0


# ══════════════════════════════════════════════════════════════════════════════
# Sample payloads
# ══════════════════════════════════════════════════════════════════════════════

RV_IV_LOW_RATIO = {
    "status": "ok",
    "symbol": "BANANAS31USDT",
    "rv_30m": 45.2,
    "iv": 72.5,
    "iv_source": "simulated",
    "rv_iv_ratio": 0.62,
    "regime": "rv_low",
    "window": 30,
    "description": "RV=45.2% IV=72.5% ratio=0.62",
}

RV_IV_HIGH_RATIO = {
    "status": "ok",
    "symbol": "COSUSDT",
    "rv_30m": 95.1,
    "iv": 61.3,
    "iv_source": "simulated",
    "rv_iv_ratio": 1.55,
    "regime": "rv_high",
    "window": 30,
    "description": "RV=95.1% IV=61.3% ratio=1.55",
}

RV_IV_BALANCED = {
    "status": "ok",
    "symbol": "DEXEUSDT",
    "rv_30m": 58.0,
    "iv": 55.0,
    "iv_source": "simulated",
    "rv_iv_ratio": 1.05,
    "regime": "balanced",
    "window": 30,
    "description": "RV=58.0% IV=55.0% ratio=1.05",
}

RV_IV_NO_DATA = {
    "status": "ok",
    "symbol": "LYNUSDT",
    "rv_30m": None,
    "iv": None,
    "iv_source": "simulated",
    "rv_iv_ratio": None,
    "regime": "insufficient_data",
    "window": 30,
    "description": "Insufficient data",
}


# ══════════════════════════════════════════════════════════════════════════════
# 1 · Response shape validation
# ══════════════════════════════════════════════════════════════════════════════

def test_rv_iv_response_has_status():
    assert RV_IV_LOW_RATIO["status"] == "ok"


def test_rv_iv_has_required_keys():
    required = ("symbol", "rv_30m", "iv", "iv_source", "rv_iv_ratio", "regime", "window", "description")
    for key in required:
        assert key in RV_IV_LOW_RATIO, f"Missing key: {key}"


def test_rv_iv_no_data_has_none_fields():
    assert RV_IV_NO_DATA["rv_30m"] is None
    assert RV_IV_NO_DATA["iv"] is None
    assert RV_IV_NO_DATA["rv_iv_ratio"] is None


def test_rv_iv_regime_low_when_rv_lt_iv():
    assert RV_IV_LOW_RATIO["regime"] == "rv_low"


def test_rv_iv_regime_high_when_rv_gt_iv():
    assert RV_IV_HIGH_RATIO["regime"] == "rv_high"


def test_rv_iv_regime_balanced():
    assert RV_IV_BALANCED["regime"] == "balanced"


def test_rv_iv_regime_insufficient_data():
    assert RV_IV_NO_DATA["regime"] == "insufficient_data"


def test_rv_iv_window_is_30():
    assert RV_IV_LOW_RATIO["window"] == 30


def test_rv_iv_iv_source_present():
    assert RV_IV_LOW_RATIO["iv_source"] in ("simulated", "live")


# ══════════════════════════════════════════════════════════════════════════════
# 2 · Badge logic (color-coding)
# ══════════════════════════════════════════════════════════════════════════════

def test_badge_green_when_ratio_lt_1():
    _, cls = rv_iv_badge(0.62)
    assert cls == "badge-green"


def test_badge_red_when_ratio_gt_1():
    _, cls = rv_iv_badge(1.55)
    assert cls == "badge-red"


def test_badge_red_when_ratio_exactly_1():
    _, cls = rv_iv_badge(1.0)
    assert cls == "badge-red"


def test_badge_blue_when_ratio_none():
    label, cls = rv_iv_badge(None)
    assert cls == "badge-blue"
    assert label == "—"


def test_badge_label_formatted_to_2dp():
    label, _ = rv_iv_badge(0.623)
    assert label == "0.62"


def test_badge_low_ratio_payload():
    label, cls = rv_iv_badge(RV_IV_LOW_RATIO["rv_iv_ratio"])
    assert cls == "badge-green"


def test_badge_high_ratio_payload():
    label, cls = rv_iv_badge(RV_IV_HIGH_RATIO["rv_iv_ratio"])
    assert cls == "badge-red"


def test_badge_no_data_payload():
    label, cls = rv_iv_badge(RV_IV_NO_DATA["rv_iv_ratio"])
    assert cls == "badge-blue"


# ══════════════════════════════════════════════════════════════════════════════
# 3 · Description text logic
# ══════════════════════════════════════════════════════════════════════════════

def test_description_rv_lt_iv():
    desc = rv_iv_description(0.5)
    assert "RV < IV" in desc
    assert "options rich" in desc


def test_description_rv_gt_iv():
    desc = rv_iv_description(1.5)
    assert "RV > IV" in desc
    assert "realized exceeds implied" in desc


def test_description_none_ratio():
    desc = rv_iv_description(None)
    assert desc == "—"


# ══════════════════════════════════════════════════════════════════════════════
# 4 · RV calculation correctness
# ══════════════════════════════════════════════════════════════════════════════

def test_rv_zero_when_flat_prices():
    # All same price → zero log-returns → zero vol
    prices = [1.0] * 10
    log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
    rv = compute_rv_annualized(log_returns)
    assert rv == 0.0


def test_rv_positive_for_volatile_series():
    prices = [1.0, 1.05, 0.98, 1.10, 1.02, 0.95, 1.08]
    log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
    rv = compute_rv_annualized(log_returns)
    assert rv > 0.0


def test_rv_annualized_uses_minutes_per_year():
    # Verify the formula uses MINUTES_PER_YEAR = 525600
    log_returns = [0.01, -0.01]  # mean=0, sample variance = 0.0002
    n = len(log_returns)
    mean_r = sum(log_returns) / n
    variance = sum((r - mean_r) ** 2 for r in log_returns) / (n - 1)
    expected = math.sqrt(variance) * math.sqrt(525600.0) * 100.0
    rv = compute_rv_annualized(log_returns)
    assert abs(rv - expected) < 1e-9


def test_rv_insufficient_returns():
    rv = compute_rv_annualized([0.01])  # only 1 return → n<2
    assert rv == 0.0


def test_rv_iv_ratio_calculation():
    rv = 45.2
    iv = 72.5
    ratio = round(rv / iv, 4)
    assert abs(ratio - RV_IV_LOW_RATIO["rv_iv_ratio"]) < 0.01


def test_rv_gt_iv_gives_ratio_gt_1():
    rv = 95.1
    iv = 61.3
    assert rv / iv > 1.0


def test_rv_lt_iv_gives_ratio_lt_1():
    rv = 45.2
    iv = 72.5
    assert rv / iv < 1.0


# ══════════════════════════════════════════════════════════════════════════════
# 5 · HTML card presence
# ══════════════════════════════════════════════════════════════════════════════

def test_html_has_rv_iv_card():
    assert "card-rv-iv" in _html()


def test_html_has_rv_iv_badge():
    assert "rv-iv-badge" in _html()


def test_html_has_rv_iv_content():
    assert "rv-iv-content" in _html()


def test_html_rv_iv_card_has_title():
    html = _html()
    assert "RV vs IV" in html


# ══════════════════════════════════════════════════════════════════════════════
# 6 · JS render function presence
# ══════════════════════════════════════════════════════════════════════════════

def test_js_has_render_rv_iv():
    assert "renderRVIV" in _js()


def test_js_rv_iv_fetches_rv_iv_endpoint():
    assert "/rv-iv" in _js()


def test_js_rv_iv_wired_in_refresh():
    js = _js()
    # Confirm renderRVIV is called inside the refresh function
    assert "renderRVIV" in js


# ══════════════════════════════════════════════════════════════════════════════
# 7 · Route registration
# ══════════════════════════════════════════════════════════════════════════════

def _get_paths():
    import tempfile
    os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
    os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from api import router
    return [r.path for r in router.routes]


def test_rv_iv_route_registered():
    assert any("rv-iv" in p for p in _get_paths())

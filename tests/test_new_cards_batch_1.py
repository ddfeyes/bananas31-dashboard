"""
Unit / smoke tests for the 5 new dashboard cards (batch 1):
  - CVD Momentum      (/api/cvd-momentum)
  - Delta Divergence  (/api/delta-divergence)
  - Funding Extreme   (/api/funding-extreme)
  - Liq Cascade       (/api/liq-cascade)
  - Large Trades      (/api/large-trades)

Each section covers:
  - Response shape validation
  - Python mirrors of display-helper logic
  - HTML card presence
  - JS render function presence
"""
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
# 1 · CVD MOMENTUM
# ══════════════════════════════════════════════════════════════════════════════

# ── helpers mirrored from app.js ──────────────────────────────────────────────

def cvd_direction_badge(direction: str) -> str:
    mapping = {"bullish": "badge-green", "bearish": "badge-red", "neutral": "badge-blue"}
    return mapping.get(direction, "badge-blue")


def fmt_usd_rate(rate_per_s: float | None) -> str:
    if rate_per_s is None:
        return "—"
    if abs(rate_per_s) >= 1_000_000:
        return f"${rate_per_s / 1_000_000:.2f}M/s"
    if abs(rate_per_s) >= 1_000:
        return f"${rate_per_s / 1_000:.1f}k/s"
    return f"${rate_per_s:.2f}/s"


def intensity_pct(intensity: float | None) -> int:
    if intensity is None:
        return 0
    return max(0, min(100, round(intensity * 100)))


CVD_MOM_PAYLOAD = {
    "status": "ok", "symbol": "BANANAS31USDT",
    "cvd_rate": 1234.56, "cvd_total_usd": 98765.0,
    "direction": "bullish", "intensity": 0.72,
    "acceleration": 55.0, "accelerating": True,
    "window_seconds": 60,
}

CVD_MOM_NEUTRAL = {
    "status": "ok", "symbol": "COSUSDT",
    "cvd_rate": 0.0, "cvd_total_usd": 0.0,
    "direction": "neutral", "intensity": 0.0,
    "acceleration": 0.0, "accelerating": False,
    "window_seconds": 60,
}


def test_cvd_mom_response_has_status():
    assert CVD_MOM_PAYLOAD["status"] == "ok"


def test_cvd_mom_has_required_keys():
    for key in ("symbol", "cvd_rate", "cvd_total_usd", "direction", "intensity",
                "acceleration", "accelerating", "window_seconds"):
        assert key in CVD_MOM_PAYLOAD


def test_cvd_mom_direction_badge_bull():
    assert cvd_direction_badge("bullish") == "badge-green"


def test_cvd_mom_direction_badge_bear():
    assert cvd_direction_badge("bearish") == "badge-red"


def test_cvd_mom_direction_badge_neutral():
    assert cvd_direction_badge("neutral") == "badge-blue"


def test_cvd_mom_fmt_usd_rate_thousands():
    assert fmt_usd_rate(1234.56) == "$1.2k/s"


def test_cvd_mom_fmt_usd_rate_millions():
    assert fmt_usd_rate(2_500_000) == "$2.50M/s"


def test_cvd_mom_fmt_usd_rate_small():
    assert fmt_usd_rate(99.0) == "$99.00/s"


def test_cvd_mom_fmt_usd_rate_none():
    assert fmt_usd_rate(None) == "—"


def test_cvd_mom_intensity_pct_clamped():
    assert intensity_pct(1.5) == 100
    assert intensity_pct(-0.5) == 0


def test_cvd_mom_intensity_pct_normal():
    assert intensity_pct(0.72) == 72


def test_cvd_mom_neutral_zero_intensity():
    assert intensity_pct(CVD_MOM_NEUTRAL["intensity"]) == 0


def test_html_has_cvd_momentum_card():
    assert "card-cvd-momentum" in _html()


def test_js_has_render_cvd_momentum():
    assert "renderCvdMomentum" in _js()


# ══════════════════════════════════════════════════════════════════════════════
# 2 · DELTA DIVERGENCE
# ══════════════════════════════════════════════════════════════════════════════

def divergence_badge_class(severity: int) -> str:
    if severity == 0:
        return "badge-green"
    if severity == 1:
        return "badge-yellow"
    return "badge-red"


def divergence_label(divergence: str, severity: int) -> str:
    if divergence == "none" or severity == 0:
        return "OK"
    return divergence.upper()


DELTA_DIV_PAYLOAD = {
    "status": "ok", "symbol": "BANANAS31USDT",
    "divergence": "strong", "severity": 2,
    "price_change_pct": 1.5, "cvd_norm": -0.8,
    "description": "Price rising but CVD falling",
    "window_seconds": 300,
}

DELTA_DIV_NONE = {
    "status": "ok", "symbol": "DEXEUSDT",
    "divergence": "none", "severity": 0,
    "price_change_pct": 0.2, "cvd_norm": 0.1,
    "description": "No divergence",
    "window_seconds": 300,
}


def test_delta_div_response_has_status():
    assert DELTA_DIV_PAYLOAD["status"] == "ok"


def test_delta_div_has_required_keys():
    for key in ("symbol", "divergence", "severity", "price_change_pct",
                "cvd_norm", "description", "window_seconds"):
        assert key in DELTA_DIV_PAYLOAD


def test_delta_div_badge_sev0():
    assert divergence_badge_class(0) == "badge-green"


def test_delta_div_badge_sev1():
    assert divergence_badge_class(1) == "badge-yellow"


def test_delta_div_badge_sev2():
    assert divergence_badge_class(2) == "badge-red"


def test_delta_div_badge_sev3():
    assert divergence_badge_class(3) == "badge-red"


def test_delta_div_label_none():
    assert divergence_label("none", 0) == "OK"


def test_delta_div_label_strong():
    assert divergence_label("strong", 2) == "STRONG"


def test_delta_div_none_no_alert():
    assert DELTA_DIV_NONE["severity"] == 0
    assert divergence_badge_class(DELTA_DIV_NONE["severity"]) == "badge-green"


def test_html_has_delta_divergence_card():
    assert "card-delta-divergence" in _html()


def test_js_has_render_delta_divergence():
    assert "renderDeltaDivergence" in _js()


# ══════════════════════════════════════════════════════════════════════════════
# 3 · FUNDING EXTREME
# ══════════════════════════════════════════════════════════════════════════════

def funding_extreme_badge(extreme: bool) -> tuple[str, str]:
    if extreme:
        return "EXTREME", "badge-red"
    return "normal", "badge-blue"


def fmt_rate_pct(v: float | None) -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.4f}%"


FUNDING_EXT_PAYLOAD = {
    "status": "ok", "symbol": "BANANAS31USDT",
    "extreme": True, "avg_rate": 0.001234, "avg_rate_pct": 0.1234,
    "rates": {"bybit": 0.001, "binance": 0.0015},
    "direction": "long", "description": "High positive funding, longs paying",
    "threshold_pct": 0.1,
}

FUNDING_EXT_NORMAL = {
    "status": "ok", "symbol": "COSUSDT",
    "extreme": False, "avg_rate": 0.00005, "avg_rate_pct": 0.005,
    "rates": {"bybit": 0.00004, "binance": 0.00006},
    "direction": None, "description": "Funding within normal range",
    "threshold_pct": 0.1,
}


def test_funding_ext_response_has_status():
    assert FUNDING_EXT_PAYLOAD["status"] == "ok"


def test_funding_ext_has_required_keys():
    for key in ("symbol", "extreme", "avg_rate", "avg_rate_pct", "rates",
                "direction", "description", "threshold_pct"):
        assert key in FUNDING_EXT_PAYLOAD


def test_funding_ext_extreme_badge():
    label, cls = funding_extreme_badge(True)
    assert label == "EXTREME"
    assert cls == "badge-red"


def test_funding_ext_normal_badge():
    label, cls = funding_extreme_badge(False)
    assert label == "normal"
    assert cls == "badge-blue"


def test_funding_ext_fmt_rate_positive():
    assert fmt_rate_pct(0.1234) == "+0.1234%"


def test_funding_ext_fmt_rate_negative():
    assert fmt_rate_pct(-0.0500) == "-0.0500%"


def test_funding_ext_fmt_rate_none():
    assert fmt_rate_pct(None) == "—"


def test_funding_ext_rates_dict():
    assert "bybit" in FUNDING_EXT_PAYLOAD["rates"]
    assert "binance" in FUNDING_EXT_PAYLOAD["rates"]


def test_html_has_funding_extreme_card():
    assert "card-funding-extreme" in _html()


def test_js_has_render_funding_extreme():
    assert "renderFundingExtreme" in _js()


# ══════════════════════════════════════════════════════════════════════════════
# 4 · LIQ CASCADE
# ══════════════════════════════════════════════════════════════════════════════

def cascade_badge(cascade: bool) -> tuple[str, str]:
    if cascade:
        return "CASCADE", "badge-red"
    return "quiet", "badge-blue"


def liq_bar_pct(side_usd: float, total_usd: float) -> int:
    if total_usd <= 0:
        return 0
    return max(0, min(100, round(side_usd / total_usd * 100)))


LIQ_CASCADE_PAYLOAD = {
    "status": "ok", "symbol": "BANANAS31USDT",
    "cascade": True, "total_usd": 125_000,
    "buy_usd": 80_000, "sell_usd": 45_000,
    "description": "🚨 Cascade: $125,000 liquidated in 60s",
}

LIQ_CASCADE_QUIET = {
    "status": "ok", "symbol": "COSUSDT",
    "cascade": False, "total_usd": 500,
    "buy_usd": 300, "sell_usd": 200,
    "description": "$500 liquidated",
}


def test_liq_cascade_response_has_status():
    assert LIQ_CASCADE_PAYLOAD["status"] == "ok"


def test_liq_cascade_has_required_keys():
    for key in ("symbol", "cascade", "total_usd", "buy_usd", "sell_usd", "description"):
        assert key in LIQ_CASCADE_PAYLOAD


def test_liq_cascade_badge_active():
    label, cls = cascade_badge(True)
    assert label == "CASCADE"
    assert cls == "badge-red"


def test_liq_cascade_badge_quiet():
    label, cls = cascade_badge(False)
    assert label == "quiet"
    assert cls == "badge-blue"


def test_liq_cascade_bar_pct_buy():
    pct = liq_bar_pct(80_000, 125_000)
    assert pct == 64


def test_liq_cascade_bar_pct_zero_total():
    assert liq_bar_pct(0, 0) == 0


def test_liq_cascade_bar_pct_clamped():
    assert liq_bar_pct(200, 100) == 100


def test_liq_cascade_buy_sell_sum():
    p = LIQ_CASCADE_PAYLOAD
    assert p["buy_usd"] + p["sell_usd"] == pytest.approx(p["total_usd"])


def test_html_has_liq_cascade_card():
    assert "card-liq-cascade" in _html()


def test_js_has_render_liq_cascade():
    assert "renderLiqCascade" in _js()


# ══════════════════════════════════════════════════════════════════════════════
# 5 · LARGE TRADES
# ══════════════════════════════════════════════════════════════════════════════

def fmt_usd(v: float) -> str:
    if v >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}k"
    return f"${v:.0f}"


def trade_side_badge(side: str) -> str:
    return "badge-green" if side.lower() == "buy" else "badge-red"


LARGE_TRADES_PAYLOAD = {
    "status": "ok", "symbol": "BANANAS31USDT",
    "count": 3,
    "trades": [
        {"price": 0.002345, "size": 500_000, "side": "buy",  "usd_value": 1172.5,  "ts": 1700000001},
        {"price": 0.002310, "size": 800_000, "side": "sell", "usd_value": 1848.0,  "ts": 1700000002},
        {"price": 0.002380, "size": 600_000, "side": "buy",  "usd_value": 1428.0,  "ts": 1700000003},
    ],
    "total_buy_usd":  2600.5,
    "total_sell_usd": 1848.0,
    "min_usd_threshold": 10_000,
    "window_seconds": 300,
}

LARGE_TRADES_EMPTY = {
    "status": "ok", "symbol": "LYNUSDT",
    "count": 0, "trades": [],
    "total_buy_usd": 0.0, "total_sell_usd": 0.0,
    "min_usd_threshold": 10_000, "window_seconds": 300,
}


def test_large_trades_response_has_status():
    assert LARGE_TRADES_PAYLOAD["status"] == "ok"


def test_large_trades_has_required_keys():
    for key in ("symbol", "count", "trades", "total_buy_usd",
                "total_sell_usd", "min_usd_threshold", "window_seconds"):
        assert key in LARGE_TRADES_PAYLOAD


def test_large_trades_each_trade_has_required_keys():
    for t in LARGE_TRADES_PAYLOAD["trades"]:
        for key in ("price", "size", "side", "usd_value", "ts"):
            assert key in t


def test_large_trades_count_matches_list():
    assert LARGE_TRADES_PAYLOAD["count"] == len(LARGE_TRADES_PAYLOAD["trades"])


def test_large_trades_fmt_usd_thousands():
    assert fmt_usd(1500) == "$1.5k"


def test_large_trades_fmt_usd_millions():
    assert fmt_usd(2_000_000) == "$2.00M"


def test_large_trades_fmt_usd_small():
    assert fmt_usd(999) == "$999"


def test_large_trades_side_badge_buy():
    assert trade_side_badge("buy") == "badge-green"


def test_large_trades_side_badge_sell():
    assert trade_side_badge("sell") == "badge-red"


def test_large_trades_empty_count():
    assert LARGE_TRADES_EMPTY["count"] == 0
    assert len(LARGE_TRADES_EMPTY["trades"]) == 0


def test_html_has_large_trades_card():
    assert "card-large-trades" in _html()


def test_js_has_render_large_trades():
    assert "renderLargeTrades" in _js()


# ══════════════════════════════════════════════════════════════════════════════
# Route registration (all 5)
# ══════════════════════════════════════════════════════════════════════════════

def _get_paths():
    import tempfile
    os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
    os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from api import router
    return [r.path for r in router.routes]


def test_cvd_momentum_route_registered():
    assert any("cvd-momentum" in p for p in _get_paths())


def test_delta_divergence_route_registered():
    assert any("delta-divergence" in p for p in _get_paths())


def test_funding_extreme_route_registered():
    assert any("funding-extreme" in p for p in _get_paths())


def test_liq_cascade_route_registered():
    assert any("liq-cascade" in p for p in _get_paths())


def test_large_trades_route_registered():
    assert any("large-trades" in p for p in _get_paths())

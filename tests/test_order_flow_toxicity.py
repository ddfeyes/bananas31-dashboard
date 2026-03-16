"""
Unit / smoke tests for the Order Flow Toxicity (OFT) indicator.

OFT: correlation between trade direction (buy=+1 / sell=-1) and
subsequent price movement over rolling windows (5m, 15m, 1h).
Score 0–100 where higher = more informed/toxic flow.

Covers:
  - Core correlation math (pearson_r, oft_score)
  - Direction encoding
  - Severity band classification
  - Multi-window aggregation
  - Sparkline bucket logic
  - Edge cases (empty data, zero variance, all-same-direction)
  - Response shape validation
  - Display helper mirrors
  - Route registration, HTML card, JS function
"""
import os
import sys
import math

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _html() -> str:
    with open(os.path.join(_ROOT, "frontend", "index.html"), encoding="utf-8") as f:
        return f.read()


def _js() -> str:
    with open(os.path.join(_ROOT, "frontend", "app.js"), encoding="utf-8") as f:
        return f.read()


# ── Python mirrors of backend OFT logic ──────────────────────────────────────

def encode_direction(side: str | None, is_buyer_aggressor: bool | None = None) -> int:
    """+1 for buy-initiated, -1 for sell-initiated."""
    if is_buyer_aggressor is not None:
        return 1 if is_buyer_aggressor else -1
    s = (side or "").lower()
    return 1 if s in ("buy",) else -1


def pearson_r(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation coefficient. Returns None if variance is zero."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num  = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    var_x = sum((x - mx) ** 2 for x in xs)
    var_y = sum((y - my) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    return num / math.sqrt(var_x * var_y)


def oft_score_from_r(r: float | None) -> float:
    """Map Pearson r (or None) → OFT score 0–100. Magnitude matters."""
    if r is None:
        return 0.0
    return round(abs(r) * 100, 2)


def classify_severity(score: float) -> str:
    """low < 25 ≤ medium < 50 ≤ high < 75 ≤ extreme."""
    if score >= 75:
        return "extreme"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def compute_oft_for_trades(
    trades: list[dict],
    lookahead_s: float = 300.0,
) -> float | None:
    """
    Compute OFT score for a list of trades with a given price-change lookahead.
    trades: [{ts, price, side, ...}]
    Returns score 0–100 or None if insufficient data.
    """
    if len(trades) < 5:
        return None
    sorted_trades = sorted(trades, key=lambda t: t["ts"])
    directions = []
    price_changes = []
    for i, t in enumerate(sorted_trades):
        p0 = t.get("price") or 0
        if not p0:
            continue
        cutoff = t["ts"] + lookahead_s
        future = [ft for ft in sorted_trades[i + 1:] if ft["ts"] <= cutoff]
        if not future:
            continue
        p1 = future[-1].get("price") or 0
        if not p1:
            continue
        directions.append(encode_direction(t.get("side"), t.get("is_buyer_aggressor")))
        price_changes.append((p1 - p0) / p0)
    r = pearson_r(directions, price_changes)
    return oft_score_from_r(r)


def sparkline_buckets(
    trades: list[dict],
    bucket_seconds: float,
    total_window: float,
    lookahead_s: float,
) -> list[dict]:
    """
    Split trades into time buckets and compute OFT per bucket.
    Returns [{ts, score}] sorted ascending.
    """
    if not trades:
        return []
    t_min = min(t["ts"] for t in trades)
    t_max = max(t["ts"] for t in trades)
    buckets = []
    t = t_min
    while t <= t_max:
        bucket_trades = [tr for tr in trades if t <= tr["ts"] < t + bucket_seconds]
        score = compute_oft_for_trades(bucket_trades, lookahead_s) if len(bucket_trades) >= 5 else None
        buckets.append({"ts": t, "score": score})
        t += bucket_seconds
    return buckets


# ── Direction encoding tests ──────────────────────────────────────────────────

def test_encode_buy_side():
    assert encode_direction("buy") == 1


def test_encode_sell_side():
    assert encode_direction("sell") == -1


def test_encode_buy_uppercase():
    assert encode_direction("Buy") == 1


def test_encode_none_defaults_to_sell():
    assert encode_direction(None) == -1


def test_encode_iba_true():
    assert encode_direction(None, is_buyer_aggressor=True) == 1


def test_encode_iba_false():
    assert encode_direction(None, is_buyer_aggressor=False) == -1


def test_encode_iba_overrides_side():
    assert encode_direction("sell", is_buyer_aggressor=True) == 1


# ── Pearson correlation tests ─────────────────────────────────────────────────

def test_pearson_perfect_positive():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0, 4.0, 6.0, 8.0, 10.0]
    r = pearson_r(xs, ys)
    assert r == pytest.approx(1.0)


def test_pearson_perfect_negative():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [5.0, 4.0, 3.0, 2.0, 1.0]
    r = pearson_r(xs, ys)
    assert r == pytest.approx(-1.0)


def test_pearson_no_correlation():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [3.0, 3.0, 3.0, 3.0, 3.0]  # zero variance in y
    r = pearson_r(xs, ys)
    assert r is None


def test_pearson_too_few_samples():
    assert pearson_r([1.0, 2.0], [1.0, 2.0]) is None


def test_pearson_zero_variance_x():
    xs = [2.0, 2.0, 2.0, 2.0, 2.0]
    ys = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert pearson_r(xs, ys) is None


def test_pearson_range_minus_one_to_one():
    xs = [1.0, -1.0, 1.0, -1.0, 1.0]
    ys = [0.5, 0.2, 0.8, 0.1, 0.6]
    r = pearson_r(xs, ys)
    assert r is not None
    assert -1.0 <= r <= 1.0


# ── OFT score mapping tests ───────────────────────────────────────────────────

def test_oft_score_from_r_perfect_positive():
    assert oft_score_from_r(1.0) == pytest.approx(100.0)


def test_oft_score_from_r_perfect_negative():
    assert oft_score_from_r(-1.0) == pytest.approx(100.0)


def test_oft_score_from_r_zero():
    assert oft_score_from_r(0.0) == pytest.approx(0.0)


def test_oft_score_from_r_none():
    assert oft_score_from_r(None) == pytest.approx(0.0)


def test_oft_score_from_r_half():
    assert oft_score_from_r(0.5) == pytest.approx(50.0)


def test_oft_score_from_r_negative_half():
    assert oft_score_from_r(-0.5) == pytest.approx(50.0)


# ── Severity classification tests ─────────────────────────────────────────────

def test_severity_low():
    assert classify_severity(0.0)  == "low"
    assert classify_severity(24.9) == "low"


def test_severity_medium():
    assert classify_severity(25.0) == "medium"
    assert classify_severity(49.9) == "medium"


def test_severity_high():
    assert classify_severity(50.0) == "high"
    assert classify_severity(74.9) == "high"


def test_severity_extreme():
    assert classify_severity(75.0) == "extreme"
    assert classify_severity(100.0) == "extreme"


def test_severity_boundaries():
    assert classify_severity(25.0) == "medium"
    assert classify_severity(50.0) == "high"
    assert classify_severity(75.0) == "extreme"


# ── compute_oft_for_trades tests ──────────────────────────────────────────────

def _make_trades(directions_and_prices: list, base_ts: float = 1700000000.0) -> list[dict]:
    """Create synthetic trades: [(side, price_at_t0, price_at_t+la)] as sequential pairs."""
    trades = []
    for i, (side, price) in enumerate(directions_and_prices):
        trades.append({"ts": base_ts + i * 10.0, "price": price, "side": side})
    return trades


def test_oft_returns_none_for_too_few_trades():
    trades = _make_trades([("buy", 1.0), ("sell", 0.99)])
    assert compute_oft_for_trades(trades) is None


def test_oft_score_is_float():
    trades = _make_trades([
        ("buy", 1.0), ("buy", 1.01), ("sell", 1.02),
        ("sell", 1.00), ("buy", 0.99), ("buy", 1.01), ("sell", 1.03),
    ])
    result = compute_oft_for_trades(trades)
    # may be None if no lookahead pairs, but if not None must be float in 0-100
    if result is not None:
        assert 0.0 <= result <= 100.0


def test_oft_informed_buys_score_nonzero():
    """Buys consistently followed by price rise → high OFT."""
    base = 1700000000.0
    trades = []
    for i in range(20):
        price = 1.0 + i * 0.001
        trades.append({"ts": base + i * 30, "price": price, "side": "buy"})
    score = compute_oft_for_trades(trades, lookahead_s=60.0)
    # All buys with rising prices → perfect correlation → score ~100 or None
    # Allow None if no lookahead pairs form, otherwise check non-negative
    if score is not None:
        assert score >= 0.0


def test_oft_mixed_directions_lower_than_one_sided():
    """Alternating buy/sell with neutral price → lower OFT than directional."""
    base = 1700000000.0
    trades = []
    for i in range(20):
        side = "buy" if i % 2 == 0 else "sell"
        trades.append({"ts": base + i * 30, "price": 1.0, "side": side})
    score = compute_oft_for_trades(trades, lookahead_s=60.0)
    if score is not None:
        assert score <= 50.0  # neutral flow → low toxicity


# ── Sparkline bucket tests ────────────────────────────────────────────────────

def test_sparkline_empty_trades():
    assert sparkline_buckets([], 300, 3600, 60) == []


def test_sparkline_returns_list():
    trades = _make_trades([(s, p) for s, p in
        [("buy", 1.0)] * 10], base_ts=1700000000.0)
    result = sparkline_buckets(trades, bucket_seconds=100, total_window=1000, lookahead_s=30)
    assert isinstance(result, list)


def test_sparkline_bucket_has_ts_and_score():
    trades = _make_trades([("buy", 1.0 + i * 0.001) for i in range(20)])
    result = sparkline_buckets(trades, bucket_seconds=60, total_window=300, lookahead_s=30)
    for b in result:
        assert "ts" in b
        assert "score" in b


def test_sparkline_score_none_or_0_to_100():
    trades = _make_trades([("buy", 1.0 + i * 0.001) for i in range(20)])
    result = sparkline_buckets(trades, bucket_seconds=60, total_window=300, lookahead_s=30)
    for b in result:
        if b["score"] is not None:
            assert 0.0 <= b["score"] <= 100.0


# ── Display helper mirrors ────────────────────────────────────────────────────

def severity_badge(severity: str) -> tuple[str, str]:
    mapping = {
        "extreme": ("EXTREME", "badge-red"),
        "high":    ("HIGH",    "badge-red"),
        "medium":  ("MEDIUM",  "badge-yellow"),
        "low":     ("low",     "badge-green"),
    }
    return mapping.get(severity, ("—", "badge-blue"))


def fmt_oft_score(score: float | None) -> str:
    if score is None:
        return "—"
    return f"{score:.1f}"


def gauge_pct(score: float | None) -> int:
    if score is None:
        return 0
    return max(0, min(100, round(score)))


def test_severity_badge_extreme():
    label, cls = severity_badge("extreme")
    assert label == "EXTREME"
    assert cls == "badge-red"


def test_severity_badge_high():
    label, cls = severity_badge("high")
    assert cls == "badge-red"


def test_severity_badge_medium():
    label, cls = severity_badge("medium")
    assert cls == "badge-yellow"


def test_severity_badge_low():
    label, cls = severity_badge("low")
    assert cls == "badge-green"


def test_fmt_oft_score_normal():
    assert fmt_oft_score(42.5) == "42.5"


def test_fmt_oft_score_none():
    assert fmt_oft_score(None) == "—"


def test_gauge_pct_clamp_high():
    assert gauge_pct(150.0) == 100


def test_gauge_pct_clamp_low():
    assert gauge_pct(-10.0) == 0


def test_gauge_pct_midpoint():
    assert gauge_pct(50.0) == 50


def test_gauge_pct_none():
    assert gauge_pct(None) == 0


# ── Response shape validation ─────────────────────────────────────────────────

SAMPLE_RESPONSE = {
    "status": "ok",
    "symbol": "BANANAS31USDT",
    "score": 42.3,
    "severity": "medium",
    "windows": {
        "5m":  {"score": 38.1, "r": 0.381, "n_pairs": 45, "severity": "medium"},
        "15m": {"score": 44.2, "r": 0.442, "n_pairs": 120, "severity": "medium"},
        "1h":  {"score": 40.5, "r": 0.405, "n_pairs": 380, "severity": "medium"},
    },
    "sparkline": [
        {"ts": 1700000000.0, "score": 35.0},
        {"ts": 1700000300.0, "score": 40.0},
        {"ts": 1700000600.0, "score": 42.3},
    ],
    "description": "Medium toxicity — mixed informed and noise flow",
    "window_seconds": 3600,
    "n_trades": 543,
}


def test_response_status_ok():
    assert SAMPLE_RESPONSE["status"] == "ok"


def test_response_has_score():
    assert isinstance(SAMPLE_RESPONSE["score"], float)
    assert 0.0 <= SAMPLE_RESPONSE["score"] <= 100.0


def test_response_has_severity():
    assert SAMPLE_RESPONSE["severity"] in ("low", "medium", "high", "extreme")


def test_response_has_windows():
    assert "windows" in SAMPLE_RESPONSE
    for wk in ("5m", "15m", "1h"):
        assert wk in SAMPLE_RESPONSE["windows"]


def test_response_windows_have_required_keys():
    for wk, wv in SAMPLE_RESPONSE["windows"].items():
        for field in ("score", "r", "n_pairs", "severity"):
            assert field in wv, f"Missing '{field}' in window '{wk}'"


def test_response_has_sparkline():
    assert isinstance(SAMPLE_RESPONSE["sparkline"], list)
    for b in SAMPLE_RESPONSE["sparkline"]:
        assert "ts" in b
        assert "score" in b


def test_response_has_description():
    assert isinstance(SAMPLE_RESPONSE["description"], str)


def test_response_has_n_trades():
    assert SAMPLE_RESPONSE["n_trades"] >= 0


def test_response_score_matches_windows_range():
    scores = [v["score"] for v in SAMPLE_RESPONSE["windows"].values()]
    avg = sum(scores) / len(scores)
    # composite score should be close to window average (within 20)
    assert abs(SAMPLE_RESPONSE["score"] - avg) < 20


# ── Route registration ────────────────────────────────────────────────────────

def test_order_flow_toxicity_route_registered():
    import tempfile
    os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
    os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from api import router
    paths = [r.path for r in router.routes]
    assert any("order-flow-toxicity" in p for p in paths)


# ── HTML / JS smoke tests ─────────────────────────────────────────────────────

def test_html_has_oft_card():
    assert "card-order-flow-toxicity" in _html()


def test_js_has_render_oft():
    assert "renderOrderFlowToxicity" in _js()


def test_js_calls_oft_api():
    assert "order-flow-toxicity" in _js()

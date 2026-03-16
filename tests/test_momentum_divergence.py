"""
Unit / smoke tests for /api/momentum-divergence.

Price vs OI (Open Interest) momentum divergence detector.

Definitions:
  - Price momentum per bucket: (close - open) / open * 100
  - OI momentum per bucket:   (oi_end - oi_start) / oi_start * 100
  - Bullish divergence: price_mom < 0 AND oi_mom > threshold (OI rising while price falls)
  - Bearish divergence: price_mom > 0 AND oi_mom < -threshold (OI falling while price rises)

Covers:
  - Momentum calculation helpers
  - Divergence event detection logic
  - Severity scoring
  - Series alignment
  - Edge cases (empty data, flat OI, no divergence)
  - Display helpers
  - Response shape
  - Route registration, HTML card, JS smoke tests
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


# ── Python mirrors of backend logic ──────────────────────────────────────────

def price_momentum(open_: float, close: float) -> float | None:
    """% change open → close. None if open is zero."""
    if not open_:
        return None
    return round((close - open_) / open_ * 100, 4)


def oi_momentum(oi_start: float, oi_end: float) -> float | None:
    """% change in OI. None if oi_start is zero."""
    if not oi_start:
        return None
    return round((oi_end - oi_start) / oi_start * 100, 4)


def classify_divergence(price_mom: float | None, oi_mom: float | None,
                         threshold: float = 0.1) -> str:
    """
    Returns 'bullish', 'bearish', or 'none'.
    Bullish: price falling, OI rising  (shorts piling in → squeeze fuel)
    Bearish: price rising, OI falling  (weak rally → reversal risk)
    """
    if price_mom is None or oi_mom is None:
        return "none"
    if price_mom < -threshold and oi_mom > threshold:
        return "bullish"
    if price_mom > threshold and oi_mom < -threshold:
        return "bearish"
    return "none"


def divergence_score(events: list[dict], total_buckets: int) -> float:
    """
    Score 0–100: fraction of buckets with a divergence event, amplified by
    average |price_mom - oi_mom| spread.
    """
    if total_buckets <= 0 or not events:
        return 0.0
    frac = len(events) / total_buckets
    if not events:
        return 0.0
    spreads = [abs((e.get("price_mom") or 0) - (e.get("oi_mom") or 0)) for e in events]
    avg_spread = sum(spreads) / len(spreads) if spreads else 0
    # Map: frac contributes 0-60, avg_spread (clamped 0-10) contributes 0-40
    score = frac * 60 + min(avg_spread, 10.0) * 4
    return round(min(100.0, score), 2)


def classify_severity(score: float) -> str:
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def align_series(price_series: list[dict], oi_series: list[dict],
                 bucket_s: int) -> list[dict]:
    """
    Align price and OI buckets by timestamp (nearest bucket_s boundary).
    price_series: [{ts, price_mom}]
    oi_series:    [{ts, oi_mom}]
    Returns [{ts, price_mom, oi_mom}] for buckets present in both.
    """
    oi_map = {round(r["ts"] / bucket_s) * bucket_s: r["oi_mom"] for r in oi_series}
    result = []
    for p in price_series:
        key = round(p["ts"] / bucket_s) * bucket_s
        if key in oi_map:
            result.append({"ts": key, "price_mom": p["price_mom"],
                           "oi_mom": oi_map[key]})
    return result


# ── price_momentum tests ──────────────────────────────────────────────────────

def test_price_mom_positive():
    assert price_momentum(100.0, 102.0) == pytest.approx(2.0)


def test_price_mom_negative():
    assert price_momentum(100.0, 98.0) == pytest.approx(-2.0)


def test_price_mom_flat():
    assert price_momentum(100.0, 100.0) == pytest.approx(0.0)


def test_price_mom_zero_open():
    assert price_momentum(0.0, 100.0) is None


def test_price_mom_small_prices():
    v = price_momentum(0.002, 0.00202)
    assert v is not None
    assert v == pytest.approx(1.0)


# ── oi_momentum tests ─────────────────────────────────────────────────────────

def test_oi_mom_positive():
    assert oi_momentum(1000.0, 1050.0) == pytest.approx(5.0)


def test_oi_mom_negative():
    assert oi_momentum(1000.0, 950.0) == pytest.approx(-5.0)


def test_oi_mom_zero_start():
    assert oi_momentum(0.0, 1000.0) is None


def test_oi_mom_flat():
    assert oi_momentum(1000.0, 1000.0) == pytest.approx(0.0)


# ── classify_divergence tests ─────────────────────────────────────────────────

def test_div_bullish():
    assert classify_divergence(-1.0, 2.0) == "bullish"


def test_div_bearish():
    assert classify_divergence(1.0, -2.0) == "bearish"


def test_div_none_both_positive():
    assert classify_divergence(1.0, 2.0) == "none"


def test_div_none_both_negative():
    assert classify_divergence(-1.0, -2.0) == "none"


def test_div_none_below_threshold():
    # Price barely negative but within threshold
    assert classify_divergence(-0.05, 2.0, threshold=0.1) == "none"


def test_div_none_oi_below_threshold():
    assert classify_divergence(-1.0, 0.05, threshold=0.1) == "none"


def test_div_none_values():
    assert classify_divergence(None, 2.0) == "none"
    assert classify_divergence(-1.0, None) == "none"


def test_div_boundary_exactly_at_threshold():
    # At exactly -0.1 / +0.1 → not classified (strictly less/greater required)
    assert classify_divergence(-0.1, 0.1, threshold=0.1) == "none"


# ── divergence_score tests ────────────────────────────────────────────────────

EVENTS_BULL = [
    {"ts": 1700000000.0, "type": "bullish", "price_mom": -2.0, "oi_mom": 3.0},
    {"ts": 1700000300.0, "type": "bullish", "price_mom": -1.5, "oi_mom": 2.5},
]

EVENTS_BEAR = [
    {"ts": 1700000000.0, "type": "bearish", "price_mom": 2.0, "oi_mom": -3.0},
]


def test_divergence_score_zero_no_events():
    assert divergence_score([], 20) == pytest.approx(0.0)


def test_divergence_score_zero_no_buckets():
    assert divergence_score(EVENTS_BULL, 0) == pytest.approx(0.0)


def test_divergence_score_positive():
    score = divergence_score(EVENTS_BULL, 12)
    assert score > 0.0


def test_divergence_score_max_100():
    # Even with extreme inputs, score must be <= 100
    many_events = [{"price_mom": -50.0, "oi_mom": 50.0}] * 100
    score = divergence_score(many_events, 100)
    assert score <= 100.0


def test_divergence_score_more_events_higher():
    s1 = divergence_score(EVENTS_BULL[:1], 12)
    s2 = divergence_score(EVENTS_BULL, 12)
    assert s2 >= s1


# ── classify_severity tests ───────────────────────────────────────────────────

def test_severity_low():
    assert classify_severity(0.0)  == "low"
    assert classify_severity(29.9) == "low"


def test_severity_medium():
    assert classify_severity(30.0) == "medium"
    assert classify_severity(59.9) == "medium"


def test_severity_high():
    assert classify_severity(60.0) == "high"
    assert classify_severity(100.0) == "high"


# ── align_series tests ────────────────────────────────────────────────────────

PRICE_SERIES = [
    {"ts": 1700000300.0, "price_mom": 1.0},
    {"ts": 1700000600.0, "price_mom": -0.5},
    {"ts": 1700000900.0, "price_mom": 2.0},
]
OI_SERIES = [
    {"ts": 1700000300.0, "oi_mom": -1.0},
    {"ts": 1700000600.0, "oi_mom": 1.5},
    {"ts": 1700001200.0, "oi_mom": 0.5},   # no matching price bucket
]


def test_align_series_returns_list():
    result = align_series(PRICE_SERIES, OI_SERIES, bucket_s=300)
    assert isinstance(result, list)


def test_align_series_matching_buckets():
    result = align_series(PRICE_SERIES, OI_SERIES, bucket_s=300)
    assert len(result) == 2  # only ts 300 and 600 match


def test_align_series_has_both_fields():
    result = align_series(PRICE_SERIES, OI_SERIES, bucket_s=300)
    for r in result:
        assert "price_mom" in r
        assert "oi_mom" in r
        assert "ts" in r


def test_align_series_empty_oi():
    result = align_series(PRICE_SERIES, [], bucket_s=300)
    assert result == []


def test_align_series_empty_price():
    result = align_series([], OI_SERIES, bucket_s=300)
    assert result == []


# ── Display helpers ───────────────────────────────────────────────────────────

def divergence_badge(div_type: str) -> tuple[str, str]:
    return {
        "bullish": ("bullish", "badge-green"),
        "bearish": ("bearish", "badge-red"),
        "none":    ("none",    "badge-blue"),
    }.get(div_type, ("—", "badge-blue"))


def fmt_mom(v: float | None) -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def test_badge_bullish():
    label, cls = divergence_badge("bullish")
    assert label == "bullish"
    assert cls == "badge-green"


def test_badge_bearish():
    label, cls = divergence_badge("bearish")
    assert cls == "badge-red"


def test_badge_none():
    label, cls = divergence_badge("none")
    assert cls == "badge-blue"


def test_fmt_mom_positive():
    assert fmt_mom(1.5) == "+1.50%"


def test_fmt_mom_negative():
    assert fmt_mom(-2.3) == "-2.30%"


def test_fmt_mom_none():
    assert fmt_mom(None) == "—"


def test_fmt_mom_zero():
    assert fmt_mom(0.0) == "+0.00%"


# ── Response shape ────────────────────────────────────────────────────────────

SAMPLE_RESPONSE = {
    "status": "ok",
    "symbol": "BANANAS31USDT",
    "divergence_type": "bullish",
    "severity": "medium",
    "score": 42.0,
    "price_momentum": -1.8,
    "oi_momentum": 3.2,
    "events": [
        {"ts": 1700000300.0, "type": "bullish", "price_mom": -2.1,
         "oi_mom": 3.5, "description": "Price fell -2.1% while OI rose +3.5%"},
        {"ts": 1700000600.0, "type": "bullish", "price_mom": -1.5,
         "oi_mom": 2.9, "description": "Price fell -1.5% while OI rose +2.9%"},
    ],
    "series": [
        {"ts": 1700000000.0, "price_mom": 0.5,  "oi_mom": 0.2,  "divergence": "none"},
        {"ts": 1700000300.0, "price_mom": -2.1, "oi_mom": 3.5,  "divergence": "bullish"},
        {"ts": 1700000600.0, "price_mom": -1.5, "oi_mom": 2.9,  "divergence": "bullish"},
        {"ts": 1700000900.0, "price_mom": 1.0,  "oi_mom": -0.2, "divergence": "none"},
    ],
    "description": "Bullish divergence: price falling while OI rises — potential squeeze",
    "window_seconds": 3600,
    "bucket_seconds": 300,
    "n_events": 2,
}


def test_response_status_ok():
    assert SAMPLE_RESPONSE["status"] == "ok"


def test_response_divergence_type_valid():
    assert SAMPLE_RESPONSE["divergence_type"] in ("bullish", "bearish", "none")


def test_response_severity_valid():
    assert SAMPLE_RESPONSE["severity"] in ("low", "medium", "high")


def test_response_score_range():
    assert 0.0 <= SAMPLE_RESPONSE["score"] <= 100.0


def test_response_has_series():
    assert isinstance(SAMPLE_RESPONSE["series"], list)
    assert len(SAMPLE_RESPONSE["series"]) > 0


def test_response_series_has_required_keys():
    for pt in SAMPLE_RESPONSE["series"]:
        for key in ("ts", "price_mom", "oi_mom", "divergence"):
            assert key in pt


def test_response_series_divergence_values_valid():
    valid = {"bullish", "bearish", "none"}
    for pt in SAMPLE_RESPONSE["series"]:
        assert pt["divergence"] in valid


def test_response_has_events():
    assert isinstance(SAMPLE_RESPONSE["events"], list)


def test_response_events_have_required_keys():
    for ev in SAMPLE_RESPONSE["events"]:
        for key in ("ts", "type", "price_mom", "oi_mom", "description"):
            assert key in ev


def test_response_n_events_matches():
    assert SAMPLE_RESPONSE["n_events"] == len(SAMPLE_RESPONSE["events"])


def test_response_has_price_oi_momentum():
    assert "price_momentum" in SAMPLE_RESPONSE
    assert "oi_momentum"    in SAMPLE_RESPONSE


def test_response_bullish_pattern_consistency():
    # For bullish divergence: recent price_mom < 0, oi_mom > 0
    assert SAMPLE_RESPONSE["price_momentum"] < 0
    assert SAMPLE_RESPONSE["oi_momentum"] > 0


def test_response_has_description():
    assert isinstance(SAMPLE_RESPONSE["description"], str)
    assert len(SAMPLE_RESPONSE["description"]) > 0


# ── Route registration ────────────────────────────────────────────────────────

def test_momentum_divergence_route_registered():
    import tempfile
    os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
    os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from api import router
    paths = [r.path for r in router.routes]
    assert any("momentum-divergence" in p for p in paths)


# ── HTML / JS smoke tests ─────────────────────────────────────────────────────

def test_html_has_momentum_divergence_card():
    assert "card-momentum-divergence" in _html()


def test_js_has_render_momentum_divergence():
    assert "renderMomentumDivergence" in _js()


def test_js_calls_momentum_divergence_api():
    assert "momentum-divergence" in _js()

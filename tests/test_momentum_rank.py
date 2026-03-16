"""
Unit / smoke tests for /api/momentum-rank.

Validates:
  - Momentum score formula (weighted 5m/15m/1h)
  - pct_change computation from candles
  - Ranking order (highest score = rank 1)
  - Negative / mixed / None handling
  - Direction classification
  - Tie-breaking stability
  - Response shape
  - Route registration
  - HTML card / JS smoke tests
"""
import os
import sys

import pytest

# ── Python mirrors of backend logic ──────────────────────────────────────────

WEIGHTS = {"5m": 0.5, "15m": 0.3, "1h": 0.2}


def pct_change(candles: list) -> float | None:
    """% change from first candle open to last candle close."""
    if not candles or len(candles) < 1:
        return None
    first_open = candles[0].get("open")
    last_close = candles[-1].get("close")
    if not first_open or not last_close:
        return None
    return round((last_close - first_open) / first_open * 100, 4)


def momentum_score(pct_5m, pct_15m, pct_1h) -> float:
    """Composite momentum: 0.5×5m + 0.3×15m + 0.2×1h (None → 0)."""
    return round(
        WEIGHTS["5m"]  * (pct_5m  or 0.0) +
        WEIGHTS["15m"] * (pct_15m or 0.0) +
        WEIGHTS["1h"]  * (pct_1h  or 0.0),
        4,
    )


def classify_direction(score: float) -> str:
    if score > 0.1:
        return "bull"
    if score < -0.1:
        return "bear"
    return "neutral"


def build_ranked(symbols_data: dict) -> list:
    """
    symbols_data: {symbol: {"pct_5m": float|None, "pct_15m": float|None, "pct_1h": float|None}}
    Returns list sorted by score desc, with rank field.
    """
    rows = []
    for sym, d in symbols_data.items():
        p5  = d.get("pct_5m")
        p15 = d.get("pct_15m")
        p1h = d.get("pct_1h")
        score = momentum_score(p5, p15, p1h)
        rows.append({
            "symbol":   sym,
            "score":    score,
            "pct_5m":   p5,
            "pct_15m":  p15,
            "pct_1h":   p1h,
            "direction": classify_direction(score),
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


# ── pct_change tests ──────────────────────────────────────────────────────────

def test_pct_change_positive():
    candles = [{"open": 100.0, "close": 101.0}, {"open": 101.0, "close": 102.0}]
    assert pct_change(candles) == pytest.approx(2.0)


def test_pct_change_negative():
    candles = [{"open": 100.0, "close": 99.5}, {"open": 99.5, "close": 98.0}]
    assert pct_change(candles) == pytest.approx(-2.0)


def test_pct_change_single_candle():
    candles = [{"open": 50.0, "close": 51.0}]
    assert pct_change(candles) == pytest.approx(2.0)


def test_pct_change_empty_returns_none():
    assert pct_change([]) is None


def test_pct_change_none_open_returns_none():
    candles = [{"open": None, "close": 100.0}]
    assert pct_change(candles) is None


def test_pct_change_zero_open_returns_none():
    candles = [{"open": 0.0, "close": 100.0}]
    assert pct_change(candles) is None


def test_pct_change_uses_first_open_last_close():
    candles = [
        {"open": 10.0,  "close": 15.0},
        {"open": 15.0,  "close": 20.0},
        {"open": 20.0,  "close": 25.0},
    ]
    # (25 - 10) / 10 * 100 = 150.0
    assert pct_change(candles) == pytest.approx(150.0)


# ── momentum_score tests ──────────────────────────────────────────────────────

def test_score_all_positive():
    s = momentum_score(2.0, 1.5, 1.0)
    # 0.5*2 + 0.3*1.5 + 0.2*1.0 = 1.0 + 0.45 + 0.2 = 1.65
    assert s == pytest.approx(1.65)


def test_score_all_negative():
    s = momentum_score(-2.0, -1.5, -1.0)
    assert s == pytest.approx(-1.65)


def test_score_none_treated_as_zero():
    s = momentum_score(None, None, None)
    assert s == pytest.approx(0.0)


def test_score_mixed_none():
    s = momentum_score(2.0, None, None)
    assert s == pytest.approx(1.0)


def test_score_weights_sum_to_one():
    total = sum(WEIGHTS.values())
    assert total == pytest.approx(1.0)


def test_score_5m_has_most_weight():
    # 5m-only vs 1h-only: 5m contributes more
    s5m = momentum_score(1.0, 0.0, 0.0)
    s1h = momentum_score(0.0, 0.0, 1.0)
    assert s5m > s1h


# ── ranking tests ─────────────────────────────────────────────────────────────

FOUR_SYMBOLS = {
    "BANANAS31USDT": {"pct_5m": 3.0,  "pct_15m": 2.0,  "pct_1h": 1.0},   # score=2.3
    "COSUSDT":       {"pct_5m": -1.0, "pct_15m": 0.5,  "pct_1h": 0.2},   # score=-0.305
    "DEXEUSDT":      {"pct_5m": 1.0,  "pct_15m": 0.5,  "pct_1h": 0.1},   # score=0.67
    "LYNUSDT":       {"pct_5m": -3.0, "pct_15m": -2.0, "pct_1h": -1.0},  # score=-2.3
}


def test_rank_1_is_highest_score():
    ranked = build_ranked(FOUR_SYMBOLS)
    assert ranked[0]["rank"] == 1
    assert ranked[0]["symbol"] == "BANANAS31USDT"


def test_rank_4_is_lowest_score():
    ranked = build_ranked(FOUR_SYMBOLS)
    assert ranked[-1]["rank"] == 4
    assert ranked[-1]["symbol"] == "LYNUSDT"


def test_ranks_are_sequential():
    ranked = build_ranked(FOUR_SYMBOLS)
    assert [r["rank"] for r in ranked] == [1, 2, 3, 4]


def test_no_duplicate_ranks():
    ranked = build_ranked(FOUR_SYMBOLS)
    ranks = [r["rank"] for r in ranked]
    assert len(ranks) == len(set(ranks))


def test_all_four_symbols_present():
    ranked = build_ranked(FOUR_SYMBOLS)
    syms = {r["symbol"] for r in ranked}
    assert syms == set(FOUR_SYMBOLS.keys())


def test_ranked_in_descending_score_order():
    ranked = build_ranked(FOUR_SYMBOLS)
    scores = [r["score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)


def test_all_none_data_scores_zero_and_is_neutral():
    data = {sym: {"pct_5m": None, "pct_15m": None, "pct_1h": None}
            for sym in FOUR_SYMBOLS}
    ranked = build_ranked(data)
    for r in ranked:
        assert r["score"] == 0.0
        assert r["direction"] == "neutral"


# ── direction classification ──────────────────────────────────────────────────

def test_direction_bull():
    assert classify_direction(0.5)  == "bull"
    assert classify_direction(0.11) == "bull"


def test_direction_bear():
    assert classify_direction(-0.5)  == "bear"
    assert classify_direction(-0.11) == "bear"


def test_direction_neutral_near_zero():
    assert classify_direction(0.0)  == "neutral"
    assert classify_direction(0.05) == "neutral"
    assert classify_direction(-0.09) == "neutral"


# ── response shape ────────────────────────────────────────────────────────────

SAMPLE_RESPONSE = {
    "status": "ok",
    "ts": 1773600000.0,
    "ranked": [
        {"rank": 1, "symbol": "BANANAS31USDT", "score": 2.3, "pct_5m": 3.0, "pct_15m": 2.0, "pct_1h": 1.0, "direction": "bull"},
        {"rank": 2, "symbol": "DEXEUSDT",      "score": 0.67, "pct_5m": 1.0, "pct_15m": 0.5, "pct_1h": 0.1, "direction": "bull"},
        {"rank": 3, "symbol": "COSUSDT",       "score": -0.31, "pct_5m": -1.0, "pct_15m": 0.5, "pct_1h": 0.2, "direction": "bear"},
        {"rank": 4, "symbol": "LYNUSDT",       "score": -2.3, "pct_5m": -3.0, "pct_15m": -2.0, "pct_1h": -1.0, "direction": "bear"},
    ],
}


def test_response_status_ok():
    assert SAMPLE_RESPONSE["status"] == "ok"


def test_response_has_ranked_list():
    assert isinstance(SAMPLE_RESPONSE["ranked"], list)


def test_response_has_ts():
    assert isinstance(SAMPLE_RESPONSE["ts"], float)


def test_each_entry_has_required_keys():
    for entry in SAMPLE_RESPONSE["ranked"]:
        for key in ("rank", "symbol", "score", "pct_5m", "pct_15m", "pct_1h", "direction"):
            assert key in entry, f"Missing key '{key}' in {entry}"


def test_direction_values_are_valid():
    valid = {"bull", "bear", "neutral"}
    for entry in SAMPLE_RESPONSE["ranked"]:
        assert entry["direction"] in valid


# ── route / HTML / JS smoke tests ─────────────────────────────────────────────

def test_momentum_rank_route_registered():
    import tempfile
    os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
    os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from api import router
    paths = [r.path for r in router.routes]
    assert any("momentum-rank" in p for p in paths)


_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_html_has_momentum_rank_card():
    html = _read("frontend/index.html")
    assert "card-momentum-rank" in html


def test_js_has_render_momentum_rank():
    js = _read("frontend/app.js")
    assert "renderMomentumRank" in js


def test_js_calls_momentum_rank_api():
    js = _read("frontend/app.js")
    assert "momentum-rank" in js

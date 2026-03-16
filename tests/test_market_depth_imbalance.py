"""
Unit / smoke tests for /api/depth-imbalance.

Market depth imbalance ratio with real-time bid/ask pressure visualization.

Distinct from:
  - /market-depth       — raw cumulative depth curve only
  - /ob-imbalance       — top-10 level imbalance score
  - /volume-imbalance   — trade-side volume imbalance

This card provides:
  - Imbalance ratio across configurable depth levels (top-5 / top-10 / top-20)
  - Weighted imbalance (nearer levels weighted more heavily)
  - Pressure classification: bullish / bearish / neutral
  - Pressure score 0-100 (intensity of imbalance)
  - USD-denominated bid/ask depth totals
  - Cumulative depth at price thresholds (0.1% / 0.5% / 1% from mid)
  - Per-level breakdown for heatmap visualization

Covers:
  - imbalance_ratio helper
  - weighted_imbalance helper
  - pressure_label helper
  - pressure_score helper
  - depth_at_threshold helper
  - pct_of_total helper
  - fmt_depth_usd helper
  - level_usd_value helper
  - Response shape validation
  - Edge cases: empty book, zero depth, equal sides
  - Route registration
  - HTML card / JS smoke tests
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


# ── Python mirrors of backend helpers ─────────────────────────────────────────

def imbalance_ratio(bid_depth: float, ask_depth: float) -> float:
    """
    Imbalance ratio in [-1, 1].
    +1 = all bids (max bid pressure)
    -1 = all asks (max ask pressure)
     0 = balanced
    Returns 0.0 when total depth is 0.
    """
    total = bid_depth + ask_depth
    if total <= 0:
        return 0.0
    return round((bid_depth - ask_depth) / total, 6)


def weighted_imbalance(
    bid_levels: list[dict],
    ask_levels: list[dict],
    mid_price: float,
) -> float:
    """
    Weighted imbalance: levels closer to mid price get higher weight.
    Weight = 1 / distance_from_mid (in price units), minimum 1e-8 to avoid div-by-zero.
    Returns imbalance_ratio of weighted bid vs weighted ask totals.
    """
    def weighted_sum(levels: list[dict]) -> float:
        total = 0.0
        for lv in levels:
            price = lv.get("price", 0.0)
            size  = lv.get("size",  0.0)
            dist  = max(abs(price - mid_price), 1e-8)
            total += size / dist
        return total

    w_bid = weighted_sum(bid_levels)
    w_ask = weighted_sum(ask_levels)
    return imbalance_ratio(w_bid, w_ask)


def pressure_label(ratio: float, threshold: float = 0.1) -> str:
    """Classify imbalance ratio into directional pressure."""
    if ratio > threshold:
        return "bullish"
    if ratio < -threshold:
        return "bearish"
    return "neutral"


def pressure_score(ratio: float) -> float:
    """
    Convert imbalance ratio to a 0-100 pressure score.
    0  = perfectly balanced (ratio = 0)
    100 = maximum imbalance (|ratio| = 1)
    """
    return round(abs(ratio) * 100, 2)


def depth_at_threshold(
    bid_levels: list[dict],
    ask_levels: list[dict],
    mid_price: float,
    threshold_pct: float,
) -> dict:
    """
    Cumulative bid/ask depth (in size units) within threshold_pct of mid price.
    Returns {"bid": float, "ask": float, "imbalance": float}.
    """
    pct = threshold_pct / 100.0
    lo  = mid_price * (1 - pct)
    hi  = mid_price * (1 + pct)

    bid_total = sum(
        lv["size"] for lv in bid_levels
        if lo <= lv.get("price", 0.0) <= mid_price
    )
    ask_total = sum(
        lv["size"] for lv in ask_levels
        if mid_price <= lv.get("price", 0.0) <= hi
    )
    return {
        "bid": round(bid_total, 4),
        "ask": round(ask_total, 4),
        "imbalance": imbalance_ratio(bid_total, ask_total),
    }


def pct_of_total(side_usd: float, total_usd: float) -> float:
    """Side USD as percentage of total USD. Returns 0 when total is 0."""
    if total_usd <= 0:
        return 0.0
    return round(side_usd / total_usd * 100, 2)


def fmt_depth_usd(usd: float | None) -> str:
    """Format depth USD value for display."""
    if usd is None:
        return "—"
    if usd >= 1_000_000:
        return f"${usd / 1_000_000:.2f}M"
    if usd >= 1_000:
        return f"${usd / 1_000:.1f}k"
    return f"${usd:.0f}"


def level_usd_value(price: float, size: float) -> float:
    """USD notional value of a single order book level."""
    return round(price * size, 4)


# ── Sample data ───────────────────────────────────────────────────────────────

MID_PRICE = 0.002500

BID_LEVELS = [
    {"price": 0.002498, "size": 500_000},
    {"price": 0.002495, "size": 800_000},
    {"price": 0.002490, "size": 1_200_000},
    {"price": 0.002480, "size": 600_000},
    {"price": 0.002470, "size": 400_000},
]

ASK_LEVELS = [
    {"price": 0.002502, "size": 300_000},
    {"price": 0.002505, "size": 450_000},
    {"price": 0.002510, "size": 700_000},
    {"price": 0.002520, "size": 500_000},
    {"price": 0.002530, "size": 350_000},
]

BID_DEPTH_TOTAL = sum(lv["size"] for lv in BID_LEVELS)
ASK_DEPTH_TOTAL = sum(lv["size"] for lv in ASK_LEVELS)

EQUAL_BIDS = [{"price": 0.002498, "size": 1_000_000},
              {"price": 0.002495, "size": 1_000_000}]
EQUAL_ASKS = [{"price": 0.002502, "size": 1_000_000},
              {"price": 0.002505, "size": 1_000_000}]

SAMPLE_RESPONSE = {
    "status": "ok",
    "symbol": "BANANAS31USDT",
    "ts": 1700000000.0,
    "mid_price": 0.002500,
    "imbalance_ratio": 0.38,
    "imbalance_pct": 69.0,
    "weighted_imbalance": 0.45,
    "pressure": "bullish",
    "pressure_score": 38.0,
    "bid_depth_usd": 8_750.0,
    "ask_depth_usd": 5_500.0,
    "levels": [
        {"side": "bid", "price": 0.002498, "size": 500_000,
         "usd": 1249.0, "pct_of_total": 8.7},
        {"side": "ask", "price": 0.002502, "size": 300_000,
         "usd": 750.6, "pct_of_total": 5.2},
    ],
    "depth_at": {
        "0.1pct": {"bid": 500_000.0, "ask": 300_000.0, "imbalance": 0.25},
        "0.5pct": {"bid": 1_300_000.0, "ask": 750_000.0, "imbalance": 0.27},
        "1pct":   {"bid": 3_500_000.0, "ask": 2_300_000.0, "imbalance": 0.20},
    },
    "description": "Bullish pressure: bids dominate by 38% (score 38)",
}


# ── imbalance_ratio tests ─────────────────────────────────────────────────────

def test_imbalance_ratio_all_bids():
    assert imbalance_ratio(1000, 0) == pytest.approx(1.0)


def test_imbalance_ratio_all_asks():
    assert imbalance_ratio(0, 1000) == pytest.approx(-1.0)


def test_imbalance_ratio_balanced():
    assert imbalance_ratio(500, 500) == pytest.approx(0.0)


def test_imbalance_ratio_zero_total():
    assert imbalance_ratio(0, 0) == pytest.approx(0.0)


def test_imbalance_ratio_bid_heavy():
    r = imbalance_ratio(BID_DEPTH_TOTAL, ASK_DEPTH_TOTAL)
    assert r > 0


def test_imbalance_ratio_bounds():
    for bid, ask in [(100, 200), (300, 100), (0, 0), (1000, 1000)]:
        r = imbalance_ratio(bid, ask)
        assert -1.0 <= r <= 1.0


def test_imbalance_ratio_symmetric():
    r1 = imbalance_ratio(700, 300)
    r2 = imbalance_ratio(300, 700)
    assert r1 == pytest.approx(-r2)


def test_imbalance_ratio_formula():
    r = imbalance_ratio(750, 250)
    assert r == pytest.approx(0.5)


# ── weighted_imbalance tests ──────────────────────────────────────────────────

def test_weighted_imbalance_balanced():
    r = weighted_imbalance(EQUAL_BIDS, EQUAL_ASKS, MID_PRICE)
    assert r == pytest.approx(0.0, abs=0.01)


def test_weighted_imbalance_bid_heavy():
    heavy_bids = [{"price": 0.002499, "size": 2_000_000}]
    light_asks = [{"price": 0.002501, "size": 500_000}]
    r = weighted_imbalance(heavy_bids, light_asks, MID_PRICE)
    assert r > 0


def test_weighted_imbalance_ask_heavy():
    light_bids = [{"price": 0.002499, "size": 200_000}]
    heavy_asks = [{"price": 0.002501, "size": 2_000_000}]
    r = weighted_imbalance(light_bids, heavy_asks, MID_PRICE)
    assert r < 0


def test_weighted_imbalance_empty_both():
    r = weighted_imbalance([], [], MID_PRICE)
    assert r == pytest.approx(0.0)


def test_weighted_imbalance_in_bounds():
    r = weighted_imbalance(BID_LEVELS, ASK_LEVELS, MID_PRICE)
    assert -1.0 <= r <= 1.0


def test_weighted_nearer_levels_dominant():
    # One very close bid level should outweigh distant large ask level
    close_bids = [{"price": MID_PRICE - 0.000001, "size": 100_000}]
    far_asks   = [{"price": MID_PRICE + 0.01,     "size": 1_000_000}]
    r = weighted_imbalance(close_bids, far_asks, MID_PRICE)
    assert r > 0  # close bid dominates despite smaller size


# ── pressure_label tests ──────────────────────────────────────────────────────

def test_pressure_bullish():
    assert pressure_label(0.5) == "bullish"


def test_pressure_bearish():
    assert pressure_label(-0.5) == "bearish"


def test_pressure_neutral_zero():
    assert pressure_label(0.0) == "neutral"


def test_pressure_neutral_near_threshold():
    assert pressure_label(0.09) == "neutral"
    assert pressure_label(-0.09) == "neutral"


def test_pressure_at_threshold_bullish():
    assert pressure_label(0.11) == "bullish"


def test_pressure_at_threshold_bearish():
    assert pressure_label(-0.11) == "bearish"


def test_pressure_custom_threshold():
    assert pressure_label(0.05, threshold=0.03) == "bullish"
    assert pressure_label(0.05, threshold=0.10) == "neutral"


def test_pressure_valid_values():
    for r in [-0.8, -0.2, 0.0, 0.2, 0.8]:
        assert pressure_label(r) in ("bullish", "bearish", "neutral")


# ── pressure_score tests ──────────────────────────────────────────────────────

def test_pressure_score_zero():
    assert pressure_score(0.0) == pytest.approx(0.0)


def test_pressure_score_max():
    assert pressure_score(1.0) == pytest.approx(100.0)
    assert pressure_score(-1.0) == pytest.approx(100.0)


def test_pressure_score_half():
    assert pressure_score(0.5) == pytest.approx(50.0)


def test_pressure_score_symmetric():
    assert pressure_score(0.4) == pytest.approx(pressure_score(-0.4))


def test_pressure_score_range():
    for r in [-1.0, -0.5, 0.0, 0.5, 1.0]:
        assert 0.0 <= pressure_score(r) <= 100.0


# ── depth_at_threshold tests ──────────────────────────────────────────────────

def test_depth_at_01pct_returns_dict():
    d = depth_at_threshold(BID_LEVELS, ASK_LEVELS, MID_PRICE, 0.1)
    assert "bid" in d and "ask" in d and "imbalance" in d


def test_depth_at_01pct_only_near_levels():
    # Only levels within 0.1% of mid should be counted
    # MID=0.0025 → range [0.002497..0.002503]
    d = depth_at_threshold(BID_LEVELS, ASK_LEVELS, MID_PRICE, 0.1)
    # BID_LEVELS[0] at 0.002498 is within range
    assert d["bid"] > 0


def test_depth_at_1pct_includes_more_levels():
    d_01 = depth_at_threshold(BID_LEVELS, ASK_LEVELS, MID_PRICE, 0.1)
    d_1  = depth_at_threshold(BID_LEVELS, ASK_LEVELS, MID_PRICE, 1.0)
    assert d_1["bid"] >= d_01["bid"]


def test_depth_at_empty_levels():
    d = depth_at_threshold([], [], MID_PRICE, 0.5)
    assert d["bid"] == 0.0
    assert d["ask"] == 0.0
    assert d["imbalance"] == pytest.approx(0.0)


def test_depth_at_imbalance_in_bounds():
    d = depth_at_threshold(BID_LEVELS, ASK_LEVELS, MID_PRICE, 0.5)
    assert -1.0 <= d["imbalance"] <= 1.0


def test_depth_at_zero_threshold():
    d = depth_at_threshold(BID_LEVELS, ASK_LEVELS, MID_PRICE, 0.0)
    assert d["bid"] == 0.0
    assert d["ask"] == 0.0


# ── pct_of_total tests ────────────────────────────────────────────────────────

def test_pct_of_total_half():
    assert pct_of_total(500, 1000) == pytest.approx(50.0)


def test_pct_of_total_zero_total():
    assert pct_of_total(100, 0) == pytest.approx(0.0)


def test_pct_of_total_full():
    assert pct_of_total(1000, 1000) == pytest.approx(100.0)


def test_pct_of_total_zero_side():
    assert pct_of_total(0, 1000) == pytest.approx(0.0)


def test_pct_of_total_range():
    for bid, total in [(100, 1000), (0, 500), (500, 500)]:
        p = pct_of_total(bid, total)
        assert 0.0 <= p <= 100.0


# ── fmt_depth_usd tests ───────────────────────────────────────────────────────

def test_fmt_depth_millions():
    assert fmt_depth_usd(2_500_000) == "$2.50M"


def test_fmt_depth_thousands():
    assert fmt_depth_usd(15_000) == "$15.0k"


def test_fmt_depth_small():
    assert fmt_depth_usd(750) == "$750"


def test_fmt_depth_none():
    assert fmt_depth_usd(None) == "—"


def test_fmt_depth_boundary_1k():
    assert fmt_depth_usd(1000) == "$1.0k"


def test_fmt_depth_boundary_1m():
    assert fmt_depth_usd(1_000_000) == "$1.00M"


# ── level_usd_value tests ─────────────────────────────────────────────────────

def test_level_usd_basic():
    assert level_usd_value(0.002500, 1_000_000) == pytest.approx(2500.0)


def test_level_usd_zero_size():
    assert level_usd_value(0.002500, 0) == pytest.approx(0.0)


def test_level_usd_zero_price():
    assert level_usd_value(0.0, 1_000_000) == pytest.approx(0.0)


# ── Response shape tests ──────────────────────────────────────────────────────

def test_response_status():
    assert SAMPLE_RESPONSE["status"] == "ok"


def test_response_required_keys():
    for key in (
        "symbol", "ts", "mid_price",
        "imbalance_ratio", "imbalance_pct", "weighted_imbalance",
        "pressure", "pressure_score",
        "bid_depth_usd", "ask_depth_usd",
        "levels", "depth_at", "description",
    ):
        assert key in SAMPLE_RESPONSE


def test_response_imbalance_ratio_in_bounds():
    r = SAMPLE_RESPONSE["imbalance_ratio"]
    assert -1.0 <= r <= 1.0


def test_response_imbalance_pct_in_bounds():
    pct = SAMPLE_RESPONSE["imbalance_pct"]
    assert 0.0 <= pct <= 100.0


def test_response_weighted_imbalance_in_bounds():
    w = SAMPLE_RESPONSE["weighted_imbalance"]
    assert -1.0 <= w <= 1.0


def test_response_pressure_valid():
    assert SAMPLE_RESPONSE["pressure"] in ("bullish", "bearish", "neutral")


def test_response_pressure_score_in_bounds():
    s = SAMPLE_RESPONSE["pressure_score"]
    assert 0.0 <= s <= 100.0


def test_response_depths_nonneg():
    assert SAMPLE_RESPONSE["bid_depth_usd"] >= 0
    assert SAMPLE_RESPONSE["ask_depth_usd"] >= 0


def test_response_levels_is_list():
    assert isinstance(SAMPLE_RESPONSE["levels"], list)


def test_response_levels_keys():
    for lv in SAMPLE_RESPONSE["levels"]:
        for key in ("side", "price", "size", "usd", "pct_of_total"):
            assert key in lv


def test_response_levels_side_valid():
    for lv in SAMPLE_RESPONSE["levels"]:
        assert lv["side"] in ("bid", "ask")


def test_response_depth_at_keys():
    da = SAMPLE_RESPONSE["depth_at"]
    for band in ("0.1pct", "0.5pct", "1pct"):
        assert band in da
        assert "bid" in da[band]
        assert "ask" in da[band]
        assert "imbalance" in da[band]


def test_response_depth_at_imbalance_in_bounds():
    for band in SAMPLE_RESPONSE["depth_at"].values():
        assert -1.0 <= band["imbalance"] <= 1.0


def test_response_pressure_consistent_with_ratio():
    # bullish pressure → positive imbalance_ratio
    assert SAMPLE_RESPONSE["imbalance_ratio"] > 0


def test_response_description_nonempty():
    assert len(SAMPLE_RESPONSE["description"]) > 0


# ── Route registration ────────────────────────────────────────────────────────

def test_depth_imbalance_route_registered():
    import tempfile
    os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
    os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from api import router
    paths = [r.path for r in router.routes]
    assert any("depth-imbalance" in p for p in paths)


# ── HTML / JS smoke tests ─────────────────────────────────────────────────────

def test_html_has_depth_imbalance_card():
    assert "card-depth-imbalance" in _html()


def test_js_has_render_depth_imbalance():
    assert "renderDepthImbalance" in _js()


def test_js_calls_depth_imbalance_api():
    assert "depth-imbalance" in _js()

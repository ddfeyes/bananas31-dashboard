"""
TDD tests for price ladder heatmap.

Spec:
  compute_price_ladder(snapshots, num_levels=20, bin_size=None, wall_sigma=1.5)

  snapshots: [{ts, bids: [[price, qty],...], asks: [[price, qty],...], mid_price}]
    - bids sorted desc by price (best bid first)
    - asks sorted asc by price (best ask first)
    - volumes already parsed as floats

  Bins prices into num_levels buckets on each side of mid_price.
  Accumulates bid_vol / ask_vol per bin across all snapshots (mean over snapshots).
  Detects walls: levels where volume >= mean + wall_sigma * std of all non-zero volumes.

  Returns:
    levels:          list of {price, bid_vol, ask_vol, is_bid_wall, is_ask_wall}
                     sorted ascending by price
    mid_price:       float  (latest snapshot)
    best_bid:        float  (highest bid in latest snapshot, 0 if empty)
    best_ask:        float  (lowest ask in latest snapshot, 0 if empty)
    spread:          float  (best_ask - best_bid, 0 if either missing)
    bid_wall_price:  float|None  (price of level with highest bid_vol, None if all zero)
    ask_wall_price:  float|None  (price of level with highest ask_vol, None if all zero)
    wall_threshold:  float  (volume >= this → is_*_wall = True)
    total_bid_vol:   float  (sum of bid_vol across all levels)
    total_ask_vol:   float  (sum of ask_vol across all levels)
    snapshot_count:  int
    bin_size:        float
"""
import sys, os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from metrics import compute_price_ladder  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────────

def _snap(ts, bids, asks, mid_price=None):
    """Create a snapshot dict. mid_price defaults to (best_bid + best_ask) / 2."""
    if mid_price is None:
        b0 = float(bids[0][0]) if bids else 0.0
        a0 = float(asks[0][0]) if asks else 0.0
        mid_price = (b0 + a0) / 2.0 if (bids and asks) else (b0 or a0)
    return {
        "ts":        float(ts),
        "bids":      [[float(p), float(q)] for p, q in bids],
        "asks":      [[float(p), float(q)] for p, q in asks],
        "mid_price": float(mid_price),
    }

def _simple():
    """A simple single snapshot: bids around 99-100, asks around 101-102."""
    return _snap(
        ts=0,
        bids=[[100.0, 5.0], [99.5, 3.0], [99.0, 2.0]],
        asks=[[101.0, 4.0], [101.5, 2.0], [102.0, 1.0]],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestStructure:
    def test_empty_snapshots_returns_valid_dict(self):
        r = compute_price_ladder([], num_levels=5, bin_size=1.0)
        assert isinstance(r, dict)

    def test_result_has_required_fields(self):
        r = compute_price_ladder([], num_levels=5, bin_size=1.0)
        for f in ("levels", "mid_price", "best_bid", "best_ask", "spread",
                  "bid_wall_price", "ask_wall_price", "wall_threshold",
                  "total_bid_vol", "total_ask_vol", "snapshot_count", "bin_size"):
            assert f in r, f"missing: {f}"

    def test_empty_snapshots_zero_state(self):
        r = compute_price_ladder([], num_levels=5, bin_size=1.0)
        assert r["snapshot_count"] == 0
        assert r["mid_price"] == pytest.approx(0.0)
        assert r["total_bid_vol"] == pytest.approx(0.0)
        assert r["total_ask_vol"] == pytest.approx(0.0)
        assert r["bid_wall_price"] is None
        assert r["ask_wall_price"] is None

    def test_levels_is_list(self):
        r = compute_price_ladder([_simple()], num_levels=5, bin_size=1.0)
        assert isinstance(r["levels"], list)

    def test_level_has_required_fields(self):
        r = compute_price_ladder([_simple()], num_levels=5, bin_size=1.0)
        assert len(r["levels"]) > 0
        level = r["levels"][0]
        for f in ("price", "bid_vol", "ask_vol", "is_bid_wall", "is_ask_wall"):
            assert f in level, f"missing level field: {f}"

    def test_bin_size_echoed(self):
        r = compute_price_ladder([_simple()], num_levels=5, bin_size=0.5)
        assert r["bin_size"] == pytest.approx(0.5)

    def test_snapshot_count(self):
        snaps = [_simple(), _simple(), _simple()]
        r = compute_price_ladder(snaps, num_levels=5, bin_size=1.0)
        assert r["snapshot_count"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Mid price, best bid/ask, spread
# ═══════════════════════════════════════════════════════════════════════════════

class TestMidAndSpread:
    def test_mid_price_from_latest_snapshot(self):
        snap1 = _snap(0, [[99.0, 1.0]], [[101.0, 1.0]], mid_price=100.0)
        snap2 = _snap(1, [[199.0, 1.0]], [[201.0, 1.0]], mid_price=200.0)
        r = compute_price_ladder([snap1, snap2], num_levels=5, bin_size=5.0)
        assert r["mid_price"] == pytest.approx(200.0)

    def test_best_bid_from_latest_snapshot(self):
        snap = _snap(0, [[100.0, 5.0], [99.0, 2.0]], [[101.0, 3.0]])
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        assert r["best_bid"] == pytest.approx(100.0)

    def test_best_ask_from_latest_snapshot(self):
        snap = _snap(0, [[100.0, 5.0]], [[101.0, 3.0], [102.0, 1.0]])
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        assert r["best_ask"] == pytest.approx(101.0)

    def test_spread_is_ask_minus_bid(self):
        snap = _snap(0, [[100.0, 1.0]], [[101.5, 1.0]])
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        assert r["spread"] == pytest.approx(1.5)

    def test_spread_zero_when_no_bids(self):
        snap = _snap(0, [], [[101.0, 1.0]], mid_price=101.0)
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        assert r["spread"] == pytest.approx(0.0)

    def test_spread_zero_when_no_asks(self):
        snap = _snap(0, [[100.0, 1.0]], [], mid_price=100.0)
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        assert r["spread"] == pytest.approx(0.0)

    def test_best_bid_zero_when_empty_bids(self):
        snap = _snap(0, [], [[101.0, 1.0]], mid_price=101.0)
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        assert r["best_bid"] == pytest.approx(0.0)

    def test_best_ask_zero_when_empty_asks(self):
        snap = _snap(0, [[100.0, 1.0]], [], mid_price=100.0)
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        assert r["best_ask"] == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Levels ordering and structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestLevels:
    def test_levels_sorted_ascending_by_price(self):
        r = compute_price_ladder([_simple()], num_levels=5, bin_size=1.0)
        prices = [lv["price"] for lv in r["levels"]]
        assert prices == sorted(prices)

    def test_levels_count_is_2_times_num_levels(self):
        """2 * num_levels total bins (num_levels bid-side + num_levels ask-side)."""
        r = compute_price_ladder([_simple()], num_levels=5, bin_size=1.0)
        assert len(r["levels"]) == 10

    def test_levels_span_mid_price(self):
        """Some levels are below mid and some above."""
        snap = _snap(0, [[99.0, 1.0]], [[101.0, 1.0]], mid_price=100.0)
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        prices = [lv["price"] for lv in r["levels"]]
        assert min(prices) < 100.0
        assert max(prices) > 100.0

    def test_bid_vol_and_ask_vol_non_negative(self):
        r = compute_price_ladder([_simple()], num_levels=5, bin_size=1.0)
        for lv in r["levels"]:
            assert lv["bid_vol"] >= 0.0
            assert lv["ask_vol"] >= 0.0

    def test_bid_vol_zero_above_mid(self):
        """Asks appear above mid → those levels should have bid_vol=0."""
        snap = _snap(0, [[99.0, 5.0]], [[101.0, 5.0]], mid_price=100.0)
        r = compute_price_ladder([snap], num_levels=3, bin_size=1.0)
        above = [lv for lv in r["levels"] if lv["price"] > 100.0]
        for lv in above:
            assert lv["bid_vol"] == pytest.approx(0.0), f"price={lv['price']}"

    def test_ask_vol_zero_below_mid(self):
        """Bids appear below mid → those levels should have ask_vol=0."""
        snap = _snap(0, [[99.0, 5.0]], [[101.0, 5.0]], mid_price=100.0)
        r = compute_price_ladder([snap], num_levels=3, bin_size=1.0)
        below = [lv for lv in r["levels"] if lv["price"] < 100.0]
        for lv in below:
            assert lv["ask_vol"] == pytest.approx(0.0), f"price={lv['price']}"


# ═══════════════════════════════════════════════════════════════════════════════
# Volume accumulation
# ═══════════════════════════════════════════════════════════════════════════════

class TestVolumeAccumulation:
    def test_single_bid_level_has_correct_volume(self):
        """A bid of 5.0 at price 99 should appear in the bid_vol of the 99-bin."""
        snap = _snap(0, [[99.0, 5.0]], [[101.0, 0.1]], mid_price=100.0)
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        # Find the level closest to 99
        level = min(r["levels"], key=lambda lv: abs(lv["price"] - 99.0))
        assert level["bid_vol"] == pytest.approx(5.0)

    def test_single_ask_level_has_correct_volume(self):
        """An ask of 4.0 at price 101 should appear in ask_vol of the 101-bin."""
        snap = _snap(0, [[99.0, 0.1]], [[101.0, 4.0]], mid_price=100.0)
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        level = min(r["levels"], key=lambda lv: abs(lv["price"] - 101.0))
        assert level["ask_vol"] == pytest.approx(4.0)

    def test_total_bid_vol_equals_sum_of_levels(self):
        r = compute_price_ladder([_simple()], num_levels=5, bin_size=1.0)
        assert r["total_bid_vol"] == pytest.approx(sum(lv["bid_vol"] for lv in r["levels"]))

    def test_total_ask_vol_equals_sum_of_levels(self):
        r = compute_price_ladder([_simple()], num_levels=5, bin_size=1.0)
        assert r["total_ask_vol"] == pytest.approx(sum(lv["ask_vol"] for lv in r["levels"]))

    def test_multiple_bids_in_same_bin_aggregated(self):
        """Two bids within the same 1.0-wide bin → bid_vol = sum."""
        snap = _snap(0,
            bids=[[99.0, 3.0], [99.4, 2.0]],   # both in [99, 100) bin
            asks=[[101.0, 1.0]],
            mid_price=100.0,
        )
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        level = min(r["levels"], key=lambda lv: abs(lv["price"] - 99.0))
        assert level["bid_vol"] == pytest.approx(5.0)

    def test_multiple_snapshots_volumes_averaged(self):
        """
        Two identical snapshots → bid_vol = same as one snapshot
        (mean across snapshots, not sum).
        """
        snap = _snap(0, [[99.0, 6.0]], [[101.0, 0.1]], mid_price=100.0)
        r1 = compute_price_ladder([snap],       num_levels=5, bin_size=1.0)
        r2 = compute_price_ladder([snap, snap], num_levels=5, bin_size=1.0)
        lv1 = min(r1["levels"], key=lambda lv: abs(lv["price"] - 99.0))
        lv2 = min(r2["levels"], key=lambda lv: abs(lv["price"] - 99.0))
        assert lv2["bid_vol"] == pytest.approx(lv1["bid_vol"])

    def test_total_bid_vol_positive_when_bids_present(self):
        snap = _snap(0, [[99.0, 5.0], [98.0, 3.0]], [[101.0, 1.0]])
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        assert r["total_bid_vol"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Wall detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestWallDetection:
    def _make_wall_snap(self, wall_price=99.0, wall_vol=100.0, normal_vol=1.0):
        """Snapshot with one dominant bid level (wall) and small asks."""
        bids = [
            [wall_price, wall_vol],
            [98.0, normal_vol],
            [97.0, normal_vol],
        ]
        asks = [[101.0, normal_vol], [102.0, normal_vol]]
        return _snap(0, bids, asks, mid_price=100.0)

    def test_bid_wall_detected(self):
        snap = self._make_wall_snap(wall_price=99.0, wall_vol=100.0, normal_vol=0.5)
        r = compute_price_ladder([snap], num_levels=10, bin_size=1.0)
        # There should be at least one bid wall
        bid_walls = [lv for lv in r["levels"] if lv["is_bid_wall"]]
        assert len(bid_walls) >= 1

    def test_bid_wall_price_is_level_with_max_bid_vol(self):
        snap = self._make_wall_snap(wall_price=99.0, wall_vol=100.0, normal_vol=0.5)
        r = compute_price_ladder([snap], num_levels=10, bin_size=1.0)
        assert r["bid_wall_price"] is not None
        max_bid_level = max(r["levels"], key=lambda lv: lv["bid_vol"])
        assert r["bid_wall_price"] == pytest.approx(max_bid_level["price"])

    def test_ask_wall_detected(self):
        snap = _snap(0,
            bids=[[99.0, 0.5]],
            asks=[[101.0, 100.0], [102.0, 0.5]],
            mid_price=100.0,
        )
        r = compute_price_ladder([snap], num_levels=10, bin_size=1.0)
        ask_walls = [lv for lv in r["levels"] if lv["is_ask_wall"]]
        assert len(ask_walls) >= 1

    def test_ask_wall_price_is_level_with_max_ask_vol(self):
        snap = _snap(0,
            bids=[[99.0, 0.5]],
            asks=[[101.0, 100.0], [102.0, 0.5], [103.0, 0.5]],
            mid_price=100.0,
        )
        r = compute_price_ladder([snap], num_levels=10, bin_size=1.0)
        assert r["ask_wall_price"] is not None
        max_ask_level = max(r["levels"], key=lambda lv: lv["ask_vol"])
        assert r["ask_wall_price"] == pytest.approx(max_ask_level["price"])

    def test_no_wall_when_volumes_uniform(self):
        """Uniform volume → no outliers → no walls."""
        bids = [[100.0 - i, 1.0] for i in range(1, 6)]
        asks = [[100.0 + i, 1.0] for i in range(1, 6)]
        snap = _snap(0, bids, asks, mid_price=100.0)
        r = compute_price_ladder([snap], num_levels=10, bin_size=1.0)
        bid_walls = [lv for lv in r["levels"] if lv["is_bid_wall"]]
        ask_walls = [lv for lv in r["levels"] if lv["is_ask_wall"]]
        assert len(bid_walls) == 0
        assert len(ask_walls) == 0

    def test_wall_threshold_positive(self):
        snap = self._make_wall_snap()
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        assert r["wall_threshold"] >= 0.0

    def test_bid_wall_price_none_when_no_bids(self):
        snap = _snap(0, [], [[101.0, 1.0]], mid_price=101.0)
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        assert r["bid_wall_price"] is None

    def test_ask_wall_price_none_when_no_asks(self):
        snap = _snap(0, [[99.0, 1.0]], [], mid_price=99.0)
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        assert r["ask_wall_price"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# Bin size
# ═══════════════════════════════════════════════════════════════════════════════

class TestBinSize:
    def test_manual_bin_size_used(self):
        r = compute_price_ladder([_simple()], num_levels=5, bin_size=2.0)
        assert r["bin_size"] == pytest.approx(2.0)

    def test_auto_bin_size_computed_when_none(self):
        """Auto bin_size is positive when snapshots have data."""
        r = compute_price_ladder([_simple()], num_levels=5)
        assert r["bin_size"] > 0.0

    def test_auto_bin_size_none_raises_no_error_on_empty(self):
        """Empty snapshots with no bin_size should not crash."""
        r = compute_price_ladder([], num_levels=5)
        assert r["bin_size"] >= 0.0

    def test_larger_bin_size_fewer_distinct_level_prices(self):
        """Larger bins → prices more widely spaced."""
        r_small = compute_price_ladder([_simple()], num_levels=5, bin_size=0.5)
        r_large = compute_price_ladder([_simple()], num_levels=5, bin_size=2.0)
        prices_small = [lv["price"] for lv in r_small["levels"]]
        prices_large = [lv["price"] for lv in r_large["levels"]]
        span_small = max(prices_small) - min(prices_small)
        span_large = max(prices_large) - min(prices_large)
        assert span_large > span_small

    def test_level_prices_are_multiples_of_bin_size(self):
        """Level prices should be aligned to bin_size grid."""
        snap = _snap(0, [[99.0, 1.0]], [[101.0, 1.0]], mid_price=100.0)
        r = compute_price_ladder([snap], num_levels=5, bin_size=1.0)
        for lv in r["levels"]:
            remainder = round(lv["price"] % 1.0, 6)
            assert remainder == pytest.approx(0.0) or remainder == pytest.approx(1.0), \
                f"price {lv['price']} not on bin grid"


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_single_snapshot_no_crash(self):
        r = compute_price_ladder([_simple()], num_levels=10, bin_size=1.0)
        assert r["snapshot_count"] == 1

    def test_single_bid_single_ask_snapshot(self):
        snap = _snap(0, [[99.0, 3.0]], [[101.0, 4.0]])
        r = compute_price_ladder([snap], num_levels=3, bin_size=1.0)
        assert r["total_bid_vol"] == pytest.approx(3.0)
        assert r["total_ask_vol"] == pytest.approx(4.0)

    def test_out_of_range_levels_have_zero_volume(self):
        """If OB entry falls outside the num_levels * bin_size window, it's ignored."""
        snap = _snap(0,
            bids=[[99.0, 5.0], [50.0, 999.0]],   # 50 is far out of range
            asks=[[101.0, 4.0]],
            mid_price=100.0,
        )
        r = compute_price_ladder([snap], num_levels=3, bin_size=1.0)
        # The level at ~50 should not appear in the 3-level window around 100
        prices = [lv["price"] for lv in r["levels"]]
        assert all(p > 90 for p in prices), f"unexpected far price: {prices}"

    def test_large_num_levels_no_crash(self):
        r = compute_price_ladder([_simple()], num_levels=50, bin_size=0.1)
        assert len(r["levels"]) == 100

    def test_snapshots_use_latest_for_best_bid_ask(self):
        """Uses latest snapshot (by ts) for best_bid/best_ask."""
        old  = _snap(0, [[90.0, 1.0]], [[110.0, 1.0]], mid_price=100.0)
        new  = _snap(1, [[99.0, 1.0]], [[101.0, 1.0]], mid_price=100.0)
        r = compute_price_ladder([old, new], num_levels=5, bin_size=1.0)
        assert r["best_bid"] == pytest.approx(99.0)
        assert r["best_ask"] == pytest.approx(101.0)

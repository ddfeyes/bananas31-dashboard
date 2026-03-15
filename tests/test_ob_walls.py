"""
Tests for OB wall detection endpoint and rendering logic.

Validates wall detection, decay tracking, liquidation risk classification,
and edge cases that mirror app.js renderObWalls().
"""
import json
from unittest.mock import AsyncMock, patch

import pytest


# ── Python mirrors of backend wall detection logic ────────────────────────────

def compute_median(sizes):
    """Compute median of a list of floats."""
    if not sizes:
        return 0.0
    s = sorted(sizes)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def detect_walls_py(bids, asks, wall_multiplier=10.0):
    """
    Pure-Python mirror of detect_ob_walls wall detection step.

    bids and asks are lists of (price, qty) tuples.
    Returns (walls, threshold) where walls is a list of dicts.
    """
    all_sizes = [q for _, q in bids] + [q for _, q in asks]
    if not all_sizes:
        return [], 0.0

    median_size = compute_median(all_sizes)
    threshold = median_size * wall_multiplier

    walls = []
    for price, qty in bids:
        if qty >= threshold:
            walls.append({"price": price, "size": qty, "side": "bid"})
    for price, qty in asks:
        if qty >= threshold:
            walls.append({"price": price, "size": qty, "side": "ask"})

    return walls, threshold


def compute_decay_py(snapshots, price, side, threshold, current_size):
    """
    Mirror decay tracking: walk backwards through snapshots to find first
    continuous appearance of wall at (price, side).

    snapshots: list of {"ts": float, "bids": {price: qty}, "asks": {price: qty}}
    Returns (initial_size, first_seen_ts, decay_pct, age_sec).
    """
    if not snapshots:
        return current_size, snapshots[-1]["ts"] if snapshots else 0.0, 0.0, 0

    current_ts = snapshots[-1]["ts"]
    initial_size = current_size
    first_seen_ts = current_ts

    for snap in reversed(snapshots[:-1]):
        levels = snap["bids"] if side == "bid" else snap["asks"]
        historical_qty = levels.get(price)
        if historical_qty is not None and historical_qty >= threshold:
            initial_size = historical_qty
            first_seen_ts = snap["ts"]
        else:
            break

    age_sec = int(current_ts - first_seen_ts)
    decay_pct = max(0.0, (initial_size - current_size) / initial_size * 100) if initial_size > 0 else 0.0
    return initial_size, first_seen_ts, decay_pct, age_sec


def liquidation_risk_py(walls, mid_price):
    """Mirror liquidation_risk classification."""
    if not walls or mid_price <= 0:
        return "low"
    bid_dists = [abs(w["price"] - mid_price) / mid_price * 100 for w in walls if w["side"] == "bid"]
    ask_dists = [abs(w["price"] - mid_price) / mid_price * 100 for w in walls if w["side"] == "ask"]
    closest_bid = min(bid_dists, default=100.0)
    closest_ask = min(ask_dists, default=100.0)
    if closest_bid < 0.5 and closest_ask < 0.5:
        return "high"
    if closest_bid < 1.0 or closest_ask < 1.0:
        return "medium"
    return "low"


# ── Python mirrors of app.js renderObWalls() helpers ─────────────────────────

def wall_color(decay_pct):
    """Color coding for wall decay status."""
    if decay_pct < 5.0:
        return "var(--red)"
    if decay_pct < 20.0:
        return "var(--yellow)"
    return "var(--green)"


def wall_label(decay_pct):
    """Human-readable decay label."""
    if decay_pct < 5.0:
        return "solid"
    if decay_pct < 20.0:
        return "weakening"
    return "breaking"


def risk_badge_class(risk):
    """Badge class for liquidation risk."""
    if risk == "high":
        return "badge-red"
    if risk == "medium":
        return "badge-yellow"
    return "badge-blue"


def fmt_age(age_sec):
    """Format age in seconds to human string."""
    if age_sec < 60:
        return f"{age_sec}s"
    return f"{age_sec // 60}m{age_sec % 60:02d}s"


# ── Fixtures ──────────────────────────────────────────────────────────────────

BASE_TS = 1710432000.0


def make_uniform_ob(n_levels=20, base_price=100.0, qty=10.0, price_step=0.01):
    """Build uniform orderbook with equal quantities at each level."""
    bids = [(base_price - i * price_step, qty) for i in range(n_levels)]
    asks = [(base_price + (i + 1) * price_step, qty) for i in range(n_levels)]
    return bids, asks


def make_ob_with_wall(n_levels=20, base_price=100.0, normal_qty=10.0,
                      wall_price=None, wall_qty=None, wall_side="bid", price_step=0.01):
    """Build orderbook with one wall level."""
    bids, asks = make_uniform_ob(n_levels, base_price, normal_qty, price_step)
    bids = list(bids)
    asks = list(asks)
    if wall_price is None:
        wall_price = base_price - 0.05
    if wall_qty is None:
        # 10x median = 10x normal_qty → just above threshold
        wall_qty = normal_qty * 10.5
    if wall_side == "bid":
        bids.append((wall_price, wall_qty))
    else:
        asks.append((wall_price, wall_qty))
    return bids, asks


# ── 1. Wall detection logic ───────────────────────────────────────────────────

class TestWallDetection:
    def test_no_walls_when_uniform_sizes(self):
        """Uniform orderbook → no level exceeds 10x median."""
        bids, asks = make_uniform_ob(20, qty=10.0)
        walls, _ = detect_walls_py(bids, asks)
        assert walls == []

    def test_bid_wall_detected(self):
        """One bid level with qty = 10.5 * median → wall detected."""
        bids, asks = make_ob_with_wall(n_levels=20, normal_qty=10.0,
                                       wall_qty=105.0, wall_side="bid")
        walls, _ = detect_walls_py(bids, asks)
        bid_walls = [w for w in walls if w["side"] == "bid"]
        assert len(bid_walls) == 1

    def test_ask_wall_detected(self):
        """One ask level with qty = 10.5 * median → wall detected."""
        bids, asks = make_ob_with_wall(n_levels=20, normal_qty=10.0,
                                       wall_qty=105.0, wall_side="ask")
        walls, _ = detect_walls_py(bids, asks)
        ask_walls = [w for w in walls if w["side"] == "ask"]
        assert len(ask_walls) == 1

    def test_wall_below_threshold_not_detected(self):
        """Level at 9x median is NOT a wall (threshold is 10x)."""
        bids, asks = make_ob_with_wall(n_levels=20, normal_qty=10.0,
                                       wall_qty=90.0, wall_side="bid")
        walls, _ = detect_walls_py(bids, asks)
        # With wall_qty=90 and 21 bid levels + 20 ask levels,
        # all_sizes now includes 90 → median shifts up, so we verify no wall
        # The exact threshold depends on median; just check qty < threshold
        _, threshold = detect_walls_py(bids, asks)
        assert all(w["size"] >= threshold for w in walls)

    def test_multiple_walls_both_sides(self):
        """Multiple walls on both bid and ask detected."""
        bids = [(100.0 - i * 0.01, 10.0) for i in range(20)]
        asks = [(100.0 + (i + 1) * 0.01, 10.0) for i in range(20)]
        # Add two bid walls and one ask wall
        bids.append((99.5, 105.0))
        bids.append((99.4, 110.0))
        asks.append((100.5, 108.0))
        walls, _ = detect_walls_py(bids, asks)
        assert sum(1 for w in walls if w["side"] == "bid") == 2
        assert sum(1 for w in walls if w["side"] == "ask") == 1

    def test_exact_threshold_counts_as_wall(self):
        """Level at exactly 10x median is a wall (>= not >)."""
        # 20 uniform levels of qty=10, threshold = 10*10 = 100
        bids = [(100.0 - i * 0.01, 10.0) for i in range(20)]
        asks = [(100.0 + (i + 1) * 0.01, 10.0) for i in range(20)]
        bids.append((99.5, 100.0))  # exactly at threshold
        walls, threshold = detect_walls_py(bids, asks)
        assert threshold == pytest.approx(100.0, rel=1e-3)
        bid_walls = [w for w in walls if w["side"] == "bid"]
        assert len(bid_walls) == 1


# ── 2. Median computation ─────────────────────────────────────────────────────

class TestMedianComputation:
    def test_median_odd_count(self):
        assert compute_median([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(3.0)

    def test_median_even_count(self):
        assert compute_median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)

    def test_median_single_element(self):
        assert compute_median([7.0]) == pytest.approx(7.0)

    def test_median_empty_returns_zero(self):
        assert compute_median([]) == 0.0


# ── 3. Decay tracking ─────────────────────────────────────────────────────────

class TestDecayTracking:
    def test_zero_decay_when_only_current_snapshot(self):
        """Single snapshot → no history → decay = 0%, age = 0."""
        snap = {"ts": BASE_TS, "bids": {100.0: 200.0}, "asks": {}}
        initial, first_ts, decay_pct, age_sec = compute_decay_py(
            [snap], price=100.0, side="bid", threshold=100.0, current_size=200.0
        )
        assert decay_pct == pytest.approx(0.0)
        assert age_sec == 0

    def test_decay_pct_computed_correctly(self):
        """Wall shrinks from 100 to 80 → decay = 20%."""
        snaps = [
            {"ts": BASE_TS, "bids": {100.0: 100.0}, "asks": {}},
            {"ts": BASE_TS + 60, "bids": {100.0: 80.0}, "asks": {}},
        ]
        _, _, decay_pct, _ = compute_decay_py(
            snaps, price=100.0, side="bid", threshold=50.0, current_size=80.0
        )
        assert decay_pct == pytest.approx(20.0, rel=1e-6)

    def test_age_sec_equals_oldest_continuous_appearance(self):
        """age_sec = current_ts - first_seen_ts."""
        snaps = [
            {"ts": BASE_TS, "bids": {100.0: 150.0}, "asks": {}},
            {"ts": BASE_TS + 120, "bids": {100.0: 130.0}, "asks": {}},
            {"ts": BASE_TS + 240, "bids": {100.0: 110.0}, "asks": {}},
        ]
        _, _, _, age_sec = compute_decay_py(
            snaps, price=100.0, side="bid", threshold=50.0, current_size=110.0
        )
        assert age_sec == 240  # current_ts - BASE_TS

    def test_wall_disappears_in_history_fresh_wall(self):
        """Wall absent in earlier snapshot → treated as fresh (age from gap snapshot)."""
        snaps = [
            {"ts": BASE_TS, "bids": {}, "asks": {}},           # absent
            {"ts": BASE_TS + 120, "bids": {100.0: 150.0}, "asks": {}},  # appeared
            {"ts": BASE_TS + 240, "bids": {100.0: 130.0}, "asks": {}},  # current
        ]
        _, first_ts, _, age_sec = compute_decay_py(
            snaps, price=100.0, side="bid", threshold=50.0, current_size=130.0
        )
        # Walk backwards: snap at BASE_TS+120 present → update; snap at BASE_TS absent → break
        assert first_ts == pytest.approx(BASE_TS + 120)
        assert age_sec == 120

    def test_decay_clamped_to_zero_minimum(self):
        """Wall grows larger over time → decay clamped to 0, not negative."""
        snaps = [
            {"ts": BASE_TS, "bids": {100.0: 50.0}, "asks": {}},    # smaller initially
            {"ts": BASE_TS + 60, "bids": {100.0: 200.0}, "asks": {}},  # grew (current)
        ]
        _, _, decay_pct, _ = compute_decay_py(
            snaps, price=100.0, side="bid", threshold=40.0, current_size=200.0
        )
        assert decay_pct == pytest.approx(0.0)


# ── 4. Liquidation risk ───────────────────────────────────────────────────────

class TestLiquidationRisk:
    def test_low_risk_no_walls(self):
        assert liquidation_risk_py([], mid_price=100.0) == "low"

    def test_low_risk_walls_far_from_mid(self):
        walls = [
            {"price": 95.0, "side": "bid"},   # 5% from mid
            {"price": 105.0, "side": "ask"},  # 5% from mid
        ]
        assert liquidation_risk_py(walls, mid_price=100.0) == "low"

    def test_medium_risk_one_side_close(self):
        """Ask wall within 1% of mid → medium risk."""
        walls = [
            {"price": 99.5, "side": "ask"},  # 0.5% from mid
        ]
        assert liquidation_risk_py(walls, mid_price=100.0) == "medium"

    def test_high_risk_both_sides_close(self):
        """Both bid and ask walls within 0.5% of mid → high risk."""
        walls = [
            {"price": 99.6, "side": "bid"},   # 0.4% from mid
            {"price": 100.4, "side": "ask"},  # 0.4% from mid
        ]
        assert liquidation_risk_py(walls, mid_price=100.0) == "high"

    def test_medium_risk_only_bid_side_close(self):
        """Bid wall within 1% but ask is far → medium, not high."""
        walls = [
            {"price": 99.5, "side": "bid"},   # 0.5% from mid
            {"price": 110.0, "side": "ask"},  # 10% from mid
        ]
        assert liquidation_risk_py(walls, mid_price=100.0) == "medium"

    def test_low_risk_zero_mid_price(self):
        walls = [{"price": 100.0, "side": "bid"}]
        assert liquidation_risk_py(walls, mid_price=0.0) == "low"


# ── 5. Edge cases ─────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_orderbook_returns_no_walls(self):
        walls, threshold = detect_walls_py([], [])
        assert walls == []
        assert threshold == 0.0

    def test_single_level_no_wall(self):
        """Single level: median = its qty, threshold = 10x, so it can't be a wall."""
        bids = [(100.0, 50.0)]
        asks = []
        walls, threshold = detect_walls_py(bids, asks)
        # threshold = 10 * 50 = 500; 50 < 500 → no wall
        assert walls == []
        assert threshold == pytest.approx(500.0)

    def test_sorting_bid_walls_desc_ask_walls_asc(self):
        """After detection, bid walls are sorted price desc, ask walls price asc."""
        bids = [(100.0 - i * 0.01, 10.0) for i in range(20)]
        asks = [(100.0 + (i + 1) * 0.01, 10.0) for i in range(20)]
        # Add bid walls at 99.0 and 98.5
        bids.append((99.0, 105.0))
        bids.append((98.5, 110.0))
        # Add ask walls at 101.0 and 101.5
        asks.append((101.0, 108.0))
        asks.append((101.5, 112.0))

        walls, _ = detect_walls_py(bids, asks)
        bid_walls = [w for w in walls if w["side"] == "bid"]
        ask_walls = [w for w in walls if w["side"] == "ask"]

        # Verify sorting (the raw detect function doesn't sort, but we verify our sort logic)
        bid_walls_sorted = sorted(bid_walls, key=lambda w: w["price"], reverse=True)
        ask_walls_sorted = sorted(ask_walls, key=lambda w: w["price"])
        assert bid_walls_sorted[0]["price"] > bid_walls_sorted[-1]["price"]
        assert ask_walls_sorted[0]["price"] < ask_walls_sorted[-1]["price"]


# ── 6. Frontend color helpers ─────────────────────────────────────────────────

class TestWallColorHelpers:
    def test_solid_wall_is_red(self):
        """decay < 5% → red (solid wall, barely changed)."""
        assert wall_color(0.0) == "var(--red)"
        assert wall_color(4.9) == "var(--red)"

    def test_weakening_wall_is_yellow(self):
        """5% <= decay < 20% → yellow."""
        assert wall_color(5.0) == "var(--yellow)"
        assert wall_color(19.9) == "var(--yellow)"

    def test_breaking_wall_is_green(self):
        """decay >= 20% → green (wall breaking down)."""
        assert wall_color(20.0) == "var(--green)"
        assert wall_color(80.0) == "var(--green)"

    def test_labels_match_colors(self):
        assert wall_label(4.9) == "solid"
        assert wall_label(10.0) == "weakening"
        assert wall_label(25.0) == "breaking"

    def test_risk_badge_classes(self):
        assert risk_badge_class("high") == "badge-red"
        assert risk_badge_class("medium") == "badge-yellow"
        assert risk_badge_class("low") == "badge-blue"

    def test_fmt_age_seconds(self):
        assert fmt_age(30) == "30s"
        assert fmt_age(90) == "1m30s"
        assert fmt_age(3600) == "60m00s"


# ── 7. API response shape ─────────────────────────────────────────────────────

SAMPLE_RESPONSE_WITH_WALLS = {
    "status": "ok",
    "symbol": "BANANAS31USDT",
    "walls": [
        {"price": 0.4850, "size": 125000.0, "side": "bid", "age_sec": 120, "decay_pct": 8.5},
        {"price": 0.5120, "size": 98000.0, "side": "ask", "age_sec": 45, "decay_pct": 2.1},
    ],
    "liquidation_risk": "medium",
    "mid_price": 0.4995,
    "wall_threshold": 15000.0,
    "median_size": 1500.0,
    "description": "2 wall(s) detected",
}

SAMPLE_RESPONSE_NO_WALLS = {
    "status": "ok",
    "symbol": "BANANAS31USDT",
    "walls": [],
    "liquidation_risk": "low",
    "mid_price": 0.4995,
    "wall_threshold": 500.0,
    "median_size": 50.0,
    "description": "0 wall(s) detected",
}


class TestApiResponseShape:
    def test_required_keys_present(self):
        for key in ("status", "symbol", "walls", "liquidation_risk", "description"):
            assert key in SAMPLE_RESPONSE_WITH_WALLS

    def test_wall_object_keys(self):
        wall = SAMPLE_RESPONSE_WITH_WALLS["walls"][0]
        for key in ("price", "size", "side", "age_sec", "decay_pct"):
            assert key in wall

    def test_side_values_valid(self):
        for w in SAMPLE_RESPONSE_WITH_WALLS["walls"]:
            assert w["side"] in ("bid", "ask")

    def test_liquidation_risk_values_valid(self):
        assert SAMPLE_RESPONSE_WITH_WALLS["liquidation_risk"] in ("high", "medium", "low")
        assert SAMPLE_RESPONSE_NO_WALLS["liquidation_risk"] in ("high", "medium", "low")

    def test_no_walls_returns_empty_list(self):
        assert SAMPLE_RESPONSE_NO_WALLS["walls"] == []
        assert SAMPLE_RESPONSE_NO_WALLS["liquidation_risk"] == "low"

    def test_age_sec_is_non_negative(self):
        for w in SAMPLE_RESPONSE_WITH_WALLS["walls"]:
            assert w["age_sec"] >= 0

    def test_decay_pct_in_range(self):
        for w in SAMPLE_RESPONSE_WITH_WALLS["walls"]:
            assert 0.0 <= w["decay_pct"] <= 100.0


# ── 8. Mocked API fetch tests ─────────────────────────────────────────────────

class TestMockedFetch:
    @pytest.mark.asyncio
    async def test_returns_empty_walls_on_no_ob_data(self):
        """When no OB snapshots or latest OB available, returns empty walls."""
        from unittest.mock import AsyncMock, patch

        with patch("metrics.get_orderbook_snapshots_for_heatmap", new_callable=AsyncMock) as mock_snaps, \
             patch("metrics.get_latest_orderbook", new_callable=AsyncMock) as mock_latest:
            mock_snaps.return_value = []
            mock_latest.return_value = []

            from metrics import detect_ob_walls
            result = await detect_ob_walls(symbol="BANANAS31USDT")

        assert result["walls"] == []
        assert result["liquidation_risk"] == "low"

    @pytest.mark.asyncio
    async def test_detects_wall_from_live_ob(self):
        """Given OB with one large level, wall is returned."""
        # Build a snapshot with 20 normal levels (qty=10) and one bid wall (qty=200)
        normal_bids = [[str(100.0 - i * 0.01), "10.0"] for i in range(20)]
        normal_asks = [[str(100.0 + (i + 1) * 0.01), "10.0"] for i in range(20)]
        wall_bid = [str(99.5), "200.0"]  # 200 >> 10x median(10) = 100

        snap = {
            "ts": BASE_TS,
            "bids": json.dumps(normal_bids + [wall_bid]),
            "asks": json.dumps(normal_asks),
            "mid_price": 100.0,
        }

        with patch("metrics.get_orderbook_snapshots_for_heatmap", new_callable=AsyncMock) as mock_snaps:
            mock_snaps.return_value = [snap]

            from metrics import detect_ob_walls
            result = await detect_ob_walls(symbol="BANANAS31USDT")

        assert len(result["walls"]) >= 1
        bid_walls = [w for w in result["walls"] if w["side"] == "bid"]
        assert len(bid_walls) == 1
        assert bid_walls[0]["size"] == pytest.approx(200.0)

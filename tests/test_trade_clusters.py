"""
TDD tests for trade clustering detector.

Spec:
  - Detect when many trades happen at the same price level in a short window
  - "Same price level" = within price_tolerance % of the cluster center
  - "Short window" = window_seconds (sliding)
  - "Many trades" = at least min_trades within (window, price_tolerance)
  - Returns list of cluster dicts with ts_start, ts_end, price_level,
    trade_count, total_qty, total_usd, buy_count, sell_count, dominant_side
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import detect_trade_clusters  # noqa: E402


# ── Helper ───────────────────────────────────────────────────────────────────

def _trade(ts, price, qty=1.0, side="buy"):
    return {"ts": float(ts), "price": float(price), "qty": float(qty), "side": side}


# ── Basic structure ───────────────────────────────────────────────────────────

class TestDetectTradeClustersStructure:
    def test_empty_returns_empty(self):
        result = detect_trade_clusters([], window_seconds=30, price_tolerance=0.01, min_trades=3)
        assert result == []

    def test_too_few_trades_returns_empty(self):
        trades = [_trade(ts=i, price=100.0, qty=1.0) for i in range(4)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert result == []

    def test_enough_trades_returns_cluster(self):
        trades = [_trade(ts=i, price=100.0, qty=1.0) for i in range(5)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert len(result) >= 1

    def test_cluster_has_required_fields(self):
        trades = [_trade(ts=i, price=100.0, qty=1.0) for i in range(5)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        c = result[0]
        for field in ("ts_start", "ts_end", "price_level", "trade_count",
                      "total_qty", "total_usd", "buy_count", "sell_count", "dominant_side"):
            assert field in c, f"missing field: {field}"


# ── Time window enforcement ───────────────────────────────────────────────────

class TestTimeWindow:
    def test_trades_within_window_cluster(self):
        """5 trades within 30s window at same price → cluster."""
        trades = [_trade(ts=i * 5, price=100.0) for i in range(5)]  # 0,5,10,15,20s
        result = detect_trade_clusters(trades, window_seconds=30, price_tolerance=0.01, min_trades=5)
        assert len(result) >= 1

    def test_trades_spread_beyond_window_no_cluster(self):
        """5 trades spread over 200s with only 4 per any 30s window → no cluster."""
        # 4 trades at t=0,10,20,30 then next at t=100
        trades = [_trade(ts=i * 10, price=100.0) for i in range(3)]  # 0,10,20 → 3 in 30s
        result = detect_trade_clusters(trades, window_seconds=30, price_tolerance=0.01, min_trades=5)
        assert result == []

    def test_ts_start_and_end_span_window(self):
        trades = [_trade(ts=float(i * 5), price=100.0) for i in range(5)]
        result = detect_trade_clusters(trades, window_seconds=30, price_tolerance=0.01, min_trades=5)
        c = result[0]
        assert c["ts_start"] <= c["ts_end"]
        assert c["ts_end"] - c["ts_start"] <= 30.0 + 1e-9

    def test_cluster_ts_start_equals_first_trade_ts(self):
        trades = [_trade(ts=float(100 + i), price=100.0) for i in range(5)]
        result = detect_trade_clusters(trades, window_seconds=30, price_tolerance=0.01, min_trades=5)
        assert result[0]["ts_start"] == 100.0

    def test_cluster_ts_end_equals_last_trade_ts(self):
        trades = [_trade(ts=float(100 + i), price=100.0) for i in range(5)]
        result = detect_trade_clusters(trades, window_seconds=30, price_tolerance=0.01, min_trades=5)
        assert result[0]["ts_end"] == 104.0


# ── Price tolerance ───────────────────────────────────────────────────────────

class TestPriceTolerance:
    def test_prices_within_tolerance_grouped(self):
        """Prices within 0.05% of 100.0 → same cluster."""
        prices = [100.00, 100.01, 99.99, 100.02, 99.98]  # all within ~0.02%
        trades = [_trade(ts=i, price=p) for i, p in enumerate(prices)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.05, min_trades=5)
        assert len(result) >= 1

    def test_prices_far_apart_separate_clusters(self):
        """Prices 1% apart → separate clusters (neither reaches min_trades alone)."""
        trades = (
            [_trade(ts=i, price=100.0) for i in range(3)] +
            [_trade(ts=3 + i, price=101.5) for i in range(3)]
        )
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=4)
        assert result == []

    def test_price_tolerance_zero_requires_exact_match(self):
        """tolerance=0 → only exact same price groups."""
        trades = [
            _trade(ts=0, price=100.00),
            _trade(ts=1, price=100.00),
            _trade(ts=2, price=100.00),
            _trade(ts=3, price=100.01),  # different price
            _trade(ts=4, price=100.00),
        ]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.0, min_trades=4)
        assert len(result) >= 1
        for c in result:
            assert c["price_level"] == pytest.approx(100.00)

    def test_wider_tolerance_catches_more(self):
        """Wider tolerance merges what narrower splits."""
        trades = [
            _trade(ts=i, price=100.0 + (i * 0.05)) for i in range(5)
        ]  # prices: 100.0,100.05,100.1,100.15,100.2 → ~0.2% spread
        narrow = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        wide   = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.25, min_trades=5)
        assert len(wide) >= len(narrow)


# ── Aggregation fields ────────────────────────────────────────────────────────

class TestAggregation:
    def test_trade_count_correct(self):
        trades = [_trade(ts=i, price=100.0, qty=1.0) for i in range(7)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert result[0]["trade_count"] == 7

    def test_total_qty_correct(self):
        trades = [_trade(ts=i, price=100.0, qty=2.5) for i in range(5)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert result[0]["total_qty"] == pytest.approx(12.5)

    def test_total_usd_correct(self):
        trades = [_trade(ts=i, price=200.0, qty=3.0) for i in range(5)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert result[0]["total_usd"] == pytest.approx(3000.0)

    def test_total_usd_uses_each_trade_price(self):
        """USD = sum(price * qty) per trade, not avg_price * total_qty."""
        trades = [
            _trade(ts=0, price=100.0, qty=2.0),
            _trade(ts=1, price=100.5, qty=1.0),
            _trade(ts=2, price=99.5, qty=3.0),
            _trade(ts=3, price=100.0, qty=1.0),
            _trade(ts=4, price=100.0, qty=1.0),
        ]
        expected = 100.0*2 + 100.5*1 + 99.5*3 + 100.0*1 + 100.0*1
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=1.5, min_trades=5)
        assert result[0]["total_usd"] == pytest.approx(expected)

    def test_price_level_is_mean_of_cluster_prices(self):
        prices = [100.0, 100.1, 99.9, 100.05, 99.95]
        trades = [_trade(ts=i, price=p) for i, p in enumerate(prices)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.5, min_trades=5)
        expected = sum(prices) / len(prices)
        assert result[0]["price_level"] == pytest.approx(expected, rel=1e-4)


# ── Side tracking ─────────────────────────────────────────────────────────────

class TestSideTracking:
    def test_all_buys_dominant_side_buy(self):
        trades = [_trade(ts=i, price=100.0, side="buy") for i in range(5)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert result[0]["dominant_side"] == "buy"
        assert result[0]["buy_count"] == 5
        assert result[0]["sell_count"] == 0

    def test_all_sells_dominant_side_sell(self):
        trades = [_trade(ts=i, price=100.0, side="sell") for i in range(5)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert result[0]["dominant_side"] == "sell"
        assert result[0]["sell_count"] == 5
        assert result[0]["buy_count"] == 0

    def test_majority_buy_dominant_side_buy(self):
        trades = (
            [_trade(ts=i, price=100.0, side="buy") for i in range(4)] +
            [_trade(ts=4, price=100.0, side="sell")]
        )
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert result[0]["dominant_side"] == "buy"

    def test_majority_sell_dominant_side_sell(self):
        trades = (
            [_trade(ts=i, price=100.0, side="sell") for i in range(4)] +
            [_trade(ts=4, price=100.0, side="buy")]
        )
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert result[0]["dominant_side"] == "sell"

    def test_equal_buys_sells_dominant_side_mixed(self):
        trades = (
            [_trade(ts=i, price=100.0, side="buy") for i in range(3)] +
            [_trade(ts=3 + i, price=100.0, side="sell") for i in range(3)]
        )
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=6)
        assert result[0]["dominant_side"] == "mixed"


# ── Multiple clusters ─────────────────────────────────────────────────────────

class TestMultipleClusters:
    def test_two_separate_price_levels_two_clusters(self):
        """Two groups at different prices, both meeting min_trades → two clusters."""
        t1 = [_trade(ts=i, price=100.0) for i in range(5)]
        t2 = [_trade(ts=100 + i, price=200.0) for i in range(5)]
        result = detect_trade_clusters(t1 + t2, window_seconds=30, price_tolerance=0.01, min_trades=5)
        assert len(result) == 2

    def test_two_separate_time_windows_two_clusters(self):
        """Same price, but separated by > window_seconds → two distinct clusters."""
        t1 = [_trade(ts=float(i), price=100.0) for i in range(5)]
        t2 = [_trade(ts=float(200 + i), price=100.0) for i in range(5)]
        result = detect_trade_clusters(t1 + t2, window_seconds=30, price_tolerance=0.01, min_trades=5)
        ts_starts = {c["ts_start"] for c in result}
        assert len(ts_starts) == 2

    def test_clusters_ordered_by_ts_start(self):
        t1 = [_trade(ts=float(i), price=100.0) for i in range(5)]
        t2 = [_trade(ts=float(200 + i), price=100.0) for i in range(5)]
        result = detect_trade_clusters(t1 + t2, window_seconds=30, price_tolerance=0.01, min_trades=5)
        ts_starts = [c["ts_start"] for c in result]
        assert ts_starts == sorted(ts_starts)

    def test_no_duplicate_clusters_for_same_group(self):
        """10 trades in same window/price → exactly one cluster, not one per pair."""
        trades = [_trade(ts=float(i), price=100.0) for i in range(10)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert len(result) == 1

    def test_all_usd_values_non_negative(self):
        import random
        random.seed(7)
        trades = [
            _trade(ts=float(i * 2), price=100.0 + random.uniform(-0.05, 0.05), qty=random.uniform(0.1, 5.0))
            for i in range(20)
        ]
        result = detect_trade_clusters(trades, window_seconds=30, price_tolerance=0.1, min_trades=3)
        for c in result:
            assert c["total_usd"] >= 0
            assert c["total_qty"] >= 0
            assert c["buy_count"] >= 0
            assert c["sell_count"] >= 0


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_single_trade_no_cluster(self):
        result = detect_trade_clusters([_trade(0, 100.0)], window_seconds=60, price_tolerance=0.01, min_trades=2)
        assert result == []

    def test_exactly_min_trades_threshold(self):
        trades = [_trade(ts=i, price=100.0) for i in range(5)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert len(result) >= 1

    def test_one_below_min_trades_no_cluster(self):
        trades = [_trade(ts=i, price=100.0) for i in range(4)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=5)
        assert result == []

    def test_unsorted_input_same_result_as_sorted(self):
        import random
        base = [_trade(ts=float(i), price=100.0) for i in range(10)]
        shuffled = base.copy()
        random.seed(3)
        random.shuffle(shuffled)
        r1 = detect_trade_clusters(base, window_seconds=30, price_tolerance=0.01, min_trades=5)
        r2 = detect_trade_clusters(shuffled, window_seconds=30, price_tolerance=0.01, min_trades=5)
        assert len(r1) == len(r2)
        for c1, c2 in zip(r1, r2):
            assert c1["ts_start"] == c2["ts_start"]
            assert c1["trade_count"] == c2["trade_count"]

    def test_min_trades_one_every_trade_is_cluster(self):
        trades = [_trade(ts=i, price=100.0) for i in range(3)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=0.01, min_trades=1)
        assert len(result) >= 1

    def test_large_price_tolerance_groups_all(self):
        """With 100% tolerance everything is one cluster."""
        trades = [_trade(ts=i, price=float(100 + i * 10)) for i in range(5)]
        result = detect_trade_clusters(trades, window_seconds=60, price_tolerance=100.0, min_trades=5)
        assert len(result) >= 1
        assert result[0]["trade_count"] == 5

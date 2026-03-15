"""
TDD tests for liquidation magnitude heatmap.

Spec: x=time bucket, y=price bucket, color=total liquidation USD in zone.
Each cell: {ts_bucket, price_bucket, price_mid, total_usd, long_usd, short_usd, count}
"""
import sys
import os
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import compute_liq_heatmap  # noqa: E402


def _liq(ts, price, qty, side="sell", value=None):
    """Convenience constructor for a liquidation dict."""
    return {
        "ts": ts,
        "price": float(price),
        "qty": float(qty),
        "side": side,
        "value": value if value is not None else price * qty,
    }


# ── Basic structure ──────────────────────────────────────────────────────────

class TestLiqHeatmapStructure:
    def test_empty_returns_empty(self):
        result = compute_liq_heatmap([], time_bucket=300, price_bins=20)
        assert result["cells"] == []

    def test_single_liq_produces_one_cell(self):
        liqs = [_liq(ts=1000.0, price=100.0, qty=10.0, side="sell")]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=10)
        assert len(result["cells"]) == 1

    def test_cell_has_required_fields(self):
        liqs = [_liq(ts=1000.0, price=100.0, qty=5.0, side="buy")]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=10)
        cell = result["cells"][0]
        for field in ("ts_bucket", "price_bucket", "price_mid", "total_usd", "long_usd", "short_usd", "count"):
            assert field in cell, f"missing field: {field}"

    def test_result_has_meta_fields(self):
        liqs = [_liq(1000.0, 100.0, 1.0)]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=10)
        assert "price_min" in result
        assert "price_max" in result
        assert "price_step" in result
        assert "time_bucket" in result
        assert "cells" in result


# ── Time bucketing ───────────────────────────────────────────────────────────

class TestTimeBucketing:
    def test_two_liqs_same_bucket_aggregated(self):
        """Liquidations within the same time bucket → one cell."""
        liqs = [
            _liq(ts=1000.0, price=100.0, qty=5.0),
            _liq(ts=1050.0, price=100.0, qty=3.0),  # same 300s bucket
        ]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=10)
        assert len(result["cells"]) == 1
        assert result["cells"][0]["count"] == 2

    def test_two_liqs_different_buckets_separate_cells(self):
        """Liquidations in different time buckets → separate cells."""
        liqs = [
            _liq(ts=0.0,   price=100.0, qty=5.0),
            _liq(ts=400.0, price=100.0, qty=5.0),  # different 300s bucket
        ]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=10)
        ts_buckets = {c["ts_bucket"] for c in result["cells"]}
        assert len(ts_buckets) == 2

    def test_ts_bucket_aligns_to_bucket_boundary(self):
        """ts_bucket = floor(ts / time_bucket) * time_bucket."""
        liqs = [_liq(ts=350.0, price=100.0, qty=1.0)]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=10)
        assert result["cells"][0]["ts_bucket"] == 300  # floor(350/300)*300


# ── Price bucketing ──────────────────────────────────────────────────────────

class TestPriceBucketing:
    def test_two_liqs_same_price_same_bucket(self):
        """Same exact price → always same bucket regardless of bin count."""
        liqs = [
            _liq(ts=0.0, price=100.0, qty=5.0),
            _liq(ts=0.0, price=100.0, qty=3.0),  # identical price
        ]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=5)
        assert len(result["cells"]) == 1

    def test_two_liqs_different_price_different_bucket(self):
        liqs = [
            _liq(ts=0.0, price=100.0, qty=1.0),
            _liq(ts=0.0, price=200.0, qty=1.0),  # very different price
        ]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=10)
        price_buckets = {c["price_bucket"] for c in result["cells"]}
        assert len(price_buckets) == 2

    def test_price_mid_is_center_of_bucket(self):
        """price_mid should be between price_min and price_max."""
        liqs = [_liq(ts=0.0, price=100.0, qty=1.0)]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=10)
        cell = result["cells"][0]
        price_step = result["price_step"]
        price_min = result["price_min"]
        expected_mid = price_min + (cell["price_bucket"] + 0.5) * price_step
        assert abs(cell["price_mid"] - expected_mid) < 1e-6


# ── USD aggregation ──────────────────────────────────────────────────────────

class TestUsdAggregation:
    def test_total_usd_equals_price_times_qty(self):
        liqs = [_liq(ts=0.0, price=200.0, qty=3.0)]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=5)
        assert result["cells"][0]["total_usd"] == pytest.approx(600.0)

    def test_total_usd_sums_multiple_in_same_cell(self):
        liqs = [
            _liq(ts=0.0, price=100.0, qty=5.0),   # 500
            _liq(ts=10.0, price=100.0, qty=3.0),   # 300
        ]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=5)
        assert result["cells"][0]["total_usd"] == pytest.approx(800.0)

    def test_uses_value_field_when_present(self):
        """If 'value' field already computed, use it."""
        liqs = [{"ts": 0.0, "price": 100.0, "qty": 5.0, "side": "sell", "value": 550.0}]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=5)
        assert result["cells"][0]["total_usd"] == pytest.approx(550.0)


# ── Long/short separation ────────────────────────────────────────────────────

class TestLongShortSeparation:
    def test_sell_side_liquidation_is_long_liquidation(self):
        """side='sell' = forced position close of a long → long_usd."""
        liqs = [_liq(ts=0.0, price=100.0, qty=5.0, side="sell")]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=5)
        cell = result["cells"][0]
        assert cell["long_usd"] == pytest.approx(500.0)
        assert cell["short_usd"] == pytest.approx(0.0)

    def test_buy_side_liquidation_is_short_liquidation(self):
        """side='buy' = forced position close of a short → short_usd."""
        liqs = [_liq(ts=0.0, price=100.0, qty=5.0, side="buy")]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=5)
        cell = result["cells"][0]
        assert cell["short_usd"] == pytest.approx(500.0)
        assert cell["long_usd"] == pytest.approx(0.0)

    def test_mixed_sides_aggregated_separately(self):
        liqs = [
            _liq(ts=0.0, price=100.0, qty=5.0, side="sell"),  # long liq: 500
            _liq(ts=10.0, price=100.0, qty=3.0, side="buy"),  # short liq: 300
        ]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=5)
        cell = result["cells"][0]
        assert cell["long_usd"] == pytest.approx(500.0)
        assert cell["short_usd"] == pytest.approx(300.0)
        assert cell["total_usd"] == pytest.approx(800.0)

    def test_count_tracks_all_liqs_regardless_of_side(self):
        liqs = [
            _liq(ts=0.0, price=100.0, qty=1.0, side="sell"),
            _liq(ts=0.0, price=100.0, qty=1.0, side="buy"),
            _liq(ts=0.0, price=100.0, qty=1.0, side="sell"),
        ]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=5)
        assert result["cells"][0]["count"] == 3


# ── Multi-cell scenarios ─────────────────────────────────────────────────────

class TestMultiCellScenarios:
    def test_all_cells_non_negative_usd(self):
        import random
        random.seed(42)
        liqs = [
            _liq(ts=float(i * 60), price=100.0 + random.uniform(-5, 5), qty=random.uniform(1, 10))
            for i in range(20)
        ]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=10)
        for cell in result["cells"]:
            assert cell["total_usd"] >= 0
            assert cell["long_usd"] >= 0
            assert cell["short_usd"] >= 0

    def test_sum_of_cells_equals_total_liquidated(self):
        liqs = [
            _liq(ts=float(i * 60), price=100.0 + float(i % 5), qty=1.0)
            for i in range(10)
        ]
        total_usd = sum(l["price"] * l["qty"] for l in liqs)
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=10)
        cell_total = sum(c["total_usd"] for c in result["cells"])
        assert abs(cell_total - total_usd) < 1e-4

    def test_single_liq_per_different_time_price_combo(self):
        """Each liq in its own (time, price) cell."""
        liqs = [
            _liq(ts=0.0,    price=100.0, qty=1.0),
            _liq(ts=400.0,  price=200.0, qty=1.0),
        ]
        result = compute_liq_heatmap(liqs, time_bucket=300, price_bins=2)
        assert len(result["cells"]) == 2

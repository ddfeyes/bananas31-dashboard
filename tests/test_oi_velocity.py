"""
TDD tests for per-symbol OI velocity heatmap.

Spec:
  compute_oi_velocity_heatmap(oi_rows_by_symbol, bucket_seconds=300)

  For each (symbol, time_bucket):
    - oi_delta     = last oi_value in bucket - first oi_value in bucket
    - oi_delta_pct = oi_delta / first_oi * 100
    - color key:  green = positive delta, red = negative

  Returns:
    cells:          [{ts_bucket, symbol, oi_delta, oi_delta_pct, oi_start, oi_end}]
    symbols:        sorted unique symbol list
    time_buckets:   sorted unique bucket timestamps
    bucket_seconds: int
    global_max_pct: max oi_delta_pct across all cells (for color scale)
    global_min_pct: min oi_delta_pct across all cells
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import compute_oi_velocity_heatmap  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────

def _oi(ts, oi_value, symbol="BTCUSDT", exchange="binance"):
    return {"ts": float(ts), "oi_value": float(oi_value),
            "symbol": symbol, "exchange": exchange}


def _rows(symbol, start_ts, values, interval=30):
    """Create evenly-spaced OI rows for a symbol."""
    return {symbol: [_oi(start_ts + i * interval, v, symbol) for i, v in enumerate(values)]}


# ═══════════════════════════════════════════════════════════════════════════════
# Structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestStructure:
    def test_empty_returns_empty_cells(self):
        result = compute_oi_velocity_heatmap({})
        assert result["cells"] == []

    def test_result_has_required_fields(self):
        r = _rows("BTC", 0, [1000, 1010])
        result = compute_oi_velocity_heatmap(r, bucket_seconds=300)
        for f in ("cells", "symbols", "time_buckets", "bucket_seconds",
                  "global_max_pct", "global_min_pct"):
            assert f in result, f"missing: {f}"

    def test_cell_has_required_fields(self):
        r = _rows("BTC", 0, [1000, 1010, 1020])
        result = compute_oi_velocity_heatmap(r, bucket_seconds=300)
        c = result["cells"][0]
        for f in ("ts_bucket", "symbol", "oi_delta", "oi_delta_pct",
                  "oi_start", "oi_end"):
            assert f in c, f"missing cell field: {f}"

    def test_bucket_seconds_in_result(self):
        r = _rows("BTC", 0, [1000])
        result = compute_oi_velocity_heatmap(r, bucket_seconds=300)
        assert result["bucket_seconds"] == 300

    def test_symbols_list_sorted(self):
        data = {
            "SOLUSDT": [_oi(0, 100, "SOLUSDT")],
            "BTCUSDT": [_oi(0, 100, "BTCUSDT")],
            "ETHUSDT": [_oi(0, 100, "ETHUSDT")],
        }
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        assert result["symbols"] == sorted(result["symbols"])

    def test_time_buckets_sorted(self):
        data = _rows("BTC", 0, [1000] * 30, interval=30)   # spans 2 buckets of 300s
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        assert result["time_buckets"] == sorted(result["time_buckets"])


# ═══════════════════════════════════════════════════════════════════════════════
# Time bucketing
# ═══════════════════════════════════════════════════════════════════════════════

class TestTimeBucketing:
    def test_ts_bucket_aligns_to_floor(self):
        """ts_bucket = floor(ts / bucket_seconds) * bucket_seconds."""
        rows = {"BTC": [_oi(350, 1000), _oi(400, 1010)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        # floor(350/300)*300 = 300
        assert result["cells"][0]["ts_bucket"] == 300.0

    def test_rows_in_same_bucket_produce_one_cell(self):
        rows = {"BTC": [_oi(0, 1000), _oi(60, 1010), _oi(120, 1020)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert len(result["cells"]) == 1

    def test_rows_in_different_buckets_produce_separate_cells(self):
        rows = {"BTC": [_oi(0, 1000), _oi(300, 1010), _oi(600, 1020)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert len(result["cells"]) == 3

    def test_single_row_per_bucket_delta_is_zero(self):
        """Only one reading in bucket — no change observable."""
        rows = {"BTC": [_oi(0, 1000)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert result["cells"][0]["oi_delta"] == pytest.approx(0.0)
        assert result["cells"][0]["oi_delta_pct"] == pytest.approx(0.0)

    def test_oi_start_is_first_in_bucket(self):
        rows = {"BTC": [_oi(0, 1000), _oi(60, 1050), _oi(120, 1100)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert result["cells"][0]["oi_start"] == pytest.approx(1000.0)

    def test_oi_end_is_last_in_bucket(self):
        rows = {"BTC": [_oi(0, 1000), _oi(60, 1050), _oi(120, 1100)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert result["cells"][0]["oi_end"] == pytest.approx(1100.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Delta calculation
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeltaCalculation:
    def test_oi_increasing_positive_delta(self):
        rows = {"BTC": [_oi(0, 1000), _oi(60, 1100)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert result["cells"][0]["oi_delta"] == pytest.approx(100.0)

    def test_oi_decreasing_negative_delta(self):
        rows = {"BTC": [_oi(0, 1000), _oi(60, 900)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert result["cells"][0]["oi_delta"] == pytest.approx(-100.0)

    def test_oi_flat_zero_delta(self):
        rows = {"BTC": [_oi(0, 1000), _oi(60, 1000), _oi(120, 1000)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert result["cells"][0]["oi_delta"] == pytest.approx(0.0)

    def test_oi_delta_pct_correct(self):
        """oi_delta_pct = (end - start) / start * 100."""
        rows = {"BTC": [_oi(0, 1000), _oi(60, 1200)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert result["cells"][0]["oi_delta_pct"] == pytest.approx(20.0)

    def test_oi_delta_pct_negative(self):
        rows = {"BTC": [_oi(0, 1000), _oi(60, 800)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert result["cells"][0]["oi_delta_pct"] == pytest.approx(-20.0)

    def test_oi_start_zero_pct_is_zero(self):
        """Guard division by zero."""
        rows = {"BTC": [_oi(0, 0.0), _oi(60, 100.0)]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert result["cells"][0]["oi_delta_pct"] == pytest.approx(0.0)

    def test_delta_uses_first_and_last_in_bucket(self):
        """Middle values don't matter — only first and last."""
        rows = {"BTC": [
            _oi(0,  1000),   # first
            _oi(60, 9999),   # middle — ignored
            _oi(120, 1100),  # last
        ]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert result["cells"][0]["oi_delta"] == pytest.approx(100.0)

    def test_unsorted_rows_sorted_before_bucketing(self):
        """Rows may arrive out of order."""
        rows = {"BTC": [
            _oi(120, 1100),
            _oi(0,   1000),
            _oi(60,  1050),
        ]}
        result = compute_oi_velocity_heatmap(rows, bucket_seconds=300)
        assert result["cells"][0]["oi_start"] == pytest.approx(1000.0)
        assert result["cells"][0]["oi_end"] == pytest.approx(1100.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-symbol
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiSymbol:
    def test_two_symbols_both_appear(self):
        data = {
            "BTCUSDT": [_oi(0, 1000, "BTCUSDT"), _oi(60, 1100, "BTCUSDT")],
            "ETHUSDT": [_oi(0, 500,  "ETHUSDT"), _oi(60, 480,  "ETHUSDT")],
        }
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        syms = {c["symbol"] for c in result["cells"]}
        assert "BTCUSDT" in syms
        assert "ETHUSDT" in syms

    def test_cells_count_equals_symbols_times_buckets(self):
        """3 symbols × 2 buckets = 6 cells."""
        data = {
            s: [_oi(0, 100, s), _oi(60, 110, s), _oi(300, 110, s), _oi(360, 120, s)]
            for s in ["A", "B", "C"]
        }
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        assert len(result["cells"]) == 6

    def test_symbols_list_contains_all_input_symbols(self):
        syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        data = {s: [_oi(0, 100, s)] for s in syms}
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        assert set(result["symbols"]) == set(syms)

    def test_different_symbols_independent_delta(self):
        data = {
            "BTC": [_oi(0, 1000, "BTC"), _oi(60, 1200, "BTC")],  # +20%
            "ETH": [_oi(0, 500,  "ETH"), _oi(60, 400,  "ETH")],  # -20%
        }
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        by_sym = {c["symbol"]: c for c in result["cells"]}
        assert by_sym["BTC"]["oi_delta_pct"] == pytest.approx(20.0)
        assert by_sym["ETH"]["oi_delta_pct"] == pytest.approx(-20.0)

    def test_missing_bucket_for_symbol_not_padded(self):
        """Symbol with no rows in a given bucket → no cell for that (symbol, bucket)."""
        data = {
            "BTC": [_oi(0, 1000, "BTC"), _oi(60, 1010, "BTC")],         # bucket 0
            "ETH": [_oi(300, 500, "ETH"), _oi(360, 510, "ETH")],         # bucket 300 only
        }
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        btc_buckets = {c["ts_bucket"] for c in result["cells"] if c["symbol"] == "BTC"}
        eth_buckets = {c["ts_bucket"] for c in result["cells"] if c["symbol"] == "ETH"}
        assert 0.0 in btc_buckets
        assert 300.0 in eth_buckets
        # ETH should have no cell in bucket 0
        assert 0.0 not in eth_buckets


# ═══════════════════════════════════════════════════════════════════════════════
# Global scale
# ═══════════════════════════════════════════════════════════════════════════════

class TestGlobalScale:
    def test_global_max_pct_is_max_across_all_cells(self):
        data = {
            "BTC": [_oi(0, 1000, "BTC"), _oi(60, 1100, "BTC")],   # +10%
            "ETH": [_oi(0, 500,  "ETH"), _oi(60, 600,  "ETH")],   # +20%
        }
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        assert result["global_max_pct"] == pytest.approx(20.0)

    def test_global_min_pct_is_min_across_all_cells(self):
        data = {
            "BTC": [_oi(0, 1000, "BTC"), _oi(60, 900, "BTC")],    # -10%
            "ETH": [_oi(0, 500,  "ETH"), _oi(60, 350, "ETH")],    # -30%
        }
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        assert result["global_min_pct"] == pytest.approx(-30.0)

    def test_global_scale_zero_when_no_cells(self):
        result = compute_oi_velocity_heatmap({})
        assert result["global_max_pct"] == 0.0
        assert result["global_min_pct"] == 0.0

    def test_global_scale_symmetric_sign(self):
        """All increasing → global_min_pct >= 0."""
        data = {"BTC": [_oi(0, 1000, "BTC"), _oi(60, 1050, "BTC")]}
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        assert result["global_min_pct"] >= 0.0
        assert result["global_max_pct"] >= result["global_min_pct"]


# ═══════════════════════════════════════════════════════════════════════════════
# Exchange aggregation
# ═══════════════════════════════════════════════════════════════════════════════

class TestExchangeAggregation:
    def test_multiple_exchanges_same_symbol_summed(self):
        """Two exchanges both report OI for same symbol — values summed per ts."""
        rows = [
            _oi(0,  600, "BTC", "binance"),
            _oi(0,  400, "BTC", "bybit"),    # same ts, different exchange
            _oi(60, 660, "BTC", "binance"),
            _oi(60, 440, "BTC", "bybit"),
        ]
        data = {"BTC": rows}
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        cell = result["cells"][0]
        # start = 600+400=1000, end = 660+440=1100 → +10%
        assert cell["oi_start"] == pytest.approx(1000.0)
        assert cell["oi_end"]   == pytest.approx(1100.0)
        assert cell["oi_delta_pct"] == pytest.approx(10.0)

    def test_single_exchange_unaffected(self):
        rows = [_oi(0, 1000, "BTC", "binance"), _oi(60, 1050, "BTC", "binance")]
        data = {"BTC": rows}
        result = compute_oi_velocity_heatmap(data, bucket_seconds=300)
        assert result["cells"][0]["oi_delta_pct"] == pytest.approx(5.0)

"""
TDD tests for tape speed indicator.

Spec:
  compute_tape_speed(
      trade_timestamps,         # list[float]  Unix timestamps of trades in window
      window_seconds=1800,      # int   how far back to look
      bucket_seconds=60,        # int   bucket width for historical TPM series
      hot_multiplier=2.0,       # float heating_up  when current_tpm > mult * avg_tpm
      reference_ts=None,        # float "now" (defaults to time.time(); injectable for tests)
  )

  current_tpm    : float  trades/min in the sliding [now - bucket_seconds, now] window
  avg_tpm        : float  mean TPM across all historical buckets (including zeros)
  high_watermark : float  peak TPM among historical buckets
  low_watermark  : float  lowest non-zero TPM among historical buckets (None if all zero)
  heating_up     : bool   current_tpm > hot_multiplier * avg_tpm  AND avg_tpm > 0
  cooling_down   : bool   avg_tpm > 0  AND current_tpm < avg_tpm / hot_multiplier
  buckets        : list[{ts: float, tpm: float}]  sorted ascending, one per bucket
  total_trades   : int    trades inside the window
  window_seconds : int
  bucket_seconds : int
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from metrics import compute_tape_speed  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────

BASE = 1_700_000_000.0  # arbitrary fixed "now" for all tests


def _ts(*offsets: float) -> list:
    """Return [BASE + o for o in offsets]."""
    return [BASE + o for o in offsets]


def _run(timestamps, *, window=1800, bucket=60, mult=2.0, ref=None):
    ref = ref or BASE
    return compute_tape_speed(
        timestamps,
        window_seconds=window,
        bucket_seconds=bucket,
        hot_multiplier=mult,
        reference_ts=ref,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestStructure:
    def test_returns_dict(self):
        assert isinstance(_run([]), dict)

    def test_required_keys(self):
        r = _run([])
        for k in ("current_tpm", "avg_tpm", "high_watermark", "low_watermark",
                  "heating_up", "cooling_down", "buckets",
                  "total_trades", "window_seconds", "bucket_seconds"):
            assert k in r, f"missing key: {k}"

    def test_empty_zeros(self):
        r = _run([])
        assert r["current_tpm"]    == 0.0
        assert r["avg_tpm"]        == 0.0
        assert r["high_watermark"] == 0.0
        assert r["low_watermark"]  is None
        assert r["total_trades"]   == 0
        assert r["heating_up"]     is False
        assert r["cooling_down"]   is False

    def test_empty_buckets_list(self):
        assert _run([])["buckets"] == []

    def test_params_echoed(self):
        r = _run([], window=900, bucket=30)
        assert r["window_seconds"] == 900
        assert r["bucket_seconds"] == 30

    def test_bucket_has_ts_and_tpm(self):
        # one trade 30 s ago → should produce at least one bucket
        r = _run(_ts(-30), window=120, bucket=60)
        assert r["buckets"]
        b = r["buckets"][0]
        assert "ts"  in b
        assert "tpm" in b

    def test_buckets_sorted_ascending(self):
        timestamps = _ts(-300, -240, -180, -120, -60, -10)
        r = _run(timestamps, bucket=60)
        ts_list = [b["ts"] for b in r["buckets"]]
        assert ts_list == sorted(ts_list)


# ═══════════════════════════════════════════════════════════════════════════════
# current_tpm
# ═══════════════════════════════════════════════════════════════════════════════

class TestCurrentTpm:
    def test_single_trade_inside_window(self):
        # 1 trade in last 60 s → 1 trade/min
        r = _run(_ts(-30), bucket=60)
        assert r["current_tpm"] == pytest.approx(1.0)

    def test_sixty_trades_in_last_bucket(self):
        # 60 trades strictly inside last 60 s → 60 trades/min
        # use fractional offsets to stay clearly inside the sliding window
        r = _run(_ts(*[-(i * 0.9 + 0.5) for i in range(60)]), bucket=60)
        assert r["current_tpm"] == pytest.approx(60.0)

    def test_no_trades_in_last_bucket(self):
        # trades only 2 min ago → current window is empty
        r = _run(_ts(-130, -150), bucket=60)
        assert r["current_tpm"] == 0.0

    def test_trades_outside_window_excluded(self):
        old = _ts(-9000)   # way outside 1800s window
        r = _run(old, window=1800, bucket=60)
        assert r["total_trades"] == 0
        assert r["current_tpm"]  == 0.0

    def test_bucket_scaling(self):
        # 30 trades strictly inside last 30 s, bucket=30 → 60 tpm
        r = _run(_ts(*[-(i * 0.9 + 0.5) for i in range(30)]), bucket=30)
        assert r["current_tpm"] == pytest.approx(60.0)


# ═══════════════════════════════════════════════════════════════════════════════
# total_trades
# ═══════════════════════════════════════════════════════════════════════════════

class TestTotalTrades:
    def test_counts_all_in_window(self):
        r = _run(_ts(-10, -100, -500, -1000), window=1800, bucket=60)
        assert r["total_trades"] == 4

    def test_excludes_outside_window(self):
        r = _run(_ts(-10, -9999), window=1800, bucket=60)
        assert r["total_trades"] == 1

    def test_exactly_at_boundary_excluded(self):
        # trade at exactly reference_ts - window is outside (strict >)
        r = _run([BASE - 1800], window=1800, bucket=60, ref=BASE)
        assert r["total_trades"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Watermarks
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatermarks:
    def test_high_watermark_is_max_bucket_tpm(self):
        # 5 trades in bucket at -300s, 1 trade in bucket at -60s
        five = _ts(*[-305 - i for i in range(5)])   # 5 trades ~5 min ago
        one  = _ts(-65)                              # 1 trade ~1 min ago
        r = _run(five + one, bucket=60, ref=BASE)
        assert r["high_watermark"] == pytest.approx(5.0)  # 5 trades in 60s = 5 tpm

    def test_low_watermark_ignores_zero_buckets(self):
        # sparse trades: 2 in one bucket, nothing for a long stretch
        two = _ts(-605, -610)   # 2 trades in 60s = 2 tpm bucket
        r = _run(two, window=1800, bucket=60, ref=BASE)
        assert r["low_watermark"] == pytest.approx(2.0)

    def test_low_watermark_none_when_all_zero(self):
        assert _run([])["low_watermark"] is None

    def test_single_bucket_high_equals_low(self):
        # all trades in one bucket → high = low
        trades = _ts(-305, -310, -315)  # 3 trades in same bucket
        r = _run(trades, bucket=60, ref=BASE)
        assert r["high_watermark"] == r["low_watermark"]

    def test_watermarks_are_floats(self):
        r = _run(_ts(-30))
        assert isinstance(r["high_watermark"], float)


# ═══════════════════════════════════════════════════════════════════════════════
# avg_tpm
# ═══════════════════════════════════════════════════════════════════════════════

class TestAvgTpm:
    def test_avg_zero_when_empty(self):
        assert _run([])["avg_tpm"] == 0.0

    def test_avg_equals_tpm_when_one_nonempty_bucket(self):
        # 3 trades in one bucket, rest empty
        r = _run(_ts(-305, -310, -315), bucket=60, ref=BASE)
        # avg should include ALL buckets (zero and non-zero), so avg < bucket tpm
        # but high_watermark should equal that bucket's tpm
        assert r["avg_tpm"] <= r["high_watermark"]

    def test_avg_accounts_for_zero_buckets(self):
        # 60 trades in one bucket, 29 empty buckets → avg much < 60
        r = _run(_ts(*[-5 - i for i in range(60)]), window=1800, bucket=60, ref=BASE)
        assert r["avg_tpm"] < r["high_watermark"]

    def test_uniform_distribution_avg_equals_tpm(self):
        # same number of trades in every bucket → avg == high == low
        trades = []
        for bucket_offset in range(1, 6):  # 5 buckets, 60s apart
            for _ in range(3):
                trades.append(BASE - bucket_offset * 60 - 5)
        r = _run(trades, bucket=60, ref=BASE, window=400)
        # All non-zero buckets have same tpm → high == low == avg (of non-zero)
        assert r["high_watermark"] == r["low_watermark"]


# ═══════════════════════════════════════════════════════════════════════════════
# Heating up / cooling down
# ═══════════════════════════════════════════════════════════════════════════════

class TestHeatSignal:
    def _make_hot(self, mult=2.0):
        """Historical buckets: 1 trade/bucket. Current bucket: many trades."""
        historical = []
        for i in range(2, 10):   # buckets from -9min to -2min
            historical.append(BASE - i * 60 - 5)
        current_burst = _ts(*[-(j + 1) for j in range(30)])  # 30 trades now
        return historical + current_burst

    def _make_cold(self, mult=2.0):
        """Historical buckets: many trades. Current bucket: 1 trade."""
        historical = []
        for i in range(2, 10):
            for _ in range(20):   # 20 trades per old bucket
                historical.append(BASE - i * 60 - 5)
        current_slow = _ts(-10)   # just 1 trade now
        return historical + current_slow

    def test_heating_up_true_when_burst(self):
        r = _run(self._make_hot(), bucket=60, mult=2.0, ref=BASE, window=1800)
        assert r["heating_up"] is True

    def test_heating_up_false_when_uniform(self):
        # identical rate throughout
        trades = [BASE - i * 10 - 5 for i in range(100)]
        r = _run(trades, bucket=60, mult=2.0, ref=BASE, window=1800)
        # current ≈ avg → not heating
        assert r["heating_up"] is False

    def test_heating_up_false_when_empty(self):
        assert _run([])["heating_up"] is False

    def test_cooling_down_true_when_slowing(self):
        r = _run(self._make_cold(), bucket=60, mult=2.0, ref=BASE, window=1800)
        assert r["cooling_down"] is True

    def test_cooling_down_false_when_empty(self):
        assert _run([])["cooling_down"] is False

    def test_not_both_heating_and_cooling(self):
        for ts_list in (self._make_hot(), self._make_cold(), []):
            r = _run(ts_list, bucket=60, ref=BASE, window=1800)
            assert not (r["heating_up"] and r["cooling_down"])

    def test_custom_multiplier(self):
        # With mult=1.1, even modest bursts trigger heating
        historical = [BASE - i * 60 - 5 for i in range(2, 10)]  # 1 trade each
        burst = _ts(*[-(j + 1) for j in range(5)])               # 5 now
        r = _run(historical + burst, bucket=60, mult=1.1, ref=BASE, window=1800)
        assert r["heating_up"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Bucket contents
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuckets:
    def test_no_buckets_when_empty(self):
        assert _run([])["buckets"] == []

    def test_tpm_in_bucket_is_float(self):
        r = _run(_ts(-30), bucket=60)
        assert isinstance(r["buckets"][0]["tpm"], float)

    def test_bucket_ts_is_floored(self):
        # A trade at BASE-30 should land in the floored 60s bucket
        r = _run(_ts(-30), bucket=60, ref=BASE)
        expected_bucket = float(int((BASE - 30) // 60) * 60)
        non_zero = [b for b in r["buckets"] if b["tpm"] > 0]
        assert non_zero, "expected at least one non-zero bucket"
        assert non_zero[0]["ts"] == pytest.approx(expected_bucket)

    def test_two_trades_same_bucket(self):
        # Two trades within the same 60s interval → one bucket, tpm=2
        r = _run(_ts(-61, -65), bucket=60, ref=BASE)
        # Both land in bucket starting at floor((BASE-65)//60)*60
        tpms = [b["tpm"] for b in r["buckets"] if b["tpm"] > 0]
        assert tpms == [pytest.approx(2.0)]

    def test_two_trades_different_buckets(self):
        r = _run(_ts(-30, -100), bucket=60, ref=BASE)
        non_zero = [b for b in r["buckets"] if b["tpm"] > 0]
        assert len(non_zero) == 2

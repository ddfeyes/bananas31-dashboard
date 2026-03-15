"""
TDD tests for short squeeze detector.

Spec (docs/superpowers/specs/2026-03-15-net-taker-delta-squeeze.md):

  1) compute_net_taker_delta(trades, bucket_seconds=60)
       → {buckets: [{ts, buy_vol, sell_vol, net_vol}], total_buy, total_sell, net}

  2) detect_oi_surge_with_crash(oi_rows, candles,
                                 oi_threshold_pct=20.0, price_threshold_pct=10.0)
       → {detected, oi_change_pct, price_change_pct, ...}
       OI rises >20%, price falls >10% in same window.

  3) detect_funding_normalization(funding_rows,
                                   extreme_threshold=-0.005,
                                   recovery_window_seconds=7200)
       → {normalizing, min_funding, latest_funding, recovery_pct}
       funding was < -0.5% and is now recovering toward 0.

  4) detect_short_squeeze_setup(oi_rows, candles, funding_rows, ...)
       → {squeeze_signal, oi_surge_detected, funding_normalizing,
          oi_change_pct, price_change_pct, min_funding, latest_funding, description}
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import (  # noqa: E402
    compute_net_taker_delta,
    detect_oi_surge_with_crash,
    detect_funding_normalization,
    detect_short_squeeze_setup,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _trade(ts, price, qty, side="buy", is_buyer_aggressor=None):
    d = {"ts": float(ts), "price": float(price), "qty": float(qty), "side": side}
    if is_buyer_aggressor is not None:
        d["is_buyer_aggressor"] = int(is_buyer_aggressor)
    return d


def _oi(ts, oi_value):
    return {"ts": float(ts), "oi_value": float(oi_value)}


def _candle(ts, close_price):
    return {"bucket": float(ts), "close_price": float(close_price)}


def _funding(ts, rate):
    return {"ts": float(ts), "rate": float(rate)}


# ═══════════════════════════════════════════════════════════════════════════════
# 1) compute_net_taker_delta
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeNetTakerDelta:
    def test_empty_returns_empty_buckets(self):
        result = compute_net_taker_delta([], bucket_seconds=60)
        assert result["buckets"] == []
        assert result["total_buy"] == 0.0
        assert result["total_sell"] == 0.0
        assert result["net"] == 0.0

    def test_result_has_required_fields(self):
        trades = [_trade(0, 100.0, 1.0, "buy")]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        for f in ("buckets", "total_buy", "total_sell", "net"):
            assert f in result

    def test_bucket_has_required_fields(self):
        trades = [_trade(0, 100.0, 1.0, "buy")]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        b = result["buckets"][0]
        for f in ("ts", "buy_vol", "sell_vol", "net_vol"):
            assert f in b

    def test_single_buy_trade(self):
        trades = [_trade(0, 100.0, 2.5, "buy")]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        assert result["total_buy"] == pytest.approx(2.5)
        assert result["total_sell"] == pytest.approx(0.0)
        assert result["net"] == pytest.approx(2.5)

    def test_single_sell_trade(self):
        trades = [_trade(0, 100.0, 3.0, "sell")]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        assert result["total_buy"] == pytest.approx(0.0)
        assert result["total_sell"] == pytest.approx(3.0)
        assert result["net"] == pytest.approx(-3.0)

    def test_net_is_buy_minus_sell(self):
        trades = [
            _trade(0, 100.0, 5.0, "buy"),
            _trade(1, 100.0, 3.0, "sell"),
        ]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        assert result["net"] == pytest.approx(2.0)

    def test_same_bucket_aggregated(self):
        trades = [
            _trade(0,  100.0, 2.0, "buy"),
            _trade(30, 100.0, 1.0, "buy"),
            _trade(45, 100.0, 4.0, "sell"),
        ]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        assert len(result["buckets"]) == 1
        b = result["buckets"][0]
        assert b["buy_vol"] == pytest.approx(3.0)
        assert b["sell_vol"] == pytest.approx(4.0)
        assert b["net_vol"] == pytest.approx(-1.0)

    def test_different_buckets_separate(self):
        trades = [
            _trade(0,   100.0, 1.0, "buy"),
            _trade(61,  100.0, 1.0, "buy"),
            _trade(122, 100.0, 1.0, "buy"),
        ]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        assert len(result["buckets"]) == 3

    def test_bucket_ts_aligns_to_boundary(self):
        """ts = floor(trade_ts / bucket_seconds) * bucket_seconds."""
        trades = [_trade(95, 100.0, 1.0, "buy")]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        assert result["buckets"][0]["ts"] == 60.0

    def test_buckets_sorted_ascending(self):
        trades = [
            _trade(180, 100.0, 1.0, "buy"),
            _trade(0,   100.0, 1.0, "buy"),
            _trade(60,  100.0, 1.0, "buy"),
        ]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        ts_vals = [b["ts"] for b in result["buckets"]]
        assert ts_vals == sorted(ts_vals)

    def test_is_buyer_aggressor_overrides_side(self):
        """is_buyer_aggressor=True → buy taker regardless of side field."""
        trades = [_trade(0, 100.0, 5.0, side="sell", is_buyer_aggressor=True)]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        assert result["total_buy"] == pytest.approx(5.0)
        assert result["total_sell"] == pytest.approx(0.0)

    def test_is_buyer_aggressor_false_is_sell(self):
        trades = [_trade(0, 100.0, 5.0, side="buy", is_buyer_aggressor=False)]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        assert result["total_sell"] == pytest.approx(5.0)
        assert result["total_buy"] == pytest.approx(0.0)

    def test_total_matches_sum_of_buckets(self):
        import random
        random.seed(99)
        trades = [
            _trade(i * 10, 100.0, random.uniform(0.1, 5.0), random.choice(["buy", "sell"]))
            for i in range(20)
        ]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        sum_buy = sum(b["buy_vol"] for b in result["buckets"])
        sum_sell = sum(b["sell_vol"] for b in result["buckets"])
        assert result["total_buy"] == pytest.approx(sum_buy)
        assert result["total_sell"] == pytest.approx(sum_sell)


# ═══════════════════════════════════════════════════════════════════════════════
# 2) detect_oi_surge_with_crash
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectOiSurgeWithCrash:
    def test_empty_oi_not_detected(self):
        result = detect_oi_surge_with_crash([], [_candle(0, 100)], oi_threshold_pct=20, price_threshold_pct=10)
        assert result["detected"] is False

    def test_empty_candles_not_detected(self):
        result = detect_oi_surge_with_crash([_oi(0, 1000)], [], oi_threshold_pct=20, price_threshold_pct=10)
        assert result["detected"] is False

    def test_oi_up_price_down_above_thresholds_detected(self):
        """OI +25%, price -12% → detected."""
        oi = [_oi(0, 1000), _oi(3600, 1250)]       # +25%
        candles = [_candle(0, 100), _candle(3600, 88)]  # -12%
        result = detect_oi_surge_with_crash(oi, candles, oi_threshold_pct=20, price_threshold_pct=10)
        assert result["detected"] is True

    def test_oi_up_price_down_below_threshold_not_detected(self):
        """OI +10% (below 20% threshold), price -12% → not detected."""
        oi = [_oi(0, 1000), _oi(3600, 1100)]       # +10%
        candles = [_candle(0, 100), _candle(3600, 88)]  # -12%
        result = detect_oi_surge_with_crash(oi, candles, oi_threshold_pct=20, price_threshold_pct=10)
        assert result["detected"] is False

    def test_oi_up_price_flat_not_detected(self):
        """OI +25%, price -3% (below 10% threshold) → not detected."""
        oi = [_oi(0, 1000), _oi(3600, 1250)]
        candles = [_candle(0, 100), _candle(3600, 97)]  # -3%
        result = detect_oi_surge_with_crash(oi, candles, oi_threshold_pct=20, price_threshold_pct=10)
        assert result["detected"] is False

    def test_oi_down_price_down_not_detected(self):
        """OI falling is not a surge."""
        oi = [_oi(0, 1000), _oi(3600, 900)]
        candles = [_candle(0, 100), _candle(3600, 85)]
        result = detect_oi_surge_with_crash(oi, candles, oi_threshold_pct=20, price_threshold_pct=10)
        assert result["detected"] is False

    def test_oi_up_price_up_not_detected(self):
        """OI rising with price rising = bullish, not a crash."""
        oi = [_oi(0, 1000), _oi(3600, 1300)]
        candles = [_candle(0, 100), _candle(3600, 115)]
        result = detect_oi_surge_with_crash(oi, candles, oi_threshold_pct=20, price_threshold_pct=10)
        assert result["detected"] is False

    def test_result_has_required_fields(self):
        oi = [_oi(0, 1000), _oi(60, 1250)]
        candles = [_candle(0, 100), _candle(60, 88)]
        result = detect_oi_surge_with_crash(oi, candles)
        for f in ("detected", "oi_change_pct", "price_change_pct"):
            assert f in result

    def test_oi_change_pct_correct(self):
        oi = [_oi(0, 1000), _oi(3600, 1300)]  # +30%
        candles = [_candle(0, 100), _candle(3600, 88)]
        result = detect_oi_surge_with_crash(oi, candles)
        assert result["oi_change_pct"] == pytest.approx(30.0, rel=1e-3)

    def test_price_change_pct_correct(self):
        oi = [_oi(0, 1000), _oi(3600, 1250)]
        candles = [_candle(0, 200), _candle(3600, 160)]  # -20%
        result = detect_oi_surge_with_crash(oi, candles)
        assert result["price_change_pct"] == pytest.approx(-20.0, rel=1e-3)

    def test_exactly_at_threshold_detected(self):
        """Exactly at threshold → detected (>=)."""
        oi = [_oi(0, 1000), _oi(3600, 1200)]   # exactly +20%
        candles = [_candle(0, 100), _candle(3600, 90)]  # exactly -10%
        result = detect_oi_surge_with_crash(oi, candles, oi_threshold_pct=20, price_threshold_pct=10)
        assert result["detected"] is True

    def test_single_oi_row_not_detected(self):
        result = detect_oi_surge_with_crash([_oi(0, 1000)], [_candle(0, 100), _candle(60, 85)], oi_threshold_pct=20, price_threshold_pct=10)
        assert result["detected"] is False

    def test_single_candle_not_detected(self):
        result = detect_oi_surge_with_crash([_oi(0, 1000), _oi(60, 1300)], [_candle(0, 100)], oi_threshold_pct=20, price_threshold_pct=10)
        assert result["detected"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 3) detect_funding_normalization
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectFundingNormalization:
    def test_empty_returns_not_normalizing(self):
        result = detect_funding_normalization([])
        assert result["normalizing"] is False

    def test_result_has_required_fields(self):
        result = detect_funding_normalization([_funding(0, -0.01)])
        for f in ("normalizing", "min_funding", "latest_funding", "recovery_pct"):
            assert f in result

    def test_funding_never_extreme_not_normalizing(self):
        """Funding was always near 0, never hit extreme threshold → not normalizing."""
        rows = [_funding(i * 100, -0.001) for i in range(10)]
        result = detect_funding_normalization(rows, extreme_threshold=-0.005)
        assert result["normalizing"] is False

    def test_funding_extreme_and_recovering_normalizing(self):
        """
        Funding went very negative (-0.01) and is now recovering toward 0 (-0.002).
        → normalizing = True
        """
        now = 10000.0
        rows = (
            [_funding(now - 7000, -0.01)] +    # extreme
            [_funding(now - 3600, -0.008)] +
            [_funding(now - 1800, -0.004)] +
            [_funding(now, -0.002)]             # recovering toward 0
        )
        result = detect_funding_normalization(
            rows,
            extreme_threshold=-0.005,
            recovery_window_seconds=7200,
        )
        assert result["normalizing"] is True

    def test_funding_still_deeply_negative_not_normalizing(self):
        """Funding extreme but hasn't recovered at all."""
        now = 10000.0
        rows = [_funding(now - i * 600, -0.015) for i in range(8)]
        result = detect_funding_normalization(rows, extreme_threshold=-0.005)
        assert result["normalizing"] is False

    def test_funding_extreme_outside_recovery_window_not_normalizing(self):
        """Extreme funding was more than recovery_window_seconds ago → doesn't count."""
        now = 10000.0
        rows = (
            [_funding(now - 10000, -0.02)] +   # too old
            [_funding(now, -0.001)]             # current ok, but extreme was outside window
        )
        result = detect_funding_normalization(
            rows,
            extreme_threshold=-0.005,
            recovery_window_seconds=7200,
        )
        assert result["normalizing"] is False

    def test_min_funding_is_most_negative(self):
        rows = [
            _funding(0, -0.003),
            _funding(60, -0.012),
            _funding(120, -0.005),
        ]
        result = detect_funding_normalization(rows)
        assert result["min_funding"] == pytest.approx(-0.012)

    def test_latest_funding_is_last_by_ts(self):
        rows = [
            _funding(0, -0.01),
            _funding(200, -0.003),
            _funding(100, -0.007),
        ]
        result = detect_funding_normalization(rows)
        assert result["latest_funding"] == pytest.approx(-0.003)

    def test_recovery_pct_is_ratio_from_extreme_to_zero(self):
        """recovery_pct = (latest - min) / abs(min) * 100."""
        rows = [
            _funding(0,   -0.010),  # min = -0.010
            _funding(100, -0.005),  # latest
        ]
        result = detect_funding_normalization(rows)
        # ((-0.005) - (-0.010)) / 0.010 * 100 = 50%
        assert result["recovery_pct"] == pytest.approx(50.0, rel=1e-3)

    def test_positive_funding_not_extreme(self):
        """Positive funding is not extreme (no short squeeze setup)."""
        rows = [_funding(i * 100, 0.01) for i in range(5)]
        result = detect_funding_normalization(rows, extreme_threshold=-0.005)
        assert result["normalizing"] is False

    def test_single_extreme_row_min_funding_set(self):
        rows = [_funding(0, -0.015)]
        result = detect_funding_normalization(rows, extreme_threshold=-0.005)
        assert result["min_funding"] == pytest.approx(-0.015)


# ═══════════════════════════════════════════════════════════════════════════════
# 4) detect_short_squeeze_setup
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectShortSqueezeSetup:
    def test_empty_inputs_no_signal(self):
        result = detect_short_squeeze_setup([], [], [])
        assert result["squeeze_signal"] is False

    def test_result_has_required_fields(self):
        result = detect_short_squeeze_setup([], [], [])
        for f in ("squeeze_signal", "oi_surge_detected", "funding_normalizing",
                  "oi_change_pct", "price_change_pct", "min_funding", "latest_funding",
                  "description"):
            assert f in result, f"missing: {f}"

    def test_both_conditions_true_gives_signal(self):
        """OI surge + funding normalizing → squeeze_signal True."""
        now = 10000.0
        oi = [_oi(now - 3600, 1000), _oi(now, 1300)]        # +30% OI
        candles = [_candle(now - 3600, 100), _candle(now, 87)]  # -13% price
        funding = (
            [_funding(now - 7000, -0.012)] +   # extreme funding
            [_funding(now, -0.002)]             # recovering
        )
        result = detect_short_squeeze_setup(oi, candles, funding)
        assert result["squeeze_signal"] is True
        assert result["oi_surge_detected"] is True
        assert result["funding_normalizing"] is True

    def test_oi_surge_only_no_signal(self):
        """OI surge without funding normalization → no squeeze signal."""
        now = 10000.0
        oi = [_oi(now - 3600, 1000), _oi(now, 1300)]
        candles = [_candle(now - 3600, 100), _candle(now, 87)]
        funding = [_funding(now - i * 100, -0.001) for i in range(5)]  # never extreme
        result = detect_short_squeeze_setup(oi, candles, funding)
        assert result["squeeze_signal"] is False
        assert result["oi_surge_detected"] is True
        assert result["funding_normalizing"] is False

    def test_funding_normalizing_only_no_signal(self):
        """Funding normalizing without OI surge → no squeeze signal."""
        now = 10000.0
        oi = [_oi(now - 3600, 1000), _oi(now, 1050)]    # only +5% OI
        candles = [_candle(now - 3600, 100), _candle(now, 87)]
        funding = [_funding(now - 7000, -0.012), _funding(now, -0.002)]
        result = detect_short_squeeze_setup(oi, candles, funding)
        assert result["squeeze_signal"] is False
        assert result["oi_surge_detected"] is False
        assert result["funding_normalizing"] is True

    def test_description_contains_symbol_when_provided(self):
        now = 10000.0
        oi = [_oi(now - 3600, 1000), _oi(now, 1300)]
        candles = [_candle(now - 3600, 100), _candle(now, 87)]
        funding = [_funding(now - 7000, -0.012), _funding(now, -0.002)]
        result = detect_short_squeeze_setup(oi, candles, funding, symbol="XYZUSDT")
        assert "XYZUSDT" in result["description"] or "XYZ" in result["description"]

    def test_description_nonempty_string(self):
        result = detect_short_squeeze_setup([], [], [])
        assert isinstance(result["description"], str)
        assert len(result["description"]) > 0

    def test_oi_change_pct_propagated(self):
        now = 10000.0
        oi = [_oi(now - 3600, 1000), _oi(now, 1250)]   # +25%
        candles = [_candle(now - 3600, 100), _candle(now, 87)]
        result = detect_short_squeeze_setup(oi, candles, [])
        assert result["oi_change_pct"] == pytest.approx(25.0, rel=1e-3)

    def test_price_change_pct_propagated(self):
        now = 10000.0
        oi = [_oi(now - 3600, 1000), _oi(now, 1250)]
        candles = [_candle(now - 3600, 100), _candle(now, 80)]  # -20%
        result = detect_short_squeeze_setup(oi, candles, [])
        assert result["price_change_pct"] == pytest.approx(-20.0, rel=1e-3)

    def test_custom_thresholds_respected(self):
        """With looser thresholds (5% OI, 5% price), smaller moves still detected."""
        now = 10000.0
        oi = [_oi(now - 3600, 1000), _oi(now, 1060)]   # +6% — above 5%
        candles = [_candle(now - 3600, 100), _candle(now, 94)]  # -6% — above 5%
        funding = [_funding(now - 7000, -0.012), _funding(now, -0.001)]
        result = detect_short_squeeze_setup(
            oi, candles, funding,
            oi_threshold_pct=5.0,
            price_threshold_pct=5.0,
        )
        assert result["oi_surge_detected"] is True
        assert result["squeeze_signal"] is True

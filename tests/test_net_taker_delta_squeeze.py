"""
TDD tests for Net Taker Delta + Short Squeeze Detector.

Spec: docs/superpowers/specs/2026-03-15-net-taker-delta-squeeze.md

Pure functions under test:

compute_net_taker_delta(trades, bucket_seconds=60)
    - Buckets trades into time windows of bucket_seconds
    - For each bucket: buy_vol = qty of taker-buy trades, sell_vol = qty of taker-sell trades
    - net_delta = buy_vol - sell_vol
    - Side determined by: is_buyer_aggressor (if present) else "side" field
    - Returns:
        buckets:       [{ts, buy_vol, sell_vol, net_delta}]
        total_buy:     float
        total_sell:    float
        total_net:     float  (total_buy - total_sell)

detect_oi_surge_with_crash(
    oi_data,               # [{ts, oi_value}]
    price_data,            # [{ts, price}] or [{ts, close}]
    oi_threshold_pct=0.20, # OI must rise >= 20%
    price_drop_pct=0.10,   # price must fall >= 10%
)
    - Uses first vs last values in provided data arrays
    - oi_change_pct = (oi_last - oi_first) / oi_first
    - price_change_pct = (price_last - price_first) / price_first
    - oi_surge_with_crash = oi_change_pct >= oi_threshold_pct AND price_change_pct <= -price_drop_pct
    - Returns:
        oi_surge_with_crash:  bool
        oi_change_pct:        float
        price_change_pct:     float
        alert:                bool (same as oi_surge_with_crash)

detect_squeeze_setup(
    oi_data,               # [{ts, oi_value}]
    price_data,            # [{ts, price}] or [{ts, close}]
    funding_data,          # [{ts, rate}]
    oi_threshold_pct=0.20,
    price_drop_pct=0.10,
    funding_extreme=-0.005,   # -0.5% threshold for "extreme negative"
    funding_recovery=0.0,     # toward 0 counts as recovering
)
    - Calls detect_oi_surge_with_crash internally
    - Funding normalizing = earliest funding rate < funding_extreme AND latest > earliest AND latest > funding_recovery
    - squeeze_signal = oi_surge_with_crash AND funding_normalizing
    - Returns:
        squeeze_signal:       bool
        oi_surge_with_crash:  bool
        funding_normalizing:  bool
        funding_start:        float or None
        funding_end:          float or None
        description:          str
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import (  # noqa: E402
    compute_net_taker_delta,
    detect_oi_surge_with_crash,
    detect_squeeze_setup,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _trade(ts, price, qty, side="buy", is_buyer_aggressor=None):
    d = {"ts": float(ts), "price": float(price), "qty": float(qty), "side": side}
    if is_buyer_aggressor is not None:
        d["is_buyer_aggressor"] = int(is_buyer_aggressor)
    return d


def _buy(ts, qty=1.0, price=100.0):
    return _trade(ts, price, qty, side="buy")


def _sell(ts, qty=1.0, price=100.0):
    return _trade(ts, price, qty, side="sell")


def _oi(ts, value):
    return {"ts": float(ts), "oi_value": float(value)}


def _price(ts, p):
    return {"ts": float(ts), "price": float(p)}


def _funding(ts, rate):
    return {"ts": float(ts), "rate": float(rate)}


# ═══════════════════════════════════════════════════════════════════════════════
# compute_net_taker_delta — Structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestNetTakerDeltaStructure:
    def test_empty_returns_valid_dict(self):
        r = compute_net_taker_delta([])
        assert isinstance(r, dict)

    def test_result_has_required_fields(self):
        r = compute_net_taker_delta([])
        for f in ("buckets", "total_buy", "total_sell", "total_net"):
            assert f in r, f"missing field: {f}"

    def test_empty_gives_zero_totals(self):
        r = compute_net_taker_delta([])
        assert r["total_buy"] == 0.0
        assert r["total_sell"] == 0.0
        assert r["total_net"] == 0.0
        assert r["buckets"] == []

    def test_bucket_has_required_fields(self):
        r = compute_net_taker_delta([_buy(ts=0)])
        b = r["buckets"][0]
        for f in ("ts", "buy_vol", "sell_vol", "net_delta"):
            assert f in b, f"missing bucket field: {f}"


# ═══════════════════════════════════════════════════════════════════════════════
# compute_net_taker_delta — Bucketing
# ═══════════════════════════════════════════════════════════════════════════════

class TestNetTakerDeltaBucketing:
    def test_single_buy_trade_one_bucket(self):
        r = compute_net_taker_delta([_buy(ts=0, qty=5.0)], bucket_seconds=60)
        assert len(r["buckets"]) == 1

    def test_trades_in_same_minute_one_bucket(self):
        trades = [_buy(ts=0), _buy(ts=30), _sell(ts=59)]
        r = compute_net_taker_delta(trades, bucket_seconds=60)
        assert len(r["buckets"]) == 1

    def test_trades_in_different_minutes_two_buckets(self):
        trades = [_buy(ts=0), _buy(ts=60)]
        r = compute_net_taker_delta(trades, bucket_seconds=60)
        assert len(r["buckets"]) == 2

    def test_bucket_ts_is_start_of_window(self):
        r = compute_net_taker_delta([_buy(ts=45)], bucket_seconds=60)
        assert r["buckets"][0]["ts"] == 0.0

    def test_bucket_ts_for_second_minute(self):
        r = compute_net_taker_delta([_buy(ts=90)], bucket_seconds=60)
        assert r["buckets"][0]["ts"] == 60.0

    def test_buckets_sorted_by_ts(self):
        trades = [_buy(ts=120), _buy(ts=0), _buy(ts=60)]
        r = compute_net_taker_delta(trades, bucket_seconds=60)
        ts_vals = [b["ts"] for b in r["buckets"]]
        assert ts_vals == sorted(ts_vals)


# ═══════════════════════════════════════════════════════════════════════════════
# compute_net_taker_delta — Volume calculation
# ═══════════════════════════════════════════════════════════════════════════════

class TestNetTakerDeltaVolume:
    def test_buy_vol_sums_buy_trades(self):
        trades = [_buy(ts=0, qty=2.0), _buy(ts=10, qty=3.0)]
        r = compute_net_taker_delta(trades, bucket_seconds=60)
        assert r["buckets"][0]["buy_vol"] == pytest.approx(5.0)

    def test_sell_vol_sums_sell_trades(self):
        trades = [_sell(ts=0, qty=1.5), _sell(ts=10, qty=2.5)]
        r = compute_net_taker_delta(trades, bucket_seconds=60)
        assert r["buckets"][0]["sell_vol"] == pytest.approx(4.0)

    def test_net_delta_is_buy_minus_sell(self):
        trades = [_buy(ts=0, qty=5.0), _sell(ts=10, qty=3.0)]
        r = compute_net_taker_delta(trades, bucket_seconds=60)
        assert r["buckets"][0]["net_delta"] == pytest.approx(2.0)

    def test_net_delta_negative_when_sell_dominates(self):
        trades = [_buy(ts=0, qty=2.0), _sell(ts=10, qty=5.0)]
        r = compute_net_taker_delta(trades, bucket_seconds=60)
        assert r["buckets"][0]["net_delta"] == pytest.approx(-3.0)

    def test_total_buy_sums_across_buckets(self):
        trades = [_buy(ts=0, qty=2.0), _buy(ts=60, qty=3.0)]
        r = compute_net_taker_delta(trades, bucket_seconds=60)
        assert r["total_buy"] == pytest.approx(5.0)

    def test_total_sell_sums_across_buckets(self):
        trades = [_sell(ts=0, qty=1.0), _sell(ts=60, qty=2.0)]
        r = compute_net_taker_delta(trades, bucket_seconds=60)
        assert r["total_sell"] == pytest.approx(3.0)

    def test_total_net_equals_total_buy_minus_sell(self):
        trades = [_buy(ts=0, qty=5.0), _sell(ts=0, qty=3.0)]
        r = compute_net_taker_delta(trades, bucket_seconds=60)
        assert r["total_net"] == pytest.approx(r["total_buy"] - r["total_sell"])

    def test_total_net_positive_when_buys_dominate(self):
        trades = [_buy(ts=0, qty=10.0), _sell(ts=0, qty=4.0)]
        r = compute_net_taker_delta(trades, bucket_seconds=60)
        assert r["total_net"] == pytest.approx(6.0)


# ═══════════════════════════════════════════════════════════════════════════════
# compute_net_taker_delta — Side detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestNetTakerDeltaSide:
    def test_side_buy_counts_as_buy(self):
        r = compute_net_taker_delta([_trade(ts=0, price=100, qty=1.0, side="buy")])
        assert r["buckets"][0]["buy_vol"] == pytest.approx(1.0)
        assert r["buckets"][0]["sell_vol"] == pytest.approx(0.0)

    def test_side_sell_counts_as_sell(self):
        r = compute_net_taker_delta([_trade(ts=0, price=100, qty=1.0, side="sell")])
        assert r["buckets"][0]["sell_vol"] == pytest.approx(1.0)
        assert r["buckets"][0]["buy_vol"] == pytest.approx(0.0)

    def test_is_buyer_aggressor_true_counts_as_buy(self):
        t = _trade(ts=0, price=100, qty=2.0, side="sell", is_buyer_aggressor=True)
        r = compute_net_taker_delta([t])
        assert r["buckets"][0]["buy_vol"] == pytest.approx(2.0)
        assert r["buckets"][0]["sell_vol"] == pytest.approx(0.0)

    def test_is_buyer_aggressor_false_counts_as_sell(self):
        t = _trade(ts=0, price=100, qty=2.0, side="buy", is_buyer_aggressor=False)
        r = compute_net_taker_delta([t])
        assert r["buckets"][0]["sell_vol"] == pytest.approx(2.0)
        assert r["buckets"][0]["buy_vol"] == pytest.approx(0.0)

    def test_is_buyer_aggressor_overrides_side_field(self):
        """is_buyer_aggressor takes precedence over side field."""
        buy_as_sell = _trade(ts=0, price=100, qty=3.0, side="sell", is_buyer_aggressor=True)
        r = compute_net_taker_delta([buy_as_sell])
        assert r["total_buy"] == pytest.approx(3.0)
        assert r["total_sell"] == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# detect_oi_surge_with_crash — Structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestOiSurgeCrashStructure:
    def test_empty_returns_valid_dict(self):
        r = detect_oi_surge_with_crash([], [])
        assert isinstance(r, dict)

    def test_result_has_required_fields(self):
        r = detect_oi_surge_with_crash([], [])
        for f in ("oi_surge_with_crash", "oi_change_pct", "price_change_pct", "alert"):
            assert f in r, f"missing field: {f}"

    def test_empty_gives_no_surge(self):
        r = detect_oi_surge_with_crash([], [])
        assert r["oi_surge_with_crash"] is False
        assert r["alert"] is False

    def test_alert_matches_oi_surge_with_crash(self):
        oi = [_oi(0, 100), _oi(1, 130)]
        price = [_price(0, 100), _price(1, 85)]
        r = detect_oi_surge_with_crash(oi, price, oi_threshold_pct=0.20, price_drop_pct=0.10)
        assert r["alert"] == r["oi_surge_with_crash"]


# ═══════════════════════════════════════════════════════════════════════════════
# detect_oi_surge_with_crash — Detection logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestOiSurgeCrashDetection:
    def test_detects_oi_surge_and_price_crash(self):
        """OI +30%, price -15% → should fire."""
        oi = [_oi(0, 100), _oi(60, 130)]
        price = [_price(0, 100), _price(60, 85)]
        r = detect_oi_surge_with_crash(oi, price, oi_threshold_pct=0.20, price_drop_pct=0.10)
        assert r["oi_surge_with_crash"] is True

    def test_no_surge_when_oi_below_threshold(self):
        """OI +10% (below 20%), price -15% → no surge."""
        oi = [_oi(0, 100), _oi(60, 110)]
        price = [_price(0, 100), _price(60, 85)]
        r = detect_oi_surge_with_crash(oi, price, oi_threshold_pct=0.20, price_drop_pct=0.10)
        assert r["oi_surge_with_crash"] is False

    def test_no_surge_when_price_did_not_crash(self):
        """OI +30%, price only -5% (below 10%) → no surge."""
        oi = [_oi(0, 100), _oi(60, 130)]
        price = [_price(0, 100), _price(60, 95)]
        r = detect_oi_surge_with_crash(oi, price, oi_threshold_pct=0.20, price_drop_pct=0.10)
        assert r["oi_surge_with_crash"] is False

    def test_no_surge_when_price_rose(self):
        """OI +30%, price +5% → no surge."""
        oi = [_oi(0, 100), _oi(60, 130)]
        price = [_price(0, 100), _price(60, 105)]
        r = detect_oi_surge_with_crash(oi, price, oi_threshold_pct=0.20, price_drop_pct=0.10)
        assert r["oi_surge_with_crash"] is False

    def test_exactly_at_threshold_fires(self):
        """OI +20%, price -10% exactly at threshold → should fire."""
        oi = [_oi(0, 100), _oi(60, 120)]
        price = [_price(0, 100), _price(60, 90)]
        r = detect_oi_surge_with_crash(oi, price, oi_threshold_pct=0.20, price_drop_pct=0.10)
        assert r["oi_surge_with_crash"] is True

    def test_oi_change_pct_calculated_correctly(self):
        oi = [_oi(0, 100), _oi(60, 125)]
        price = [_price(0, 100), _price(60, 100)]
        r = detect_oi_surge_with_crash(oi, price)
        assert r["oi_change_pct"] == pytest.approx(0.25)

    def test_price_change_pct_calculated_correctly(self):
        oi = [_oi(0, 100), _oi(60, 100)]
        price = [_price(0, 200), _price(60, 180)]
        r = detect_oi_surge_with_crash(oi, price)
        assert r["price_change_pct"] == pytest.approx(-0.10)

    def test_uses_first_and_last_values(self):
        """oi_change_pct uses first vs last, not min/max."""
        oi = [_oi(0, 100), _oi(30, 50), _oi(60, 130)]  # dip in middle
        price = [_price(0, 100), _price(30, 110), _price(60, 85)]
        r = detect_oi_surge_with_crash(oi, price, oi_threshold_pct=0.20, price_drop_pct=0.10)
        assert r["oi_change_pct"] == pytest.approx(0.30)
        assert r["price_change_pct"] == pytest.approx(-0.15)
        assert r["oi_surge_with_crash"] is True

    def test_supports_close_key_for_price(self):
        """price_data can use 'close' instead of 'price'."""
        oi = [_oi(0, 100), _oi(60, 130)]
        price = [{"ts": 0.0, "close": 100.0}, {"ts": 60.0, "close": 85.0}]
        r = detect_oi_surge_with_crash(oi, price, oi_threshold_pct=0.20, price_drop_pct=0.10)
        assert r["oi_surge_with_crash"] is True

    def test_single_oi_data_point_no_surge(self):
        """Single data point means no change → no surge."""
        r = detect_oi_surge_with_crash([_oi(0, 100)], [_price(0, 100)])
        assert r["oi_surge_with_crash"] is False

    def test_oi_decreased_no_surge(self):
        """OI fell → no surge."""
        oi = [_oi(0, 100), _oi(60, 70)]
        price = [_price(0, 100), _price(60, 80)]
        r = detect_oi_surge_with_crash(oi, price, oi_threshold_pct=0.20, price_drop_pct=0.10)
        assert r["oi_surge_with_crash"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# detect_squeeze_setup — Structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestSqueezeSetupStructure:
    def test_empty_returns_valid_dict(self):
        r = detect_squeeze_setup([], [], [])
        assert isinstance(r, dict)

    def test_result_has_required_fields(self):
        r = detect_squeeze_setup([], [], [])
        for f in ("squeeze_signal", "oi_surge_with_crash", "funding_normalizing",
                  "funding_start", "funding_end", "description"):
            assert f in r, f"missing field: {f}"

    def test_empty_gives_no_signal(self):
        r = detect_squeeze_setup([], [], [])
        assert r["squeeze_signal"] is False
        assert r["oi_surge_with_crash"] is False
        assert r["funding_normalizing"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# detect_squeeze_setup — Funding normalization
# ═══════════════════════════════════════════════════════════════════════════════

class TestSqueezeSetupFundingNormalization:
    def test_funding_normalizing_when_from_extreme_toward_zero(self):
        """funding starts < -0.5%, ends > start and > recovery threshold."""
        funding = [_funding(0, -0.008), _funding(60, -0.003)]
        r = detect_squeeze_setup([], [], funding, funding_extreme=-0.005, funding_recovery=0.0)
        assert r["funding_normalizing"] is True

    def test_not_normalizing_when_funding_stable_extreme(self):
        """funding stays at -1% → not normalizing."""
        funding = [_funding(0, -0.010), _funding(60, -0.010)]
        r = detect_squeeze_setup([], [], funding, funding_extreme=-0.005, funding_recovery=0.0)
        assert r["funding_normalizing"] is False

    def test_not_normalizing_when_start_not_extreme(self):
        """funding starts at -0.2% (not extreme) → not normalizing."""
        funding = [_funding(0, -0.002), _funding(60, 0.001)]
        r = detect_squeeze_setup([], [], funding, funding_extreme=-0.005, funding_recovery=0.0)
        assert r["funding_normalizing"] is False

    def test_not_normalizing_when_funding_worsening(self):
        """funding goes from -0.8% to -1.2% → not normalizing."""
        funding = [_funding(0, -0.008), _funding(60, -0.012)]
        r = detect_squeeze_setup([], [], funding, funding_extreme=-0.005, funding_recovery=0.0)
        assert r["funding_normalizing"] is False

    def test_funding_start_is_earliest_value(self):
        funding = [_funding(30, -0.007), _funding(0, -0.009), _funding(60, -0.003)]
        r = detect_squeeze_setup([], [], funding, funding_extreme=-0.005)
        assert r["funding_start"] == pytest.approx(-0.009)

    def test_funding_end_is_latest_value(self):
        funding = [_funding(0, -0.009), _funding(30, -0.007), _funding(60, -0.003)]
        r = detect_squeeze_setup([], [], funding, funding_extreme=-0.005)
        assert r["funding_end"] == pytest.approx(-0.003)

    def test_funding_none_when_no_data(self):
        r = detect_squeeze_setup([], [], [])
        assert r["funding_start"] is None
        assert r["funding_end"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# detect_squeeze_setup — Combined signal
# ═══════════════════════════════════════════════════════════════════════════════

class TestSqueezeSetupCombinedSignal:
    def test_squeeze_signal_requires_both_conditions(self):
        """squeeze_signal = oi_surge_with_crash AND funding_normalizing."""
        oi = [_oi(0, 100), _oi(60, 130)]
        price = [_price(0, 100), _price(60, 85)]
        funding = [_funding(0, -0.008), _funding(60, -0.002)]
        r = detect_squeeze_setup(
            oi, price, funding,
            oi_threshold_pct=0.20, price_drop_pct=0.10,
            funding_extreme=-0.005, funding_recovery=0.0,
        )
        assert r["oi_surge_with_crash"] is True
        assert r["funding_normalizing"] is True
        assert r["squeeze_signal"] is True

    def test_no_squeeze_without_oi_surge(self):
        """OI did not surge → no signal even if funding normalizes."""
        oi = [_oi(0, 100), _oi(60, 105)]   # only +5%
        price = [_price(0, 100), _price(60, 85)]
        funding = [_funding(0, -0.008), _funding(60, -0.002)]
        r = detect_squeeze_setup(
            oi, price, funding,
            oi_threshold_pct=0.20, price_drop_pct=0.10,
            funding_extreme=-0.005,
        )
        assert r["oi_surge_with_crash"] is False
        assert r["squeeze_signal"] is False

    def test_no_squeeze_without_funding_normalization(self):
        """OI surged + crash but funding not normalizing → no signal."""
        oi = [_oi(0, 100), _oi(60, 130)]
        price = [_price(0, 100), _price(60, 85)]
        funding = [_funding(0, -0.008), _funding(60, -0.010)]  # getting worse
        r = detect_squeeze_setup(
            oi, price, funding,
            oi_threshold_pct=0.20, price_drop_pct=0.10,
            funding_extreme=-0.005,
        )
        assert r["funding_normalizing"] is False
        assert r["squeeze_signal"] is False

    def test_description_mentions_squeeze_when_signal(self):
        """description should contain 'squeeze' when signal fires."""
        oi = [_oi(0, 100), _oi(60, 130)]
        price = [_price(0, 100), _price(60, 85)]
        funding = [_funding(0, -0.008), _funding(60, -0.002)]
        r = detect_squeeze_setup(oi, price, funding, oi_threshold_pct=0.20, price_drop_pct=0.10)
        assert "squeeze" in r["description"].lower()

    def test_description_non_empty_always(self):
        r = detect_squeeze_setup([], [], [])
        assert isinstance(r["description"], str)
        assert len(r["description"]) > 0

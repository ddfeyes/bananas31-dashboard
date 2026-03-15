"""
TDD tests for volume clock chart (volume bars).

Spec:
  compute_volume_bars(trades, volume_threshold=1.0)

  trades: [{ts, price, qty, side, [is_buyer_aggressor]}]  — may be unsorted

  Each bar accumulates trades until sum(qty) >= volume_threshold, then closes.
  The trade that crosses the threshold is the last trade of that bar.

  Closed bar fields:
    ts_start     float  — ts of first trade in bar
    ts_end       float  — ts of last trade in bar
    open         float  — price of first trade
    high         float  — max price in bar
    low          float  — min price in bar
    close        float  — price of last trade
    volume       float  — total qty in bar  (>= volume_threshold)
    buy_volume   float  — qty of buy-side trades
    sell_volume  float  — qty of sell-side trades
    trade_count  int    — number of trades
    vwap         float  — sum(price*qty) / sum(qty)

  Returns:
    bars:                  list of closed bar dicts (sorted asc by ts_start)
    current_volume:        accumulated qty in open bar  (< volume_threshold)
    current_trade_count:   trades in open bar
    volume_threshold:      float (echoed)
    bar_count:             len(bars)
    pct_to_close:          current_volume / volume_threshold * 100
"""
import sys, os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from metrics import compute_volume_bars  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────────

def _t(ts, price, qty=0.5, side="buy"):
    return {"ts": float(ts), "price": float(price), "qty": float(qty), "side": side}

def _buy(ts, price=100.0, qty=0.5):
    return _t(ts, price, qty, "buy")

def _sell(ts, price=100.0, qty=0.5):
    return _t(ts, price, qty, "sell")

def _fill(n, price=100.0, qty=0.5, start_ts=0, side="buy"):
    """n identical trades."""
    return [_t(start_ts + i, price, qty, side) for i in range(n)]


# ═══════════════════════════════════════════════════════════════════════════════
# Structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestStructure:
    def test_empty_returns_valid_dict(self):
        r = compute_volume_bars([], volume_threshold=1.0)
        assert isinstance(r, dict)

    def test_result_has_required_fields(self):
        r = compute_volume_bars([], volume_threshold=1.0)
        for f in ("bars", "current_volume", "current_trade_count",
                  "volume_threshold", "bar_count", "pct_to_close"):
            assert f in r, f"missing: {f}"

    def test_empty_gives_zero_state(self):
        r = compute_volume_bars([], volume_threshold=1.0)
        assert r["bars"] == []
        assert r["bar_count"] == 0
        assert r["current_volume"] == pytest.approx(0.0)
        assert r["current_trade_count"] == 0
        assert r["pct_to_close"] == pytest.approx(0.0)

    def test_bar_has_required_fields(self):
        trades = _fill(3, qty=0.5)   # 3 × 0.5 = 1.5 >= threshold=1.0 → 1 bar
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bar_count"] >= 1
        b = r["bars"][0]
        for f in ("ts_start", "ts_end", "open", "high", "low", "close",
                  "volume", "buy_volume", "sell_volume", "trade_count", "vwap"):
            assert f in b, f"missing bar field: {f}"

    def test_volume_threshold_echoed(self):
        r = compute_volume_bars([], volume_threshold=2.5)
        assert r["volume_threshold"] == pytest.approx(2.5)

    def test_bar_count_equals_len_bars(self):
        trades = _fill(10, qty=0.5)
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bar_count"] == len(r["bars"])


# ═══════════════════════════════════════════════════════════════════════════════
# Bar closing logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestBarClosing:
    def test_no_bar_before_threshold(self):
        trades = [_buy(0, qty=0.4), _buy(1, qty=0.4)]   # total 0.8 < 1.0
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bar_count"] == 0

    def test_bar_closes_exactly_at_threshold(self):
        """Two trades of 0.5 each → 1.0 >= threshold → one bar."""
        trades = [_buy(0, qty=0.5), _buy(1, qty=0.5)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bar_count"] == 1

    def test_bar_volume_gte_threshold(self):
        """Bar that crosses threshold with overshoot: 0.5 < 1.0, then 0.5+0.8=1.3 >= 1.0."""
        trades = [_buy(0, qty=0.5), _buy(1, qty=0.8)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bar_count"] == 1
        assert r["bars"][0]["volume"] == pytest.approx(1.3)

    def test_residual_stays_in_new_bar(self):
        """After bar 1 closes, remaining volume starts fresh in bar 2 (no carry)."""
        # 3 trades × 0.5 = 1.5: bar closes after trade 2 (1.0), trade 3 starts new bar
        trades = _fill(3, qty=0.5)   # vol 0.5, 1.0, 1.5
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bar_count"] == 1
        assert r["current_volume"] == pytest.approx(0.5)
        assert r["current_trade_count"] == 1

    def test_two_bars_from_sufficient_volume(self):
        """5 trades × 0.5 = 2.5: two bars of threshold=1.0."""
        trades = _fill(5, qty=0.5)
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bar_count"] == 2
        assert r["current_volume"] == pytest.approx(0.5)

    def test_single_large_trade_closes_bar(self):
        """One trade with qty > threshold → closes bar immediately."""
        trades = [_buy(0, qty=5.0)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bar_count"] == 1
        assert r["bars"][0]["volume"] == pytest.approx(5.0)

    def test_unsorted_input_sorted_before_processing(self):
        trades = [_buy(2, qty=0.5), _buy(0, qty=0.5), _buy(1, qty=0.5)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bar_count"] == 1
        assert r["bars"][0]["ts_start"] == pytest.approx(0.0)
        assert r["bars"][0]["ts_end"] == pytest.approx(1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# OHLC + metadata
# ═══════════════════════════════════════════════════════════════════════════════

class TestOHLC:
    def test_open_is_first_trade_price(self):
        trades = [_buy(0, price=100.0, qty=0.5), _buy(1, price=105.0, qty=0.5)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][0]["open"] == pytest.approx(100.0)

    def test_close_is_last_trade_price(self):
        trades = [_buy(0, price=100.0, qty=0.5), _buy(1, price=105.0, qty=0.5)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][0]["close"] == pytest.approx(105.0)

    def test_high_is_max_price(self):
        trades = [_buy(0, price=100.0, qty=0.5), _buy(1, price=108.0, qty=0.3),
                  _buy(2, price=103.0, qty=0.5)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][0]["high"] == pytest.approx(108.0)

    def test_low_is_min_price(self):
        trades = [_buy(0, price=100.0, qty=0.5), _buy(1, price=95.0, qty=0.3),
                  _buy(2, price=103.0, qty=0.5)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][0]["low"] == pytest.approx(95.0)

    def test_ts_start_first_ts(self):
        trades = [_buy(10, qty=0.5), _buy(20, qty=0.5)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][0]["ts_start"] == pytest.approx(10.0)

    def test_ts_end_last_ts_in_bar(self):
        trades = [_buy(10, qty=0.5), _buy(20, qty=0.5), _buy(30, qty=0.5)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        # bar closes after trade 2 (ts=20)
        assert r["bars"][0]["ts_end"] == pytest.approx(20.0)

    def test_trade_count_correct(self):
        trades = [_buy(i, qty=0.25) for i in range(8)]  # 8×0.25=2.0: 2 bars
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][0]["trade_count"] == 4
        assert r["bars"][1]["trade_count"] == 4

    def test_single_trade_bar_ohlc_all_same(self):
        """Single huge trade: open=high=low=close."""
        trades = [_buy(5, price=200.0, qty=10.0)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        b = r["bars"][0]
        assert b["open"] == pytest.approx(200.0)
        assert b["high"] == pytest.approx(200.0)
        assert b["low"]  == pytest.approx(200.0)
        assert b["close"] == pytest.approx(200.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Volume split and VWAP
# ═══════════════════════════════════════════════════════════════════════════════

class TestVolumeAndVwap:
    def test_volume_is_sum_of_qty(self):
        trades = [_buy(0, qty=0.3), _buy(1, qty=0.7)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][0]["volume"] == pytest.approx(1.0)

    def test_buy_volume_is_sum_of_buy_side(self):
        trades = [_buy(0, qty=0.6), _sell(1, qty=0.6)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][0]["buy_volume"]  == pytest.approx(0.6)
        assert r["bars"][0]["sell_volume"] == pytest.approx(0.6)

    def test_sell_volume_correct(self):
        trades = [_sell(0, qty=0.4), _sell(1, qty=0.4), _sell(2, qty=0.4)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][0]["sell_volume"] == pytest.approx(1.2)
        assert r["bars"][0]["buy_volume"]  == pytest.approx(0.0)

    def test_is_buyer_aggressor_determines_side(self):
        """is_buyer_aggressor=True → buy_volume, False → sell_volume."""
        t1 = {"ts": 0.0, "price": 100.0, "qty": 0.6, "side": "sell", "is_buyer_aggressor": 1}
        t2 = {"ts": 1.0, "price": 100.0, "qty": 0.6, "side": "buy",  "is_buyer_aggressor": 0}
        r = compute_volume_bars([t1, t2], volume_threshold=1.0)
        assert r["bars"][0]["buy_volume"]  == pytest.approx(0.6)
        assert r["bars"][0]["sell_volume"] == pytest.approx(0.6)

    def test_vwap_formula(self):
        """vwap = sum(price*qty) / sum(qty)."""
        # price=100, qty=0.5: pv=50
        # price=120, qty=0.5: pv=60
        # vwap = (50+60)/1.0 = 110
        trades = [_buy(0, price=100.0, qty=0.5), _buy(1, price=120.0, qty=0.5)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][0]["vwap"] == pytest.approx(110.0)

    def test_vwap_weighted_by_qty(self):
        """Larger trade has more weight in vwap."""
        # price=100 qty=0.2, price=200 qty=0.8
        # vwap = (100*0.2 + 200*0.8) / 1.0 = (20+160)/1.0 = 180
        trades = [_buy(0, price=100.0, qty=0.2), _buy(1, price=200.0, qty=0.8)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][0]["vwap"] == pytest.approx(180.0)

    def test_buy_sell_volume_sum_equals_total_volume(self):
        trades = [_buy(0, qty=0.3), _sell(1, qty=0.4), _buy(2, qty=0.5)]
        r = compute_volume_bars(trades, volume_threshold=1.0)
        b = r["bars"][0]
        assert b["buy_volume"] + b["sell_volume"] == pytest.approx(b["volume"])


# ═══════════════════════════════════════════════════════════════════════════════
# Current (open) bar state
# ═══════════════════════════════════════════════════════════════════════════════

class TestCurrentState:
    def test_current_volume_accumulates(self):
        trades = [_buy(0, qty=0.3), _buy(1, qty=0.2)]   # 0.5 < threshold=1.0
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["current_volume"] == pytest.approx(0.5)

    def test_current_trade_count(self):
        trades = [_buy(i, qty=0.1) for i in range(7)]   # 0.7 < 1.0
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["current_trade_count"] == 7

    def test_pct_to_close_formula(self):
        """pct_to_close = current_volume / volume_threshold * 100."""
        trades = [_buy(0, qty=0.4)]   # 40% of threshold=1.0
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["pct_to_close"] == pytest.approx(40.0)

    def test_pct_to_close_zero_when_no_trades(self):
        r = compute_volume_bars([], volume_threshold=1.0)
        assert r["pct_to_close"] == pytest.approx(0.0)

    def test_current_state_resets_after_bar_close(self):
        """After bar closes, current_volume starts at 0 for new trades."""
        trades = _fill(3, qty=0.5)   # bar closes after 2, 3rd starts new bar
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["current_volume"] == pytest.approx(0.5)

    def test_pct_to_close_capped_logic(self):
        """pct_to_close reflects current open bar, which is always < threshold."""
        # No matter how many bars closed, current bar reflects remaining volume
        trades = _fill(11, qty=0.5)   # 5 bars of threshold=1.0, 0.5 remaining
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["pct_to_close"] == pytest.approx(50.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Bars sorted and independent
# ═══════════════════════════════════════════════════════════════════════════════

class TestBarsOrder:
    def test_bars_sorted_asc_by_ts_start(self):
        trades = _fill(6, qty=0.5)
        r = compute_volume_bars(trades, volume_threshold=1.0)
        starts = [b["ts_start"] for b in r["bars"]]
        assert starts == sorted(starts)

    def test_second_bar_starts_after_first_ends(self):
        trades = _fill(5, qty=0.5, start_ts=10)
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bars"][1]["ts_start"] > r["bars"][0]["ts_end"]

    def test_each_bar_independent_ohlc(self):
        """Bar 1: prices 100-101, bar 2: prices 200-201 — no bleed."""
        trades = (
            [_buy(i, price=100.0 + i, qty=0.5) for i in range(2)] +   # bar 1: 2×0.5=1.0
            [_buy(i+10, price=200.0 + i, qty=0.5) for i in range(2)]  # bar 2: 2×0.5=1.0
        )
        r = compute_volume_bars(trades, volume_threshold=1.0)
        assert r["bar_count"] == 2
        assert r["bars"][0]["high"] < 200.0
        assert r["bars"][1]["low"] > 150.0


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_threshold_larger_than_total_volume_no_bar(self):
        trades = _fill(5, qty=0.1)   # total 0.5 < threshold=10
        r = compute_volume_bars(trades, volume_threshold=10.0)
        assert r["bar_count"] == 0
        assert r["current_volume"] == pytest.approx(0.5)

    def test_very_small_threshold_many_bars(self):
        trades = [_buy(i, qty=1.0) for i in range(20)]
        r = compute_volume_bars(trades, volume_threshold=0.1)
        assert r["bar_count"] == 20
        assert r["current_volume"] == pytest.approx(0.0)

    def test_fractional_threshold_precision(self):
        trades = [_buy(0, qty=0.1), _buy(1, qty=0.1), _buy(2, qty=0.1)]
        r = compute_volume_bars(trades, volume_threshold=0.3)
        assert r["bar_count"] == 1
        assert r["bars"][0]["volume"] == pytest.approx(0.3)

    def test_large_dataset_no_crash(self):
        import random; random.seed(13)
        trades = [
            _t(i, price=100 + random.gauss(0, 2),
               qty=random.uniform(0.01, 2.0),
               side=random.choice(["buy", "sell"]))
            for i in range(1000)
        ]
        r = compute_volume_bars(trades, volume_threshold=5.0)
        assert r["bar_count"] >= 0
        assert r["current_volume"] >= 0

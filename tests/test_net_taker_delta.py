"""
TDD tests for net taker delta — per-symbol ranking and multi-symbol view.

Spec (2026-03-15-net-taker-delta-squeeze.md):
  - /api/net-taker-delta?symbol=X&window=60  (window in minutes)
  - Sum buy-taker vol minus sell-taker vol over window, per 1-min bucket
  - Per-symbol comparison: rank all symbols by net delta
  - Frontend: stacked bar (buy=green, sell=red), net line overlay

New pure function tested here:
  rank_symbols_by_net_taker_delta(symbol_results: Dict[str, dict]) -> List[dict]
    Input:  {symbol: compute_net_taker_delta() result, ...}
    Output: [{symbol, total_buy, total_sell, net, buy_pct, rank}] sorted desc by net

Note: compute_net_taker_delta() is already tested in test_short_squeeze.py.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import compute_net_taker_delta, rank_symbols_by_net_taker_delta  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _trade(ts, qty, side="buy", is_buyer_aggressor=None):
    d = {"ts": float(ts), "price": 100.0, "qty": float(qty), "side": side}
    if is_buyer_aggressor is not None:
        d["is_buyer_aggressor"] = int(is_buyer_aggressor)
    return d


def _ntd_result(total_buy, total_sell):
    """Minimal compute_net_taker_delta()-style result dict."""
    net = total_buy - total_sell
    return {
        "buckets": [],
        "total_buy": float(total_buy),
        "total_sell": float(total_sell),
        "net": float(net),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# rank_symbols_by_net_taker_delta
# ═══════════════════════════════════════════════════════════════════════════════

class TestRankSymbolsByNetTakerDelta:
    def test_empty_input_returns_empty(self):
        assert rank_symbols_by_net_taker_delta({}) == []

    def test_single_symbol_returns_one_entry(self):
        result = rank_symbols_by_net_taker_delta({"BTCUSDT": _ntd_result(10, 5)})
        assert len(result) == 1

    def test_entry_has_required_fields(self):
        result = rank_symbols_by_net_taker_delta({"BTCUSDT": _ntd_result(10, 5)})
        e = result[0]
        for f in ("symbol", "total_buy", "total_sell", "net", "buy_pct", "rank"):
            assert f in e, f"missing field: {f}"

    def test_symbol_field_matches_key(self):
        result = rank_symbols_by_net_taker_delta({"ETHUSDT": _ntd_result(10, 5)})
        assert result[0]["symbol"] == "ETHUSDT"

    def test_rank_1_is_highest_net(self):
        data = {
            "BTCUSDT": _ntd_result(10, 5),   # net +5
            "ETHUSDT": _ntd_result(20, 5),   # net +15  ← highest
            "SOLUSDT": _ntd_result(5, 10),   # net -5
        }
        result = rank_symbols_by_net_taker_delta(data)
        ranked = {e["symbol"]: e["rank"] for e in result}
        assert ranked["ETHUSDT"] == 1
        assert ranked["BTCUSDT"] == 2
        assert ranked["SOLUSDT"] == 3

    def test_ranks_sequential_and_unique(self):
        data = {s: _ntd_result(i + 1, 1) for i, s in enumerate(["A", "B", "C", "D"])}
        result = rank_symbols_by_net_taker_delta(data)
        ranks = sorted(e["rank"] for e in result)
        assert ranks == [1, 2, 3, 4]

    def test_sorted_desc_by_net(self):
        data = {
            "A": _ntd_result(3, 1),   # net +2
            "B": _ntd_result(10, 1),  # net +9
            "C": _ntd_result(1, 5),   # net -4
        }
        result = rank_symbols_by_net_taker_delta(data)
        nets = [e["net"] for e in result]
        assert nets == sorted(nets, reverse=True)

    def test_buy_pct_is_buy_fraction_of_total(self):
        """buy_pct = total_buy / (total_buy + total_sell) * 100."""
        result = rank_symbols_by_net_taker_delta({"X": _ntd_result(30, 70)})
        assert result[0]["buy_pct"] == pytest.approx(30.0)

    def test_buy_pct_all_buy_is_100(self):
        result = rank_symbols_by_net_taker_delta({"X": _ntd_result(10, 0)})
        assert result[0]["buy_pct"] == pytest.approx(100.0)

    def test_buy_pct_all_sell_is_zero(self):
        result = rank_symbols_by_net_taker_delta({"X": _ntd_result(0, 10)})
        assert result[0]["buy_pct"] == pytest.approx(0.0)

    def test_buy_pct_zero_total_is_50(self):
        """No trades → neutral 50% buy_pct."""
        result = rank_symbols_by_net_taker_delta({"X": _ntd_result(0, 0)})
        assert result[0]["buy_pct"] == pytest.approx(50.0)

    def test_total_buy_sell_propagated(self):
        result = rank_symbols_by_net_taker_delta({"X": _ntd_result(12.5, 7.3)})
        assert result[0]["total_buy"] == pytest.approx(12.5)
        assert result[0]["total_sell"] == pytest.approx(7.3)
        assert result[0]["net"] == pytest.approx(5.2)

    def test_negative_net_ranked_last(self):
        data = {
            "UP": _ntd_result(10, 2),   # net +8
            "DN": _ntd_result(2, 10),   # net -8
        }
        result = rank_symbols_by_net_taker_delta(data)
        ranked = {e["symbol"]: e["rank"] for e in result}
        assert ranked["UP"] == 1
        assert ranked["DN"] == 2

    def test_4_symbols_all_appear(self):
        syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
        data = {s: _ntd_result(i + 1, 1) for i, s in enumerate(syms)}
        result = rank_symbols_by_net_taker_delta(data)
        assert {e["symbol"] for e in result} == set(syms)


# ═══════════════════════════════════════════════════════════════════════════════
# compute_net_taker_delta — window_minutes compatibility
# ═══════════════════════════════════════════════════════════════════════════════

class TestNetTakerDeltaWindowMinutes:
    """
    Spec says window=60 means 60 minutes.
    The existing function takes window_seconds, so we verify the conversion
    logic works correctly (caller passes window*60 to get_recent_trades).
    These tests confirm compute_net_taker_delta handles various real-trade
    scenarios correctly so the API conversion is safe.
    """
    def test_1h_of_60_buckets(self):
        """60 minutes of 1-minute buckets = 60 rows."""
        now = 7200.0
        trades = [_trade(ts=now - i * 60, qty=1.0, side="buy") for i in range(60)]
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        assert len(result["buckets"]) == 60

    def test_net_accumulates_across_full_window(self):
        """net = sum of all per-bucket net_vols."""
        now = 3600.0
        buy_trades  = [_trade(now - i * 60, qty=3.0, side="buy")  for i in range(10)]
        sell_trades = [_trade(now - i * 60 - 30, qty=1.0, side="sell") for i in range(10)]
        result = compute_net_taker_delta(buy_trades + sell_trades, bucket_seconds=60)
        assert result["net"] == pytest.approx(20.0)   # 10*3 - 10*1

    def test_dominant_side_buy_positive_net(self):
        trades = (
            [_trade(i * 10, qty=5.0, side="buy") for i in range(10)] +
            [_trade(i * 10 + 5, qty=2.0, side="sell") for i in range(10)]
        )
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        assert result["net"] > 0

    def test_dominant_side_sell_negative_net(self):
        trades = (
            [_trade(i * 10, qty=1.0, side="buy") for i in range(10)] +
            [_trade(i * 10 + 5, qty=5.0, side="sell") for i in range(10)]
        )
        result = compute_net_taker_delta(trades, bucket_seconds=60)
        assert result["net"] < 0

    def test_is_buyer_maker_false_means_buyer_aggressor(self):
        """
        Spec note: trades table has is_buyer_maker column.
        is_buyer_maker=False → buyer is taker (aggressor) → buy volume.
        Our function maps is_buyer_aggressor=True → buy.
        When caller converts: is_buyer_aggressor = not is_buyer_maker.
        """
        # Simulate what collectors.py does: is_buyer_aggressor = not is_buyer_maker
        # is_buyer_maker=False → aggressor=True → buy
        trade = _trade(0, qty=5.0, side="buy", is_buyer_aggressor=True)
        result = compute_net_taker_delta([trade] * 5, bucket_seconds=60)
        assert result["total_buy"] == pytest.approx(25.0)
        assert result["total_sell"] == pytest.approx(0.0)

    def test_is_buyer_maker_true_means_seller_aggressor(self):
        """is_buyer_maker=True → seller is taker → sell volume."""
        trade = _trade(0, qty=5.0, side="sell", is_buyer_aggressor=False)
        result = compute_net_taker_delta([trade] * 5, bucket_seconds=60)
        assert result["total_sell"] == pytest.approx(25.0)
        assert result["total_buy"] == pytest.approx(0.0)

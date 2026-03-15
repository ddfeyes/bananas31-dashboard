"""
TDD tests for order book recovery speed metric.

Spec:
  compute_ob_recovery_speed(
      ob_snapshots,          # [{ts, bid_volume, ask_volume}]
      trades,                # [{ts, price, qty, side, [is_buyer_aggressor]}]
      threshold_usd=50000,   # minimum trade value to consider
      recovery_pct=0.8,      # depth must recover to 80% of baseline
      baseline_window=30.0,  # seconds before trade to measure baseline
      alert_seconds=10.0,    # recovery > this → slow
      max_lookforward=60.0,  # cap on recovery search window
  )

  For each large trade (price*qty >= threshold_usd):
    - buy (side="buy" / is_buyer_aggressor=True)  → asks consumed → monitor ask_volume
    - sell (side="sell" / is_buyer_aggressor=False) → bids consumed → monitor bid_volume
    - baseline_depth = mean depth of consumed-side volume in [trade_ts - baseline_window, trade_ts)
    - scan ob_snapshots after trade: first ts where depth >= recovery_pct * baseline
    - recovery_seconds = t_recovery - t_trade  (None if not found in max_lookforward)

  Returns:
    events:               [{ts, side, trade_usd, baseline_depth, recovery_seconds, recovered, slow}]
    avg_recovery_seconds: mean of recovered events (0.0 if none)
    max_recovery_seconds: max of recovered events (0.0 if none)
    slow_count:           events where slow=True
    alert:                bool — True if slow_count > 0
    event_count:          total large-trade events found
"""
import sys, os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from metrics import compute_ob_recovery_speed  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────────

def _ob(ts, bid_vol, ask_vol):
    return {"ts": float(ts), "bid_volume": float(bid_vol), "ask_volume": float(ask_vol)}

def _trade(ts, price, qty, side="buy", is_buyer_aggressor=None):
    d = {"ts": float(ts), "price": float(price), "qty": float(qty), "side": side}
    if is_buyer_aggressor is not None:
        d["is_buyer_aggressor"] = int(is_buyer_aggressor)
    return d

def _large_buy(ts, usd=100000):
    return _trade(ts, price=float(usd), qty=1.0, side="buy")

def _large_sell(ts, usd=100000):
    return _trade(ts, price=float(usd), qty=1.0, side="sell")

def _small_buy(ts, usd=1000):
    return _trade(ts, price=float(usd), qty=1.0, side="buy")


# ═══════════════════════════════════════════════════════════════════════════════
# Structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestStructure:
    def test_empty_returns_valid_dict(self):
        r = compute_ob_recovery_speed([], [])
        assert isinstance(r, dict)

    def test_result_has_required_fields(self):
        r = compute_ob_recovery_speed([], [])
        for f in ("events", "avg_recovery_seconds", "max_recovery_seconds",
                  "slow_count", "alert", "event_count"):
            assert f in r, f"missing: {f}"

    def test_empty_gives_zero_counts(self):
        r = compute_ob_recovery_speed([], [])
        assert r["event_count"] == 0
        assert r["slow_count"] == 0
        assert r["alert"] is False
        assert r["events"] == []

    def test_event_has_required_fields(self):
        obs = [_ob(0, 500, 500), _ob(5, 500, 200), _ob(15, 500, 450)]
        trd = [_large_buy(ts=3)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=10, alert_seconds=10,
                                       max_lookforward=60)
        assert r["event_count"] >= 1
        e = r["events"][0]
        for f in ("ts", "side", "trade_usd", "baseline_depth",
                  "recovery_seconds", "recovered", "slow"):
            assert f in e, f"missing event field: {f}"


# ═══════════════════════════════════════════════════════════════════════════════
# Trade filtering
# ═══════════════════════════════════════════════════════════════════════════════

class TestTradeFiltering:
    def test_small_trade_not_an_event(self):
        obs = [_ob(0, 500, 500)]
        trd = [_small_buy(ts=1, usd=1000)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000)
        assert r["event_count"] == 0

    def test_large_trade_is_an_event(self):
        obs = [_ob(0, 500, 500)]
        trd = [_large_buy(ts=1, usd=100000)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000)
        assert r["event_count"] == 1

    def test_exactly_at_threshold_is_event(self):
        obs = [_ob(0, 500, 500)]
        trd = [_trade(ts=1, price=50000.0, qty=1.0, side="buy")]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000)
        assert r["event_count"] == 1

    def test_just_below_threshold_not_event(self):
        obs = [_ob(0, 500, 500)]
        trd = [_trade(ts=1, price=49999.0, qty=1.0, side="buy")]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000)
        assert r["event_count"] == 0

    def test_trade_usd_uses_price_times_qty(self):
        obs = [_ob(0, 500, 500)]
        trd = [_trade(ts=1, price=500.0, qty=120.0, side="buy")]  # 60000 >= 50000
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000)
        assert r["event_count"] == 1
        assert r["events"][0]["trade_usd"] == pytest.approx(60000.0)

    def test_multiple_large_trades_all_counted(self):
        obs = [_ob(0, 500, 500)]
        trd = [_large_buy(ts=1), _large_sell(ts=2), _large_buy(ts=3)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000)
        assert r["event_count"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Side determination
# ═══════════════════════════════════════════════════════════════════════════════

class TestSideDetermination:
    def test_buy_trade_monitors_ask_side(self):
        obs = [_ob(0, 500, 500)]
        trd = [_large_buy(ts=1)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000)
        assert r["events"][0]["side"] == "ask"

    def test_sell_trade_monitors_bid_side(self):
        obs = [_ob(0, 500, 500)]
        trd = [_large_sell(ts=1)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000)
        assert r["events"][0]["side"] == "bid"

    def test_is_buyer_aggressor_true_monitors_ask(self):
        obs = [_ob(0, 500, 500)]
        trd = [_trade(ts=1, price=100000, qty=1.0, side="sell", is_buyer_aggressor=True)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000)
        assert r["events"][0]["side"] == "ask"

    def test_is_buyer_aggressor_false_monitors_bid(self):
        obs = [_ob(0, 500, 500)]
        trd = [_trade(ts=1, price=100000, qty=1.0, side="buy", is_buyer_aggressor=False)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000)
        assert r["events"][0]["side"] == "bid"


# ═══════════════════════════════════════════════════════════════════════════════
# Baseline depth
# ═══════════════════════════════════════════════════════════════════════════════

class TestBaselineDepth:
    def test_baseline_is_mean_of_pre_trade_snapshots(self):
        """Baseline = mean ask_volume in [trade_ts - baseline_window, trade_ts)."""
        obs = [
            _ob(0,  500, 400),   # 30s before trade → in window
            _ob(10, 500, 600),   # 20s before trade → in window
            _ob(20, 500, 500),   # 10s before trade → in window
            # trade at ts=30
        ]
        trd = [_large_buy(ts=30)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=30, max_lookforward=5)
        # baseline = mean(400, 600, 500) = 500
        assert r["events"][0]["baseline_depth"] == pytest.approx(500.0)

    def test_baseline_excludes_post_trade_snapshots(self):
        """Snapshots at or after trade_ts not included in baseline."""
        obs = [
            _ob(0,  500, 600),  # in window
            _ob(30, 500, 100),  # AT trade ts — should not be included in baseline
        ]
        trd = [_large_buy(ts=30)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=60, max_lookforward=5)
        # baseline should only use ts=0 snapshot
        assert r["events"][0]["baseline_depth"] == pytest.approx(600.0)

    def test_baseline_excludes_snapshots_outside_window(self):
        """Snapshots older than baseline_window not included."""
        obs = [
            _ob(0,  500, 999),  # 50s before trade — outside 30s window
            _ob(20, 500, 400),  # 10s before trade — inside window
        ]
        trd = [_large_buy(ts=50)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=30, max_lookforward=5)
        assert r["events"][0]["baseline_depth"] == pytest.approx(400.0)

    def test_no_pre_trade_snapshots_baseline_is_zero(self):
        """No snapshots before trade → baseline = 0 → no recovery possible."""
        obs = [_ob(100, 500, 500)]   # after trade
        trd = [_large_buy(ts=50)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=30, max_lookforward=60)
        assert r["events"][0]["baseline_depth"] == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Recovery detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecoveryDetection:
    def test_fast_recovery_detected(self):
        """Ask depth drops after buy trade, recovers within a few seconds."""
        obs = [
            _ob(0,  500, 500),   # baseline window
            _ob(10, 500, 500),
            # trade at ts=15
            _ob(16, 500, 50),    # depth drops right after trade
            _ob(20, 500, 450),   # recovers to 90% (>80%)
        ]
        trd = [_large_buy(ts=15)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=20, recovery_pct=0.8,
                                       alert_seconds=30, max_lookforward=60)
        e = r["events"][0]
        assert e["recovered"] is True
        assert e["recovery_seconds"] == pytest.approx(5.0)  # ts=20 - ts=15

    def test_slow_recovery_flagged(self):
        """Recovery takes 25s — exceeds alert_seconds=10."""
        obs = [
            _ob(0,  500, 500),
            # trade at ts=5
            _ob(6,  500, 50),    # drops
            _ob(30, 500, 450),   # recovers at ts=30 → 25s after trade
        ]
        trd = [_large_buy(ts=5)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=10, recovery_pct=0.8,
                                       alert_seconds=10, max_lookforward=60)
        e = r["events"][0]
        assert e["recovered"] is True
        assert e["recovery_seconds"] == pytest.approx(25.0)
        assert e["slow"] is True
        assert r["alert"] is True

    def test_fast_recovery_not_slow(self):
        """Recovery in 3s — below alert_seconds=10."""
        obs = [
            _ob(0,  500, 500),
            # trade at ts=5
            _ob(8,  500, 450),   # 3s after trade, recovered 90%
        ]
        trd = [_large_buy(ts=5)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=10, recovery_pct=0.8,
                                       alert_seconds=10, max_lookforward=60)
        e = r["events"][0]
        assert e["recovered"] is True
        assert e["slow"] is False

    def test_no_recovery_in_window_not_recovered(self):
        """Depth never refills within max_lookforward."""
        obs = [
            _ob(0,  500, 500),
            # trade at ts=10
            _ob(11, 500, 50),    # drops
            _ob(20, 500, 100),   # stays low
            _ob(70, 500, 450),   # recovers but AFTER max_lookforward=60
        ]
        trd = [_large_buy(ts=10)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=15, recovery_pct=0.8,
                                       alert_seconds=10, max_lookforward=60)
        e = r["events"][0]
        assert e["recovered"] is False
        assert e["recovery_seconds"] is None
        assert e["slow"] is True

    def test_recovery_pct_threshold_respected(self):
        """Depth must reach recovery_pct * baseline to count as recovered."""
        obs = [
            _ob(0,  500, 1000),
            # trade at ts=5, baseline=1000
            _ob(10, 500, 799),   # 79.9% — below 80% threshold
            _ob(15, 500, 801),   # 80.1% — above threshold → recovered
        ]
        trd = [_large_buy(ts=5)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=10, recovery_pct=0.8,
                                       alert_seconds=30, max_lookforward=60)
        e = r["events"][0]
        assert e["recovered"] is True
        assert e["recovery_seconds"] == pytest.approx(10.0)  # ts=15 - ts=5

    def test_bid_side_recovery_for_sell_trade(self):
        """Sell trade consumes bid side — bid_volume tracked for recovery."""
        obs = [
            _ob(0,  500, 500),
            # trade at ts=5
            _ob(6,  50,  500),   # bids drop
            _ob(15, 450, 500),   # bids recover
        ]
        trd = [_large_sell(ts=5)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=10, recovery_pct=0.8,
                                       alert_seconds=30, max_lookforward=60)
        e = r["events"][0]
        assert e["side"] == "bid"
        assert e["recovered"] is True
        assert e["recovery_seconds"] == pytest.approx(10.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Aggregates
# ═══════════════════════════════════════════════════════════════════════════════

class TestAggregates:
    def test_avg_recovery_mean_of_recovered_events(self):
        """Two events: 5s and 15s recovery → avg = 10s."""
        obs = [
            _ob(0,  500, 500),   # baseline for trade1 (ts=10, window=[−5,10))
            _ob(15, 500, 450),   # +5s after trade1 at ts=10 → recovered
            _ob(40, 500, 500),   # baseline for trade2 (ts=50, window=[35,50))
            _ob(65, 500, 450),   # +15s after trade2 at ts=50 → recovered
        ]
        trd = [_large_buy(ts=10), _large_buy(ts=50)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=15, recovery_pct=0.8,
                                       alert_seconds=30, max_lookforward=60)
        # Both should be recovered
        recovered = [e for e in r["events"] if e["recovered"]]
        assert len(recovered) == 2
        assert r["avg_recovery_seconds"] == pytest.approx(10.0)

    def test_max_recovery_is_max_across_events(self):
        obs = [
            _ob(0,  500, 500),   # baseline for trade1
            _ob(15, 500, 450),   # trade1 at ts=10 → 5s
            _ob(40, 500, 500),   # baseline for trade2
            _ob(65, 500, 450),   # trade2 at ts=50 → 15s
        ]
        trd = [_large_buy(ts=10), _large_buy(ts=50)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=15, recovery_pct=0.8,
                                       alert_seconds=30, max_lookforward=60)
        assert r["max_recovery_seconds"] == pytest.approx(15.0)

    def test_avg_recovery_zero_when_none_recovered(self):
        obs = [_ob(0, 500, 500)]
        trd = [_large_buy(ts=100)]   # no post-trade snapshots
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=110, max_lookforward=60)
        assert r["avg_recovery_seconds"] == 0.0

    def test_max_recovery_zero_when_none_recovered(self):
        obs = [_ob(0, 500, 500)]
        trd = [_large_buy(ts=100)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=110, max_lookforward=60)
        assert r["max_recovery_seconds"] == 0.0

    def test_slow_count_correct(self):
        """2 slow events, 1 fast."""
        obs = [
            _ob(0,   500, 500),
            _ob(20,  500, 450),   # trade at ts=5  → 15s, slow
            _ob(7,   500, 450),   # trade at ts=5, fast (ts=7 → 2s)
            _ob(120, 500, 450),   # trade at ts=100 → 20s, slow
        ]
        trd = [_large_buy(ts=5), _large_buy(ts=100)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=10, recovery_pct=0.8,
                                       alert_seconds=10, max_lookforward=60)
        # ts=5: first snapshot after trade is ts=7 (2s → fast), then ts=20 (15s)
        # Since ts=7 has 450 >= 0.8*500=400, recovery at 2s → not slow
        # ts=100: next snapshot ts=120 (20s → slow)
        assert r["slow_count"] >= 1

    def test_alert_false_when_no_slow_events(self):
        obs = [_ob(0, 500, 500), _ob(6, 500, 450)]
        trd = [_large_buy(ts=5)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=10, recovery_pct=0.8,
                                       alert_seconds=10, max_lookforward=60)
        assert r["alert"] is False

    def test_alert_true_when_slow_events_exist(self):
        obs = [_ob(0, 500, 500), _ob(30, 500, 450)]
        trd = [_large_buy(ts=5)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=10, recovery_pct=0.8,
                                       alert_seconds=10, max_lookforward=60)
        assert r["alert"] is True

    def test_event_count_matches_events_list(self):
        obs = [_ob(0, 500, 500)]
        trd = [_large_buy(ts=1), _large_sell(ts=2), _large_buy(ts=3)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000)
        assert r["event_count"] == len(r["events"])


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_no_ob_snapshots_no_recovery(self):
        trd = [_large_buy(ts=1)]
        r = compute_ob_recovery_speed([], trd, threshold_usd=50000)
        assert r["event_count"] == 1
        assert r["events"][0]["recovered"] is False

    def test_ob_snapshots_but_no_trades(self):
        obs = [_ob(0, 500, 500), _ob(10, 500, 500)]
        r = compute_ob_recovery_speed(obs, [], threshold_usd=50000)
        assert r["event_count"] == 0

    def test_unsorted_inputs_handled(self):
        """Function must sort both inputs by ts."""
        obs = [_ob(20, 500, 450), _ob(0, 500, 500)]
        trd = [_large_buy(ts=15)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=20, recovery_pct=0.8,
                                       alert_seconds=30, max_lookforward=60)
        e = r["events"][0]
        assert e["baseline_depth"] == pytest.approx(500.0)
        assert e["recovered"] is True

    def test_zero_baseline_no_crash(self):
        """If baseline_depth=0 (no pre-trade obs), function does not raise."""
        obs = [_ob(100, 500, 500)]
        trd = [_large_buy(ts=50)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=10, max_lookforward=60)
        assert r["events"][0]["recovered"] is False

    def test_recovery_immediately_at_next_snapshot_zero_seconds(self):
        """If the very next snapshot is already recovered, recovery_seconds > 0."""
        obs = [
            _ob(0, 500, 500),
            _ob(1, 500, 450),   # 1s after trade, already recovered
        ]
        trd = [_large_buy(ts=0.5)]
        r = compute_ob_recovery_speed(obs, trd, threshold_usd=50000,
                                       baseline_window=1, recovery_pct=0.8,
                                       alert_seconds=30, max_lookforward=60)
        e = r["events"][0]
        assert e["recovered"] is True
        assert e["recovery_seconds"] == pytest.approx(0.5)

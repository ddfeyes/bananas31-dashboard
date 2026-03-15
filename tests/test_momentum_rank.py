"""
TDD tests for symbol momentum rank.

Spec:
  - compute_momentum_score(candles, window_seconds) -> float (% change)
  - rank_symbols_by_momentum(symbol_candles: dict) -> list of ranked dicts
  - Each ranked entry: symbol, score_5m, score_15m, score_1h, composite, rank
  - composite = weighted avg: 0.5*score_5m + 0.3*score_15m + 0.2*score_1h
  - Rank 1 = highest composite (strongest upward momentum)
  - Candle format: {bucket, close_price, open_price, volume, ...}
"""
import sys
import os
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import compute_momentum_score, rank_symbols_by_momentum  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _candle(bucket, close, open_p=None, volume=1.0):
    """Minimal candle dict matching get_ohlcv() output format."""
    return {
        "bucket": float(bucket),
        "close_price": float(close),
        "open_price": float(open_p if open_p is not None else close),
        "volume": float(volume),
    }


def _candles_linear(start_ts, n, start_price, end_price, interval=60):
    """n candles linearly interpolated from start_price to end_price."""
    candles = []
    for i in range(n):
        t = start_ts + i * interval
        price = start_price + (end_price - start_price) * i / max(n - 1, 1)
        candles.append(_candle(bucket=t, close=price))
    return candles


# ── compute_momentum_score ─────────────────────────────────────────────────────

class TestComputeMomentumScore:
    def test_empty_candles_returns_zero(self):
        assert compute_momentum_score([], window_seconds=300) == 0.0

    def test_single_candle_returns_zero(self):
        c = [_candle(0, 100.0)]
        assert compute_momentum_score(c, window_seconds=300) == 0.0

    def test_price_up_10pct_returns_positive(self):
        now = 10000.0
        candles = [
            _candle(now - 300, 100.0),
            _candle(now, 110.0),
        ]
        score = compute_momentum_score(candles, window_seconds=300)
        assert score == pytest.approx(10.0, rel=1e-3)

    def test_price_down_10pct_returns_negative(self):
        now = 10000.0
        candles = [
            _candle(now - 300, 100.0),
            _candle(now, 90.0),
        ]
        score = compute_momentum_score(candles, window_seconds=300)
        assert score == pytest.approx(-10.0, rel=1e-3)

    def test_flat_price_returns_zero(self):
        now = 10000.0
        candles = [_candle(now - i * 60, 100.0) for i in range(10)]
        score = compute_momentum_score(candles, window_seconds=300)
        assert score == pytest.approx(0.0, abs=1e-9)

    def test_uses_oldest_candle_within_window(self):
        """Momentum = (latest - first_in_window) / first_in_window * 100."""
        now = 10000.0
        # Candles outside window should be ignored
        candles = [
            _candle(now - 7200, 50.0),   # outside 1h window
            _candle(now - 3600, 80.0),   # oldest inside 1h
            _candle(now - 1800, 90.0),
            _candle(now, 100.0),         # latest
        ]
        score = compute_momentum_score(candles, window_seconds=3600)
        # (100 - 80) / 80 * 100 = 25%
        assert score == pytest.approx(25.0, rel=1e-3)

    def test_window_shorter_than_history(self):
        """Only candles within window_seconds from the latest are considered."""
        now = 10000.0
        candles = [
            _candle(now - 1000, 100.0),  # outside 300s window
            _candle(now - 200, 110.0),   # oldest inside 300s
            _candle(now, 121.0),
        ]
        score = compute_momentum_score(candles, window_seconds=300)
        # (121 - 110) / 110 * 100 = 10%
        assert score == pytest.approx(10.0, rel=1e-3)

    def test_no_candles_in_window_returns_zero(self):
        """All candles older than window → zero."""
        now = 10000.0
        candles = [
            _candle(now - 7200, 90.0),
            _candle(now - 5000, 95.0),
        ]
        score = compute_momentum_score(candles, window_seconds=300)
        assert score == 0.0

    def test_returns_float(self):
        candles = [_candle(0, 100.0), _candle(60, 105.0)]
        result = compute_momentum_score(candles, window_seconds=300)
        assert isinstance(result, float)

    def test_base_price_zero_returns_zero(self):
        """Guard division by zero if oldest candle has close=0."""
        candles = [_candle(0, 0.0), _candle(60, 100.0)]
        result = compute_momentum_score(candles, window_seconds=300)
        assert result == 0.0

    def test_unsorted_candles_handled(self):
        """Function should use bucket order, not list order."""
        now = 10000.0
        candles = [
            _candle(now, 110.0),
            _candle(now - 300, 100.0),
        ]
        score = compute_momentum_score(candles, window_seconds=300)
        assert score == pytest.approx(10.0, rel=1e-3)


# ── rank_symbols_by_momentum ───────────────────────────────────────────────────

class TestRankSymbolsByMomentum:
    def test_empty_input_returns_empty(self):
        assert rank_symbols_by_momentum({}) == []

    def test_single_symbol_returns_one_entry(self):
        now = 10000.0
        candles = [_candle(now - 300, 100.0), _candle(now, 110.0)]
        result = rank_symbols_by_momentum({"BTCUSDT": candles})
        assert len(result) == 1

    def test_entry_has_required_fields(self):
        now = 10000.0
        candles = [_candle(now - 300, 100.0), _candle(now, 110.0)]
        result = rank_symbols_by_momentum({"BTCUSDT": candles})
        entry = result[0]
        for field in ("symbol", "score_5m", "score_15m", "score_1h", "composite", "rank"):
            assert field in entry, f"missing field: {field}"

    def test_symbol_field_matches_input(self):
        now = 10000.0
        candles = [_candle(now - 300, 100.0), _candle(now, 110.0)]
        result = rank_symbols_by_momentum({"ETHUSDT": candles})
        assert result[0]["symbol"] == "ETHUSDT"

    def test_rank_1_is_strongest_momentum(self):
        """Symbol with highest composite gets rank=1."""
        now = 10000.0
        btc = _candles_linear(now - 3600, 60, 100.0, 110.0)   # +10%
        eth = _candles_linear(now - 3600, 60, 100.0, 120.0)   # +20%
        result = rank_symbols_by_momentum({"BTCUSDT": btc, "ETHUSDT": eth})
        ranked = {e["symbol"]: e["rank"] for e in result}
        assert ranked["ETHUSDT"] == 1
        assert ranked["BTCUSDT"] == 2

    def test_ranks_are_unique_and_sequential(self):
        now = 10000.0
        syms = {
            "A": _candles_linear(now - 3600, 60, 100.0, 105.0),
            "B": _candles_linear(now - 3600, 60, 100.0, 110.0),
            "C": _candles_linear(now - 3600, 60, 100.0, 95.0),
            "D": _candles_linear(now - 3600, 60, 100.0, 102.0),
        }
        result = rank_symbols_by_momentum(syms)
        ranks = sorted(e["rank"] for e in result)
        assert ranks == [1, 2, 3, 4]

    def test_composite_formula(self):
        """composite = 0.5*score_5m + 0.3*score_15m + 0.2*score_1h."""
        now = 10000.0
        # Build candles so each timeframe has known % move
        candles = (
            [_candle(now - 3600, 100.0)] +   # 1h start
            [_candle(now - 900, 104.0)] +    # 15m start (dummy intermediate)
            [_candle(now - 300, 108.0)] +    # 5m start
            [_candle(now, 110.0)]            # latest
        )
        result = rank_symbols_by_momentum({"X": candles})
        e = result[0]
        expected = 0.5 * e["score_5m"] + 0.3 * e["score_15m"] + 0.2 * e["score_1h"]
        assert e["composite"] == pytest.approx(expected, rel=1e-4)

    def test_sorted_by_composite_desc(self):
        """Result list is ordered rank1 first."""
        now = 10000.0
        syms = {
            "A": _candles_linear(now - 3600, 60, 100.0, 115.0),
            "B": _candles_linear(now - 3600, 60, 100.0, 108.0),
            "C": _candles_linear(now - 3600, 60, 100.0, 90.0),
        }
        result = rank_symbols_by_momentum(syms)
        composites = [e["composite"] for e in result]
        assert composites == sorted(composites, reverse=True)

    def test_scores_are_floats(self):
        now = 10000.0
        candles = _candles_linear(now - 3600, 60, 100.0, 110.0)
        result = rank_symbols_by_momentum({"SYM": candles})
        e = result[0]
        for f in ("score_5m", "score_15m", "score_1h", "composite"):
            assert isinstance(e[f], float), f"{f} is not float"

    def test_4_symbols_all_ranked(self):
        now = 10000.0
        syms = {s: _candles_linear(now - 3600, 60, 100.0, 100.0 + i * 5)
                for i, s in enumerate(["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"])}
        result = rank_symbols_by_momentum(syms)
        assert len(result) == 4
        assert {e["symbol"] for e in result} == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"}

    def test_negative_momentum_ranked_last(self):
        now = 10000.0
        syms = {
            "UP": _candles_linear(now - 3600, 60, 100.0, 110.0),
            "DN": _candles_linear(now - 3600, 60, 100.0, 85.0),
        }
        result = rank_symbols_by_momentum(syms)
        ranked = {e["symbol"]: e["rank"] for e in result}
        assert ranked["UP"] == 1
        assert ranked["DN"] == 2

    def test_score_5m_uses_300s_window(self):
        now = 10000.0
        candles = [
            _candle(now - 3600, 100.0),
            _candle(now - 301, 100.0),   # just outside 5m
            _candle(now - 299, 110.0),   # oldest inside 5m
            _candle(now, 121.0),
        ]
        result = rank_symbols_by_momentum({"X": candles})
        # score_5m = (121-110)/110*100 ≈ 10%
        assert result[0]["score_5m"] == pytest.approx(10.0, rel=1e-2)

    def test_score_15m_uses_900s_window(self):
        now = 10000.0
        candles = [
            _candle(now - 3600, 100.0),
            _candle(now - 901, 100.0),   # just outside 15m
            _candle(now - 899, 80.0),    # oldest inside 15m
            _candle(now, 100.0),
        ]
        result = rank_symbols_by_momentum({"X": candles})
        # score_15m = (100-80)/80*100 = 25%
        assert result[0]["score_15m"] == pytest.approx(25.0, rel=1e-2)

    def test_score_1h_uses_3600s_window(self):
        now = 10000.0
        candles = [
            _candle(now - 3600, 100.0),  # oldest inside 1h
            _candle(now - 1800, 110.0),
            _candle(now, 120.0),
        ]
        result = rank_symbols_by_momentum({"X": candles})
        # score_1h = (120-100)/100*100 = 20%
        assert result[0]["score_1h"] == pytest.approx(20.0, rel=1e-2)

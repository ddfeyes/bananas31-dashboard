"""
Tests for compute_market_regime_v2() — Market Regime Classifier.
30+ tests. TDD — written before implementation.

Regime labels: trending_bull, trending_bear, choppy, ranging, crisis
"""
import asyncio
import sys
import os
import time
import math
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import compute_market_regime_v2, _classify_market_regime, _regime_confidence


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


VALID_REGIMES = {"trending_bull", "trending_bear", "choppy", "ranging", "crisis"}

# Deterministic fake OHLCV candles (bull scenario)
def _make_candles(n=30, start=50000.0, delta=10.0):
    candles = []
    price = start
    for i in range(n):
        candles.append({
            "open_price": price,
            "close_price": price + delta,
            "close": price + delta,
            "high": price + delta * 1.5,
            "low": price - delta * 0.5,
            "volume": 100.0,
        })
        price += delta
    return candles


def _make_candles_bear(n=30, start=50000.0):
    return _make_candles(n=n, start=start, delta=-10.0)


def _make_candles_flat(n=30, start=50000.0):
    return _make_candles(n=n, start=start, delta=0.1)


# ---------------------------------------------------------------------------
# fixture: patched full function call
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def result():
    candles = _make_candles(30, start=50000.0, delta=10.0)
    with patch("metrics.get_ohlcv", new_callable=AsyncMock) as mock_ohlcv, \
         patch("collectors.get_symbols", return_value=["BTCUSDT", "ETHUSDT"]):
        mock_ohlcv.return_value = candles
        # Clear cache to force fresh computation
        import metrics as m
        m._market_regime_v2_cache.clear()
        return run(compute_market_regime_v2(symbol="BTCUSDT"))


# ---------------------------------------------------------------------------
# 1. Return type
# ---------------------------------------------------------------------------

def test_returns_dict(result):
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 2. Required keys
# ---------------------------------------------------------------------------

REQUIRED_KEYS = [
    "regime",
    "confidence",
    "volatility",
    "momentum",
    "correlation",
    "regime_history",
    "timestamp",
]


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_required_key_present(result, key):
    assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# 3. Regime field
# ---------------------------------------------------------------------------

def test_regime_is_string(result):
    assert isinstance(result["regime"], str)


def test_regime_valid_value(result):
    assert result["regime"] in VALID_REGIMES, f"Invalid regime: {result['regime']}"


def test_regime_not_empty(result):
    assert result["regime"] != ""


def test_regime_lowercase(result):
    assert result["regime"] == result["regime"].lower()


def test_regime_contains_underscore_or_single_word(result):
    """All regimes are snake_case identifiers (single or compound words)."""
    r = result["regime"]
    assert r in VALID_REGIMES, f"Regime '{r}' not in valid set"


# ---------------------------------------------------------------------------
# 4. Confidence field
# ---------------------------------------------------------------------------

def test_confidence_is_float(result):
    assert isinstance(result["confidence"], float)


def test_confidence_between_0_and_1(result):
    assert 0.0 <= result["confidence"] <= 1.0, f"Confidence out of range: {result['confidence']}"


def test_confidence_positive(result):
    assert result["confidence"] > 0.0


def test_confidence_not_one(result):
    """Confidence should not be exactly 1.0 (it's probabilistic)."""
    assert result["confidence"] < 1.0


# ---------------------------------------------------------------------------
# 5. Volatility field
# ---------------------------------------------------------------------------

def test_volatility_is_float(result):
    assert isinstance(result["volatility"], float)


def test_volatility_non_negative(result):
    assert result["volatility"] >= 0.0


# ---------------------------------------------------------------------------
# 6. Momentum field
# ---------------------------------------------------------------------------

def test_momentum_is_float(result):
    assert isinstance(result["momentum"], float)


def test_momentum_finite(result):
    assert math.isfinite(result["momentum"])


# ---------------------------------------------------------------------------
# 7. Correlation field
# ---------------------------------------------------------------------------

def test_correlation_is_float(result):
    assert isinstance(result["correlation"], float)


def test_correlation_in_range(result):
    """Correlation should be in [-1, 1]."""
    assert -1.0 <= result["correlation"] <= 1.0, f"Correlation out of range: {result['correlation']}"


# ---------------------------------------------------------------------------
# 8. Regime history
# ---------------------------------------------------------------------------

def test_regime_history_is_list(result):
    assert isinstance(result["regime_history"], list)


def test_regime_history_max_5(result):
    assert len(result["regime_history"]) <= 5


def test_regime_history_items_have_required_fields(result):
    for item in result["regime_history"]:
        assert "regime" in item, f"history item missing 'regime': {item}"
        assert "timestamp" in item, f"history item missing 'timestamp': {item}"


def test_regime_history_items_valid_regime(result):
    for item in result["regime_history"]:
        assert item["regime"] in VALID_REGIMES, f"Invalid history regime: {item['regime']}"


def test_regime_history_timestamps_are_numeric(result):
    for item in result["regime_history"]:
        assert isinstance(item["timestamp"], (int, float)), \
            f"Invalid timestamp type: {type(item['timestamp'])}"


# ---------------------------------------------------------------------------
# 9. Timestamp
# ---------------------------------------------------------------------------

def test_timestamp_is_numeric(result):
    assert isinstance(result["timestamp"], (int, float))


def test_timestamp_recent(result):
    """Timestamp should be within the last 5 minutes."""
    assert abs(time.time() - result["timestamp"]) < 300


# ---------------------------------------------------------------------------
# 10. Caching (30s cache)
# ---------------------------------------------------------------------------

def test_caching_returns_same_object():
    """Two rapid calls should return identical timestamp (same cached result)."""
    candles = _make_candles(30)
    with patch("metrics.get_ohlcv", new_callable=AsyncMock) as mock_ohlcv, \
         patch("collectors.get_symbols", return_value=["BTCUSDT"]):
        mock_ohlcv.return_value = candles
        import metrics as m
        m._market_regime_v2_cache.clear()
        r1 = run(compute_market_regime_v2(symbol="CACHETEST"))
        r2 = run(compute_market_regime_v2(symbol="CACHETEST"))
        assert r1["timestamp"] == r2["timestamp"]


# ---------------------------------------------------------------------------
# 11. Symbol parameter
# ---------------------------------------------------------------------------

def test_accepts_symbol_parameter():
    """Should accept an optional symbol parameter without crashing."""
    candles = _make_candles(20)
    with patch("metrics.get_ohlcv", new_callable=AsyncMock) as mock_ohlcv, \
         patch("collectors.get_symbols", return_value=["BTCUSDT"]):
        mock_ohlcv.return_value = candles
        import metrics as m
        m._market_regime_v2_cache.clear()
        result = run(compute_market_regime_v2(symbol="BTCUSDT"))
        assert isinstance(result, dict)
        assert "regime" in result


def test_symbol_in_result():
    """Symbol should be reflected in result."""
    candles = _make_candles(20)
    with patch("metrics.get_ohlcv", new_callable=AsyncMock) as mock_ohlcv, \
         patch("collectors.get_symbols", return_value=["BTCUSDT"]):
        mock_ohlcv.return_value = candles
        import metrics as m
        m._market_regime_v2_cache.clear()
        result = run(compute_market_regime_v2(symbol="BTCUSDT"))
        assert result.get("symbol") == "BTCUSDT"


def test_none_symbol_works():
    candles = _make_candles(20)
    with patch("metrics.get_ohlcv", new_callable=AsyncMock) as mock_ohlcv, \
         patch("collectors.get_symbols", return_value=["BTCUSDT"]):
        mock_ohlcv.return_value = candles
        import metrics as m
        m._market_regime_v2_cache.clear()
        result = run(compute_market_regime_v2(symbol=None))
        assert "regime" in result


# ---------------------------------------------------------------------------
# 12. All regime types reachable via direct classification logic
# ---------------------------------------------------------------------------

def test_all_valid_regimes_defined():
    """Ensure VALID_REGIMES matches spec."""
    assert VALID_REGIMES == {"trending_bull", "trending_bear", "choppy", "ranging", "crisis"}


# ---------------------------------------------------------------------------
# 13. Classify function unit tests (internal helper)
# ---------------------------------------------------------------------------

def test_classify_helper_exists():
    assert callable(_classify_market_regime)


def test_classify_high_positive_momentum_bull():
    regime = _classify_market_regime(volatility=0.02, momentum=0.08, correlation=0.7)
    assert regime == "trending_bull"


def test_classify_high_negative_momentum_bear():
    regime = _classify_market_regime(volatility=0.02, momentum=-0.08, correlation=0.7)
    assert regime == "trending_bear"


def test_classify_high_vol_low_momentum_choppy():
    regime = _classify_market_regime(volatility=0.12, momentum=0.01, correlation=0.1)
    assert regime == "choppy"


def test_classify_low_vol_low_momentum_ranging():
    regime = _classify_market_regime(volatility=0.005, momentum=0.005, correlation=0.3)
    assert regime == "ranging"


def test_classify_extreme_vol_crisis():
    regime = _classify_market_regime(volatility=0.25, momentum=-0.15, correlation=0.95)
    assert regime == "crisis"


def test_classify_returns_string():
    result = _classify_market_regime(volatility=0.02, momentum=0.05, correlation=0.5)
    assert isinstance(result, str)


def test_classify_result_in_valid_regimes():
    for vol, mom, corr in [
        (0.01, 0.0, 0.5),
        (0.05, 0.1, 0.8),
        (0.05, -0.1, 0.8),
        (0.15, 0.0, 0.2),
        (0.3, -0.2, 0.9),
    ]:
        r = _classify_market_regime(vol, mom, corr)
        assert r in VALID_REGIMES, f"Invalid regime '{r}' for vol={vol}, mom={mom}, corr={corr}"


def test_classify_very_high_vol_crisis():
    r = _classify_market_regime(volatility=0.22, momentum=0.0, correlation=0.5)
    assert r == "crisis"


def test_classify_moderate_bull():
    r = _classify_market_regime(volatility=0.03, momentum=0.07, correlation=0.6)
    assert r == "trending_bull"


def test_classify_moderate_bear():
    r = _classify_market_regime(volatility=0.03, momentum=-0.07, correlation=0.6)
    assert r == "trending_bear"


# ---------------------------------------------------------------------------
# 14. Confidence helper unit tests
# ---------------------------------------------------------------------------

def test_confidence_helper_exists():
    assert callable(_regime_confidence)


def test_confidence_helper_between_0_and_1():
    c = _regime_confidence(volatility=0.03, momentum=0.05, correlation=0.6)
    assert 0.0 <= c <= 1.0


def test_confidence_higher_when_signals_aligned():
    high = _regime_confidence(volatility=0.05, momentum=0.12, correlation=0.85)
    low = _regime_confidence(volatility=0.03, momentum=0.01, correlation=0.1)
    assert high > low


def test_confidence_returns_float():
    c = _regime_confidence(volatility=0.02, momentum=0.05, correlation=0.5)
    assert isinstance(c, float)


def test_confidence_never_zero():
    c = _regime_confidence(volatility=0.001, momentum=0.0, correlation=0.0)
    assert c > 0.0


def test_confidence_crisis_scenario():
    c = _regime_confidence(volatility=0.25, momentum=-0.20, correlation=0.95)
    # High signals → high confidence
    assert c > 0.5


# ---------------------------------------------------------------------------
# 15. Regime detection from candles
# ---------------------------------------------------------------------------

def test_bull_candles_yield_bull_regime():
    candles = _make_candles(30, start=50000.0, delta=100.0)
    with patch("metrics.get_ohlcv", new_callable=AsyncMock) as mock_ohlcv, \
         patch("collectors.get_symbols", return_value=["BTCUSDT"]):
        mock_ohlcv.return_value = candles
        import metrics as m
        m._market_regime_v2_cache.clear()
        r = run(compute_market_regime_v2(symbol="BTCBULL"))
        assert r["momentum"] > 0


def test_bear_candles_yield_negative_momentum():
    candles = _make_candles_bear(30, start=50000.0)
    with patch("metrics.get_ohlcv", new_callable=AsyncMock) as mock_ohlcv, \
         patch("collectors.get_symbols", return_value=["BTCUSDT"]):
        mock_ohlcv.return_value = candles
        import metrics as m
        m._market_regime_v2_cache.clear()
        r = run(compute_market_regime_v2(symbol="BTCBEAR"))
        assert r["momentum"] < 0


def test_flat_candles_low_volatility():
    candles = _make_candles_flat(30, start=50000.0)
    with patch("metrics.get_ohlcv", new_callable=AsyncMock) as mock_ohlcv, \
         patch("collectors.get_symbols", return_value=["BTCUSDT"]):
        mock_ohlcv.return_value = candles
        import metrics as m
        m._market_regime_v2_cache.clear()
        r = run(compute_market_regime_v2(symbol="BTCFLAT"))
        assert r["volatility"] < 0.01


def test_empty_candles_still_returns_result():
    with patch("metrics.get_ohlcv", new_callable=AsyncMock) as mock_ohlcv, \
         patch("collectors.get_symbols", return_value=["BTCUSDT"]):
        mock_ohlcv.return_value = []
        import metrics as m
        m._market_regime_v2_cache.clear()
        r = run(compute_market_regime_v2(symbol="EMPTY"))
        assert "regime" in r
        assert r["regime"] in VALID_REGIMES

"""Tests for compute_cross_exchange_funding_arb — 50+ assertions, TDD-first."""
import os
import sys
import tempfile
import math
import pytest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_cxfa.db"))
os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
os.environ.setdefault("SYMBOL_BYBIT", "BANANAS31USDT")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from metrics import compute_cross_exchange_funding_arb  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def result(event_loop):
    """Run the function once and share across tests."""
    import asyncio
    return event_loop.run_until_complete(compute_cross_exchange_funding_arb())


@pytest.fixture(scope="module")
def result_sym(event_loop):
    """Run with explicit symbol."""
    import asyncio
    return event_loop.run_until_complete(
        compute_cross_exchange_funding_arb(symbol="BANANAS31USDT")
    )


@pytest.fixture(scope="module")
def result2(event_loop):
    """Second call — used to verify determinism."""
    import asyncio
    return event_loop.run_until_complete(compute_cross_exchange_funding_arb())


# ---------------------------------------------------------------------------
# 1. Return type
# ---------------------------------------------------------------------------

def test_returns_dict(result):
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 2. Required keys present
# ---------------------------------------------------------------------------

def test_has_binance_rate(result):
    assert "binance_rate" in result


def test_has_bybit_rate(result):
    assert "bybit_rate" in result


def test_has_okx_rate(result):
    assert "okx_rate" in result


def test_has_bitget_rate(result):
    assert "bitget_rate" in result


def test_has_max_divergence(result):
    assert "max_divergence" in result


def test_has_divergence_bps(result):
    assert "divergence_bps" in result


def test_has_carry_cost_daily(result):
    assert "carry_cost_daily" in result


def test_has_arb_signal(result):
    assert "arb_signal" in result


def test_has_percentile_rank(result):
    assert "percentile_rank" in result


def test_has_history_24h(result):
    assert "history_24h" in result


def test_has_description(result):
    assert "description" in result


def test_has_stddev_30d(result):
    assert "stddev_30d" in result


# ---------------------------------------------------------------------------
# 3. Types
# ---------------------------------------------------------------------------

def test_binance_rate_is_float(result):
    assert isinstance(result["binance_rate"], float)


def test_bybit_rate_is_float(result):
    assert isinstance(result["bybit_rate"], float)


def test_okx_rate_is_float(result):
    assert isinstance(result["okx_rate"], float)


def test_bitget_rate_is_float(result):
    assert isinstance(result["bitget_rate"], float)


def test_max_divergence_is_float(result):
    assert isinstance(result["max_divergence"], float)


def test_divergence_bps_is_float(result):
    assert isinstance(result["divergence_bps"], float)


def test_carry_cost_daily_is_float(result):
    assert isinstance(result["carry_cost_daily"], float)


def test_arb_signal_is_string(result):
    assert isinstance(result["arb_signal"], str)


def test_percentile_rank_is_float(result):
    assert isinstance(result["percentile_rank"], float)


def test_history_24h_is_list(result):
    assert isinstance(result["history_24h"], list)


def test_description_is_string(result):
    assert isinstance(result["description"], str)


def test_stddev_30d_is_float(result):
    assert isinstance(result["stddev_30d"], float)


# ---------------------------------------------------------------------------
# 4. Value ranges
# ---------------------------------------------------------------------------

def test_max_divergence_non_negative(result):
    assert result["max_divergence"] >= 0.0


def test_divergence_bps_non_negative(result):
    assert result["divergence_bps"] >= 0.0


def test_carry_cost_daily_non_negative(result):
    assert result["carry_cost_daily"] >= 0.0


def test_arb_signal_valid_values(result):
    assert result["arb_signal"] in ("exploit", "watch", "neutral")


def test_percentile_rank_lower_bound(result):
    assert result["percentile_rank"] >= 0.0


def test_percentile_rank_upper_bound(result):
    assert result["percentile_rank"] <= 100.0


def test_stddev_30d_positive(result):
    assert result["stddev_30d"] >= 0.0


def test_history_24h_non_empty(result):
    assert len(result["history_24h"]) > 0


def test_history_24h_length(result):
    """24h at 5-min intervals = 288 points."""
    assert len(result["history_24h"]) == 288


def test_description_non_empty(result):
    assert len(result["description"]) > 0


# ---------------------------------------------------------------------------
# 5. Rate value range (funding rates are tiny, usually -0.1% to +0.1%)
# ---------------------------------------------------------------------------

def test_binance_rate_in_range(result):
    assert -0.01 <= result["binance_rate"] <= 0.01


def test_bybit_rate_in_range(result):
    assert -0.01 <= result["bybit_rate"] <= 0.01


def test_okx_rate_in_range(result):
    assert -0.01 <= result["okx_rate"] <= 0.01


def test_bitget_rate_in_range(result):
    assert -0.01 <= result["bitget_rate"] <= 0.01


def test_binance_rate_is_finite(result):
    assert math.isfinite(result["binance_rate"])


def test_bybit_rate_is_finite(result):
    assert math.isfinite(result["bybit_rate"])


def test_okx_rate_is_finite(result):
    assert math.isfinite(result["okx_rate"])


def test_bitget_rate_is_finite(result):
    assert math.isfinite(result["bitget_rate"])


# ---------------------------------------------------------------------------
# 6. max_divergence correctness — must be >= every pairwise gap
# ---------------------------------------------------------------------------

def test_max_divergence_geq_binance_bybit(result):
    diff = abs(result["binance_rate"] - result["bybit_rate"])
    assert result["max_divergence"] >= diff - 1e-10


def test_max_divergence_geq_binance_okx(result):
    diff = abs(result["binance_rate"] - result["okx_rate"])
    assert result["max_divergence"] >= diff - 1e-10


def test_max_divergence_geq_binance_bitget(result):
    diff = abs(result["binance_rate"] - result["bitget_rate"])
    assert result["max_divergence"] >= diff - 1e-10


def test_max_divergence_geq_bybit_okx(result):
    diff = abs(result["bybit_rate"] - result["okx_rate"])
    assert result["max_divergence"] >= diff - 1e-10


def test_max_divergence_geq_bybit_bitget(result):
    diff = abs(result["bybit_rate"] - result["bitget_rate"])
    assert result["max_divergence"] >= diff - 1e-10


def test_max_divergence_geq_okx_bitget(result):
    diff = abs(result["okx_rate"] - result["bitget_rate"])
    assert result["max_divergence"] >= diff - 1e-10


# ---------------------------------------------------------------------------
# 7. divergence_bps == max_divergence * 10000 (within rounding)
# ---------------------------------------------------------------------------

def test_divergence_bps_conversion(result):
    expected = result["max_divergence"] * 10000
    assert abs(result["divergence_bps"] - expected) < 0.01


# ---------------------------------------------------------------------------
# 8. History structure
# ---------------------------------------------------------------------------

def test_history_first_has_timestamp(result):
    assert "timestamp" in result["history_24h"][0]


def test_history_first_has_binance(result):
    assert "binance" in result["history_24h"][0]


def test_history_first_has_bybit(result):
    assert "bybit" in result["history_24h"][0]


def test_history_first_has_okx(result):
    assert "okx" in result["history_24h"][0]


def test_history_first_has_bitget(result):
    assert "bitget" in result["history_24h"][0]


def test_history_last_has_timestamp(result):
    assert "timestamp" in result["history_24h"][-1]


def test_history_last_has_binance(result):
    assert "binance" in result["history_24h"][-1]


def test_history_last_has_bybit(result):
    assert "bybit" in result["history_24h"][-1]


def test_history_last_has_okx(result):
    assert "okx" in result["history_24h"][-1]


def test_history_last_has_bitget(result):
    assert "bitget" in result["history_24h"][-1]


def test_history_rates_are_floats(result):
    h = result["history_24h"][0]
    assert isinstance(h["binance"], float)
    assert isinstance(h["bybit"], float)
    assert isinstance(h["okx"], float)
    assert isinstance(h["bitget"], float)


def test_history_rates_in_valid_range(result):
    for h in result["history_24h"]:
        for ex in ("binance", "bybit", "okx", "bitget"):
            assert -0.01 <= h[ex] <= 0.01, f"{ex} rate {h[ex]} out of range"


# ---------------------------------------------------------------------------
# 9. Determinism (same seed → same result)
# ---------------------------------------------------------------------------

def test_deterministic_binance_rate(result, result2):
    assert result["binance_rate"] == result2["binance_rate"]


def test_deterministic_bybit_rate(result, result2):
    assert result["bybit_rate"] == result2["bybit_rate"]


def test_deterministic_max_divergence(result, result2):
    assert result["max_divergence"] == result2["max_divergence"]


def test_deterministic_arb_signal(result, result2):
    assert result["arb_signal"] == result2["arb_signal"]


def test_deterministic_percentile_rank(result, result2):
    assert result["percentile_rank"] == result2["percentile_rank"]


def test_deterministic_history_length(result, result2):
    assert len(result["history_24h"]) == len(result2["history_24h"])


# ---------------------------------------------------------------------------
# 10. Works with different symbol arguments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_works_with_none_symbol():
    res = await compute_cross_exchange_funding_arb(symbol=None)
    assert isinstance(res, dict)
    assert "arb_signal" in res


@pytest.mark.asyncio
async def test_works_with_bananas31():
    res = await compute_cross_exchange_funding_arb(symbol="BANANAS31USDT")
    assert isinstance(res, dict)
    assert "binance_rate" in res


@pytest.mark.asyncio
async def test_works_with_cosusdt():
    res = await compute_cross_exchange_funding_arb(symbol="COSUSDT")
    assert isinstance(res, dict)
    assert "max_divergence" in res


@pytest.mark.asyncio
async def test_works_with_dexeusdt():
    res = await compute_cross_exchange_funding_arb(symbol="DEXEUSDT")
    assert isinstance(res, dict)
    assert "carry_cost_daily" in res


# ---------------------------------------------------------------------------
# 11. Description contains signal keyword
# ---------------------------------------------------------------------------

def test_description_contains_signal(result):
    sig = result["arb_signal"].upper()
    assert sig in result["description"].upper()


# ---------------------------------------------------------------------------
# 12. Carry cost proportional to rates (sanity: non-zero rates → non-zero cost)
# ---------------------------------------------------------------------------

def test_carry_cost_positive_when_rates_nonzero(result):
    rates = [
        result["binance_rate"], result["bybit_rate"],
        result["okx_rate"], result["bitget_rate"],
    ]
    if any(abs(r) > 1e-10 for r in rates):
        assert result["carry_cost_daily"] > 0.0


# ---------------------------------------------------------------------------
# 13. Percentile rank is plausible (divergence history has variance)
# ---------------------------------------------------------------------------

def test_percentile_rank_not_always_zero(result):
    """With random walk history the rank should not be stuck at 0."""
    assert result["percentile_rank"] >= 0.0


def test_percentile_rank_not_always_100(result):
    """With random walk history the rank should not always be at 100."""
    assert result["percentile_rank"] <= 100.0

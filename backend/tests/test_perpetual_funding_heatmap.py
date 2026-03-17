"""Tests for compute_perpetual_funding_heatmap (Wave 26, Task 1)."""
import asyncio
import pytest
from metrics import compute_perpetual_funding_heatmap

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def result():
    return run(compute_perpetual_funding_heatmap())


@pytest.fixture(scope="module")
def result2():
    return run(compute_perpetual_funding_heatmap())


# ── Return type ───────────────────────────────────────────────────────────────

def test_returns_dict(result):
    assert isinstance(result, dict)


# ── Top-level keys ────────────────────────────────────────────────────────────

def test_has_symbols_key(result):
    assert "symbols" in result

def test_has_exchanges_key(result):
    assert "exchanges" in result

def test_has_matrix_key(result):
    assert "matrix" in result

def test_has_funding_extremes_key(result):
    assert "funding_extremes" in result

def test_has_arbitrage_opportunities_key(result):
    assert "arbitrage_opportunities" in result

def test_has_avg_rates_key(result):
    assert "avg_rates" in result

def test_has_timestamp_key(result):
    assert "timestamp" in result


# ── symbols ───────────────────────────────────────────────────────────────────

def test_symbols_is_list(result):
    assert isinstance(result["symbols"], list)

def test_symbols_length(result):
    assert len(result["symbols"]) == 3

def test_symbols_contains_btc(result):
    assert "BTC" in result["symbols"]

def test_symbols_contains_eth(result):
    assert "ETH" in result["symbols"]

def test_symbols_contains_sol(result):
    assert "SOL" in result["symbols"]

def test_symbols_exact(result):
    assert result["symbols"] == ["BTC", "ETH", "SOL"]


# ── exchanges ─────────────────────────────────────────────────────────────────

def test_exchanges_is_list(result):
    assert isinstance(result["exchanges"], list)

def test_exchanges_length(result):
    assert len(result["exchanges"]) == 3

def test_exchanges_contains_binance(result):
    assert "binance" in result["exchanges"]

def test_exchanges_contains_bybit(result):
    assert "bybit" in result["exchanges"]

def test_exchanges_contains_okx(result):
    assert "okx" in result["exchanges"]

def test_exchanges_exact(result):
    assert result["exchanges"] == ["binance", "bybit", "okx"]


# ── matrix ────────────────────────────────────────────────────────────────────

def test_matrix_is_list(result):
    assert isinstance(result["matrix"], list)

def test_matrix_length(result):
    assert len(result["matrix"]) == 3

def test_matrix_entries_are_dicts(result):
    for entry in result["matrix"]:
        assert isinstance(entry, dict)

def test_matrix_entry_has_symbol(result):
    for entry in result["matrix"]:
        assert "symbol" in entry

def test_matrix_entry_has_binance(result):
    for entry in result["matrix"]:
        assert "binance" in entry

def test_matrix_entry_has_bybit(result):
    for entry in result["matrix"]:
        assert "bybit" in entry

def test_matrix_entry_has_okx(result):
    for entry in result["matrix"]:
        assert "okx" in entry

def test_matrix_rate_values_are_floats(result):
    for entry in result["matrix"]:
        for exc in ["binance", "bybit", "okx"]:
            assert isinstance(entry[exc], float)

def test_matrix_rates_in_expected_range(result):
    for entry in result["matrix"]:
        for exc in ["binance", "bybit", "okx"]:
            assert -0.1 <= entry[exc] <= 0.2, f"Rate {entry[exc]} out of range"

def test_matrix_symbols_match(result):
    matrix_syms = [e["symbol"] for e in result["matrix"]]
    assert set(matrix_syms) == {"BTC", "ETH", "SOL"}


# ── funding_extremes ──────────────────────────────────────────────────────────

def test_funding_extremes_is_dict(result):
    assert isinstance(result["funding_extremes"], dict)

def test_funding_extremes_has_max_symbol(result):
    assert "max_symbol" in result["funding_extremes"]

def test_funding_extremes_has_max_exchange(result):
    assert "max_exchange" in result["funding_extremes"]

def test_funding_extremes_has_max_rate(result):
    assert "max_rate" in result["funding_extremes"]

def test_funding_extremes_has_min_symbol(result):
    assert "min_symbol" in result["funding_extremes"]

def test_funding_extremes_has_min_exchange(result):
    assert "min_exchange" in result["funding_extremes"]

def test_funding_extremes_has_min_rate(result):
    assert "min_rate" in result["funding_extremes"]

def test_funding_extremes_max_symbol_valid(result):
    assert result["funding_extremes"]["max_symbol"] in ["BTC", "ETH", "SOL"]

def test_funding_extremes_min_symbol_valid(result):
    assert result["funding_extremes"]["min_symbol"] in ["BTC", "ETH", "SOL"]

def test_funding_extremes_max_exchange_valid(result):
    assert result["funding_extremes"]["max_exchange"] in ["binance", "bybit", "okx"]

def test_funding_extremes_min_exchange_valid(result):
    assert result["funding_extremes"]["min_exchange"] in ["binance", "bybit", "okx"]

def test_funding_extremes_max_rate_is_float(result):
    assert isinstance(result["funding_extremes"]["max_rate"], float)

def test_funding_extremes_min_rate_is_float(result):
    assert isinstance(result["funding_extremes"]["min_rate"], float)

def test_funding_extremes_max_gte_min(result):
    assert result["funding_extremes"]["max_rate"] >= result["funding_extremes"]["min_rate"]


# ── arbitrage_opportunities ───────────────────────────────────────────────────

def test_arbitrage_opportunities_is_list(result):
    assert isinstance(result["arbitrage_opportunities"], list)

def test_arbitrage_opps_entries_are_dicts(result):
    for opp in result["arbitrage_opportunities"]:
        assert isinstance(opp, dict)

def test_arbitrage_opps_have_symbol(result):
    for opp in result["arbitrage_opportunities"]:
        assert "symbol" in opp

def test_arbitrage_opps_have_long_exchange(result):
    for opp in result["arbitrage_opportunities"]:
        assert "long_exchange" in opp

def test_arbitrage_opps_have_short_exchange(result):
    for opp in result["arbitrage_opportunities"]:
        assert "short_exchange" in opp

def test_arbitrage_opps_have_rate_diff_bps(result):
    for opp in result["arbitrage_opportunities"]:
        assert "rate_diff_bps" in opp

def test_arbitrage_opps_rate_diff_above_threshold(result):
    for opp in result["arbitrage_opportunities"]:
        assert opp["rate_diff_bps"] > 2.0

def test_arbitrage_opps_long_short_different(result):
    for opp in result["arbitrage_opportunities"]:
        assert opp["long_exchange"] != opp["short_exchange"]


# ── avg_rates ─────────────────────────────────────────────────────────────────

def test_avg_rates_is_dict(result):
    assert isinstance(result["avg_rates"], dict)

def test_avg_rates_has_btc(result):
    assert "BTC" in result["avg_rates"]

def test_avg_rates_has_eth(result):
    assert "ETH" in result["avg_rates"]

def test_avg_rates_has_sol(result):
    assert "SOL" in result["avg_rates"]

def test_avg_rates_keys_match_symbols(result):
    assert set(result["avg_rates"].keys()) == set(result["symbols"])

def test_avg_rates_are_floats(result):
    for sym, rate in result["avg_rates"].items():
        assert isinstance(rate, float)


# ── timestamp ─────────────────────────────────────────────────────────────────

def test_timestamp_is_string(result):
    assert isinstance(result["timestamp"], str)

def test_timestamp_not_empty(result):
    assert len(result["timestamp"]) > 0

def test_timestamp_format(result):
    import re
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", result["timestamp"])


# ── Determinism ───────────────────────────────────────────────────────────────

def test_deterministic_matrix(result, result2):
    assert result["matrix"] == result2["matrix"]

def test_deterministic_funding_extremes(result, result2):
    assert result["funding_extremes"] == result2["funding_extremes"]

def test_deterministic_avg_rates(result, result2):
    assert result["avg_rates"] == result2["avg_rates"]

def test_deterministic_symbols(result, result2):
    assert result["symbols"] == result2["symbols"]

def test_deterministic_exchanges(result, result2):
    assert result["exchanges"] == result2["exchanges"]

def test_deterministic_arb_opportunities(result, result2):
    assert result["arbitrage_opportunities"] == result2["arbitrage_opportunities"]

def test_deterministic_arb_count(result, result2):
    assert len(result["arbitrage_opportunities"]) == len(result2["arbitrage_opportunities"])

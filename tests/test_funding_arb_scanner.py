"""
Tests for Funding Rate Arbitrage Scanner (Wave 23 Task 5, Issue #119).

TDD: tests written before implementation.
Covers:
  - scan_funding_rates: 6 symbols × 3 exchanges = 18 entries
  - compute_arb_pairs: one arb pair per symbol, sorted by spread_bps
  - flag_extreme_pairs: is_extreme flag logic
  - compute_funding_arb_scanner: top 3 pairs, avg_spread_bps, extreme_count
  - APR calculation: spread_pct * 3 * 365
  - Determinism: seeded mock gives same results every call
  - Performance: < 200ms
  - Frontend HTML: card-funding-arb-scanner, badge, content div
  - Frontend JS: renderFundingArbScanner, API call, signal colors
"""

import math
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from funding_arb_scanner import (
    EXCHANGES,
    EXTREME_MULTIPLIER,
    FUNDING_INTERVALS_PER_DAY,
    SYMBOLS,
    TOP_N,
    compute_arb_pairs,
    compute_funding_arb_scanner,
    flag_extreme_pairs,
    scan_funding_rates,
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def html_content():
    with open(os.path.join(FRONTEND_DIR, "index.html")) as f:
        return f.read()


@pytest.fixture(scope="module")
def js_content():
    with open(os.path.join(FRONTEND_DIR, "app.js")) as f:
        return f.read()


@pytest.fixture(scope="module")
def scanner_result():
    return compute_funding_arb_scanner()


@pytest.fixture(scope="module")
def rates():
    return scan_funding_rates()


@pytest.fixture(scope="module")
def all_pairs(rates):
    pairs = compute_arb_pairs(rates)
    return flag_extreme_pairs(pairs)


# ── Category 1: Return Shape ──────────────────────────────────────────────────


class TestReturnShape:
    def test_returns_dict(self, scanner_result):
        assert isinstance(scanner_result, dict)

    def test_has_top_pairs(self, scanner_result):
        assert "top_pairs" in scanner_result

    def test_has_all_pairs(self, scanner_result):
        assert "all_pairs" in scanner_result

    def test_has_avg_spread_bps(self, scanner_result):
        assert "avg_spread_bps" in scanner_result

    def test_has_extreme_count(self, scanner_result):
        assert "extreme_count" in scanner_result

    def test_has_timestamp(self, scanner_result):
        assert "timestamp" in scanner_result

    def test_timestamp_is_numeric(self, scanner_result):
        assert isinstance(scanner_result["timestamp"], (int, float))

    def test_avg_spread_bps_is_numeric(self, scanner_result):
        assert isinstance(scanner_result["avg_spread_bps"], (int, float))

    def test_extreme_count_is_non_negative_int(self, scanner_result):
        ec = scanner_result["extreme_count"]
        assert isinstance(ec, int)
        assert ec >= 0

    def test_top_pairs_is_list(self, scanner_result):
        assert isinstance(scanner_result["top_pairs"], list)

    def test_all_pairs_is_list(self, scanner_result):
        assert isinstance(scanner_result["all_pairs"], list)


# ── Category 2: Top Pairs Shape ───────────────────────────────────────────────


class TestTopPairsShape:
    def test_top_pairs_at_most_3(self, scanner_result):
        assert len(scanner_result["top_pairs"]) <= TOP_N

    def test_top_pairs_exactly_3_with_default_symbols(self, scanner_result):
        # 6 default symbols → 6 arb pairs → top 3 returned
        assert len(scanner_result["top_pairs"]) == TOP_N

    def test_top_pairs_sorted_by_spread_bps_descending(self, scanner_result):
        spreads = [p["spread_bps"] for p in scanner_result["top_pairs"]]
        assert spreads == sorted(spreads, reverse=True)

    def test_top_pairs_have_symbol(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert "symbol" in pair

    def test_top_pairs_have_long_exchange(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert "long_exchange" in pair

    def test_top_pairs_have_short_exchange(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert "short_exchange" in pair

    def test_top_pairs_have_long_rate_pct(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert "long_rate_pct" in pair

    def test_top_pairs_have_short_rate_pct(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert "short_rate_pct" in pair

    def test_top_pairs_have_spread_bps(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert "spread_bps" in pair

    def test_top_pairs_have_estimated_apr_pct(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert "estimated_apr_pct" in pair

    def test_top_pairs_have_is_extreme(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert "is_extreme" in pair

    def test_top_pairs_have_rank(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert "rank" in pair

    def test_top_pair_rank_starts_at_1(self, scanner_result):
        assert scanner_result["top_pairs"][0]["rank"] == 1

    def test_top_pair_ranks_are_sequential(self, scanner_result):
        ranks = [p["rank"] for p in scanner_result["top_pairs"]]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_exchanges_differ_per_pair(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert pair["long_exchange"] != pair["short_exchange"]

    def test_spread_bps_non_negative(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert pair["spread_bps"] >= 0

    def test_estimated_apr_non_negative(self, scanner_result):
        for pair in scanner_result["top_pairs"]:
            assert pair["estimated_apr_pct"] >= 0

    def test_top_pair_has_highest_spread(self, scanner_result):
        top_spread = scanner_result["top_pairs"][0]["spread_bps"]
        for pair in scanner_result["all_pairs"]:
            assert top_spread >= pair["spread_bps"]


# ── Category 3: All Pairs ─────────────────────────────────────────────────────


class TestAllPairs:
    def test_all_pairs_count_equals_symbol_count(self, scanner_result):
        assert len(scanner_result["all_pairs"]) == len(SYMBOLS)

    def test_all_pairs_sorted_by_spread_bps_descending(self, scanner_result):
        spreads = [p["spread_bps"] for p in scanner_result["all_pairs"]]
        assert spreads == sorted(spreads, reverse=True)

    def test_all_pairs_symbols_are_valid(self, scanner_result):
        for pair in scanner_result["all_pairs"]:
            assert pair["symbol"] in SYMBOLS

    def test_all_pairs_cover_all_symbols(self, scanner_result):
        result_symbols = {p["symbol"] for p in scanner_result["all_pairs"]}
        assert result_symbols == set(SYMBOLS)

    def test_extreme_count_matches_is_extreme_flags(self, scanner_result):
        count = sum(1 for p in scanner_result["all_pairs"] if p["is_extreme"])
        assert scanner_result["extreme_count"] == count


# ── Category 4: Computation Tests ─────────────────────────────────────────────


class TestScanFundingRates:
    def test_scan_returns_correct_count(self, rates):
        expected = len(SYMBOLS) * len(EXCHANGES)
        assert len(rates) == expected

    def test_each_rate_has_symbol(self, rates):
        for r in rates:
            assert "symbol" in r

    def test_each_rate_has_exchange(self, rates):
        for r in rates:
            assert "exchange" in r

    def test_each_rate_has_rate_pct(self, rates):
        for r in rates:
            assert "rate_pct" in r

    def test_rate_pct_in_valid_range(self, rates):
        for r in rates:
            assert -0.15 <= r["rate_pct"] <= 0.15

    def test_exchanges_include_binance(self, rates):
        exchanges = {r["exchange"] for r in rates}
        assert "binance" in exchanges

    def test_exchanges_include_bybit(self, rates):
        exchanges = {r["exchange"] for r in rates}
        assert "bybit" in exchanges

    def test_exchanges_include_okx(self, rates):
        exchanges = {r["exchange"] for r in rates}
        assert "okx" in exchanges


class TestComputeArbPairs:
    def test_arb_pairs_one_per_symbol(self, rates):
        pairs = compute_arb_pairs(rates)
        assert len(pairs) == len(SYMBOLS)

    def test_long_rate_lte_short_rate(self, rates):
        pairs = compute_arb_pairs(rates)
        for pair in pairs:
            assert pair["long_rate_pct"] <= pair["short_rate_pct"]

    def test_spread_bps_matches_formula(self, rates):
        pairs = compute_arb_pairs(rates)
        for pair in pairs:
            expected = (pair["short_rate_pct"] - pair["long_rate_pct"]) * 100
            assert abs(pair["spread_bps"] - expected) < 0.01

    def test_apr_matches_formula(self, rates):
        pairs = compute_arb_pairs(rates)
        for pair in pairs:
            spread_pct = pair["short_rate_pct"] - pair["long_rate_pct"]
            expected_apr = spread_pct * FUNDING_INTERVALS_PER_DAY * 365
            assert abs(pair["estimated_apr_pct"] - expected_apr) < 0.1

    def test_pairs_sorted_by_spread_descending(self, rates):
        pairs = compute_arb_pairs(rates)
        spreads = [p["spread_bps"] for p in pairs]
        assert spreads == sorted(spreads, reverse=True)


class TestDeterminism:
    def test_same_results_on_repeated_calls(self):
        r1 = compute_funding_arb_scanner()
        r2 = compute_funding_arb_scanner()
        assert r1["top_pairs"][0]["symbol"] == r2["top_pairs"][0]["symbol"]
        assert r1["top_pairs"][0]["spread_bps"] == r2["top_pairs"][0]["spread_bps"]
        assert r1["avg_spread_bps"] == r2["avg_spread_bps"]
        assert r1["extreme_count"] == r2["extreme_count"]

    def test_rates_differ_across_exchanges_same_symbol(self, rates):
        btc_rates = [r["rate_pct"] for r in rates if r["symbol"] == "BTCUSDT"]
        assert len(set(btc_rates)) > 1

    def test_rates_differ_across_symbols_same_exchange(self, rates):
        binance_rates = [r["rate_pct"] for r in rates if r["exchange"] == "binance"]
        assert len(set(binance_rates)) > 1


# ── Category 5: Extreme Flags ─────────────────────────────────────────────────


class TestExtremeFlags:
    def test_extreme_pairs_have_high_spread(self, scanner_result):
        avg = scanner_result["avg_spread_bps"]
        threshold = avg * EXTREME_MULTIPLIER
        for pair in scanner_result["all_pairs"]:
            if pair["is_extreme"]:
                assert pair["spread_bps"] > threshold

    def test_non_extreme_pairs_have_low_spread(self, scanner_result):
        avg = scanner_result["avg_spread_bps"]
        threshold = avg * EXTREME_MULTIPLIER
        for pair in scanner_result["all_pairs"]:
            if not pair["is_extreme"]:
                assert pair["spread_bps"] <= threshold

    def test_is_extreme_is_bool(self, scanner_result):
        for pair in scanner_result["all_pairs"]:
            assert isinstance(pair["is_extreme"], bool)


# ── Category 6: Performance ────────────────────────────────────────────────────


class TestPerformance:
    def test_response_under_200ms(self):
        t0 = time.time()
        compute_funding_arb_scanner()
        elapsed_ms = (time.time() - t0) * 1000
        assert elapsed_ms < 200, f"Took {elapsed_ms:.0f}ms, expected <200ms"


# ── Category 7: Frontend HTML ─────────────────────────────────────────────────


class TestFrontendHtml:
    def test_card_id_exists(self, html_content):
        assert "card-funding-arb-scanner" in html_content

    def test_card_has_content_div(self, html_content):
        assert "funding-arb-scanner-content" in html_content

    def test_card_has_badge_span(self, html_content):
        assert "funding-arb-scanner-badge" in html_content

    def test_card_has_title(self, html_content):
        assert "Funding Arb" in html_content or "Funding Rate Arb" in html_content

    def test_card_has_meta_description(self, html_content):
        assert "arb" in html_content.lower() or "APR" in html_content


# ── Category 8: Frontend JS ───────────────────────────────────────────────────


class TestFrontendJs:
    def test_render_function_exists(self, js_content):
        assert "renderFundingArbScanner" in js_content

    def test_api_endpoint_wired(self, js_content):
        assert "/api/funding-arb-scanner" in js_content

    def test_badge_id_referenced(self, js_content):
        assert "funding-arb-scanner-badge" in js_content

    def test_top_pairs_referenced(self, js_content):
        assert "top_pairs" in js_content

    def test_estimated_apr_referenced(self, js_content):
        assert "estimated_apr_pct" in js_content

    def test_spread_bps_referenced(self, js_content):
        assert "spread_bps" in js_content

    def test_render_in_refresh_loop(self, js_content):
        assert "safe(renderFundingArbScanner)" in js_content

    def test_is_extreme_referenced(self, js_content):
        assert "is_extreme" in js_content

    def test_content_div_referenced(self, js_content):
        assert "funding-arb-scanner-content" in js_content

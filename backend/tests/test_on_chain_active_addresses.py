"""Tests for compute_on_chain_active_addresses (Wave 26, Issue 156)."""

import asyncio
import re
import pytest
from metrics import compute_on_chain_active_addresses

# ── Helpers ───────────────────────────────────────────────────────────────────


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def result():
    return run(compute_on_chain_active_addresses())


@pytest.fixture(scope="module")
def result2():
    return run(compute_on_chain_active_addresses())


# ── Return type ───────────────────────────────────────────────────────────────


def test_returns_dict(result):
    assert isinstance(result, dict)


# ── Top-level keys ────────────────────────────────────────────────────────────


def test_has_active_addresses_24h(result):
    assert "active_addresses_24h" in result


def test_has_active_addresses_7d_avg(result):
    assert "active_addresses_7d_avg" in result


def test_has_growth_rate_7d(result):
    assert "growth_rate_7d" in result


def test_has_growth_rate_30d(result):
    assert "growth_rate_30d" in result


def test_has_trend(result):
    assert "trend" in result


def test_has_price_correlation_30d(result):
    assert "price_correlation_30d" in result


def test_has_historical_daily(result):
    assert "historical_daily" in result


def test_has_network_utilization(result):
    assert "network_utilization" in result


def test_has_new_addresses_ratio(result):
    assert "new_addresses_ratio" in result


def test_has_timestamp(result):
    assert "timestamp" in result


# ── active_addresses_24h ──────────────────────────────────────────────────────


def test_active_addresses_24h_is_int(result):
    assert isinstance(result["active_addresses_24h"], int)


def test_active_addresses_24h_positive(result):
    assert result["active_addresses_24h"] > 0


def test_active_addresses_24h_in_range(result):
    assert 100_000 <= result["active_addresses_24h"] <= 5_000_000


# ── active_addresses_7d_avg ───────────────────────────────────────────────────


def test_active_addresses_7d_avg_is_int(result):
    assert isinstance(result["active_addresses_7d_avg"], int)


def test_active_addresses_7d_avg_positive(result):
    assert result["active_addresses_7d_avg"] > 0


def test_active_addresses_7d_avg_in_range(result):
    assert 100_000 <= result["active_addresses_7d_avg"] <= 5_000_000


# ── growth_rate_7d ────────────────────────────────────────────────────────────


def test_growth_rate_7d_is_float(result):
    assert isinstance(result["growth_rate_7d"], float)


def test_growth_rate_7d_in_range(result):
    assert -50.0 <= result["growth_rate_7d"] <= 50.0


# ── growth_rate_30d ───────────────────────────────────────────────────────────


def test_growth_rate_30d_is_float(result):
    assert isinstance(result["growth_rate_30d"], float)


def test_growth_rate_30d_in_range(result):
    assert -50.0 <= result["growth_rate_30d"] <= 50.0


# ── trend ─────────────────────────────────────────────────────────────────────


def test_trend_is_string(result):
    assert isinstance(result["trend"], str)


def test_trend_not_empty(result):
    assert len(result["trend"]) > 0


def test_trend_valid_value(result):
    assert result["trend"] in ("growing", "declining", "stable")


# ── price_correlation_30d ─────────────────────────────────────────────────────


def test_price_correlation_30d_is_float(result):
    assert isinstance(result["price_correlation_30d"], float)


def test_price_correlation_30d_in_range(result):
    assert -1.0 <= result["price_correlation_30d"] <= 1.0


# ── historical_daily ──────────────────────────────────────────────────────────


def test_historical_daily_is_list(result):
    assert isinstance(result["historical_daily"], list)


def test_historical_daily_length(result):
    assert len(result["historical_daily"]) == 30


def test_historical_daily_entries_are_dicts(result):
    for entry in result["historical_daily"]:
        assert isinstance(entry, dict)


def test_historical_daily_has_date_key(result):
    for entry in result["historical_daily"]:
        assert "date" in entry


def test_historical_daily_has_count_key(result):
    for entry in result["historical_daily"]:
        assert "count" in entry


def test_historical_daily_date_format(result):
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for entry in result["historical_daily"]:
        assert pattern.match(entry["date"]), f"Bad date format: {entry['date']}"


def test_historical_daily_count_is_int(result):
    for entry in result["historical_daily"]:
        assert isinstance(entry["count"], int)


def test_historical_daily_count_positive(result):
    for entry in result["historical_daily"]:
        assert entry["count"] > 0


def test_historical_daily_dates_unique(result):
    dates = [e["date"] for e in result["historical_daily"]]
    assert len(dates) == len(set(dates))


def test_historical_daily_dates_ordered(result):
    dates = [e["date"] for e in result["historical_daily"]]
    assert dates == sorted(dates)


def test_historical_daily_last_date_is_today(result):
    assert result["historical_daily"][-1]["date"] == "2026-03-17"


# ── network_utilization ───────────────────────────────────────────────────────


def test_network_utilization_is_float(result):
    assert isinstance(result["network_utilization"], float)


def test_network_utilization_in_range(result):
    assert 0.0 <= result["network_utilization"] <= 1.0


# ── new_addresses_ratio ───────────────────────────────────────────────────────


def test_new_addresses_ratio_is_float(result):
    assert isinstance(result["new_addresses_ratio"], float)


def test_new_addresses_ratio_in_range(result):
    assert 0.0 <= result["new_addresses_ratio"] <= 1.0


# ── timestamp ─────────────────────────────────────────────────────────────────


def test_timestamp_is_string(result):
    assert isinstance(result["timestamp"], str)


def test_timestamp_not_empty(result):
    assert len(result["timestamp"]) > 0


def test_timestamp_format(result):
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", result["timestamp"])


# ── Determinism ───────────────────────────────────────────────────────────────


def test_deterministic_active_addresses_24h(result, result2):
    assert result["active_addresses_24h"] == result2["active_addresses_24h"]


def test_deterministic_active_addresses_7d_avg(result, result2):
    assert result["active_addresses_7d_avg"] == result2["active_addresses_7d_avg"]


def test_deterministic_growth_rate_7d(result, result2):
    assert result["growth_rate_7d"] == result2["growth_rate_7d"]


def test_deterministic_growth_rate_30d(result, result2):
    assert result["growth_rate_30d"] == result2["growth_rate_30d"]


def test_deterministic_trend(result, result2):
    assert result["trend"] == result2["trend"]


def test_deterministic_price_correlation_30d(result, result2):
    assert result["price_correlation_30d"] == result2["price_correlation_30d"]


def test_deterministic_historical_daily(result, result2):
    assert result["historical_daily"] == result2["historical_daily"]


def test_deterministic_network_utilization(result, result2):
    assert result["network_utilization"] == result2["network_utilization"]


def test_deterministic_new_addresses_ratio(result, result2):
    assert result["new_addresses_ratio"] == result2["new_addresses_ratio"]


def test_deterministic_historical_daily_length(result, result2):
    assert len(result["historical_daily"]) == len(result2["historical_daily"])


# ── Extra value checks ────────────────────────────────────────────────────────


def test_historical_daily_first_date(result):
    assert result["historical_daily"][0]["date"] == "2026-02-16"


def test_historical_daily_count_in_reasonable_range(result):
    for entry in result["historical_daily"]:
        assert 10_000 <= entry["count"] <= 10_000_000


def test_historical_daily_no_extra_keys(result):
    allowed = {"date", "count"}
    for entry in result["historical_daily"]:
        assert set(entry.keys()) == allowed


def test_top_level_key_count(result):
    assert len(result) == 10


def test_growth_rate_7d_rounded_to_2dp(result):
    val = result["growth_rate_7d"]
    assert round(val, 2) == val


def test_growth_rate_30d_rounded_to_2dp(result):
    val = result["growth_rate_30d"]
    assert round(val, 2) == val


def test_network_utilization_rounded(result):
    val = result["network_utilization"]
    assert round(val, 4) == val


def test_new_addresses_ratio_rounded(result):
    val = result["new_addresses_ratio"]
    assert round(val, 4) == val

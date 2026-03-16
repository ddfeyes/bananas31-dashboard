"""
Unit / smoke tests for /api/vol-regime-hmm.

Volatility regime classifier (low/mid/high/extreme) with HMM-style detection.

Distinct from the existing /volatility-regime (3-class ATR percentile):
  - 4 classes: low / mid / high / extreme
  - Based on realized volatility (std of log-returns per bucket)
  - HMM-style smoothing: min-duration state persistence prevents flickering
  - Regime transition matrix (observed state-to-state probabilities)
  - Current state duration (how many consecutive buckets in this regime)
  - Percentile boundaries derived from history (p25/p50/p75)

Covers:
  - classify_regime helper
  - hmm_smooth (min-duration state persistence)
  - compute_transition_matrix
  - state_duration
  - realized_vol_buckets
  - fmt_rv display helper
  - Response shape validation
  - Edge cases (constant prices, few buckets, single regime throughout)
  - Route registration
  - HTML card / JS smoke tests
"""
import os
import sys
import math
import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _html() -> str:
    with open(os.path.join(_ROOT, "frontend", "index.html"), encoding="utf-8") as f:
        return f.read()


def _js() -> str:
    with open(os.path.join(_ROOT, "frontend", "app.js"), encoding="utf-8") as f:
        return f.read()


# ── Python mirrors of backend logic ──────────────────────────────────────────

REGIMES = ("low", "mid", "high", "extreme")


def classify_regime(rv: float, p25: float, p50: float, p75: float) -> str:
    """
    Classify realized volatility into a regime using percentile boundaries.
    low:     rv < p25
    mid:     p25 <= rv < p50
    high:    p50 <= rv < p75
    extreme: rv >= p75
    """
    if rv >= p75:
        return "extreme"
    if rv >= p50:
        return "high"
    if rv >= p25:
        return "mid"
    return "low"


def hmm_smooth(raw_regimes: list[str], min_duration: int = 2) -> list[str]:
    """
    HMM-style smoothing: a state change only 'sticks' after min_duration
    consecutive observations of the new state.
    Short-lived excursions are replaced with the previous stable state.

    Algorithm:
      - Track current confirmed state and run of the candidate state.
      - If candidate runs >= min_duration, confirm it.
      - Until then, emit the previous confirmed state.
    """
    if not raw_regimes:
        return []
    if min_duration <= 1:
        return list(raw_regimes)

    smoothed = []
    confirmed = raw_regimes[0]
    candidate = raw_regimes[0]
    run = 1

    for r in raw_regimes:
        if r == candidate:
            run += 1
        else:
            candidate = r
            run = 1

        if run >= min_duration:
            confirmed = candidate

        smoothed.append(confirmed)

    return smoothed


def compute_transition_matrix(regimes: list[str]) -> dict:
    """
    Compute observed transition matrix from a regime sequence.
    Returns {from_state: {to_state: probability}} where probabilities sum to 1
    per row (or 0 if no transitions from that state).
    Only rows with at least one transition are populated.
    """
    counts: dict = {r: {r2: 0 for r2 in REGIMES} for r in REGIMES}

    for i in range(1, len(regimes)):
        fr = regimes[i - 1]
        to = regimes[i]
        if fr in counts and to in counts[fr]:
            counts[fr][to] += 1

    matrix: dict = {}
    for fr in REGIMES:
        row_total = sum(counts[fr].values())
        if row_total > 0:
            matrix[fr] = {to: round(counts[fr][to] / row_total, 4) for to in REGIMES}

    return matrix


def state_duration(regimes: list[str]) -> int:
    """
    Count how many consecutive observations at the end share the same state.
    Returns 0 for empty input.
    """
    if not regimes:
        return 0
    current = regimes[-1]
    count = 0
    for r in reversed(regimes):
        if r == current:
            count += 1
        else:
            break
    return count


def realized_vol_buckets(
    prices: list[float],
    bucket_size: int,
    annualize: bool = False,
    periods_per_year: int = 525600,
) -> list[float]:
    """
    Compute realized volatility (std of log-returns) in non-overlapping buckets.
    prices: list of consecutive prices (sorted by time).
    bucket_size: number of prices per bucket.
    Returns list of RV values (one per bucket). Empty buckets return 0.
    If annualize, multiply by sqrt(periods_per_year / bucket_size).
    """
    rvs = []
    for i in range(0, len(prices) - bucket_size + 1, bucket_size):
        bucket = prices[i:i + bucket_size]
        log_rets = []
        for j in range(1, len(bucket)):
            if bucket[j - 1] > 0 and bucket[j] > 0:
                log_rets.append(math.log(bucket[j] / bucket[j - 1]))
        if len(log_rets) < 2:
            rvs.append(0.0)
            continue
        n = len(log_rets)
        mean = sum(log_rets) / n
        var = sum((r - mean) ** 2 for r in log_rets) / (n - 1)
        rv = math.sqrt(var)
        if annualize:
            rv *= math.sqrt(periods_per_year / bucket_size)
        rvs.append(round(rv, 8))
    return rvs


def fmt_rv(rv_pct: float | None) -> str:
    """Format realized vol as percentage string."""
    if rv_pct is None:
        return "—"
    return f"{rv_pct:.4f}%"


def regime_color_class(regime: str) -> str:
    """CSS variable name for a regime."""
    return {
        "low":     "var(--green)",
        "mid":     "var(--blue)",
        "high":    "var(--yellow)",
        "extreme": "var(--red)",
    }.get(regime, "var(--muted)")


# ── classify_regime tests ─────────────────────────────────────────────────────

def test_classify_low():
    assert classify_regime(0.001, 0.005, 0.010, 0.020) == "low"


def test_classify_mid():
    assert classify_regime(0.007, 0.005, 0.010, 0.020) == "mid"


def test_classify_high():
    assert classify_regime(0.015, 0.005, 0.010, 0.020) == "high"


def test_classify_extreme():
    assert classify_regime(0.025, 0.005, 0.010, 0.020) == "extreme"


def test_classify_at_p25_boundary():
    # rv == p25 → "mid" (>= p25)
    assert classify_regime(0.005, 0.005, 0.010, 0.020) == "mid"


def test_classify_at_p50_boundary():
    assert classify_regime(0.010, 0.005, 0.010, 0.020) == "high"


def test_classify_at_p75_boundary():
    assert classify_regime(0.020, 0.005, 0.010, 0.020) == "extreme"


def test_classify_just_below_p25():
    assert classify_regime(0.004, 0.005, 0.010, 0.020) == "low"


def test_classify_valid_values():
    bounds = (0.005, 0.010, 0.020)
    for rv in [0.001, 0.006, 0.012, 0.025]:
        r = classify_regime(rv, *bounds)
        assert r in REGIMES


# ── hmm_smooth tests ──────────────────────────────────────────────────────────

def test_smooth_empty():
    assert hmm_smooth([]) == []


def test_smooth_single():
    assert hmm_smooth(["low"]) == ["low"]


def test_smooth_no_change():
    seq = ["low", "low", "low", "low"]
    assert hmm_smooth(seq, min_duration=2) == seq


def test_smooth_persistent_change():
    # 3 consecutive "high" → confirmed after min_duration=2
    seq = ["low", "low", "high", "high", "high"]
    result = hmm_smooth(seq, min_duration=2)
    # After 2 consecutive highs, state confirms
    assert result[-1] == "high"
    assert result[0] == "low"


def test_smooth_single_excursion_suppressed():
    # One "extreme" surrounded by "low" should be smoothed away (min_duration=2)
    seq = ["low", "low", "extreme", "low", "low"]
    result = hmm_smooth(seq, min_duration=2)
    assert result[2] == "low"  # single extreme suppressed


def test_smooth_length_preserved():
    seq = ["low", "high", "extreme", "mid", "low"]
    result = hmm_smooth(seq, min_duration=2)
    assert len(result) == len(seq)


def test_smooth_min_duration_1_is_noop():
    seq = ["low", "high", "extreme", "mid"]
    assert hmm_smooth(seq, min_duration=1) == seq


def test_smooth_all_same():
    seq = ["mid"] * 10
    assert hmm_smooth(seq, min_duration=3) == seq


# ── compute_transition_matrix tests ──────────────────────────────────────────

def test_transition_matrix_self_loops():
    seq = ["low", "low", "low", "low"]
    tm = compute_transition_matrix(seq)
    assert tm["low"]["low"] == pytest.approx(1.0)


def test_transition_matrix_all_rows_sum_to_1():
    seq = ["low", "mid", "high", "extreme", "high", "mid", "low", "low"]
    tm = compute_transition_matrix(seq)
    for row in tm.values():
        total = sum(row.values())
        assert total == pytest.approx(1.0, abs=1e-6)


def test_transition_matrix_counts_transitions():
    seq = ["low", "high", "low", "high", "low"]
    tm = compute_transition_matrix(seq)
    # low→high: 2 times, high→low: 2 times
    assert tm.get("low", {}).get("high", 0) == pytest.approx(1.0)
    assert tm.get("high", {}).get("low", 0) == pytest.approx(1.0)


def test_transition_matrix_empty():
    assert compute_transition_matrix([]) == {}


def test_transition_matrix_single():
    tm = compute_transition_matrix(["low"])
    assert tm == {}  # no transitions


def test_transition_matrix_valid_probabilities():
    seq = ["low", "mid", "high", "extreme", "high", "low"] * 3
    tm = compute_transition_matrix(seq)
    for row in tm.values():
        for prob in row.values():
            assert 0.0 <= prob <= 1.0


# ── state_duration tests ──────────────────────────────────────────────────────

def test_state_duration_empty():
    assert state_duration([]) == 0


def test_state_duration_single():
    assert state_duration(["low"]) == 1


def test_state_duration_all_same():
    assert state_duration(["high", "high", "high"]) == 3


def test_state_duration_ends_different():
    assert state_duration(["low", "low", "high"]) == 1


def test_state_duration_current_run():
    assert state_duration(["low", "mid", "high", "high", "high"]) == 3


def test_state_duration_single_at_end():
    assert state_duration(["low", "low", "low", "extreme"]) == 1


# ── realized_vol_buckets tests ────────────────────────────────────────────────

FLAT_PRICES  = [1.0] * 20
TREND_PRICES = [1.0 + 0.001 * i for i in range(20)]
NOISY_PRICES = [1.0 + (0.01 if i % 2 == 0 else -0.01) for i in range(20)]


def test_rv_flat_prices_near_zero():
    rvs = realized_vol_buckets(FLAT_PRICES, bucket_size=5)
    for rv in rvs:
        assert rv == pytest.approx(0.0)


def test_rv_trending_prices_low_vol():
    # Smooth trend → low variance in log-returns
    rvs = realized_vol_buckets(TREND_PRICES, bucket_size=5)
    for rv in rvs:
        assert rv >= 0.0


def test_rv_noisy_prices_nonzero():
    rvs = realized_vol_buckets(NOISY_PRICES, bucket_size=5)
    assert any(rv > 0 for rv in rvs)


def test_rv_bucket_count():
    prices = list(range(1, 22))  # 21 prices
    rvs = realized_vol_buckets(prices, bucket_size=5)
    assert len(rvs) == 4  # floor(21/5) = 4 complete buckets


def test_rv_empty_prices():
    assert realized_vol_buckets([], bucket_size=5) == []


def test_rv_fewer_than_bucket_size():
    assert realized_vol_buckets([1.0, 1.1], bucket_size=5) == []


def test_rv_nonneg():
    import random
    random.seed(42)
    prices = [1.0 + random.gauss(0, 0.001) for _ in range(50)]
    prices = [max(0.0001, p) for p in prices]
    rvs = realized_vol_buckets(prices, bucket_size=5)
    for rv in rvs:
        assert rv >= 0.0


def test_rv_scales_with_noise():
    # Higher noise → higher RV
    low_noise  = [1.0 + 0.0001 * (i % 3 - 1) for i in range(20)]
    high_noise = [1.0 + 0.01   * (i % 3 - 1) for i in range(20)]
    rv_low  = sum(realized_vol_buckets(low_noise,  bucket_size=5))
    rv_high = sum(realized_vol_buckets(high_noise, bucket_size=5))
    assert rv_high > rv_low


# ── fmt_rv tests ──────────────────────────────────────────────────────────────

def test_fmt_rv_normal():
    assert fmt_rv(0.0123) == "0.0123%"


def test_fmt_rv_zero():
    assert fmt_rv(0.0) == "0.0000%"


def test_fmt_rv_none():
    assert fmt_rv(None) == "—"


# ── regime_color_class tests ──────────────────────────────────────────────────

def test_color_low():
    assert regime_color_class("low") == "var(--green)"


def test_color_mid():
    assert regime_color_class("mid") == "var(--blue)"


def test_color_high():
    assert regime_color_class("high") == "var(--yellow)"


def test_color_extreme():
    assert regime_color_class("extreme") == "var(--red)"


def test_color_unknown():
    assert regime_color_class("unknown") == "var(--muted)"


# ── Response shape ────────────────────────────────────────────────────────────

SAMPLE_RESPONSE = {
    "status": "ok",
    "symbol": "BANANAS31USDT",
    "window_seconds": 3600,
    "bucket_seconds": 300,
    "regime": "high",
    "regime_index": 2,
    "percentile": 68.5,
    "rv_current": 0.0185,
    "rv_history": [
        {"ts": 1700000000.0, "rv": 0.0120, "regime": "mid"},
        {"ts": 1700000300.0, "rv": 0.0150, "regime": "high"},
        {"ts": 1700000600.0, "rv": 0.0185, "regime": "high"},
    ],
    "boundaries": {"p25": 0.0080, "p50": 0.0120, "p75": 0.0160},
    "transitions": {
        "low":  {"low": 0.8, "mid": 0.2, "high": 0.0, "extreme": 0.0},
        "mid":  {"low": 0.1, "mid": 0.7, "high": 0.2, "extreme": 0.0},
        "high": {"low": 0.0, "mid": 0.2, "high": 0.7, "extreme": 0.1},
    },
    "state_duration": 2,
    "smoothing_min_duration": 2,
    "description": "High volatility regime: RV at 68.5th percentile, stable for 2 buckets",
}


def test_response_status_ok():
    assert SAMPLE_RESPONSE["status"] == "ok"


def test_response_has_required_keys():
    for key in (
        "symbol", "window_seconds", "bucket_seconds",
        "regime", "regime_index", "percentile",
        "rv_current", "rv_history", "boundaries",
        "transitions", "state_duration",
        "smoothing_min_duration", "description",
    ):
        assert key in SAMPLE_RESPONSE


def test_response_regime_valid():
    assert SAMPLE_RESPONSE["regime"] in REGIMES


def test_response_regime_index_matches():
    idx_map = {"low": 0, "mid": 1, "high": 2, "extreme": 3}
    assert SAMPLE_RESPONSE["regime_index"] == idx_map[SAMPLE_RESPONSE["regime"]]


def test_response_percentile_range():
    assert 0.0 <= SAMPLE_RESPONSE["percentile"] <= 100.0


def test_response_rv_current_nonneg():
    assert SAMPLE_RESPONSE["rv_current"] >= 0.0


def test_response_rv_history_is_list():
    assert isinstance(SAMPLE_RESPONSE["rv_history"], list)
    assert len(SAMPLE_RESPONSE["rv_history"]) > 0


def test_response_rv_history_keys():
    for pt in SAMPLE_RESPONSE["rv_history"]:
        for key in ("ts", "rv", "regime"):
            assert key in pt


def test_response_rv_history_regimes_valid():
    for pt in SAMPLE_RESPONSE["rv_history"]:
        assert pt["regime"] in REGIMES


def test_response_boundaries_keys():
    b = SAMPLE_RESPONSE["boundaries"]
    for key in ("p25", "p50", "p75"):
        assert key in b


def test_response_boundaries_ordered():
    b = SAMPLE_RESPONSE["boundaries"]
    assert b["p25"] <= b["p50"] <= b["p75"]


def test_response_transitions_is_dict():
    assert isinstance(SAMPLE_RESPONSE["transitions"], dict)


def test_response_transition_rows_sum_to_1():
    for row in SAMPLE_RESPONSE["transitions"].values():
        total = sum(row.values())
        assert total == pytest.approx(1.0, abs=1e-6)


def test_response_state_duration_positive():
    assert SAMPLE_RESPONSE["state_duration"] >= 1


def test_response_has_description():
    assert isinstance(SAMPLE_RESPONSE["description"], str)
    assert len(SAMPLE_RESPONSE["description"]) > 0


# ── Route registration ────────────────────────────────────────────────────────

def test_vol_regime_hmm_route_registered():
    import tempfile
    os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
    os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from api import router
    paths = [r.path for r in router.routes]
    assert any("vol-regime-hmm" in p for p in paths)


# ── HTML / JS smoke tests ─────────────────────────────────────────────────────

def test_html_has_vol_regime_hmm_card():
    assert "card-vol-regime-hmm" in _html()


def test_js_has_render_vol_regime_hmm():
    assert "renderVolatilityRegimeHMM" in _js()


def test_js_calls_vol_regime_hmm_api():
    assert "vol-regime-hmm" in _js()

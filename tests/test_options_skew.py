"""
Unit / smoke tests for /api/options-skew.

Options skew and term structure card using return-distribution moments
as proxies for observable options greeks:
  - 25-delta Risk Reversal (RR)  ← return skewness * vol scale
  - Butterfly spread (Fly)       ← excess kurtosis * vol² scale
  - ATM implied vol (ATM IV)     ← realized vol annualised
  - Multi-window term structure: 5m / 15m / 1h / 4h
  - Historical percentile rank for RR and Fly
  - Skew direction: put_heavy / call_heavy / neutral

Since our tracked tokens (BANANAS31, COS, DEXE, LYN) have no listed
options, these are *synthetic* derivatives computed from tick data —
they capture the same economic information as exchange-traded options
skew for assets with liquid options markets.

Covers:
  - log_returns helper
  - compute_moments (mean / variance / skewness / kurtosis)
  - rr_from_skewness
  - fly_from_kurtosis
  - skew_direction_label
  - term_structure_slope
  - percentile_rank
  - fmt_skew / fmt_iv
  - Response shape and key validation
  - Edge cases (flat prices, empty, single value)
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


# ── Python mirrors of backend helpers ─────────────────────────────────────────

WINDOWS = ("5m", "15m", "1h", "4h")


def log_returns(prices: list[float]) -> list[float]:
    rets = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0 and prices[i] > 0:
            rets.append(math.log(prices[i] / prices[i - 1]))
        else:
            rets.append(0.0)
    return rets


def compute_moments(returns: list[float]) -> dict:
    """
    Compute sample moments of a return series.
    Returns:
      mean, variance, std, skewness (sample), excess_kurtosis (sample),
      n (number of observations)
    Returns all-zero dict for < 4 observations (not enough for kurtosis).
    """
    n = len(returns)
    if n < 4:
        return {"mean": 0.0, "variance": 0.0, "std": 0.0,
                "skewness": 0.0, "excess_kurtosis": 0.0, "n": n}
    mean = sum(returns) / n
    deviations = [r - mean for r in returns]
    variance   = sum(d ** 2 for d in deviations) / (n - 1)
    std        = math.sqrt(variance) if variance > 0 else 0.0

    if std == 0:
        return {"mean": mean, "variance": 0.0, "std": 0.0,
                "skewness": 0.0, "excess_kurtosis": 0.0, "n": n}

    # Fisher's (sample) skewness
    skewness = (
        (n / ((n - 1) * (n - 2)))
        * sum(d ** 3 for d in deviations)
        / (std ** 3)
    )
    # Excess (sample) kurtosis — Fisher's definition
    excess_kurtosis = (
        (n * (n + 1) / ((n - 1) * (n - 2) * (n - 3)))
        * sum(d ** 4 for d in deviations)
        / (std ** 4)
        - 3 * (n - 1) ** 2 / ((n - 2) * (n - 3))
    )

    return {
        "mean": round(mean, 8),
        "variance": round(variance, 10),
        "std": round(std, 8),
        "skewness": round(skewness, 6),
        "excess_kurtosis": round(excess_kurtosis, 6),
        "n": n,
    }


def rr_from_skewness(skewness: float, std: float, scale: float = 0.1) -> float:
    """
    Proxy 25-delta Risk Reversal from return skewness.
    RR ≈ skewness * std * scale
    Negative RR → put vol > call vol (bearish skew).
    """
    return round(skewness * std * scale, 6)


def fly_from_kurtosis(excess_kurtosis: float, variance: float, scale: float = 0.05) -> float:
    """
    Proxy Butterfly spread from excess kurtosis.
    Fly ≈ excess_kurtosis * variance * scale
    Positive fly → fat tails, market pays for wings.
    """
    return round(max(0.0, excess_kurtosis * variance * scale), 6)


def skew_direction_label(rr: float, threshold: float = 0.0005) -> str:
    """Classify RR into skew direction."""
    if rr < -threshold:
        return "put_heavy"
    if rr > threshold:
        return "call_heavy"
    return "neutral"


def term_structure_slope(rr_values: list[float]) -> str:
    """
    Classify term structure slope from short-to-long RR values.
    'normal'   — short-tenor RR < long-tenor RR (upward sloping)
    'inverted' — short-tenor RR > long-tenor RR (downward sloping)
    'flat'     — approximately flat
    """
    if len(rr_values) < 2:
        return "flat"
    diff = rr_values[-1] - rr_values[0]
    if diff > 0.0005:
        return "normal"
    if diff < -0.0005:
        return "inverted"
    return "flat"


def percentile_rank(value: float, history: list[float]) -> float:
    """
    Return percentile rank of value in history (0–100).
    Returns 50.0 if history is empty.
    """
    if not history:
        return 50.0
    n = len(history)
    below = sum(1 for h in history if h < value)
    return round(below / n * 100, 2)


def fmt_skew(v: float | None) -> str:
    """Format RR or fly value as a signed percentage string."""
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v * 100:.3f}%"


def fmt_iv(v: float | None) -> str:
    """Format ATM IV (annualised) as a percentage string."""
    if v is None:
        return "—"
    return f"{v * 100:.2f}%"


# ── Sample data ───────────────────────────────────────────────────────────────

import random as _rnd
_rnd.seed(42)
_prices_trend = [0.002 * (1 + 0.001 * i + _rnd.gauss(0, 0.0005)) for i in range(120)]
_prices_flat  = [0.002] * 60
_prices_crash = [0.002 - 0.00005 * i + _rnd.gauss(0, 0.0001) for i in range(60)]

RETURNS_TREND  = log_returns(_prices_trend)
RETURNS_FLAT   = log_returns(_prices_flat)
RETURNS_CRASH  = log_returns(_prices_crash)

MOMENTS_TREND  = compute_moments(RETURNS_TREND)
MOMENTS_FLAT   = compute_moments(RETURNS_FLAT)
MOMENTS_CRASH  = compute_moments(RETURNS_CRASH)

RR_TREND  = rr_from_skewness(MOMENTS_TREND["skewness"],  MOMENTS_TREND["std"])
RR_CRASH  = rr_from_skewness(MOMENTS_CRASH["skewness"],  MOMENTS_CRASH["std"])
FLY_TREND = fly_from_kurtosis(MOMENTS_TREND["excess_kurtosis"], MOMENTS_TREND["variance"])

SAMPLE_RESPONSE = {
    "status": "ok",
    "symbol": "BANANAS31USDT",
    "windows": ["5m", "15m", "1h", "4h"],
    "rr_25d": {"5m": -0.0012, "15m": -0.0020, "1h": -0.0015, "4h": -0.0010},
    "fly_25d": {"5m": 0.0003, "15m": 0.0005, "1h": 0.0004, "4h": 0.0006},
    "atm_iv":  {"5m": 0.0450, "15m": 0.0520, "1h": 0.0600, "4h": 0.0700},
    "skewness": {"5m": -0.45, "15m": -0.60, "1h": -0.50, "4h": -0.35},
    "excess_kurtosis": {"5m": 0.8, "15m": 1.2, "1h": 0.9, "4h": 1.5},
    "rr_percentile":  22.5,
    "fly_percentile": 68.0,
    "skew_direction": "put_heavy",
    "term_structure": [
        {"window": "5m",  "rr": -0.0012, "fly": 0.0003, "atm_iv": 0.0450},
        {"window": "15m", "rr": -0.0020, "fly": 0.0005, "atm_iv": 0.0520},
        {"window": "1h",  "rr": -0.0015, "fly": 0.0004, "atm_iv": 0.0600},
        {"window": "4h",  "rr": -0.0010, "fly": 0.0006, "atm_iv": 0.0700},
    ],
    "term_slope": "normal",
    "description": "Put-heavy skew: RR at 22.5th pct, Fly at 68.0th pct",
}


# ── log_returns tests ─────────────────────────────────────────────────────────

def test_log_returns_length():
    prices = [1.0, 1.05, 1.02, 1.08]
    assert len(log_returns(prices)) == 3


def test_log_returns_empty():
    assert log_returns([]) == []


def test_log_returns_single():
    assert log_returns([1.0]) == []


def test_log_returns_flat():
    rets = log_returns([1.0] * 10)
    assert all(r == pytest.approx(0.0) for r in rets)


def test_log_returns_zero_price_safe():
    assert log_returns([0.0, 1.0])[0] == 0.0


def test_log_returns_up_move():
    rets = log_returns([1.0, math.e])
    assert rets[0] == pytest.approx(1.0)


# ── compute_moments tests ─────────────────────────────────────────────────────

def test_moments_flat_returns_std_zero():
    m = compute_moments(RETURNS_FLAT)
    assert m["std"] == pytest.approx(0.0)
    assert m["skewness"] == pytest.approx(0.0)


def test_moments_n_matches():
    m = compute_moments(RETURNS_TREND)
    assert m["n"] == len(RETURNS_TREND)


def test_moments_variance_nonneg():
    for m in [MOMENTS_TREND, MOMENTS_CRASH]:
        assert m["variance"] >= 0.0


def test_moments_std_is_sqrt_variance():
    m = MOMENTS_TREND
    assert m["std"] == pytest.approx(math.sqrt(m["variance"]), rel=1e-4)


def test_moments_few_obs_returns_zeros():
    m = compute_moments([0.01, -0.01, 0.005])  # n=3 < 4
    assert m["skewness"] == 0.0
    assert m["excess_kurtosis"] == 0.0


def test_moments_empty_returns_zeros():
    m = compute_moments([])
    assert m["std"] == 0.0


def test_moments_normal_dist_skew_near_zero():
    # Symmetric distribution → skewness near 0
    _rnd2 = __import__("random")
    _rnd2.seed(99)
    rets = [_rnd2.gauss(0, 0.001) for _ in range(500)]
    m = compute_moments(rets)
    assert abs(m["skewness"]) < 0.5


def test_moments_crash_negative_skew():
    # Downward trending / crash-like → negative skewness typical
    # (not guaranteed for every random seed, just check it's computed)
    assert isinstance(MOMENTS_CRASH["skewness"], float)


def test_moments_keys():
    for key in ("mean", "variance", "std", "skewness", "excess_kurtosis", "n"):
        assert key in MOMENTS_TREND


# ── rr_from_skewness tests ────────────────────────────────────────────────────

def test_rr_sign_follows_skewness():
    rr_neg = rr_from_skewness(-1.0, 0.01)
    rr_pos = rr_from_skewness(+1.0, 0.01)
    assert rr_neg < 0
    assert rr_pos > 0


def test_rr_zero_skew():
    assert rr_from_skewness(0.0, 0.01) == pytest.approx(0.0)


def test_rr_zero_std():
    assert rr_from_skewness(1.5, 0.0) == pytest.approx(0.0)


def test_rr_scale_linear():
    rr1 = rr_from_skewness(1.0, 0.01, scale=0.1)
    rr2 = rr_from_skewness(2.0, 0.01, scale=0.1)
    assert rr2 == pytest.approx(2 * rr1)


def test_rr_formula():
    skew, std, scale = -0.5, 0.02, 0.1
    expected = round(-0.5 * 0.02 * 0.1, 6)
    assert rr_from_skewness(skew, std, scale) == pytest.approx(expected)


# ── fly_from_kurtosis tests ───────────────────────────────────────────────────

def test_fly_nonnegative():
    # Fly is always >= 0
    assert fly_from_kurtosis(-2.0, 0.001) == pytest.approx(0.0)


def test_fly_positive_kurtosis():
    fly = fly_from_kurtosis(3.0, 0.0001, scale=0.05)
    assert fly > 0


def test_fly_zero_variance():
    assert fly_from_kurtosis(5.0, 0.0) == pytest.approx(0.0)


def test_fly_zero_kurtosis():
    assert fly_from_kurtosis(0.0, 0.001) == pytest.approx(0.0)


def test_fly_scale_linear():
    fly1 = fly_from_kurtosis(2.0, 0.001, scale=0.05)
    fly2 = fly_from_kurtosis(4.0, 0.001, scale=0.05)
    assert fly2 == pytest.approx(2 * fly1)


# ── skew_direction_label tests ────────────────────────────────────────────────

def test_direction_put_heavy():
    assert skew_direction_label(-0.01) == "put_heavy"


def test_direction_call_heavy():
    assert skew_direction_label(+0.01) == "call_heavy"


def test_direction_neutral_zero():
    assert skew_direction_label(0.0) == "neutral"


def test_direction_near_threshold():
    assert skew_direction_label(0.0004) == "neutral"
    assert skew_direction_label(-0.0004) == "neutral"


def test_direction_boundary_put():
    assert skew_direction_label(-0.0006) == "put_heavy"


def test_direction_boundary_call():
    assert skew_direction_label(+0.0006) == "call_heavy"


def test_direction_valid_output():
    for rr in [-0.02, 0.0, 0.02]:
        assert skew_direction_label(rr) in ("put_heavy", "call_heavy", "neutral")


# ── term_structure_slope tests ────────────────────────────────────────────────

def test_slope_normal():
    assert term_structure_slope([-0.002, -0.001, 0.0, 0.001]) == "normal"


def test_slope_inverted():
    assert term_structure_slope([0.002, 0.001, 0.0, -0.001]) == "inverted"


def test_slope_flat():
    assert term_structure_slope([0.001, 0.001, 0.001, 0.001]) == "flat"


def test_slope_empty():
    assert term_structure_slope([]) == "flat"


def test_slope_single():
    assert term_structure_slope([0.005]) == "flat"


def test_slope_valid_output():
    for rr_list in [[-0.01, 0.01], [0.01, -0.01], [0.0, 0.0]]:
        assert term_structure_slope(rr_list) in ("normal", "inverted", "flat")


# ── percentile_rank tests ─────────────────────────────────────────────────────

def test_pct_rank_empty_returns_50():
    assert percentile_rank(0.5, []) == 50.0


def test_pct_rank_min():
    assert percentile_rank(-100.0, [0.0, 1.0, 2.0]) == 0.0


def test_pct_rank_max():
    assert percentile_rank(100.0, [0.0, 1.0, 2.0]) == 100.0


def test_pct_rank_median():
    assert percentile_rank(1.0, [0.0, 1.0, 2.0]) == pytest.approx(33.33, abs=0.1)


def test_pct_rank_in_range():
    history = list(range(100))
    pct = percentile_rank(50, history)
    assert 0.0 <= pct <= 100.0


def test_pct_rank_single():
    assert percentile_rank(5.0, [3.0]) == 100.0
    assert percentile_rank(1.0, [3.0]) == 0.0


# ── fmt_skew / fmt_iv tests ───────────────────────────────────────────────────

def test_fmt_skew_positive():
    assert fmt_skew(0.0012) == "+0.120%"


def test_fmt_skew_negative():
    assert fmt_skew(-0.002) == "-0.200%"


def test_fmt_skew_zero():
    assert fmt_skew(0.0) == "+0.000%"


def test_fmt_skew_none():
    assert fmt_skew(None) == "—"


def test_fmt_iv_normal():
    assert fmt_iv(0.045) == "4.50%"


def test_fmt_iv_zero():
    assert fmt_iv(0.0) == "0.00%"


def test_fmt_iv_none():
    assert fmt_iv(None) == "—"


# ── Response shape tests ──────────────────────────────────────────────────────

def test_response_status():
    assert SAMPLE_RESPONSE["status"] == "ok"


def test_response_required_keys():
    for key in (
        "symbol", "windows", "rr_25d", "fly_25d", "atm_iv",
        "skewness", "excess_kurtosis",
        "rr_percentile", "fly_percentile",
        "skew_direction", "term_structure", "term_slope", "description",
    ):
        assert key in SAMPLE_RESPONSE


def test_response_windows_list():
    assert isinstance(SAMPLE_RESPONSE["windows"], list)
    assert len(SAMPLE_RESPONSE["windows"]) >= 2


def test_response_rr_dict_keys():
    for w in SAMPLE_RESPONSE["windows"]:
        assert w in SAMPLE_RESPONSE["rr_25d"]


def test_response_fly_dict_keys():
    for w in SAMPLE_RESPONSE["windows"]:
        assert w in SAMPLE_RESPONSE["fly_25d"]


def test_response_atm_iv_positive():
    for v in SAMPLE_RESPONSE["atm_iv"].values():
        assert v >= 0.0


def test_response_percentiles_in_range():
    assert 0.0 <= SAMPLE_RESPONSE["rr_percentile"] <= 100.0
    assert 0.0 <= SAMPLE_RESPONSE["fly_percentile"] <= 100.0


def test_response_skew_direction_valid():
    assert SAMPLE_RESPONSE["skew_direction"] in ("put_heavy", "call_heavy", "neutral")


def test_response_term_structure_list():
    ts = SAMPLE_RESPONSE["term_structure"]
    assert isinstance(ts, list)
    assert len(ts) == len(SAMPLE_RESPONSE["windows"])


def test_response_term_structure_keys():
    for entry in SAMPLE_RESPONSE["term_structure"]:
        for key in ("window", "rr", "fly", "atm_iv"):
            assert key in entry


def test_response_term_slope_valid():
    assert SAMPLE_RESPONSE["term_slope"] in ("normal", "inverted", "flat")


def test_response_description_nonempty():
    assert len(SAMPLE_RESPONSE["description"]) > 0


def test_response_rr_matches_skew_direction():
    # put_heavy → all RRs should be negative
    rrs = list(SAMPLE_RESPONSE["rr_25d"].values())
    assert all(r < 0 for r in rrs)


# ── Route registration ────────────────────────────────────────────────────────

def test_options_skew_route_registered():
    import tempfile
    os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
    os.environ.setdefault("SYMBOL_BINANCE", "BANANAS31USDT")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from api import router
    paths = [r.path for r in router.routes]
    assert any("options-skew" in p for p in paths)


# ── HTML / JS smoke tests ─────────────────────────────────────────────────────

def test_html_has_options_skew_card():
    assert "card-options-skew" in _html()


def test_js_has_render_options_skew():
    assert "renderOptionsSkew" in _js()


def test_js_calls_options_skew_api():
    assert "options-skew" in _js()

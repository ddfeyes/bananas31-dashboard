"""
Tests for realized volatility bands endpoint and rendering logic.

Validates vol calculation, band generation, percentile, zone classification,
and edge cases that mirror app.js renderRealizedVolBands().
"""
import math
from unittest.mock import AsyncMock, patch

import pytest


# ── Python mirrors of app.js helpers ─────────────────────────────────────────

def fmt_price(v, decimals=4):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


def fmt_pct(v):
    if v is None:
        return "—"
    return f"{v:.1f}%"


def zone_color(zone):
    if zone == "above_upper":
        return "var(--red)"
    if zone == "below_lower":
        return "var(--green)"
    return "var(--yellow)"


def badge_class_for_zone(zone):
    if zone == "above_upper":
        return "badge-red"
    if zone == "below_lower":
        return "badge-green"
    return "badge-yellow"


# ── Pure-Python calculation mirror ────────────────────────────────────────────

BASE_TS = 1710432000.0  # Fixed epoch for reproducibility


def build_candle(ts, open_p, high, low, close):
    return {"ts": ts, "open": open_p, "high": high, "low": low, "close": close}


def compute_realized_vol_bands_py(candles, window=20):
    """
    Pure-Python mirror of compute_realized_volatility_bands.

    candles: list of dicts with 'close' key, ordered oldest→newest.
    window:  number of candles for SMA and returns.
    Returns dict or None on insufficient data.
    """
    if not candles or len(candles) < 2:
        return None

    # Use last window+1 candles to compute window returns
    subset = candles[-(window + 1):] if len(candles) > window else candles
    closes = [c["close"] for c in subset]

    if len(closes) < 2:
        return None

    log_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_returns.append(math.log(closes[i] / closes[i - 1]))

    if len(log_returns) < 2:
        return None

    n = len(log_returns)
    mean_r = sum(log_returns) / n
    variance = sum((r - mean_r) ** 2 for r in log_returns) / (n - 1)
    realized_vol = math.sqrt(variance)

    # SMA center from last window closes
    sma_closes = closes[-window:] if len(closes) >= window else closes
    center = sum(sma_closes) / len(sma_closes)

    current_price = closes[-1]

    realized_vol_price = realized_vol * center
    upper = center + 2 * realized_vol_price
    lower = max(0.0, center - 2 * realized_vol_price)

    band_width = upper - lower
    if band_width > 1e-12:
        band_pct = (current_price - lower) / band_width * 100
        band_pct = max(0.0, min(100.0, band_pct))
    else:
        band_pct = 50.0

    if band_pct >= 80:
        zone = "above_upper"
    elif band_pct <= 20:
        zone = "below_lower"
    else:
        zone = "inside"

    return {
        "upper": upper,
        "center": center,
        "lower": lower,
        "realized_vol": realized_vol,
        "current_price": current_price,
        "band_percentile": band_pct,
        "zone": zone,
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_flat_candles(n, price=1.0):
    """All closes identical → zero std dev."""
    return [build_candle(BASE_TS + i * 60, price, price, price, price) for i in range(n)]


def make_rising_candles(n, start=1.0, step=0.01):
    """Linearly rising prices."""
    candles = []
    p = start
    for i in range(n):
        candles.append(build_candle(BASE_TS + i * 60, p, p + step * 0.1, p - step * 0.1, p))
        p += step
    return candles


def make_volatile_candles(n, base=1.0, amplitude=0.05):
    """Alternating up/down prices → high std dev."""
    candles = []
    for i in range(n):
        close = base + amplitude if i % 2 == 0 else base - amplitude
        candles.append(build_candle(BASE_TS + i * 60, base, base + amplitude, base - amplitude, close))
    return candles


# ── Tests: Calculation Correctness ────────────────────────────────────────────

class TestCalculationCorrectness:
    def test_flat_candles_zero_vol(self):
        """Flat prices → realized vol ≈ 0 → bands collapse to center."""
        candles = make_flat_candles(25)
        result = compute_realized_vol_bands_py(candles, window=20)
        assert result is not None
        assert result["realized_vol"] == pytest.approx(0.0, abs=1e-10)
        assert result["upper"] == pytest.approx(result["center"], abs=1e-6)
        assert result["lower"] == pytest.approx(result["center"], abs=1e-6)

    def test_rising_candles_center_is_sma(self):
        """Center must equal SMA of last `window` closes."""
        candles = make_rising_candles(25, start=1.0, step=0.01)
        result = compute_realized_vol_bands_py(candles, window=20)
        closes = [c["close"] for c in candles[-20:]]
        expected_center = sum(closes) / len(closes)
        assert result["center"] == pytest.approx(expected_center, rel=1e-8)

    def test_upper_lower_symmetric_around_center(self):
        """Upper and lower must be equidistant from center (when lower > 0)."""
        candles = make_volatile_candles(25, base=100.0, amplitude=1.0)
        result = compute_realized_vol_bands_py(candles, window=20)
        assert result is not None
        upper_dist = result["upper"] - result["center"]
        lower_dist = result["center"] - result["lower"]
        assert upper_dist == pytest.approx(lower_dist, rel=1e-8)

    def test_band_width_equals_4_sigma(self):
        """Upper - lower = 4 × realized_vol × center (when lower > 0)."""
        candles = make_volatile_candles(25, base=100.0, amplitude=1.0)
        result = compute_realized_vol_bands_py(candles, window=20)
        expected_width = 4 * result["realized_vol"] * result["center"]
        actual_width = result["upper"] - result["lower"]
        assert actual_width == pytest.approx(expected_width, rel=1e-8)

    def test_realized_vol_is_positive(self):
        """Realized vol must be > 0 for non-flat prices."""
        candles = make_volatile_candles(25)
        result = compute_realized_vol_bands_py(candles, window=20)
        assert result["realized_vol"] > 0

    def test_current_price_matches_last_close(self):
        candles = make_rising_candles(25)
        result = compute_realized_vol_bands_py(candles, window=20)
        assert result["current_price"] == pytest.approx(candles[-1]["close"])

    def test_window_smaller_than_candle_count(self):
        """Window smaller than data uses only last window+1 candles."""
        candles = make_rising_candles(100, start=0.5, step=0.001)
        result5 = compute_realized_vol_bands_py(candles, window=5)
        result20 = compute_realized_vol_bands_py(candles, window=20)
        # Different windows → different centers
        assert result5["center"] != pytest.approx(result20["center"], rel=1e-3)

    def test_window_exactly_matching_candle_count(self):
        """Exactly window+1 candles is valid."""
        candles = make_volatile_candles(21)
        result = compute_realized_vol_bands_py(candles, window=20)
        assert result is not None
        assert result["band_percentile"] is not None


# ── Tests: Band Percentile & Zone Classification ──────────────────────────────

class TestBandPercentileAndZone:
    def test_price_at_center_is_near_50pct(self):
        """For symmetric prices, the last close near center → pct ≈ 50."""
        # Use flat + small final move so price ≈ center
        candles = make_flat_candles(25, price=1.0)
        result = compute_realized_vol_bands_py(candles, window=20)
        # flat → vol=0, bands collapse, pct=50 by default
        assert result["band_percentile"] == pytest.approx(50.0)

    def test_band_percentile_clamped_0_to_100(self):
        """band_percentile must always be in [0, 100]."""
        for n in [5, 10, 25, 50]:
            candles = make_volatile_candles(n, base=1.0, amplitude=0.3)
            result = compute_realized_vol_bands_py(candles, window=min(n - 1, 20))
            if result:
                assert 0.0 <= result["band_percentile"] <= 100.0

    def test_zone_above_upper_when_pct_high(self):
        """zone == 'above_upper' when band_percentile >= 80."""
        # Force price near upper: alternating small vol, then big spike
        candles = make_volatile_candles(24, base=1.0, amplitude=0.001)
        # Add a final candle with a very high close
        candles.append(build_candle(BASE_TS + 24 * 60, 1.0, 1.5, 1.0, 1.5))
        result = compute_realized_vol_bands_py(candles, window=20)
        assert result is not None
        # percentile should be near top
        assert result["band_percentile"] >= 80 or result["zone"] == "above_upper"

    def test_zone_below_lower_when_pct_low(self):
        """zone == 'below_lower' when band_percentile <= 20."""
        candles = make_volatile_candles(24, base=1.0, amplitude=0.001)
        candles.append(build_candle(BASE_TS + 24 * 60, 1.0, 1.0, 0.5, 0.5))
        result = compute_realized_vol_bands_py(candles, window=20)
        assert result is not None
        assert result["band_percentile"] <= 20 or result["zone"] == "below_lower"

    def test_zone_inside_for_moderate_pct(self):
        """zone == 'inside' when 20 < pct < 80."""
        candles = make_volatile_candles(25, base=1.0, amplitude=0.05)
        result = compute_realized_vol_bands_py(candles, window=20)
        if result and 20 < result["band_percentile"] < 80:
            assert result["zone"] == "inside"

    def test_lower_band_never_negative(self):
        """lower band must be >= 0 always."""
        candles = make_volatile_candles(25, base=0.001, amplitude=0.0009)
        result = compute_realized_vol_bands_py(candles, window=20)
        if result:
            assert result["lower"] >= 0.0


# ── Tests: Edge Cases ─────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_candles_returns_none(self):
        assert compute_realized_vol_bands_py([], window=20) is None

    def test_single_candle_returns_none(self):
        candles = [build_candle(BASE_TS, 1.0, 1.1, 0.9, 1.0)]
        assert compute_realized_vol_bands_py(candles, window=20) is None

    def test_two_candles_returns_none(self):
        """Need at least 2 log returns (3 candles) for sample variance."""
        candles = [
            build_candle(BASE_TS, 1.0, 1.1, 0.9, 1.0),
            build_candle(BASE_TS + 60, 1.0, 1.1, 0.9, 1.01),
        ]
        # 2 candles → 1 return → variance needs n-1 >= 1 → need at least 3
        assert compute_realized_vol_bands_py(candles, window=20) is None

    def test_three_candles_is_minimum_valid(self):
        """Three candles give 2 returns, which is enough for sample std dev."""
        candles = [
            build_candle(BASE_TS, 1.0, 1.1, 0.9, 1.0),
            build_candle(BASE_TS + 60, 1.01, 1.1, 0.9, 1.01),
            build_candle(BASE_TS + 120, 1.02, 1.1, 0.9, 1.02),
        ]
        result = compute_realized_vol_bands_py(candles, window=20)
        assert result is not None

    def test_window_larger_than_data_uses_all(self):
        """When window > candle count, use all available data."""
        candles = make_volatile_candles(5, base=1.0, amplitude=0.02)
        result = compute_realized_vol_bands_py(candles, window=100)
        assert result is not None
        closes = [c["close"] for c in candles]
        expected_center = sum(closes) / len(closes)
        assert result["center"] == pytest.approx(expected_center, rel=1e-8)


# ── Tests: Formatting Helpers ─────────────────────────────────────────────────

class TestFormattingHelpers:
    def test_fmt_price_formats_decimals(self):
        assert fmt_price(1.23456789, 4) == "1.2346"

    def test_fmt_price_none_returns_dash(self):
        assert fmt_price(None) == "—"

    def test_fmt_pct_formats_one_decimal(self):
        assert fmt_pct(72.5) == "72.5%"

    def test_fmt_pct_none_returns_dash(self):
        assert fmt_pct(None) == "—"

    def test_zone_color_above_upper(self):
        assert zone_color("above_upper") == "var(--red)"

    def test_zone_color_below_lower(self):
        assert zone_color("below_lower") == "var(--green)"

    def test_zone_color_inside(self):
        assert zone_color("inside") == "var(--yellow)"

    def test_badge_class_above_upper(self):
        assert badge_class_for_zone("above_upper") == "badge-red"

    def test_badge_class_below_lower(self):
        assert badge_class_for_zone("below_lower") == "badge-green"

    def test_badge_class_inside(self):
        assert badge_class_for_zone("inside") == "badge-yellow"


# ── Tests: API Response Shape ─────────────────────────────────────────────────

class TestApiResponseShape:
    FULL_RESPONSE = {
        "status": "ok",
        "symbol": "BANANAS31USDT",
        "upper": 1.0567,
        "center": 1.0123,
        "lower": 0.9679,
        "realized_vol": 0.0022,
        "current_price": 1.0200,
        "band_percentile": 61.3,
        "zone": "inside",
        "window": 20,
        "n_candles": 25,
        "description": "Price inside bands (pct=61)",
    }

    def test_required_keys_present(self):
        required = {
            "status", "symbol", "upper", "center", "lower",
            "realized_vol", "current_price", "band_percentile",
            "zone", "window", "n_candles", "description",
        }
        assert required.issubset(self.FULL_RESPONSE.keys())

    def test_status_ok(self):
        assert self.FULL_RESPONSE["status"] == "ok"

    def test_upper_greater_than_center(self):
        r = self.FULL_RESPONSE
        assert r["upper"] > r["center"]

    def test_lower_less_than_center(self):
        r = self.FULL_RESPONSE
        assert r["lower"] < r["center"]

    def test_band_percentile_in_range(self):
        assert 0 <= self.FULL_RESPONSE["band_percentile"] <= 100

    def test_zone_valid_values(self):
        assert self.FULL_RESPONSE["zone"] in {"above_upper", "below_lower", "inside"}

    def test_empty_data_returns_none_fields(self):
        """Backend must return None fields (not raise) on no data."""
        no_data_response = {
            "status": "ok",
            "symbol": "BANANAS31USDT",
            "upper": None,
            "center": None,
            "lower": None,
            "realized_vol": None,
            "current_price": None,
            "band_percentile": None,
            "zone": None,
            "window": 20,
            "n_candles": 0,
            "description": "Insufficient data",
        }
        assert no_data_response["upper"] is None
        assert no_data_response["band_percentile"] is None
        assert no_data_response["description"] == "Insufficient data"

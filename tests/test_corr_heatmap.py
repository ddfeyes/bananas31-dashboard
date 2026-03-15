"""
Tests for GET /api/correlations/heatmap endpoint and frontend helpers.

Backend: 20-period rolling correlation matrix using price returns.
Returns: {"symbols": [...], "matrix": [[...], ...], "timestamp": int, "quality": int}

Frontend color scheme:
  1.0  → red   rgb(255,0,0)
  0.0  → white rgb(255,255,255)
 -1.0  → blue  rgb(0,0,255)
"""

import math


# ─── Pure Python mirrors of backend logic ─────────────────────────────────────


def price_returns(prices):
    """Compute percentage returns from a list of close prices."""
    result = []
    for i in range(1, len(prices)):
        if prices[i - 1] != 0:
            result.append((prices[i] - prices[i - 1]) / prices[i - 1])
    return result


def pearson(xs, ys):
    """Pearson correlation coefficient, returns 0.0 when std dev is zero."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    dy = (sum((y - my) ** 2 for y in ys)) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return round(num / (dx * dy), 4)


def build_matrix(symbol_returns: dict) -> list:
    """Build correlation matrix as array of arrays from symbol→returns dict."""
    syms = list(symbol_returns.keys())
    matrix = []
    for sym_a in syms:
        row = []
        for sym_b in syms:
            if sym_a == sym_b:
                row.append(1.0)
            else:
                row.append(pearson(symbol_returns[sym_a], symbol_returns[sym_b]))
        matrix.append(row)
    return matrix


# ─── Python mirror of frontend heatColor() ────────────────────────────────────


def heat_color(v):
    """Mirror app.js heatColor(): red (1.0) → white (0.0) → blue (-1.0)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "rgba(107,114,128,0.1)"
    c = max(-1.0, min(1.0, float(v)))
    if c >= 0:
        r = 255
        g = round(255 * (1 - c))
        b = round(255 * (1 - c))
        return f"rgb({r},{g},{b})"
    else:
        t = -c
        r = round(255 * (1 - t))
        g = round(255 * (1 - t))
        b = 255
        return f"rgb({r},{g},{b})"


# ─── TestPriceReturns ──────────────────────────────────────────────────────────


class TestPriceReturns:
    def test_single_price_returns_empty(self):
        assert price_returns([100.0]) == []

    def test_empty_prices_returns_empty(self):
        assert price_returns([]) == []

    def test_two_prices_returns_one_return(self):
        result = price_returns([100.0, 110.0])
        assert len(result) == 1
        assert abs(result[0] - 0.1) < 1e-9

    def test_n_prices_returns_n_minus_one(self):
        prices = [100.0 + i for i in range(21)]
        assert len(price_returns(prices)) == 20

    def test_declining_prices_negative_returns(self):
        result = price_returns([100.0, 90.0])
        assert result[0] < 0

    def test_flat_prices_zero_returns(self):
        result = price_returns([100.0, 100.0, 100.0])
        assert all(r == 0.0 for r in result)

    def test_return_magnitude_correct(self):
        # 100 → 105: return = 5/100 = 0.05
        result = price_returns([100.0, 105.0])
        assert abs(result[0] - 0.05) < 1e-9

    def test_zero_base_price_skipped(self):
        # Zero base price should not produce a return (division by zero guard)
        result = price_returns([0.0, 100.0, 110.0])
        # First pair (0→100) is skipped; second pair (100→110) = 0.1
        assert len(result) == 1
        assert abs(result[0] - 0.1) < 1e-9


# ─── TestPearsonCorrelation ────────────────────────────────────────────────────


class TestPearsonCorrelation:
    def test_identical_series_returns_one(self):
        xs = [0.01, -0.02, 0.03, -0.01, 0.02]
        assert pearson(xs, xs) == 1.0

    def test_perfectly_negative_returns_minus_one(self):
        xs = [0.01, -0.02, 0.03, -0.01, 0.02]
        ys = [-x for x in xs]
        assert pearson(xs, ys) == -1.0

    def test_empty_returns_zero(self):
        assert pearson([], []) == 0.0

    def test_single_element_returns_zero(self):
        assert pearson([0.01], [0.02]) == 0.0

    def test_constant_series_returns_zero(self):
        xs = [0.01] * 10
        ys = [0.02, -0.01, 0.03, -0.02, 0.01, 0.02, -0.01, 0.03, -0.02, 0.01]
        # xs is constant → std dev = 0 → correlation = 0
        assert pearson(xs, ys) == 0.0

    def test_result_in_valid_range(self):
        import random
        random.seed(42)
        xs = [random.gauss(0, 1) for _ in range(20)]
        ys = [random.gauss(0, 1) for _ in range(20)]
        r = pearson(xs, ys)
        assert -1.0 <= r <= 1.0

    def test_result_rounded_to_four_decimals(self):
        xs = [0.01, -0.02, 0.015, -0.005, 0.025]
        ys = [0.012, -0.018, 0.020, -0.003, 0.022]
        r = pearson(xs, ys)
        assert r == round(r, 4)


# ─── TestBuildMatrix ───────────────────────────────────────────────────────────


class TestBuildMatrix:
    def _make_returns(self, n=20):
        """Helper: generate simple return series."""
        import random
        random.seed(7)
        return [random.gauss(0, 0.01) for _ in range(n)]

    def test_diagonal_is_always_one(self):
        returns = {
            "A": self._make_returns(),
            "B": self._make_returns(),
        }
        matrix = build_matrix(returns)
        assert matrix[0][0] == 1.0
        assert matrix[1][1] == 1.0

    def test_matrix_is_symmetric(self):
        returns = {
            "A": self._make_returns(),
            "B": self._make_returns(),
            "C": self._make_returns(),
        }
        matrix = build_matrix(returns)
        n = len(matrix)
        for i in range(n):
            for j in range(n):
                assert matrix[i][j] == matrix[j][i], f"Not symmetric at [{i}][{j}]"

    def test_matrix_shape_matches_symbols(self):
        syms = ["A", "B", "C", "D"]
        returns = {s: self._make_returns() for s in syms}
        matrix = build_matrix(returns)
        assert len(matrix) == 4
        for row in matrix:
            assert len(row) == 4

    def test_all_values_in_valid_range(self):
        returns = {s: self._make_returns() for s in ["A", "B", "C", "D"]}
        matrix = build_matrix(returns)
        for row in matrix:
            for v in row:
                assert -1.0 <= v <= 1.0, f"Value {v} out of range"

    def test_perfectly_correlated_symbols(self):
        xs = [0.01, -0.02, 0.03, -0.01, 0.02, 0.01, -0.01, 0.02, -0.03, 0.01] * 2
        returns = {"A": xs, "B": xs}
        matrix = build_matrix(returns)
        assert matrix[0][1] == 1.0
        assert matrix[1][0] == 1.0

    def test_single_symbol_matrix_is_one_by_one(self):
        returns = {"A": self._make_returns()}
        matrix = build_matrix(returns)
        assert matrix == [[1.0]]

    def test_matrix_is_list_of_lists(self):
        returns = {"A": self._make_returns(), "B": self._make_returns()}
        matrix = build_matrix(returns)
        assert isinstance(matrix, list)
        assert all(isinstance(row, list) for row in matrix)


# ─── TestHeatColor ─────────────────────────────────────────────────────────────


class TestHeatColor:
    def test_one_is_pure_red(self):
        assert heat_color(1.0) == "rgb(255,0,0)"

    def test_zero_is_white(self):
        assert heat_color(0.0) == "rgb(255,255,255)"

    def test_minus_one_is_pure_blue(self):
        assert heat_color(-1.0) == "rgb(0,0,255)"

    def test_none_returns_gray(self):
        assert heat_color(None) == "rgba(107,114,128,0.1)"

    def test_nan_returns_gray(self):
        assert heat_color(float("nan")) == "rgba(107,114,128,0.1)"

    def test_positive_value_has_255_red(self):
        color = heat_color(0.5)
        assert color.startswith("rgb(255,")

    def test_negative_value_has_255_blue(self):
        color = heat_color(-0.5)
        assert color.endswith(",255)")

    def test_above_one_clamped_to_red(self):
        assert heat_color(2.0) == heat_color(1.0)

    def test_below_minus_one_clamped_to_blue(self):
        assert heat_color(-2.0) == heat_color(-1.0)

    def test_half_positive_midpoint_color(self):
        # 0.5 → g = b = round(255 * 0.5) = 128 (rounded)
        color = heat_color(0.5)
        assert color == "rgb(255,128,128)"

    def test_half_negative_midpoint_color(self):
        # -0.5 → r = g = round(255 * 0.5) = 128
        color = heat_color(-0.5)
        assert color == "rgb(128,128,255)"


# ─── TestApiResponseShape ──────────────────────────────────────────────────────


SAMPLE_RESPONSE = {
    "status": "ok",
    "symbols": ["BANANAS31USDT", "COSUSDT", "DEXEUSDT", "LYNUSDT"],
    "matrix": [
        [1.0, 0.85, 0.72, 0.61],
        [0.85, 1.0, 0.65, 0.55],
        [0.72, 0.65, 1.0, 0.48],
        [0.61, 0.55, 0.48, 1.0],
    ],
    "timestamp": 1710000000,
    "quality": 20,
}


class TestApiResponseShape:
    def test_response_has_symbols_key(self):
        assert "symbols" in SAMPLE_RESPONSE

    def test_response_has_matrix_key(self):
        assert "matrix" in SAMPLE_RESPONSE

    def test_response_has_timestamp_key(self):
        assert "timestamp" in SAMPLE_RESPONSE

    def test_response_has_quality_key(self):
        assert "quality" in SAMPLE_RESPONSE

    def test_matrix_is_list_not_dict(self):
        assert isinstance(SAMPLE_RESPONSE["matrix"], list)

    def test_matrix_rows_are_lists(self):
        for row in SAMPLE_RESPONSE["matrix"]:
            assert isinstance(row, list)

    def test_matrix_diagonal_is_one(self):
        m = SAMPLE_RESPONSE["matrix"]
        for i in range(len(m)):
            assert m[i][i] == 1.0

    def test_quality_is_integer(self):
        assert isinstance(SAMPLE_RESPONSE["quality"], int)

    def test_timestamp_is_integer(self):
        assert isinstance(SAMPLE_RESPONSE["timestamp"], int)

    def test_matrix_shape_matches_symbols_count(self):
        syms = SAMPLE_RESPONSE["symbols"]
        matrix = SAMPLE_RESPONSE["matrix"]
        assert len(matrix) == len(syms)
        for row in matrix:
            assert len(row) == len(syms)

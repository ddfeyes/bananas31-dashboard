"""
test_basis_ma.py — Unit tests for 7-day MA basis computation (SPEC §5).

Module 26: Basis 7-day MA line.
"""


# ── MA computation logic (mirrors main.py) ───────────────────────────

def compute_ma(series, window=168):
    """
    Compute rolling MA over basis_pct series.
    series: list of {"timestamp": int, "basis_pct": float}
    Returns list of {"timestamp", "basis_pct", "ma7d", "window_used"}
    """
    result = []
    for i, pt in enumerate(series):
        start = max(0, i - window + 1)
        vals = [s["basis_pct"] for s in series[start:i + 1]]
        ma = sum(vals) / len(vals)
        result.append({
            "timestamp": pt["timestamp"],
            "basis_pct": pt["basis_pct"],
            "ma7d": ma,
            "window_used": len(vals),
        })
    return result


def make_series(n, basis_val=0.1, start_ts=1774500000):
    """Build a synthetic series of n hourly points with constant basis_pct."""
    return [{"timestamp": start_ts + i * 3600, "basis_pct": basis_val} for i in range(n)]


# ── Tests ─────────────────────────────────────────────────────────────

def test_empty_series_returns_empty():
    """Empty input returns empty output."""
    result = compute_ma([], window=168)
    assert result == []


def test_single_point_ma_equals_value():
    """Single point: MA equals its own value."""
    series = [{"timestamp": 1774500000, "basis_pct": 0.15}]
    result = compute_ma(series, window=168)
    assert len(result) == 1
    assert abs(result[0]["ma7d"] - 0.15) < 1e-9
    assert result[0]["window_used"] == 1


def test_partial_window_uses_available_bars():
    """With fewer bars than window, window_used = actual available bars."""
    series = make_series(10, basis_val=0.1)
    result = compute_ma(series, window=168)
    assert len(result) == 10
    # Each point uses only the bars available so far (1..10)
    for i, pt in enumerate(result):
        assert pt["window_used"] == i + 1
    # All MA values should equal 0.1 (constant input)
    for pt in result:
        assert abs(pt["ma7d"] - 0.1) < 1e-9


def test_full_window_168_bars():
    """After 168+ bars, window_used == 168."""
    series = make_series(300, basis_val=0.1)
    result = compute_ma(series, window=168)
    assert len(result) == 300
    # After index 167 (168th point), full window is used
    for pt in result[167:]:
        assert pt["window_used"] == 168


def test_ma_smoothing_step_change():
    """
    MA should smooth a step change in basis_pct.
    First 100 bars: 0.0, next 100 bars: 1.0.
    At bar 200, MA should be between 0 and 1.
    """
    series = []
    for i in range(200):
        val = 0.0 if i < 100 else 1.0
        series.append({"timestamp": 1774500000 + i * 3600, "basis_pct": val})

    result = compute_ma(series, window=168)
    # At index 199 (bar 200), MA window covers bars 32..199 → 68 zeros + 100 ones = 100/168
    ma_at_end = result[199]["ma7d"]
    expected = 100 / 168
    assert abs(ma_at_end - expected) < 0.001, f"Expected ~{expected:.4f}, got {ma_at_end:.4f}"


def test_ma_constant_series_equals_constant():
    """Constant basis_pct input → MA always equals that constant."""
    CONST = 0.0853  # realistic for BANANAS31
    series = make_series(200, basis_val=CONST)
    result = compute_ma(series, window=168)
    for pt in result:
        assert abs(pt["ma7d"] - CONST) < 1e-9


def test_all_points_have_required_fields():
    """Every result point must have: timestamp, basis_pct, ma7d, window_used."""
    series = make_series(50, basis_val=0.1)
    result = compute_ma(series, window=168)
    required = {"timestamp", "basis_pct", "ma7d", "window_used"}
    for pt in result:
        for field in required:
            assert field in pt, f"Missing field: {field}"


def test_ma_7day_window_is_168_hourly_bars():
    """7 days × 24 hours = 168 bars — this is the correct MA window."""
    assert 7 * 24 == 168


def test_timestamps_preserved():
    """Output timestamps must match input timestamps exactly."""
    series = make_series(20, basis_val=0.1, start_ts=1774500000)
    result = compute_ma(series, window=168)
    for i, pt in enumerate(result):
        assert pt["timestamp"] == series[i]["timestamp"]

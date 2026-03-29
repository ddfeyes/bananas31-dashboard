"""
test_pattern_outcomes.py — Unit tests for historical pattern outcome analysis.

Module 42: /api/analytics/pattern-outcomes
"""
import time


def compute_outcomes(rows, basis_threshold=0.001, horizons=None):
    """
    Mirror the core logic from get_pattern_outcomes().
    rows: list of (timestamp, spot_close, perp_close)
    """
    if horizons is None:
        horizons = [30, 60]
    price_map = {float(r[0]): float(r[1]) for r in rows}

    # Find signals
    signal_times = []
    for ts, spot, perp in rows:
        ts_f = float(ts)
        if spot > 0:
            basis_pct = (perp - spot) / spot
            if basis_pct > basis_threshold:
                signal_times.append(ts_f)

    # Deduplicate (1 per 30-min window)
    dedup_signals = []
    last_ts = 0.0
    for ts_f in signal_times:
        if ts_f - last_ts >= 1800:
            dedup_signals.append(ts_f)
            last_ts = ts_f

    outcomes = {}
    for horizon in horizons:
        horizon_secs = horizon * 60
        returns = []
        for sig_ts in dedup_signals:
            entry = price_map.get(sig_ts)
            exit_p = price_map.get(sig_ts + horizon_secs)
            if entry and exit_p and entry > 0:
                returns.append((exit_p - entry) / entry * 100)

        if returns:
            ups = [r for r in returns if r > 0]
            avg_ret = sum(returns) / len(returns)
            outcomes[str(horizon)] = {
                "horizon_min": horizon,
                "sample_n": len(returns),
                "up_pct": round(len(ups) / len(returns) * 100, 1),
                "avg_return_pct": round(avg_ret, 3),
            }

    return dedup_signals, outcomes


def test_no_signals_when_basis_below_threshold():
    """No squeeze → no matches."""
    now = time.time()
    rows = [(now + i * 60, 100.0, 100.05) for i in range(100)]  # 0.05% basis, below 0.1% threshold
    signals, outcomes = compute_outcomes(rows, basis_threshold=0.001)
    assert len(signals) == 0
    assert outcomes == {}


def test_signal_detected_when_basis_above_threshold():
    """Basis > threshold → signal detected."""
    now = time.time()
    rows = [(now + i * 60, 100.0, 100.15) for i in range(100)]  # 0.15% basis
    signals, outcomes = compute_outcomes(rows, basis_threshold=0.001, horizons=[30])
    assert len(signals) >= 1


def test_outcome_up_when_price_rises():
    """When price rises at T+30min → outcome shows up."""
    now = time.time()
    # Setup: basis squeeze at T=0, then price rises 2% at T+30
    rows = []
    for i in range(200):
        ts = now + i * 60
        spot = 100.0
        perp = 100.15  # squeeze
        if i >= 30:
            spot = 102.0  # price rose 2%
        rows.append((ts, spot, perp))

    signals, outcomes = compute_outcomes(rows, basis_threshold=0.001, horizons=[30])
    assert "30" in outcomes
    assert outcomes["30"]["avg_return_pct"] > 0, "Should show positive return when price rises"


def test_dedup_prevents_signal_spam():
    """Squeeze lasting 2 hours should only produce 1 signal per 30-min window."""
    now = time.time()
    # Continuous squeeze for 120 minutes
    rows = [(now + i * 60, 100.0, 100.2) for i in range(120 + 130)]
    signals, outcomes = compute_outcomes(rows, basis_threshold=0.001, horizons=[30])
    # Should be ~4-5 deduped signals (not 120)
    assert len(signals) <= 10, f"Too many signals: {len(signals)}, expected dedup"

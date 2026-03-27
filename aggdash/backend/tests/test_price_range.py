"""
test_price_range.py — Unit tests for /api/price-range (24h high/low).

Module 35: 24h High/Low range in header stats.
"""
import sqlite3
import time


def make_db(rows):
    """price_feed in-memory DB with (exchange_id, ts, h, l, c) rows."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE price_feed (
            exchange_id TEXT, timestamp REAL, open REAL,
            high REAL, low REAL, close REAL, volume REAL
        )
    """)
    conn.executemany(
        "INSERT INTO price_feed(exchange_id,timestamp,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)",
        [(r[0], r[1], r[4], r[2], r[3], r[4], 1000.0) for r in rows],
    )
    conn.commit()
    return conn


def compute_price_range(conn, source, since):
    """Mirror /api/price-range logic."""
    row = conn.execute(
        """
        SELECT MAX(high), MIN(low),
               (SELECT close FROM price_feed WHERE exchange_id = ? ORDER BY timestamp DESC LIMIT 1)
        FROM price_feed
        WHERE exchange_id = ? AND timestamp >= ?
        """,
        (source, source, since),
    ).fetchone()
    if not row or row[0] is None:
        return {"high_24h": None, "low_24h": None, "range_pct": None}
    h, l, c = row
    range_pct = ((h - l) / l * 100) if l and l > 0 else None
    return {"high_24h": h, "low_24h": l, "range_pct": range_pct, "current": c}


def test_price_range_correct_values():
    """High is the maximum, low is the minimum."""
    now = time.time()
    rows = [
        ("binance-spot", now - 3600, 0.015, 0.013, 0.014),
        ("binance-spot", now - 1800, 0.016, 0.014, 0.015),
        ("binance-spot", now - 900,  0.0148, 0.0135, 0.0140),
    ]
    conn = make_db(rows)
    result = compute_price_range(conn, "binance-spot", now - 86400)
    assert abs(result["high_24h"] - 0.016) < 1e-8
    assert abs(result["low_24h"] - 0.013) < 1e-8


def test_price_range_pct_computation():
    """range_pct = (high - low) / low * 100."""
    now = time.time()
    rows = [("binance-spot", now - 3600, 0.011, 0.010, 0.0105)]
    conn = make_db(rows)
    result = compute_price_range(conn, "binance-spot", now - 86400)
    expected_pct = (0.011 - 0.010) / 0.010 * 100
    assert abs(result["range_pct"] - expected_pct) < 0.001


def test_price_range_empty_returns_none():
    """No data for source → all None."""
    conn = make_db([])
    result = compute_price_range(conn, "binance-spot", time.time() - 86400)
    assert result["high_24h"] is None
    assert result["low_24h"] is None


def test_price_range_excludes_old_bars():
    """Bars older than window are excluded."""
    now = time.time()
    rows = [
        ("binance-spot", now - 100000, 0.999, 0.001, 0.500),  # outside window
        ("binance-spot", now - 3600,   0.015, 0.014, 0.0145),  # inside window
    ]
    conn = make_db(rows)
    result = compute_price_range(conn, "binance-spot", now - 86400)
    # Old bar (high=0.999, low=0.001) should NOT affect range
    assert result["high_24h"] <= 0.015 + 1e-8
    assert result["low_24h"] >= 0.014 - 1e-8

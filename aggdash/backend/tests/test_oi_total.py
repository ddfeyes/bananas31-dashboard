"""
test_oi_total.py — Unit tests for oi_total in /api/stats.

Module 33: OI total absolute value in header stats.
"""
import sqlite3
import time


def make_oi_db(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE oi (exchange_id TEXT, timestamp REAL, open_interest REAL, funding_rate REAL)")
    conn.executemany("INSERT INTO oi(exchange_id,timestamp,open_interest,funding_rate) VALUES(?,?,?,?)",
                     [(r[0], r[1], r[2], 0.0) for r in rows])
    conn.commit()
    return conn


def compute_oi_total(conn):
    """Mirror oi_total computation from get_stats()."""
    oi_now_rows = conn.execute(
        """
        SELECT exchange_id, open_interest FROM oi
        WHERE (exchange_id, timestamp) IN (
            SELECT exchange_id, MAX(timestamp) FROM oi GROUP BY exchange_id
        )
        """
    ).fetchall()
    result = {"binance_perp": 0.0, "bybit_perp": 0.0, "total": 0.0}
    if oi_now_rows:
        seen = set()
        for ex, oi in oi_now_rows:
            if ex not in seen and oi:
                key = ex.replace("-", "_")
                if key in result:
                    result[key] = oi
                seen.add(ex)
        result["total"] = result["binance_perp"] + result["bybit_perp"]
    return result


def test_oi_total_schema():
    """oi_total must have binance_perp, bybit_perp, total."""
    conn = make_oi_db([])
    result = compute_oi_total(conn)
    assert set(result.keys()) == {"binance_perp", "bybit_perp", "total"}


def test_oi_total_empty_db():
    """Empty OI table → all zeros."""
    conn = make_oi_db([])
    result = compute_oi_total(conn)
    assert result["binance_perp"] == 0.0
    assert result["bybit_perp"] == 0.0
    assert result["total"] == 0.0


def test_oi_total_correct_values():
    """Latest OI values returned per exchange."""
    now = time.time()
    rows = [
        ("binance-perp", now - 60, 3_000_000_000),
        ("binance-perp", now - 30, 3_100_000_000),  # latest
        ("bybit-perp",   now - 60, 400_000_000),
        ("bybit-perp",   now - 30, 420_000_000),    # latest
    ]
    conn = make_oi_db(rows)
    result = compute_oi_total(conn)
    assert abs(result["binance_perp"] - 3_100_000_000) < 1
    assert abs(result["bybit_perp"] - 420_000_000) < 1
    assert abs(result["total"] - 3_520_000_000) < 1


def test_oi_total_uses_latest_row():
    """Uses MAX(timestamp) per exchange — not older rows."""
    now = time.time()
    rows = [
        ("binance-perp", now - 300, 1_000_000),  # old
        ("binance-perp", now - 10,  9_000_000),  # latest
    ]
    conn = make_oi_db(rows)
    result = compute_oi_total(conn)
    assert abs(result["binance_perp"] - 9_000_000) < 1, "Should use latest row"

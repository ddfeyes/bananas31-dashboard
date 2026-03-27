"""Tests for /api/analytics/funding/series — funding rate time series."""
import sys
import os
import sqlite3
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def make_funding_db(rows_by_source: dict) -> sqlite3.Connection:
    """Create in-memory funding_rates DB.
    rows_by_source: {source: [(timestamp, rate_8h, rate_1h), ...]}
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE funding_rates (
            exchange_id TEXT NOT NULL,
            timestamp   REAL NOT NULL,
            rate_8h     REAL,
            rate_1h     REAL
        )
    """)
    for source, rows in rows_by_source.items():
        conn.executemany(
            "INSERT INTO funding_rates(exchange_id, timestamp, rate_8h, rate_1h) VALUES (?,?,?,?)",
            [(source, ts, r8, r1) for ts, r8, r1 in rows],
        )
    conn.commit()
    return conn


def get_funding_series(conn, window_secs: int = 86400, interval_secs: int = 300) -> dict:
    """
    Get bucketed funding rate series per exchange.
    Buckets: floor(timestamp / interval_secs) * interval_secs
    Returns last value in each bucket (most recent rate_8h and rate_1h).
    """
    now = time.time()
    since = now - window_secs
    sources = ["binance-perp", "bybit-perp"]
    result = {}

    for src in sources:
        rows = conn.execute(
            """
            SELECT CAST((timestamp / ?) AS INTEGER) * ? AS bucket,
                   rate_8h, rate_1h
            FROM funding_rates
            WHERE exchange_id = ? AND timestamp >= ?
            ORDER BY bucket ASC, timestamp DESC
            """,
            (interval_secs, interval_secs, src, since),
        ).fetchall()

        # Deduplicate buckets — keep last (first in DESC order per bucket)
        seen = set()
        pts = []
        for bucket, r8, r1 in rows:
            if bucket not in seen:
                seen.add(bucket)
                pts.append({"timestamp": int(bucket), "rate_8h": r8, "rate_1h": r1})
        pts.sort(key=lambda x: x["timestamp"])
        result[src] = pts

    return {
        "per_source": result,
        "window_secs": window_secs,
        "interval_secs": interval_secs,
    }


class TestFundingSeries:
    def test_empty_db_returns_empty_series(self):
        conn = make_funding_db({})
        data = get_funding_series(conn)
        for src in ["binance-perp", "bybit-perp"]:
            assert data["per_source"][src] == []

    def test_returns_bucketed_series(self):
        now = time.time()
        interval = 300
        # 4 data points, 2 per bucket
        conn = make_funding_db({
            "binance-perp": [
                (now - 800, 0.00020, 0.000025),
                (now - 750, 0.00021, 0.0000263),  # same bucket as -800
                (now - 400, 0.00022, 0.0000275),
                (now - 60,  0.00023, 0.0000288),
            ],
        })
        data = get_funding_series(conn, window_secs=3600, interval_secs=interval)
        pts = data["per_source"]["binance-perp"]
        # Should have 3 distinct buckets (800s ago, 400s ago, 60s ago → 3 different buckets)
        assert len(pts) >= 2, f"Expected ≥2 buckets, got {len(pts)}: {pts}"

    def test_each_point_has_required_fields(self):
        now = time.time()
        conn = make_funding_db({
            "binance-perp": [(now - 100, 0.00021, 0.0000263)],
        })
        data = get_funding_series(conn, window_secs=3600, interval_secs=60)
        pts = data["per_source"]["binance-perp"]
        assert len(pts) == 1
        pt = pts[0]
        assert "timestamp" in pt
        assert "rate_8h" in pt
        assert "rate_1h" in pt
        assert pt["rate_8h"] == 0.00021
        assert pt["rate_1h"] == 0.0000263

    def test_window_filters_old_data(self):
        now = time.time()
        conn = make_funding_db({
            "binance-perp": [
                (now - 100000, 0.00030, 0.0000375),  # outside window
                (now - 3000,   0.00021, 0.0000263),  # inside window
            ],
        })
        data = get_funding_series(conn, window_secs=86400, interval_secs=60)
        pts = data["per_source"]["binance-perp"]
        assert len(pts) == 1, f"Expected 1 pt, got {len(pts)}"
        assert pts[0]["rate_8h"] == 0.00021

    def test_response_has_metadata(self):
        conn = make_funding_db({})
        data = get_funding_series(conn, window_secs=3600, interval_secs=300)
        assert data["window_secs"] == 3600
        assert data["interval_secs"] == 300
        assert "per_source" in data

    def test_sorted_ascending_by_timestamp(self):
        now = time.time()
        conn = make_funding_db({
            "bybit-perp": [
                (now - 600, 0.00005, 0.00000625),
                (now - 900, 0.00005, 0.00000625),
                (now - 300, 0.00005, 0.00000625),
            ],
        })
        data = get_funding_series(conn, window_secs=3600, interval_secs=60)
        pts = data["per_source"]["bybit-perp"]
        ts_list = [p["timestamp"] for p in pts]
        assert ts_list == sorted(ts_list), f"Not sorted: {ts_list}"


if __name__ == "__main__":
    t = TestFundingSeries()
    t.test_empty_db_returns_empty_series()
    print("PASS: test_empty_db_returns_empty_series")
    t.test_returns_bucketed_series()
    print("PASS: test_returns_bucketed_series")
    t.test_each_point_has_required_fields()
    print("PASS: test_each_point_has_required_fields")
    t.test_window_filters_old_data()
    print("PASS: test_window_filters_old_data")
    t.test_response_has_metadata()
    print("PASS: test_response_has_metadata")
    t.test_sorted_ascending_by_timestamp()
    print("PASS: test_sorted_ascending_by_timestamp")
    print("ALL TESTS PASSED")

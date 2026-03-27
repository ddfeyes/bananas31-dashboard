"""Tests for /api/price-change — 24h % change per source."""
import sys
import os
import sqlite3
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def make_db_with_history(rows_by_source: dict) -> sqlite3.Connection:
    """Create an in-memory price_feed DB with provided rows.

    rows_by_source: {source: [(timestamp, close), ...]}
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE price_feed (
            exchange_id TEXT NOT NULL,
            timestamp   REAL NOT NULL,
            open REAL, high REAL, low REAL,
            close REAL,
            volume REAL
        )
    """)
    for source, rows in rows_by_source.items():
        conn.executemany(
            "INSERT INTO price_feed(exchange_id, timestamp, close) VALUES (?, ?, ?)",
            [(source, ts, price) for ts, price in rows],
        )
    conn.commit()
    return conn


def compute_price_change(conn, source: str, window_secs: int = 86400) -> dict | None:
    """
    Compute 24h price change for a given source.
    Returns {current, prev_24h, change_pct} or None if insufficient data.
    """
    now = time.time()
    # Current price: most recent close
    row_current = conn.execute(
        "SELECT close FROM price_feed WHERE exchange_id = ? ORDER BY timestamp DESC LIMIT 1",
        (source,),
    ).fetchone()
    if not row_current:
        return None

    current = row_current[0]

    # Price 24h ago: closest row to (now - 86400s) within ±30min tolerance
    target_ts = now - window_secs
    row_prev = conn.execute(
        """
        SELECT close FROM price_feed
        WHERE exchange_id = ? AND timestamp >= ? AND timestamp <= ?
        ORDER BY ABS(timestamp - ?) ASC
        LIMIT 1
        """,
        (source, target_ts - 1800, target_ts + 1800, target_ts),
    ).fetchone()

    if not row_prev:
        return None

    prev = row_prev[0]
    change_pct = (current - prev) / prev * 100 if prev else None

    return {"current": current, "prev_24h": prev, "change_pct": change_pct}


class TestPriceChange:
    def test_returns_none_for_empty_db(self):
        conn = make_db_with_history({})
        result = compute_price_change(conn, "binance-spot")
        assert result is None

    def test_returns_none_when_no_historical_price(self):
        """Only recent data, no 24h-ago data."""
        now = time.time()
        conn = make_db_with_history({
            "binance-spot": [(now - 3600, 0.014), (now - 60, 0.013667)],
        })
        result = compute_price_change(conn, "binance-spot")
        # Target is now-86400, no data near there → None
        assert result is None

    def test_positive_change(self):
        now = time.time()
        conn = make_db_with_history({
            "binance-spot": [
                (now - 86400, 0.013000),  # 24h ago
                (now - 60,    0.013650),  # now
            ],
        })
        result = compute_price_change(conn, "binance-spot")
        assert result is not None
        assert abs(result["change_pct"] - 5.0) < 0.01, f"Expected ~5%, got {result['change_pct']}"
        assert result["current"] == 0.013650
        assert result["prev_24h"] == 0.013000

    def test_negative_change(self):
        now = time.time()
        conn = make_db_with_history({
            "binance-spot": [
                (now - 86400, 0.013808),  # 24h ago
                (now - 60,    0.013667),  # now
            ],
        })
        result = compute_price_change(conn, "binance-spot")
        assert result is not None
        expected = (0.013667 - 0.013808) / 0.013808 * 100
        assert abs(result["change_pct"] - expected) < 0.001

    def test_zero_change(self):
        now = time.time()
        conn = make_db_with_history({
            "binance-spot": [
                (now - 86400, 0.01368),
                (now - 60,    0.01368),
            ],
        })
        result = compute_price_change(conn, "binance-spot")
        assert result is not None
        assert result["change_pct"] == 0.0

    def test_multiple_sources(self):
        now = time.time()
        conn = make_db_with_history({
            "binance-spot":  [(now - 86400, 0.014), (now - 60, 0.013)],
            "binance-perp":  [(now - 86400, 0.0141), (now - 60, 0.01301)],
            "bybit-perp":    [(now - 86400, 0.0139), (now - 60, 0.01288)],
        })
        sources = ["binance-spot", "binance-perp", "bybit-perp"]
        results = {src: compute_price_change(conn, src) for src in sources}
        for src, r in results.items():
            assert r is not None, f"Expected result for {src}"
            assert r["change_pct"] < 0, f"Expected negative change for {src}"

    def test_uses_closest_historical_price(self):
        """Should pick the row closest to 24h ago, not the oldest."""
        now = time.time()
        conn = make_db_with_history({
            "binance-spot": [
                (now - 90000, 0.010),    # 25h ago
                (now - 86100, 0.013),    # 23.9h ago — closest to 24h
                (now - 3600,  0.013667), # 1h ago
                (now - 60,    0.013500), # now
            ],
        })
        result = compute_price_change(conn, "binance-spot")
        assert result is not None
        # Should use 0.013 as prev (closest to 24h), not 0.010 (25h)
        assert result["prev_24h"] == 0.013


if __name__ == "__main__":
    t = TestPriceChange()
    t.test_returns_none_for_empty_db()
    print("PASS: test_returns_none_for_empty_db")
    t.test_returns_none_when_no_historical_price()
    print("PASS: test_returns_none_when_no_historical_price")
    t.test_positive_change()
    print("PASS: test_positive_change")
    t.test_negative_change()
    print("PASS: test_negative_change")
    t.test_zero_change()
    print("PASS: test_zero_change")
    t.test_multiple_sources()
    print("PASS: test_multiple_sources")
    t.test_uses_closest_historical_price()
    print("PASS: test_uses_closest_historical_price")
    print("ALL TESTS PASSED")

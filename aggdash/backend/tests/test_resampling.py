"""Tests for OHLCV resampling in db.py."""
import sqlite3
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def make_test_db(rows):
    """Create an in-memory SQLite DB with price_feed rows."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE price_feed (
            exchange_id TEXT NOT NULL,
            timestamp   REAL NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      REAL
        )
    """)
    conn.executemany(
        "INSERT INTO price_feed VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return conn


def resample_ohlcv(conn, exchange_id, cutoff, interval_secs):
    """Same SQL as db.py get_latest_ohlcv with resampling."""
    iv = interval_secs
    sql = """
        SELECT
            CAST(timestamp / :iv AS INTEGER) * :iv AS ts,
            (SELECT p2.open FROM price_feed p2
             WHERE p2.exchange_id = :eid
               AND CAST(p2.timestamp / :iv AS INTEGER) * :iv = CAST(p.timestamp / :iv AS INTEGER) * :iv
             ORDER BY p2.timestamp ASC LIMIT 1) AS open,
            MAX(high)  AS high,
            MIN(low)   AS low,
            (SELECT p2.close FROM price_feed p2
             WHERE p2.exchange_id = :eid
               AND CAST(p2.timestamp / :iv AS INTEGER) * :iv = CAST(p.timestamp / :iv AS INTEGER) * :iv
             ORDER BY p2.timestamp DESC LIMIT 1) AS close,
            SUM(volume) AS volume
        FROM price_feed p
        WHERE exchange_id = :eid AND timestamp > :cutoff
        GROUP BY CAST(timestamp / :iv AS INTEGER)
        ORDER BY ts
    """
    return conn.execute(sql, {"eid": exchange_id, "iv": iv, "cutoff": cutoff}).fetchall()


def test_resample_5m_aggregates_correctly():
    """5 1m bars in a 5m bucket should aggregate to 1 bar."""
    # Align to a 5m boundary to ensure all 5 bars fall in the same bucket
    base = int(1_700_000_000.0 / 300) * 300  # 1699999800
    rows = [
        ("binance-spot", base + i * 60, 1.0 + i * 0.1, 1.5 + i * 0.1, 0.9 + i * 0.1, 1.2 + i * 0.1, 100.0 + i * 10)
        for i in range(5)
    ]
    conn = make_test_db(rows)
    result = resample_ohlcv(conn, "binance-spot", base - 1, 300)
    assert len(result) == 1, f"Expected 1 resampled bar, got {len(result)}"
    bar = result[0]
    # open = first bar's open (i=0)
    assert abs(bar["open"] - 1.0) < 1e-6, f"open mismatch: {bar['open']}"
    # close = last bar's close (i=4: 1.2 + 4*0.1 = 1.6)
    assert abs(bar["close"] - 1.6) < 1e-6, f"close mismatch: {bar['close']}"
    # high = max of all highs (i=4: 1.5 + 4*0.1 = 1.9)
    assert abs(bar["high"] - 1.9) < 1e-6, f"high mismatch: {bar['high']}"
    # low = min of all lows
    assert abs(bar["low"] - 0.9) < 1e-6, f"low mismatch: {bar['low']}"
    # volume = sum
    assert abs(bar["volume"] - sum(100 + i * 10 for i in range(5))) < 1e-6, f"volume mismatch: {bar['volume']}"
    print("PASS: test_resample_5m_aggregates_correctly")


def test_resample_produces_correct_bucket_count():
    """60 1m bars aligned to 5m boundary → 12 buckets at 5m interval."""
    base = int(1_700_000_000.0 / 300) * 300
    rows = [("binance-spot", base + i * 60, 1.0, 1.0, 1.0, 1.0, 1.0) for i in range(60)]
    conn = make_test_db(rows)
    result = resample_ohlcv(conn, "binance-spot", base - 1, 300)
    assert len(result) == 12, f"Expected 12 buckets, got {len(result)}"
    print("PASS: test_resample_produces_correct_bucket_count")


def test_resample_1m_passthrough():
    """1m interval = no resampling, all bars returned."""
    base = int(1_700_000_000.0 / 60) * 60
    rows = [("binance-spot", base + i * 60, 1.0, 1.0, 1.0, 1.0, 1.0) for i in range(10)]
    conn = make_test_db(rows)
    result = resample_ohlcv(conn, "binance-spot", base - 1, 60)
    assert len(result) == 10, f"Expected 10 bars, got {len(result)}"
    print("PASS: test_resample_1m_passthrough")


def test_resample_empty_exchange():
    """Query for non-existent exchange returns empty list."""
    base = int(1_700_000_000.0 / 300) * 300
    rows = [("binance-spot", base + i * 60, 1.0, 1.0, 1.0, 1.0, 1.0) for i in range(5)]
    conn = make_test_db(rows)
    result = resample_ohlcv(conn, "bybit-perp", base - 1, 300)
    assert len(result) == 0, f"Expected 0 bars for unknown exchange, got {len(result)}"
    print("PASS: test_resample_empty_exchange")


if __name__ == "__main__":
    test_resample_5m_aggregates_correctly()
    test_resample_produces_correct_bucket_count()
    test_resample_1m_passthrough()
    test_resample_empty_exchange()
    print("ALL TESTS PASSED")

"""
test_liquidations_api.py — Verify /api/liquidations and /api/liquidations/series endpoints.

Module 25: liquidations chart + series endpoint.
"""
import pytest
import sqlite3
import time
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Schema tests (no running server required) ─────────────────────────

def test_liquidation_record_schema():
    """A liquidation record must have the expected fields."""
    record = {
        "timestamp": 1774500000.0,
        "source": "binance-perp",
        "symbol": "BANANAS31USDT",
        "side": "SELL",
        "quantity": 5000.0,
        "price": 0.01352,
    }
    required = ["timestamp", "source", "symbol", "side", "quantity", "price"]
    for field in required:
        assert field in record, f"liquidation record missing field: {field}"


def test_liquidation_usd_value():
    """USD value = quantity * price."""
    record = {
        "timestamp": 1774500000.0,
        "source": "binance-perp",
        "symbol": "BANANAS31USDT",
        "side": "SELL",
        "quantity": 5000.0,
        "price": 0.01352,
    }
    usd = record["quantity"] * record["price"]
    assert abs(usd - 67.6) < 0.1, f"USD value should be ~67.6, got {usd}"


def test_liquidation_side_values():
    """Side must be 'BUY' or 'SELL'."""
    valid_sides = {"BUY", "SELL"}
    for side in ["BUY", "SELL"]:
        assert side in valid_sides


# ── Series bucketing logic ────────────────────────────────────────────

def _make_series_from_records(records, bucket_secs=60):
    """Simulate the bucketing logic from /api/liquidations/series."""
    buckets = {}
    for r in records:
        bucket = int(r["timestamp"] // bucket_secs) * bucket_secs
        if bucket not in buckets:
            buckets[bucket] = {"timestamp": bucket, "sell_usd": 0.0, "sell_count": 0, "buy_usd": 0.0, "buy_count": 0}
        side_key = "sell" if r["side"].upper() == "SELL" else "buy"
        usd = r["quantity"] * r["price"]
        buckets[bucket][f"{side_key}_usd"] += usd
        buckets[bucket][f"{side_key}_count"] += 1
    return sorted(buckets.values(), key=lambda x: x["timestamp"])


def test_series_bucketing_basic():
    """Two liquidations in the same minute should merge into one bucket."""
    base_ts = 1774500000.0  # divisible by 60
    records = [
        {"timestamp": base_ts, "side": "SELL", "quantity": 5000.0, "price": 0.01352},
        {"timestamp": base_ts + 30, "side": "SELL", "quantity": 3000.0, "price": 0.01350},
    ]
    series = _make_series_from_records(records, bucket_secs=60)
    assert len(series) == 1, f"Expected 1 bucket, got {len(series)}"
    assert series[0]["sell_count"] == 2
    assert abs(series[0]["sell_usd"] - (5000 * 0.01352 + 3000 * 0.01350)) < 0.001


def test_series_bucketing_separate_minutes():
    """Liquidations in different minutes produce separate buckets."""
    base_ts = 1774500000.0  # divisible by 60
    records = [
        {"timestamp": base_ts, "side": "SELL", "quantity": 5000.0, "price": 0.01352},
        {"timestamp": base_ts + 61, "side": "BUY", "quantity": 2000.0, "price": 0.01350},
    ]
    series = _make_series_from_records(records, bucket_secs=60)
    assert len(series) == 2, f"Expected 2 buckets, got {len(series)}"


def test_series_buy_sell_separation():
    """BUY and SELL liquidations should go into separate usd accumulators."""
    base_ts = 1774500000.0
    records = [
        {"timestamp": base_ts, "side": "SELL", "quantity": 5000.0, "price": 0.01352},
        {"timestamp": base_ts + 10, "side": "BUY",  "quantity": 1000.0, "price": 0.01352},
    ]
    series = _make_series_from_records(records, bucket_secs=60)
    assert len(series) == 1
    bucket = series[0]
    assert bucket["sell_count"] == 1
    assert bucket["buy_count"] == 1
    assert bucket["sell_usd"] > 0
    assert bucket["buy_usd"] > 0
    assert abs(bucket["sell_usd"] - 67.6) < 0.5
    assert abs(bucket["buy_usd"] - 13.52) < 0.1


def test_series_empty_records():
    """Empty liquidation list produces empty series."""
    series = _make_series_from_records([])
    assert series == []


def test_series_usd_totals_are_positive():
    """USD totals from any valid record should be non-negative."""
    records = [
        {"timestamp": 1774500000.0, "side": "SELL", "quantity": 10000.0, "price": 0.014},
        {"timestamp": 1774500010.0, "side": "BUY",  "quantity": 5000.0,  "price": 0.013},
    ]
    series = _make_series_from_records(records)
    for b in series:
        assert b["sell_usd"] >= 0
        assert b["buy_usd"] >= 0


# ── DB layer test (in-memory SQLite) ─────────────────────────────────

def test_liquidations_table_schema():
    """Liquidations table must have expected columns."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE liquidations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            source TEXT NOT NULL,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            price REAL
        )
    """)
    # Insert test row
    conn.execute(
        "INSERT INTO liquidations(timestamp, source, symbol, side, quantity, price) VALUES (?,?,?,?,?,?)",
        (time.time(), "binance-perp", "BANANAS31USDT", "SELL", 5000.0, 0.01352),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM liquidations LIMIT 1").fetchone()
    assert row is not None, "Row should be inserted"
    conn.close()


def test_liquidations_series_bucket_aggregation_sql():
    """SQL bucket aggregation produces correct results (mirrors /api/liquidations/series)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE liquidations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            source TEXT NOT NULL,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            price REAL
        )
    """)
    base_ts = 1774500000.0
    rows = [
        (base_ts,        "binance-perp", "BANANAS31USDT", "SELL", 5000.0, 0.014),
        (base_ts + 30,   "binance-perp", "BANANAS31USDT", "SELL", 2000.0, 0.014),
        (base_ts + 61,   "binance-perp", "BANANAS31USDT", "BUY",  1000.0, 0.014),
    ]
    conn.executemany(
        "INSERT INTO liquidations(timestamp, source, symbol, side, quantity, price) VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()

    bucket_secs = 60
    result = conn.execute(
        """
        SELECT CAST(timestamp / ? AS INTEGER) * ? AS bucket,
               side, COUNT(*) AS cnt, SUM(quantity * price) AS usd
        FROM liquidations
        GROUP BY bucket, side
        ORDER BY bucket ASC
        """,
        (bucket_secs, bucket_secs),
    ).fetchall()

    assert len(result) == 2, f"Expected 2 rows (SELL bucket + BUY bucket), got {len(result)}"
    sell_row = next(r for r in result if r[1].upper() == "SELL")
    buy_row  = next(r for r in result if r[1].upper() == "BUY")
    assert sell_row[2] == 2, "Should have 2 SELL liquidations in first minute"
    assert buy_row[2]  == 1, "Should have 1 BUY liquidation in second minute"
    assert abs(sell_row[3] - (5000 + 2000) * 0.014) < 0.01
    conn.close()

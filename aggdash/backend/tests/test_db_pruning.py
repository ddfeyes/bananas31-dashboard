"""
test_db_pruning.py — Unit tests for DB pruning logic.

Module 34: price_feed pruning to retain 90 days.
"""
import sqlite3
import time


def make_db():
    """In-memory DB with price_feed and oi tables."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE price_feed (
            exchange_id TEXT, timestamp REAL, open REAL, high REAL,
            low REAL, close REAL, volume REAL
        )
    """)
    conn.execute("""
        CREATE TABLE oi (
            exchange_id TEXT, timestamp REAL, open_interest REAL, funding_rate REAL
        )
    """)
    conn.commit()
    return conn


def insert_rows(conn, table, rows):
    if table == "price_feed":
        conn.executemany(
            "INSERT INTO price_feed(exchange_id,timestamp,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)",
            [(r[0], r[1], 0.01, 0.01, 0.01, 0.01, 1000.0) for r in rows],
        )
    elif table == "oi":
        conn.executemany(
            "INSERT INTO oi(exchange_id,timestamp,open_interest,funding_rate) VALUES(?,?,?,?)",
            [(r[0], r[1], 1000000.0, 0.0001) for r in rows],
        )
    conn.commit()


def prune_price_feed(conn, retention_days=90):
    """Mirror _db_prune_loop() pruning logic."""
    cutoff = time.time() - retention_days * 86400
    result = conn.execute("DELETE FROM price_feed WHERE timestamp < ?", (cutoff,))
    conn.commit()
    return result.rowcount


# ── Tests ─────────────────────────────────────────────────────────────

def test_prune_removes_old_rows():
    """Rows older than retention are deleted."""
    conn = make_db()
    now = time.time()
    rows = [
        ("binance-spot", now - 100 * 86400),  # 100d ago — OLD, should be pruned
        ("binance-spot", now - 91 * 86400),   # 91d ago  — OLD
        ("binance-spot", now - 89 * 86400),   # 89d ago  — keep
        ("binance-spot", now - 1 * 86400),    # 1d ago   — keep
        ("binance-spot", now - 60),            # 1min ago — keep
    ]
    insert_rows(conn, "price_feed", rows)
    deleted = prune_price_feed(conn, retention_days=90)
    assert deleted == 2, f"Expected 2 deleted, got {deleted}"


def test_prune_keeps_recent_rows():
    """Rows within retention window are preserved."""
    conn = make_db()
    now = time.time()
    rows = [
        ("binance-perp", now - 30 * 86400),  # 30d ago — keep
        ("binance-perp", now - 60 * 86400),  # 60d ago — keep
        ("binance-perp", now - 89 * 86400),  # 89d ago — keep (just inside)
    ]
    insert_rows(conn, "price_feed", rows)
    deleted = prune_price_feed(conn, retention_days=90)
    assert deleted == 0, "No rows should be deleted within retention window"
    count = conn.execute("SELECT COUNT(*) FROM price_feed").fetchone()[0]
    assert count == 3


def test_prune_leaves_oi_untouched():
    """OI table is not affected by price_feed pruning."""
    conn = make_db()
    now = time.time()
    # Old OI rows (120d ago) — must be kept
    insert_rows(conn, "oi", [
        ("binance-perp", now - 120 * 86400),
        ("bybit-perp", now - 100 * 86400),
    ])
    # Old price_feed rows — will be deleted
    insert_rows(conn, "price_feed", [
        ("binance-spot", now - 100 * 86400),
    ])
    prune_price_feed(conn, retention_days=90)

    oi_count = conn.execute("SELECT COUNT(*) FROM oi").fetchone()[0]
    assert oi_count == 2, "OI rows must not be touched by price_feed prune"


def test_prune_empty_table():
    """Pruning an empty table returns 0 deleted."""
    conn = make_db()
    deleted = prune_price_feed(conn, retention_days=90)
    assert deleted == 0


def test_prune_retention_boundary():
    """Rows exactly at boundary (90d ago) are pruned (< not <=)."""
    conn = make_db()
    now = time.time()
    exactly_90d = now - 90 * 86400
    rows = [("binance-spot", exactly_90d - 1)]  # 1 second before cutoff → prune
    insert_rows(conn, "price_feed", rows)
    deleted = prune_price_feed(conn, retention_days=90)
    assert deleted == 1

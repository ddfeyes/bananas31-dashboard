"""
test_startup_prune.py — Verify startup prune logic.

Module 37: run DB prune at startup to immediately compact historical data.
"""
import sqlite3
import time


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE price_feed (
            exchange_id TEXT, timestamp REAL, open REAL,
            high REAL, low REAL, close REAL, volume REAL
        )
    """)
    conn.commit()
    return conn


def run_prune_sync_fn(conn, retention_days=90, run_vacuum=False):
    """Mirror _run_prune_sync() logic (without VACUUM on :memory:)."""
    cutoff = time.time() - retention_days * 86400
    result = conn.execute("DELETE FROM price_feed WHERE timestamp < ?", (cutoff,))
    deleted = result.rowcount
    conn.commit()
    return deleted


def test_startup_prune_removes_historical_backfill():
    """365-day backfill rows are removed on first prune run (90d retention)."""
    conn = make_db()
    now = time.time()
    # Add rows at various ages
    rows = [(now - 365*86400, "very old"),   # 365d — DELETE
            (now - 180*86400, "6 months"),   # 180d — DELETE
            (now - 91*86400, "91d old"),     # 91d — DELETE
            (now - 89*86400, "89d old"),     # 89d — KEEP
            (now - 30*86400, "30d old"),     # 30d — KEEP
            (now - 3600, "1h old")]          # 1h  — KEEP
    conn.executemany(
        "INSERT INTO price_feed(exchange_id,timestamp,open,high,low,close,volume) VALUES(?,?,0,0,0,0,0)",
        [("binance-spot", r[0]) for r in rows],
    )
    conn.commit()
    deleted = run_prune_sync_fn(conn, retention_days=90)
    assert deleted == 3, f"Expected 3 deleted (>90d), got {deleted}"
    remaining = conn.execute("SELECT COUNT(*) FROM price_feed").fetchone()[0]
    assert remaining == 3, f"Expected 3 remaining (<=90d), got {remaining}"


def test_startup_prune_returns_deleted_count():
    """Returns correct count of deleted rows."""
    conn = make_db()
    now = time.time()
    conn.execute("INSERT INTO price_feed(exchange_id,timestamp,open,high,low,close,volume) VALUES(?,?,0,0,0,0,0)",
                 ("binance-spot", now - 200*86400))
    conn.commit()
    deleted = run_prune_sync_fn(conn, retention_days=90)
    assert deleted == 1


def test_startup_prune_empty_table():
    """No-op on empty table, returns 0."""
    conn = make_db()
    deleted = run_prune_sync_fn(conn, retention_days=90)
    assert deleted == 0


def test_startup_prune_all_recent():
    """All rows recent → nothing deleted."""
    conn = make_db()
    now = time.time()
    for i in range(5):
        conn.execute("INSERT INTO price_feed(exchange_id,timestamp,open,high,low,close,volume) VALUES(?,?,0,0,0,0,0)",
                     ("binance-spot", now - i * 86400))
    conn.commit()
    deleted = run_prune_sync_fn(conn, retention_days=90)
    assert deleted == 0

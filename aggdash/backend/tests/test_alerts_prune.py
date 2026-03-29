"""
test_alerts_prune.py — Alert dedup window + pruning tests.

Module 46: alerts table pruning + dedup aligned to cooldown.
"""
import sqlite3
import time


def _setup_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            kind TEXT, name TEXT, severity TEXT,
            message TEXT, value REAL, sent_telegram INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def _log_alert(db_path, kind, name, ts=None, dedup_window=1800):
    now = ts or time.time()
    conn = sqlite3.connect(db_path)
    try:
        recent = conn.execute(
            "SELECT id FROM alerts WHERE kind=? AND name=? AND timestamp>=? LIMIT 1",
            (kind, name, now - dedup_window),
        ).fetchone()
        if recent:
            return False
        conn.execute(
            "INSERT INTO alerts(timestamp, kind, name, severity, message) VALUES (?,?,?,?,?)",
            (now, kind, name, "medium", "test"),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def _count(db_path, name=None):
    conn = sqlite3.connect(db_path)
    try:
        if name:
            return conn.execute("SELECT COUNT(*) FROM alerts WHERE name=?", (name,)).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    finally:
        conn.close()


def _prune_alerts(db_path, retention_days=30):
    """Mirror of prune logic in main.py."""
    cutoff = time.time() - retention_days * 86400
    conn = sqlite3.connect(db_path)
    try:
        deleted = conn.execute("DELETE FROM alerts WHERE timestamp < ?", (cutoff,)).rowcount
        conn.commit()
        return deleted
    finally:
        conn.close()


def test_dedup_window_1800s(tmp_path):
    """Dedup window default 1800s — no double alert within 30min."""
    db = str(tmp_path / "test.db")
    _setup_db(db)

    now = time.time()
    # First alert
    assert _log_alert(db, "pattern", "BASIS_SQUEEZE", now) is True
    # Within 1800s window — should be deduped
    assert _log_alert(db, "pattern", "BASIS_SQUEEZE", now + 600) is False
    assert _count(db, "BASIS_SQUEEZE") == 1


def test_dedup_window_expired(tmp_path):
    """Alert after dedup window (1800s) should insert."""
    db = str(tmp_path / "test.db")
    _setup_db(db)

    now = time.time()
    _log_alert(db, "pattern", "BASIS_SQUEEZE", now)
    # After 1800s
    result = _log_alert(db, "pattern", "BASIS_SQUEEZE", now + 1801)
    assert result is True
    assert _count(db, "BASIS_SQUEEZE") == 2


def test_prune_removes_old_alerts(tmp_path):
    """Alerts older than 30 days should be pruned."""
    db = str(tmp_path / "test.db")
    _setup_db(db)

    now = time.time()
    old_ts = now - 31 * 86400  # 31 days ago

    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO alerts(timestamp, kind, name, severity, message) VALUES (?,?,?,?,?)",
        (old_ts, "pattern", "OLD_ALERT", "medium", "old"),
    )
    conn.execute(
        "INSERT INTO alerts(timestamp, kind, name, severity, message) VALUES (?,?,?,?,?)",
        (now, "pattern", "NEW_ALERT", "medium", "new"),
    )
    conn.commit()
    conn.close()

    deleted = _prune_alerts(db, retention_days=30)
    assert deleted == 1
    assert _count(db, "OLD_ALERT") == 0
    assert _count(db, "NEW_ALERT") == 1


def test_prune_keeps_recent_alerts(tmp_path):
    """Alerts within 30 days must not be deleted."""
    db = str(tmp_path / "test.db")
    _setup_db(db)

    now = time.time()
    for i in range(5):
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO alerts(timestamp, kind, name, severity, message) VALUES (?,?,?,?,?)",
            (now - i * 3600, "pattern", f"ALERT_{i}", "medium", "msg"),
        )
        conn.commit()
        conn.close()

    deleted = _prune_alerts(db, retention_days=30)
    assert deleted == 0
    assert _count(db) == 5

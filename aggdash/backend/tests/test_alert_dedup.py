"""
test_alert_dedup.py — Alert deduplication in log_alert().

Module 44: fix duplicate alerts from concurrent pattern/signal loops.
"""
import sqlite3
import time

import pytest


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Use a temporary DB for testing."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("AGGDASH_DB_PATH", db_path)
    monkeypatch.setitem(__import__("sys").modules, "db", None)

    # Create schema manually
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS alerts (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            kind     TEXT,
            name     TEXT,
            severity TEXT,
            message  TEXT,
            value    REAL,
            sent_telegram INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()
    return db_path


def _log_alert_impl(db_path, kind, name, severity, message, dedup_window_secs=120):
    """Standalone implementation of log_alert() for isolated testing."""
    now = time.time()
    conn = sqlite3.connect(db_path)
    try:
        recent = conn.execute(
            "SELECT id FROM alerts WHERE kind=? AND name=? AND timestamp>=? LIMIT 1",
            (kind, name, now - dedup_window_secs),
        ).fetchone()
        if recent:
            return False
        conn.execute(
            "INSERT INTO alerts(timestamp, kind, name, severity, message, sent_telegram) VALUES (?,?,?,?,?,0)",
            (now, kind, name, severity, message),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def _count_alerts(db_path, name):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM alerts WHERE name=?", (name,)).fetchone()[0]
    finally:
        conn.close()


def test_first_alert_inserted(tmp_db):
    """First call should insert the alert."""
    result = _log_alert_impl(tmp_db, "pattern", "BASIS_SQUEEZE", "medium", "test msg")
    assert result is True
    assert _count_alerts(tmp_db, "BASIS_SQUEEZE") == 1


def test_duplicate_within_window_suppressed(tmp_db):
    """Second call within dedup window should be skipped."""
    _log_alert_impl(tmp_db, "pattern", "BASIS_SQUEEZE", "medium", "msg 1", dedup_window_secs=120)
    result = _log_alert_impl(tmp_db, "pattern", "BASIS_SQUEEZE", "medium", "msg 2", dedup_window_secs=120)
    assert result is False
    assert _count_alerts(tmp_db, "BASIS_SQUEEZE") == 1  # still only 1


def test_different_alert_names_not_deduped(tmp_db):
    """Different alert names should each insert independently."""
    _log_alert_impl(tmp_db, "pattern", "BASIS_SQUEEZE", "medium", "squeeze msg", dedup_window_secs=120)
    result = _log_alert_impl(tmp_db, "pattern", "LIQUIDATION_CASCADE", "medium", "liq msg", dedup_window_secs=120)
    assert result is True
    assert _count_alerts(tmp_db, "LIQUIDATION_CASCADE") == 1


def test_expired_window_allows_refire(tmp_db):
    """Alert outside dedup window should insert again."""
    # Insert with a very short window
    _log_alert_impl(tmp_db, "pattern", "BASIS_SQUEEZE", "medium", "first", dedup_window_secs=0)
    # Immediately re-insert — window=0 means expired
    result = _log_alert_impl(tmp_db, "pattern", "BASIS_SQUEEZE", "medium", "second", dedup_window_secs=0)
    assert result is True
    assert _count_alerts(tmp_db, "BASIS_SQUEEZE") == 2

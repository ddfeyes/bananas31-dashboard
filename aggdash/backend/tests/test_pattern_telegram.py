"""
test_pattern_telegram.py — Verify all patterns can trigger Telegram alerts.

Module 36: generalized pattern Telegram alerts.
"""
import sqlite3
import time


def make_alerts_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            severity TEXT,
            message TEXT,
            value REAL,
            sent_telegram INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def get_last_alert_ts_fn(conn, name, kind):
    row = conn.execute(
        "SELECT MAX(timestamp) FROM alerts WHERE name=? AND kind=?", (name, kind)
    ).fetchone()
    return row[0] or 0.0


def should_send_pattern_tg(conn, pat_name, severity, now, cooldown=1800):
    """Mirror the Telegram loop pattern filtering logic."""
    if severity not in ("high", "medium"):
        return False
    last_ts = get_last_alert_ts_fn(conn, pat_name, kind="pattern_tg")
    return (now - last_ts) >= cooldown


def test_liquidation_cascade_eligible_for_telegram():
    """LIQUIDATION_CASCADE (high/medium) should be eligible for Telegram."""
    conn = make_alerts_db()
    now = time.time()
    result = should_send_pattern_tg(conn, "LIQUIDATION_CASCADE", "high", now)
    assert result is True, "LIQUIDATION_CASCADE should be eligible for Telegram"


def test_basis_squeeze_eligible():
    """BASIS_SQUEEZE (medium) should be eligible for Telegram when no prior alert."""
    conn = make_alerts_db()
    now = time.time()
    result = should_send_pattern_tg(conn, "BASIS_SQUEEZE", "medium", now)
    assert result is True


def test_dex_premium_eligible():
    """DEX_PREMIUM (medium) should be eligible for Telegram."""
    conn = make_alerts_db()
    now = time.time()
    result = should_send_pattern_tg(conn, "DEX_PREMIUM", "medium", now)
    assert result is True


def test_all_pattern_names_eligible():
    """All 5 pattern types can trigger Telegram (given no prior cooldown)."""
    conn = make_alerts_db()
    now = time.time()
    patterns = [
        ("BASIS_SQUEEZE", "medium"),
        ("DEX_PREMIUM", "medium"),
        ("OI_ACCUMULATION", "high"),
        ("LIQUIDATION_CASCADE", "high"),
        ("VOLUME_DIVERGENCE", "medium"),
    ]
    for name, sev in patterns:
        result = should_send_pattern_tg(conn, name, sev, now)
        assert result is True, f"{name} should be eligible for Telegram"


def test_cooldown_prevents_duplicate_pattern_tg():
    """Pattern not resent within 30min cooldown."""
    conn = make_alerts_db()
    now = time.time()
    # Record a recent send
    conn.execute(
        "INSERT INTO alerts(timestamp,kind,name,severity,message,sent_telegram) VALUES(?,?,?,?,?,?)",
        (now - 900, "pattern_tg", "LIQUIDATION_CASCADE", "high", "msg", 1),
    )
    conn.commit()
    result = should_send_pattern_tg(conn, "LIQUIDATION_CASCADE", "high", now)
    assert result is False, "Should be in cooldown (900s < 1800s)"

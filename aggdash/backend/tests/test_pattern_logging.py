"""
test_pattern_logging.py — Verify patterns are logged to alerts DB.

Module 30: pattern logging + Telegram alerts for patterns.
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


def log_alert_fn(conn, kind, name, severity, message, value=None, sent_telegram=False, ts=None):
    ts = ts or time.time()
    conn.execute(
        "INSERT INTO alerts(timestamp,kind,name,severity,message,value,sent_telegram) VALUES(?,?,?,?,?,?,?)",
        (ts, kind, name, severity, message, value, 1 if sent_telegram else 0),
    )
    conn.commit()


def get_last_alert_ts_fn(conn, name, kind=None):
    if kind:
        row = conn.execute(
            "SELECT MAX(timestamp) FROM alerts WHERE name=? AND kind=?", (name, kind)
        ).fetchone()
    else:
        row = conn.execute("SELECT MAX(timestamp) FROM alerts WHERE name=?", (name,)).fetchone()
    return row[0] or 0.0


def simulate_pattern_log(conn, pattern, now, cooldown=1800):
    """Simulate the pattern logging logic from /api/patterns."""
    last_ts = get_last_alert_ts_fn(conn, pattern["name"], kind="pattern")
    if now - last_ts >= cooldown:
        log_alert_fn(
            conn,
            kind="pattern",
            name=pattern["name"],
            severity=pattern.get("severity", "medium"),
            message=pattern.get("description", ""),
            value=pattern.get("confidence"),
            sent_telegram=False,
        )
        return True  # logged
    return False  # skipped (cooldown)


# ── Tests ─────────────────────────────────────────────────────────────

def test_pattern_logged_to_db():
    """Pattern is correctly logged to alerts DB."""
    conn = make_alerts_db()
    now = time.time()
    pat = {
        "name": "BASIS_SQUEEZE",
        "severity": "medium",
        "description": "Basis 0.15% with positive funding",
        "confidence": 0.15,
    }
    logged = simulate_pattern_log(conn, pat, now)
    assert logged is True

    rows = conn.execute("SELECT * FROM alerts WHERE kind='pattern'").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "BASIS_SQUEEZE"
    assert rows[0]["kind"] == "pattern"
    assert rows[0]["sent_telegram"] == 0


def test_pattern_dedup_within_cooldown():
    """Same pattern not logged twice within 30min cooldown."""
    conn = make_alerts_db()
    now = time.time()
    pat = {"name": "DEX_PREMIUM", "severity": "medium", "description": "0.35% premium", "confidence": 0.35}

    # First log — should succeed
    logged1 = simulate_pattern_log(conn, pat, now)
    # Second log within cooldown — should be skipped
    logged2 = simulate_pattern_log(conn, pat, now + 100)

    assert logged1 is True
    assert logged2 is False
    count = conn.execute("SELECT COUNT(*) FROM alerts WHERE name='DEX_PREMIUM'").fetchone()[0]
    assert count == 1, "Only one entry should exist within cooldown"


def test_pattern_logged_again_after_cooldown():
    """Pattern can fire again after cooldown expires."""
    conn = make_alerts_db()
    now = time.time()
    pat = {"name": "OI_ACCUMULATION", "severity": "high", "description": "OI +2.1%", "confidence": 0.8}

    log_alert_fn(conn, "pattern", "OI_ACCUMULATION", "high", "msg", ts=now - 2000)  # old entry

    # Should log again after cooldown (2000s > 1800s cooldown)
    logged = simulate_pattern_log(conn, pat, now, cooldown=1800)
    assert logged is True
    count = conn.execute("SELECT COUNT(*) FROM alerts WHERE name='OI_ACCUMULATION'").fetchone()[0]
    assert count == 2


def test_pattern_severity_stored_correctly():
    """Severity from pattern dict is stored in alerts table."""
    conn = make_alerts_db()
    now = time.time()
    for sev in ["high", "medium", "low"]:
        pat = {"name": f"TEST_{sev}", "severity": sev, "description": f"desc_{sev}", "confidence": 0.5}
        simulate_pattern_log(conn, pat, now)

    rows = {r["name"]: r["severity"] for r in conn.execute("SELECT * FROM alerts").fetchall()}
    assert rows["TEST_high"] == "high"
    assert rows["TEST_medium"] == "medium"
    assert rows["TEST_low"] == "low"


def test_pattern_confidence_stored_as_value():
    """Confidence is stored as the 'value' field."""
    conn = make_alerts_db()
    now = time.time()
    pat = {"name": "LIQUIDATION_CASCADE", "severity": "high", "description": "8 liqs in 5min", "confidence": 0.53}
    simulate_pattern_log(conn, pat, now)
    row = conn.execute("SELECT * FROM alerts WHERE name='LIQUIDATION_CASCADE'").fetchone()
    assert row is not None
    assert abs(row["value"] - 0.53) < 1e-6

"""
test_alerts_history.py — Unit tests for persistent alert history.

Module 29: alerts table + /api/alerts/history + DB-based Telegram dedup.
"""
import sqlite3
import time


# ── Helpers ───────────────────────────────────────────────────────────

def make_alerts_db():
    """Create in-memory DB with alerts table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE alerts (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp      REAL NOT NULL,
            kind           TEXT NOT NULL,
            name           TEXT NOT NULL,
            severity       TEXT,
            message        TEXT,
            value          REAL,
            sent_telegram  INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX idx_alerts_timestamp ON alerts(timestamp DESC)")
    conn.commit()
    return conn


def insert_alert(conn, kind, name, severity, message, value=None, sent_telegram=False, ts=None):
    ts = ts or time.time()
    conn.execute(
        "INSERT INTO alerts(timestamp, kind, name, severity, message, value, sent_telegram) VALUES(?,?,?,?,?,?,?)",
        (ts, kind, name, severity, message, value, 1 if sent_telegram else 0),
    )
    conn.commit()


def get_alerts(conn, limit=50):
    rows = conn.execute("SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_last_alert_ts(conn, name, kind=None):
    if kind:
        row = conn.execute(
            "SELECT MAX(timestamp) FROM alerts WHERE name=? AND kind=?", (name, kind)
        ).fetchone()
    else:
        row = conn.execute("SELECT MAX(timestamp) FROM alerts WHERE name=?", (name,)).fetchone()
    return row[0] or 0.0


# ── Tests ─────────────────────────────────────────────────────────────

def test_alerts_table_insert_and_query():
    """Basic insert + query round-trip."""
    conn = make_alerts_db()
    insert_alert(conn, kind="signal", name="Squeeze Risk", severity="alert",
                 message="Basis 0.25% + funding positive", value=0.0025)
    rows = get_alerts(conn)
    assert len(rows) == 1
    assert rows[0]["name"] == "Squeeze Risk"
    assert rows[0]["kind"] == "signal"
    assert rows[0]["sent_telegram"] == 0


def test_alerts_sorted_by_timestamp_desc():
    """Most recent alert first."""
    conn = make_alerts_db()
    base = time.time()
    insert_alert(conn, "signal", "A", "info", "msg", ts=base - 120)
    insert_alert(conn, "signal", "B", "info", "msg", ts=base - 60)
    insert_alert(conn, "signal", "C", "info", "msg", ts=base - 10)
    rows = get_alerts(conn)
    assert rows[0]["name"] == "C", "Most recent should be first"
    assert rows[-1]["name"] == "A", "Oldest should be last"


def test_dedup_via_last_alert_ts():
    """Cooldown check: same alert not resent within COOLDOWN_SECS."""
    conn = make_alerts_db()
    COOLDOWN_SECS = 1800
    now = time.time()
    insert_alert(conn, "signal", "Squeeze Risk", "alert", "msg", ts=now - 900)  # 15 min ago

    last_sent = get_last_alert_ts(conn, "Squeeze Risk", kind="signal")
    assert last_sent > 0
    should_skip = (now - last_sent) < COOLDOWN_SECS
    assert should_skip, "Should skip within cooldown window"


def test_dedup_fires_after_cooldown():
    """Alert should resend after cooldown period."""
    conn = make_alerts_db()
    COOLDOWN_SECS = 1800
    now = time.time()
    insert_alert(conn, "signal", "Squeeze Risk", "alert", "msg", ts=now - 2000)  # 33 min ago

    last_sent = get_last_alert_ts(conn, "Squeeze Risk", kind="signal")
    should_skip = (now - last_sent) < COOLDOWN_SECS
    assert not should_skip, "Should NOT skip after cooldown expired"


def test_alerts_sent_telegram_flag():
    """sent_telegram=True is persisted correctly."""
    conn = make_alerts_db()
    insert_alert(conn, "signal", "DEX Arbitrage", "warning", "msg", sent_telegram=True)
    rows = get_alerts(conn)
    assert rows[0]["sent_telegram"] == 1


def test_alerts_kind_filter():
    """get_last_alert_ts respects kind filter."""
    conn = make_alerts_db()
    now = time.time()
    insert_alert(conn, "signal",  "Squeeze Risk", "alert", "msg", ts=now - 1000)
    insert_alert(conn, "pattern", "Squeeze Risk", "medium", "msg", ts=now - 100)

    ts_signal  = get_last_alert_ts(conn, "Squeeze Risk", kind="signal")
    ts_pattern = get_last_alert_ts(conn, "Squeeze Risk", kind="pattern")
    # Signal was 1000s ago, pattern was 100s ago — different values
    assert abs(ts_signal - (now - 1000)) < 2
    assert abs(ts_pattern - (now - 100)) < 2


def test_alerts_history_limit():
    """Query respects limit parameter."""
    conn = make_alerts_db()
    now = time.time()
    for i in range(20):
        insert_alert(conn, "signal", f"sig_{i}", "info", "msg", ts=now - i * 60)
    rows = get_alerts(conn, limit=5)
    assert len(rows) == 5


def test_no_alerts_returns_empty():
    """Empty table → empty list."""
    conn = make_alerts_db()
    rows = get_alerts(conn)
    assert rows == []
    last = get_last_alert_ts(conn, "any_name")
    assert last == 0.0

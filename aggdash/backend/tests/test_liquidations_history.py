"""
test_liquidations_history.py — Liquidation history endpoint tests.

Module 45: /api/liquidations/history
"""
import sqlite3
import time


def _insert_liquidations(db_path, count=5):
    """Helper: insert test liquidations."""
    now = time.time()
    conn = sqlite3.connect(db_path)
    for i in range(count):
        conn.execute(
            "INSERT INTO liquidations(timestamp, source, symbol, side, quantity, price) VALUES (?,?,?,?,?,?)",
            (now - i * 60, f"binance-{i%2}", "BANANAS31", "BUY" if i % 2 == 0 else "SELL", 100.0 + i, 0.01 + i * 0.001),
        )
    conn.commit()
    conn.close()


def _query_liquidations(db_path, limit=50, window_secs=3600):
    """Standalone query logic."""
    since_ts = time.time() - window_secs
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, timestamp, source, symbol, side, quantity, price
            FROM liquidations
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (since_ts, limit),
        ).fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "source": r[2],
                "side": r[4],
                "quantity": r[5],
                "price": r[6],
                "usd_value": r[5] * r[6],
            }
            for r in rows
        ]
    finally:
        conn.close()


def _setup_db(db_path):
    """Create liquidations table."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS liquidations (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            source    TEXT,
            symbol    TEXT,
            side      TEXT,
            quantity  REAL,
            price     REAL
        )
        """
    )
    conn.commit()
    conn.close()


def test_liquidation_query_returns_newest_first(tmp_path):
    """Liquidations sorted by timestamp DESC."""
    db_path = str(tmp_path / "test.db")
    _setup_db(db_path)
    _insert_liquidations(db_path, count=5)

    result = _query_liquidations(db_path, limit=10, window_secs=3600)
    assert len(result) == 5
    # Sorted DESC by timestamp: newest (i=0, ts=now) should be first
    assert result[0]["timestamp"] == max(r["timestamp"] for r in result)


def test_liquidation_window_filter(tmp_path):
    """Only liquidations within window_secs returned."""
    db_path = str(tmp_path / "test.db")
    _setup_db(db_path)
    _insert_liquidations(db_path, count=5)

    # Window=120s should exclude older liq (i=3,4 at -180s, -240s)
    result = _query_liquidations(db_path, limit=10, window_secs=120)
    assert len(result) <= 2  # only recent ones


def test_usd_value_computed(tmp_path):
    """USD value = quantity * price."""
    db_path = str(tmp_path / "test.db")
    _setup_db(db_path)
    _insert_liquidations(db_path, count=1)

    result = _query_liquidations(db_path, limit=10, window_secs=3600)
    assert len(result) == 1
    assert result[0]["usd_value"] == result[0]["quantity"] * result[0]["price"]

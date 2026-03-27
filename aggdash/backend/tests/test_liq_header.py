"""
test_liq_header.py — Unit tests for liq_1h_usd in /api/stats.

Module 38: 1h liquidation USD total in header stats.
"""
import sqlite3
import time


def make_liq_db(rows):
    """liquidations in-memory DB."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE liquidations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL, source TEXT, symbol TEXT,
            side TEXT, quantity REAL, price REAL
        )
    """)
    conn.executemany(
        "INSERT INTO liquidations(timestamp,source,symbol,side,quantity,price) VALUES(?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return conn


def compute_liq_1h(conn, since_1h):
    """Mirror liq_1h_usd computation from get_stats()."""
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN side='SELL' THEN quantity*price ELSE 0 END),
            SUM(CASE WHEN side='BUY'  THEN quantity*price ELSE 0 END)
        FROM liquidations WHERE timestamp >= ?
        """,
        (since_1h,),
    ).fetchone()
    sell_usd = row[0] or 0.0
    buy_usd  = row[1] or 0.0
    return {"sell_usd": sell_usd, "buy_usd": buy_usd, "total_usd": sell_usd + buy_usd}


def test_liq_1h_empty():
    """No liquidations → all zeros."""
    conn = make_liq_db([])
    result = compute_liq_1h(conn, time.time() - 3600)
    assert result["sell_usd"] == 0.0
    assert result["buy_usd"] == 0.0
    assert result["total_usd"] == 0.0


def test_liq_1h_buy_side():
    """BUY liquidations (long squeeze) counted correctly."""
    now = time.time()
    rows = [
        (now - 600, "binance-perp", "BANANAS31USDT", "BUY", 50000.0, 0.014),  # $700
        (now - 300, "binance-perp", "BANANAS31USDT", "BUY", 30000.0, 0.013),  # $390
    ]
    conn = make_liq_db(rows)
    result = compute_liq_1h(conn, now - 3600)
    assert abs(result["buy_usd"] - (50000*0.014 + 30000*0.013)) < 0.01
    assert result["sell_usd"] == 0.0


def test_liq_1h_excludes_old():
    """Liquidations older than 1h are excluded."""
    now = time.time()
    rows = [
        (now - 7200, "binance-perp", "X", "BUY", 100000.0, 0.01),  # 2h old — exclude
        (now - 600,  "binance-perp", "X", "BUY", 10000.0, 0.01),   # 10min — include
    ]
    conn = make_liq_db(rows)
    result = compute_liq_1h(conn, now - 3600)
    assert abs(result["buy_usd"] - 100.0) < 0.01, "Only recent liq should count"


def test_liq_1h_total_is_sum():
    """total_usd = sell_usd + buy_usd."""
    now = time.time()
    rows = [
        (now - 100, "binance-perp", "X", "SELL", 1000.0, 0.01),  # $10
        (now - 100, "binance-perp", "X", "BUY",  2000.0, 0.01),  # $20
    ]
    conn = make_liq_db(rows)
    result = compute_liq_1h(conn, now - 3600)
    assert abs(result["sell_usd"] - 10.0) < 0.01
    assert abs(result["buy_usd"] - 20.0) < 0.01
    assert abs(result["total_usd"] - 30.0) < 0.01

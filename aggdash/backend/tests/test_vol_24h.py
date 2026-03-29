"""
test_vol_24h.py — Unit tests for 24h volume totals + OI 24h change % in /api/stats.

Module 27: 24h volume header stats.
"""
import sqlite3
import time


# ── Helpers ───────────────────────────────────────────────────────────

def make_price_feed_db(rows):
    """Create in-memory price_feed DB with given rows."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE price_feed (
            exchange_id TEXT, timestamp REAL, open REAL, high REAL,
            low REAL, close REAL, volume REAL
        )
    """)
    conn.executemany(
        "INSERT INTO price_feed(exchange_id, timestamp, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return conn


def compute_vol_24h(conn, since_24h):
    """Compute 24h volume dict from price_feed — mirrors get_stats() logic."""
    vol_rows = conn.execute(
        "SELECT exchange_id, SUM(volume) FROM price_feed WHERE timestamp >= ? GROUP BY exchange_id",
        (since_24h,),
    ).fetchall()
    vol_map = {row[0]: row[1] or 0.0 for row in vol_rows}
    result = {
        "binance_spot": vol_map.get("binance-spot", 0.0),
        "binance_perp": vol_map.get("binance-perp", 0.0),
        "bybit_perp": vol_map.get("bybit-perp", 0.0),
    }
    result["total"] = sum(result.values())
    return result


def make_oi_db(rows):
    """Create in-memory oi DB with given (exchange_id, timestamp, open_interest) rows."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE oi (exchange_id TEXT, timestamp REAL, open_interest REAL, funding_rate REAL)")
    conn.executemany(
        "INSERT INTO oi(exchange_id, timestamp, open_interest, funding_rate) VALUES (?,?,?,?)",
        [(r[0], r[1], r[2], 0.0) for r in rows],
    )
    conn.commit()
    return conn


def compute_oi_change_24h(conn, now, since_24h):
    """Compute OI 24h change % — mirrors get_stats() logic (dedup per exchange)."""
    oi_now_rows = conn.execute(
        """
        SELECT exchange_id, open_interest FROM oi
        WHERE (exchange_id, timestamp) IN (
            SELECT exchange_id, MAX(timestamp) FROM oi GROUP BY exchange_id
        )
        """,
    ).fetchall()
    oi_ago_rows = conn.execute(
        "SELECT exchange_id, open_interest FROM oi WHERE timestamp BETWEEN ? AND ? + 1800 ORDER BY timestamp ASC",
        (since_24h, since_24h),
    ).fetchall()
    if not oi_now_rows or not oi_ago_rows:
        return None
    seen = set()
    oi_now_total = 0.0
    for ex, oi in oi_now_rows:
        if ex not in seen and oi:
            oi_now_total += oi
            seen.add(ex)
    seen = set()
    oi_ago_total = 0.0
    for ex, oi in oi_ago_rows:
        if ex not in seen and oi:
            oi_ago_total += oi
            seen.add(ex)
    if oi_ago_total <= 0:
        return None
    return (oi_now_total - oi_ago_total) / oi_ago_total


# ── Volume tests ──────────────────────────────────────────────────────

def test_vol_24h_schema():
    """vol_24h must have binance_spot, binance_perp, bybit_perp, total keys."""
    conn = make_price_feed_db([])
    vol = compute_vol_24h(conn, time.time() - 86400)
    required = {"binance_spot", "binance_perp", "bybit_perp", "total"}
    assert set(vol.keys()) == required


def test_vol_24h_empty_db_returns_zeros():
    """Empty price_feed → all zeros, total=0."""
    conn = make_price_feed_db([])
    vol = compute_vol_24h(conn, time.time() - 86400)
    assert vol["binance_spot"] == 0.0
    assert vol["binance_perp"] == 0.0
    assert vol["bybit_perp"] == 0.0
    assert vol["total"] == 0.0


def test_vol_24h_single_exchange():
    """Volume for one exchange computed correctly."""
    now = time.time()
    rows = [
        ("binance-spot", now - 3600, 0.01, 0.01, 0.01, 0.01, 1_000_000.0),
        ("binance-spot", now - 1800, 0.01, 0.01, 0.01, 0.01, 500_000.0),
    ]
    conn = make_price_feed_db(rows)
    vol = compute_vol_24h(conn, now - 86400)
    assert abs(vol["binance_spot"] - 1_500_000.0) < 0.1
    assert vol["binance_perp"] == 0.0
    assert abs(vol["total"] - 1_500_000.0) < 0.1


def test_vol_24h_multi_exchange_sum():
    """Total = sum of all exchanges."""
    now = time.time()
    rows = [
        ("binance-spot", now - 3600, 0.01, 0.01, 0.01, 0.01, 500_000.0),
        ("binance-perp", now - 3600, 0.01, 0.01, 0.01, 0.01, 2_000_000.0),
        ("bybit-perp",   now - 3600, 0.01, 0.01, 0.01, 0.01, 300_000.0),
    ]
    conn = make_price_feed_db(rows)
    vol = compute_vol_24h(conn, now - 86400)
    assert abs(vol["binance_spot"] - 500_000.0) < 0.1
    assert abs(vol["binance_perp"] - 2_000_000.0) < 0.1
    assert abs(vol["bybit_perp"] - 300_000.0) < 0.1
    assert abs(vol["total"] - 2_800_000.0) < 0.1


def test_vol_24h_excludes_old_bars():
    """Bars older than 24h must not be counted."""
    now = time.time()
    rows = [
        ("binance-spot", now - 90000, 0.01, 0.01, 0.01, 0.01, 999_999.0),  # >24h ago
        ("binance-spot", now - 3600,  0.01, 0.01, 0.01, 0.01, 100_000.0),  # within 24h
    ]
    conn = make_price_feed_db(rows)
    vol = compute_vol_24h(conn, now - 86400)
    assert abs(vol["binance_spot"] - 100_000.0) < 0.1, (
        f"Expected ~100000, got {vol['binance_spot']}"
    )


# ── OI change tests ───────────────────────────────────────────────────

def test_oi_change_24h_positive():
    """OI increased → oi_change_24h_pct positive."""
    now = time.time()
    rows = [
        ("binance-perp", now - 86400, 1_000_000),  # 24h ago
        ("binance-perp", now - 10,    1_100_000),  # now (+10%)
    ]
    conn = make_oi_db(rows)
    change = compute_oi_change_24h(conn, now, now - 86400)
    assert change is not None
    assert abs(change - 0.1) < 0.001, f"Expected +10% change, got {change}"


def test_oi_change_24h_negative():
    """OI decreased → oi_change_24h_pct negative."""
    now = time.time()
    rows = [
        ("binance-perp", now - 86400, 1_000_000),
        ("binance-perp", now - 10,      900_000),  # -10%
    ]
    conn = make_oi_db(rows)
    change = compute_oi_change_24h(conn, now, now - 86400)
    assert change is not None
    assert abs(change - (-0.1)) < 0.001


def test_oi_change_24h_empty_returns_none():
    """No OI data → None returned."""
    conn = make_oi_db([])
    change = compute_oi_change_24h(conn, time.time(), time.time() - 86400)
    assert change is None


def test_stats_vol_24h_total_equals_sum_of_parts():
    """total must equal sum of all exchange volumes."""
    now = time.time()
    rows = [
        ("binance-spot", now - 1800, 0.01, 0.01, 0.01, 0.01, 1_000.0),
        ("binance-perp", now - 1800, 0.01, 0.01, 0.01, 0.01, 2_000.0),
        ("bybit-perp",   now - 1800, 0.01, 0.01, 0.01, 0.01, 500.0),
    ]
    conn = make_price_feed_db(rows)
    vol = compute_vol_24h(conn, now - 86400)
    expected_total = vol["binance_spot"] + vol["binance_perp"] + vol["bybit_perp"]
    assert abs(vol["total"] - expected_total) < 1e-9

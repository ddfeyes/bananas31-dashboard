"""Tests for compute_oi_delta() reading from DB (fix for issue #67)."""
import asyncio
import sqlite3
import sys
import os
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def make_oi_db(rows):
    """In-memory SQLite DB with oi table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE oi (
            exchange_id   TEXT NOT NULL,
            timestamp     REAL NOT NULL,
            open_interest REAL,
            funding_rate  REAL
        )
    """)
    conn.executemany(
        "INSERT INTO oi (exchange_id, timestamp, open_interest) VALUES (?,?,?)", rows
    )
    conn.commit()
    return conn


def get_latest_oi_history_factory(conn):
    """Return a get_latest_oi_history function backed by in-memory conn."""
    def _fn(exchange_id, limit=200):
        rows = conn.execute(
            "SELECT timestamp, open_interest AS oi FROM oi "
            "WHERE exchange_id = ? ORDER BY timestamp DESC LIMIT ?",
            (exchange_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    return _fn


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def make_engine():
    """Create a minimal AnalyticsEngine without any real collectors."""
    from analytics_engine import AnalyticsEngine
    rb = MagicMock()
    rb.get_snapshot.return_value = {}
    engine = AnalyticsEngine(rb, oi_funding_poller=None)
    return engine


class TestOIDeltaFromDB:
    """compute_oi_delta() must read from DB, not from empty _oi_history."""

    def test_returns_data_when_oi_history_empty(self):
        """Even with empty _oi_history, compute_oi_delta must return real OI."""
        now = time.time()
        # Use window_secs=300. Place "prev" entry clearly at now-400 (100s before window start).
        # This avoids tie-breaking issues with time.time() drift between test setup and compute.
        rows = [
            # binance-perp: prev clearly before window, then recent entries
            ("binance-perp", now - 400, 1_000_000),
            ("binance-perp", now - 120, 1_040_000),
            ("binance-perp", now - 10,  1_050_000),
            # bybit-perp: prev clearly before window
            ("bybit-perp", now - 400, 500_000),
            ("bybit-perp", now - 10,  490_000),
        ]
        conn = make_oi_db(rows)
        fn = get_latest_oi_history_factory(conn)

        engine = make_engine()
        # Confirm _oi_history is empty (old bug)
        assert len(engine._oi_history) == 0

        with patch("db.get_latest_oi_history", fn):
            result = run_async(engine.compute_oi_delta(window_secs=300))

        per = result["per_source"]
        agg = result["aggregated"]

        # binance-perp: should show real OI (latest entry)
        assert per["binance-perp"]["oi"] == 1_050_000
        assert per["binance-perp"]["delta"] is not None
        # delta_pct is a fraction (not percent): ~+5%
        assert 0.01 < per["binance-perp"]["delta_pct"] < 0.10

        # bybit-perp: negative delta
        assert per["bybit-perp"]["oi"] == 490_000
        assert per["bybit-perp"]["delta"] is not None
        assert per["bybit-perp"]["delta_pct"] < 0

        # aggregated
        assert agg["oi"] == 1_540_000  # 1_050_000 + 490_000
        assert agg["delta"] is not None
        assert agg["delta_pct"] is not None

    def test_delta_pct_is_fraction_not_percent(self):
        """delta_pct must be a fraction (0.05) not percent (5.0) for signal thresholds."""
        now = time.time()
        rows = [
            ("binance-perp", now - 300, 1_000_000),
            ("binance-perp", now,       1_100_000),  # +10%
        ]
        conn = make_oi_db(rows)
        fn = get_latest_oi_history_factory(conn)
        engine = make_engine()

        with patch("db.get_latest_oi_history", fn):
            result = run_async(engine.compute_oi_delta(window_secs=300))

        delta_pct = result["per_source"]["binance-perp"]["delta_pct"]
        # Must be ~0.10 (fraction), not ~10.0 (percent)
        assert 0.05 < delta_pct < 0.15, f"Expected ~0.10 fraction, got {delta_pct}"

    def test_empty_oi_table_returns_nulls(self):
        """If no OI data in DB, returns None gracefully."""
        conn = make_oi_db([])
        fn = get_latest_oi_history_factory(conn)
        engine = make_engine()

        with patch("db.get_latest_oi_history", fn):
            result = run_async(engine.compute_oi_delta(window_secs=300))

        assert result["aggregated"]["oi"] is None
        assert result["aggregated"]["delta"] is None


if __name__ == "__main__":
    t = TestOIDeltaFromDB()
    t.test_returns_data_when_oi_history_empty()
    print("PASS: test_returns_data_when_oi_history_empty")
    t.test_delta_pct_is_fraction_not_percent()
    print("PASS: test_delta_pct_is_fraction_not_percent")
    t.test_empty_oi_table_returns_nulls()
    print("PASS: test_empty_oi_table_returns_nulls")
    print("ALL TESTS PASSED")

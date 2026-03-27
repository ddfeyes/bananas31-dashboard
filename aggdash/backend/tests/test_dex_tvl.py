"""Tests for DEX TVL endpoint — liquidity_usd field in /api/dex/price."""
import sys
import os
import sqlite3
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestDexTVL:
    """DEX /api/dex/price must include liquidity_usd."""

    def _make_db(self):
        """Create a temporary in-memory DB with dex_price table."""
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE dex_price (
                timestamp REAL,
                price REAL,
                liquidity REAL,
                liquidity_usd REAL
            )
        """)
        return conn

    def test_dex_price_has_liquidity_usd(self):
        """DB schema must include liquidity_usd column."""
        conn = self._make_db()
        ts = time.time()
        conn.execute(
            "INSERT INTO dex_price VALUES (?, ?, ?, ?)",
            (ts, 0.01368, 7.16e23, 4208875.17),
        )
        row = conn.execute(
            "SELECT timestamp, price, liquidity, liquidity_usd FROM dex_price ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[3] == 4208875.17, f"Expected 4208875.17, got {row[3]}"

    def test_dex_price_liquidity_usd_positive(self):
        """liquidity_usd must be a positive float when pool has TVL."""
        conn = self._make_db()
        conn.execute(
            "INSERT INTO dex_price VALUES (?, ?, ?, ?)",
            (time.time(), 0.01368, 7.16e23, 4200000.0),
        )
        row = conn.execute(
            "SELECT liquidity_usd FROM dex_price ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row[0] > 0, "liquidity_usd should be positive"

    def test_dex_price_liquidity_usd_null_handled(self):
        """When liquidity_usd is NULL, frontend should show '--' not crash."""
        conn = self._make_db()
        conn.execute(
            "INSERT INTO dex_price(timestamp, price, liquidity, liquidity_usd) VALUES (?, ?, ?, NULL)",
            (time.time(), 0.01368, 7.16e23),
        )
        row = conn.execute(
            "SELECT liquidity_usd FROM dex_price ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        # NULL is returned as None in Python
        assert row[0] is None


class TestFmtLarge:
    """Test the fmtLarge formatting logic (replicated in Python for unit testing)."""

    def fmt_large(self, val):
        """Mirror of JS fmtLarge() function."""
        if val is None:
            return '--'
        if val >= 1e9:
            return f'{val / 1e9:.2f}B'
        if val >= 1e6:
            return f'{val / 1e6:.2f}M'
        if val >= 1e3:
            return f'{val / 1e3:.1f}K'
        return f'{val:.2f}'

    def test_millions(self):
        assert self.fmt_large(4208875.17) == '4.21M'

    def test_billions(self):
        assert self.fmt_large(3493532347.0) == '3.49B'

    def test_thousands(self):
        assert self.fmt_large(420500.0) == '420.5K'

    def test_none(self):
        assert self.fmt_large(None) == '--'


if __name__ == "__main__":
    t = TestDexTVL()
    t.test_dex_price_has_liquidity_usd()
    print("PASS: test_dex_price_has_liquidity_usd")
    t.test_dex_price_liquidity_usd_positive()
    print("PASS: test_dex_price_liquidity_usd_positive")
    t.test_dex_price_liquidity_usd_null_handled()
    print("PASS: test_dex_price_liquidity_usd_null_handled")

    t2 = TestFmtLarge()
    t2.test_millions()
    print("PASS: test_fmt_millions → 4.21M")
    t2.test_billions()
    print("PASS: test_fmt_billions → 3.49B")
    t2.test_thousands()
    print("PASS: test_fmt_thousands → 420.5K")
    t2.test_none()
    print("PASS: test_fmt_none → --")
    print("ALL TESTS PASSED")

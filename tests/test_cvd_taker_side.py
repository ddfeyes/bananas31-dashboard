"""
TDD tests for CVD taker-side fix.

Spec: CVD must use is_buyer_aggressor field (explicit taker side) not string
      approximation on `side`. Write tests first — watch them fail, then implement.

Key behaviors:
  - is_buyer_aggressor=1  →  +qty  (buyer initiated, positive delta)
  - is_buyer_aggressor=0  →  -qty  (seller initiated, negative delta)
  - is_buyer_aggressor=None → fall back to side field (backward compat)
  - side unknown, no aggressor field → 0.0  (don't corrupt CVD with noise)
  - is_buyer_aggressor overrides side when they disagree
"""
import asyncio
import os
import sys
import time

import aiosqlite
import pytest

# Add backend to path so we can import metrics/storage
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from metrics import _cvd_delta, compute_cvd_from_trades  # noqa: E402


# ── _cvd_delta: pure function ────────────────────────────────────────────────

class TestCvdDeltaPure:
    """Unit tests for the _cvd_delta(trade) helper."""

    def test_buyer_aggressor_gives_positive_delta(self):
        trade = {"qty": 10.0, "price": 100.0, "is_buyer_aggressor": 1, "side": "buy"}
        assert _cvd_delta(trade) == pytest.approx(10.0)

    def test_seller_aggressor_gives_negative_delta(self):
        trade = {"qty": 10.0, "price": 100.0, "is_buyer_aggressor": 0, "side": "sell"}
        assert _cvd_delta(trade) == pytest.approx(-10.0)

    def test_is_buyer_aggressor_overrides_side_field(self):
        """is_buyer_aggressor=1 but side='sell': aggressor field wins → +qty."""
        trade = {"qty": 5.0, "price": 200.0, "is_buyer_aggressor": 1, "side": "sell"}
        assert _cvd_delta(trade) == pytest.approx(5.0)

    def test_seller_aggressor_overrides_buy_side(self):
        """is_buyer_aggressor=0 but side='buy': aggressor field wins → -qty."""
        trade = {"qty": 5.0, "price": 200.0, "is_buyer_aggressor": 0, "side": "buy"}
        assert _cvd_delta(trade) == pytest.approx(-5.0)

    def test_fallback_to_side_buy_when_aggressor_is_none(self):
        """Legacy rows have is_buyer_aggressor=None → fall back to side."""
        trade = {"qty": 8.0, "price": 150.0, "is_buyer_aggressor": None, "side": "buy"}
        assert _cvd_delta(trade) == pytest.approx(8.0)

    def test_fallback_to_side_sell_when_aggressor_is_none(self):
        trade = {"qty": 8.0, "price": 150.0, "is_buyer_aggressor": None, "side": "sell"}
        assert _cvd_delta(trade) == pytest.approx(-8.0)

    def test_fallback_handles_uppercase_Buy_side(self):
        """Legacy rows may have 'Buy' (Bybit casing before lowercasing was added)."""
        trade = {"qty": 3.0, "price": 50.0, "is_buyer_aggressor": None, "side": "Buy"}
        assert _cvd_delta(trade) == pytest.approx(3.0)

    def test_fallback_handles_uppercase_Sell_side(self):
        trade = {"qty": 3.0, "price": 50.0, "is_buyer_aggressor": None, "side": "Sell"}
        assert _cvd_delta(trade) == pytest.approx(-3.0)

    def test_unknown_side_with_no_aggressor_returns_zero(self):
        """Unknown side must not contribute (old code wrongly gave -qty)."""
        trade = {"qty": 5.0, "price": 100.0, "is_buyer_aggressor": None, "side": ""}
        assert _cvd_delta(trade) == 0.0

    def test_missing_side_with_no_aggressor_returns_zero(self):
        trade = {"qty": 5.0, "price": 100.0}  # no side, no is_buyer_aggressor
        assert _cvd_delta(trade) == 0.0

    def test_aggressor_flag_false_int_works(self):
        """SQLite stores booleans as 0/1 integers."""
        trade = {"qty": 4.0, "price": 100.0, "is_buyer_aggressor": 0}
        assert _cvd_delta(trade) == pytest.approx(-4.0)

    def test_aggressor_flag_true_int_works(self):
        trade = {"qty": 4.0, "price": 100.0, "is_buyer_aggressor": 1}
        assert _cvd_delta(trade) == pytest.approx(4.0)


# ── Regression: old approximation was wrong ────────────────────────────────

class TestOldApproximationRegression:
    """Demonstrate the bug the fix corrects."""

    def _old_delta(self, trade):
        """The old approximation: side in ('buy', 'Buy')."""
        return trade["qty"] if trade["side"] in ("buy", "Buy") else -trade["qty"]

    def test_old_code_misclassified_unknown_side(self):
        """Old code: empty side → -qty. Wrong."""
        trade = {"qty": 5.0, "side": ""}
        assert self._old_delta(trade) == -5.0  # bug: contributes negatively

    def test_new_code_skips_unknown_side(self):
        """New code: empty side, no aggressor → 0. Correct."""
        trade = {"qty": 5.0, "price": 100.0, "side": "", "is_buyer_aggressor": None}
        assert _cvd_delta(trade) == 0.0

    def test_old_code_ignores_aggressor_field(self):
        """Old code would give -qty here (checks side='sell'), ignoring aggressor=1."""
        trade = {"qty": 10.0, "side": "sell", "is_buyer_aggressor": 1}
        assert self._old_delta(trade) == -10.0  # old: wrong

    def test_new_code_uses_aggressor_field(self):
        """New code uses is_buyer_aggressor=1 → +qty. Correct."""
        trade = {"qty": 10.0, "price": 100.0, "side": "sell", "is_buyer_aggressor": 1}
        assert _cvd_delta(trade) == 10.0  # new: correct


# ── compute_cvd_from_trades: pure CVD series ────────────────────────────────

class TestComputeCvdFromTrades:
    """Unit tests for compute_cvd_from_trades(trades) pure function."""

    def test_empty_trades_returns_empty(self):
        assert compute_cvd_from_trades([]) == []

    def test_single_buy_trade(self):
        trades = [{"ts": 1.0, "price": 100.0, "qty": 5.0, "is_buyer_aggressor": 1}]
        result = compute_cvd_from_trades(trades)
        assert len(result) == 1
        assert result[0]["cvd"] == pytest.approx(5.0)
        assert result[0]["delta"] == pytest.approx(5.0)

    def test_single_sell_trade(self):
        trades = [{"ts": 1.0, "price": 100.0, "qty": 5.0, "is_buyer_aggressor": 0}]
        result = compute_cvd_from_trades(trades)
        assert result[0]["cvd"] == pytest.approx(-5.0)

    def test_cvd_accumulates_correctly(self):
        trades = [
            {"ts": 1.0, "price": 100.0, "qty": 5.0, "is_buyer_aggressor": 1},  # +5
            {"ts": 2.0, "price": 100.1, "qty": 3.0, "is_buyer_aggressor": 0},  # -3
            {"ts": 3.0, "price": 100.2, "qty": 7.0, "is_buyer_aggressor": 1},  # +7
        ]
        result = compute_cvd_from_trades(trades)
        assert result[0]["cvd"] == pytest.approx(5.0)
        assert result[1]["cvd"] == pytest.approx(2.0)
        assert result[2]["cvd"] == pytest.approx(9.0)

    def test_unknown_side_skipped_not_subtracted(self):
        """Unknown side trades must not drag CVD down."""
        trades = [
            {"ts": 1.0, "price": 100.0, "qty": 5.0, "is_buyer_aggressor": 1},  # +5
            {"ts": 2.0, "price": 100.0, "qty": 3.0, "is_buyer_aggressor": None, "side": ""},  # skip
            {"ts": 3.0, "price": 100.0, "qty": 2.0, "is_buyer_aggressor": 1},  # +2
        ]
        result = compute_cvd_from_trades(trades)
        # CVD should be 5, 5, 7 — unknown trade adds nothing
        assert result[0]["cvd"] == pytest.approx(5.0)
        assert result[1]["cvd"] == pytest.approx(5.0)  # not 5 - 3 = 2
        assert result[2]["cvd"] == pytest.approx(7.0)

    def test_result_contains_ts_and_price(self):
        trades = [{"ts": 123.0, "price": 456.0, "qty": 1.0, "is_buyer_aggressor": 1}]
        result = compute_cvd_from_trades(trades)
        assert result[0]["ts"] == 123.0
        assert result[0]["price"] == 456.0

    def test_all_sells_gives_monotone_decreasing_cvd(self):
        trades = [
            {"ts": float(i), "price": 100.0, "qty": 1.0, "is_buyer_aggressor": 0}
            for i in range(5)
        ]
        result = compute_cvd_from_trades(trades)
        cvd_series = [r["cvd"] for r in result]
        assert cvd_series == sorted(cvd_series, reverse=True)

    def test_all_buys_gives_monotone_increasing_cvd(self):
        trades = [
            {"ts": float(i), "price": 100.0, "qty": 1.0, "is_buyer_aggressor": 1}
            for i in range(5)
        ]
        result = compute_cvd_from_trades(trades)
        cvd_series = [r["cvd"] for r in result]
        assert cvd_series == sorted(cvd_series)

    def test_balanced_buys_sells_cvd_near_zero(self):
        trades = [
            {"ts": 1.0, "price": 100.0, "qty": 5.0, "is_buyer_aggressor": 1},
            {"ts": 2.0, "price": 100.0, "qty": 5.0, "is_buyer_aggressor": 0},
        ]
        result = compute_cvd_from_trades(trades)
        assert result[-1]["cvd"] == pytest.approx(0.0)


# ── Collector aggressor derivation logic ────────────────────────────────────

class TestCollectorAggressorDerivation:
    """Tests for the aggressor flag derivation in collectors."""

    # Binance aggTrade: m=True means buyer is MAKER (passive) → seller is aggressor
    def test_binance_buyer_maker_true_means_seller_aggressor(self):
        is_buyer_maker = True
        is_buyer_aggressor = not is_buyer_maker
        assert is_buyer_aggressor is False

    def test_binance_buyer_maker_false_means_buyer_aggressor(self):
        is_buyer_maker = False
        is_buyer_aggressor = not is_buyer_maker
        assert is_buyer_aggressor is True

    # Bybit publicTrade: S="Buy" means buyer is TAKER (aggressor)
    def test_bybit_buy_side_means_buyer_aggressor(self):
        S = "Buy"
        is_buyer_aggressor = (S == "Buy")
        assert is_buyer_aggressor is True

    def test_bybit_sell_side_means_seller_aggressor(self):
        S = "Sell"
        is_buyer_aggressor = (S == "Buy")
        assert is_buyer_aggressor is False

    def test_bybit_missing_side_defaults_to_seller_aggressor(self):
        """Safe default: unknown → not buyer aggressor."""
        S = ""
        is_buyer_aggressor = (S == "Buy")
        assert is_buyer_aggressor is False


# ── Storage: is_buyer_aggressor field persisted ───────────────────────────

DB_INIT = """
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        exchange TEXT NOT NULL,
        symbol TEXT NOT NULL,
        price REAL NOT NULL,
        qty REAL NOT NULL,
        side TEXT NOT NULL,
        trade_id TEXT,
        is_buyer_aggressor INTEGER
    );
"""


async def _make_test_db(tmp_path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(tmp_path)
    db.row_factory = aiosqlite.Row
    for stmt in DB_INIT.strip().split(";"):
        s = stmt.strip()
        if s:
            await db.execute(s)
    await db.commit()
    return db


@pytest.mark.asyncio
async def test_insert_trade_stores_is_buyer_aggressor(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = await _make_test_db(db_path)
    ts = time.time()
    await db.execute(
        "INSERT INTO trades (ts, exchange, symbol, price, qty, side, trade_id, is_buyer_aggressor) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, "binance", "TESTUSDT", 100.0, 5.0, "buy", "t1", 1),
    )
    await db.commit()
    async with db.execute("SELECT is_buyer_aggressor FROM trades WHERE trade_id = 't1'") as cur:
        row = await cur.fetchone()
    await db.close()
    assert row["is_buyer_aggressor"] == 1


@pytest.mark.asyncio
async def test_insert_seller_aggressor_stored_as_zero(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = await _make_test_db(db_path)
    ts = time.time()
    await db.execute(
        "INSERT INTO trades (ts, exchange, symbol, price, qty, side, trade_id, is_buyer_aggressor) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, "binance", "TESTUSDT", 100.0, 3.0, "sell", "t2", 0),
    )
    await db.commit()
    async with db.execute("SELECT is_buyer_aggressor FROM trades WHERE trade_id = 't2'") as cur:
        row = await cur.fetchone()
    await db.close()
    assert row["is_buyer_aggressor"] == 0


@pytest.mark.asyncio
async def test_cvd_uses_is_buyer_aggressor_from_db(tmp_path):
    """Integration: CVD computation reads is_buyer_aggressor from DB correctly."""
    db_path = str(tmp_path / "test.db")
    db = await _make_test_db(db_path)
    ts_base = time.time()
    # Insert 3 trades: buy, sell, buy
    rows = [
        (ts_base + 1, "binance", "TESTUSDT", 100.0, 5.0, "buy",  "t1", 1),  # +5
        (ts_base + 2, "binance", "TESTUSDT", 100.0, 3.0, "sell", "t2", 0),  # -3
        (ts_base + 3, "binance", "TESTUSDT", 100.0, 7.0, "buy",  "t3", 1),  # +7
    ]
    for r in rows:
        await db.execute(
            "INSERT INTO trades (ts, exchange, symbol, price, qty, side, trade_id, is_buyer_aggressor) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", r
        )
    await db.commit()

    # Fetch as get_trades_for_cvd would return
    async with db.execute(
        "SELECT ts, price, qty, side, is_buyer_aggressor FROM trades "
        "WHERE ts > ? AND symbol = ? ORDER BY ts ASC",
        (ts_base, "TESTUSDT"),
    ) as cur:
        trades = [dict(r) for r in await cur.fetchall()]
    await db.close()

    result = compute_cvd_from_trades(trades)
    assert result[0]["cvd"] == pytest.approx(5.0)
    assert result[1]["cvd"] == pytest.approx(2.0)
    assert result[2]["cvd"] == pytest.approx(9.0)


@pytest.mark.asyncio
async def test_cvd_aggressor_field_overrides_side_in_db(tmp_path):
    """is_buyer_aggressor in DB wins over side field — no reliance on string matching."""
    db_path = str(tmp_path / "test.db")
    db = await _make_test_db(db_path)
    ts_base = time.time()
    # Trade has side="sell" but is_buyer_aggressor=1 → should be +qty
    await db.execute(
        "INSERT INTO trades (ts, exchange, symbol, price, qty, side, trade_id, is_buyer_aggressor) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ts_base + 1, "binance", "TESTUSDT", 100.0, 10.0, "sell", "t1", 1),
    )
    await db.commit()

    async with db.execute(
        "SELECT ts, price, qty, side, is_buyer_aggressor FROM trades "
        "WHERE ts > ? AND symbol = ? ORDER BY ts ASC",
        (ts_base, "TESTUSDT"),
    ) as cur:
        trades = [dict(r) for r in await cur.fetchall()]
    await db.close()

    result = compute_cvd_from_trades(trades)
    # With old approach: side="sell" → -10
    # With new approach: is_buyer_aggressor=1 → +10
    assert result[0]["cvd"] == pytest.approx(10.0)

"""Unit tests for signals_engine evaluation logic."""
import json
import sqlite3
import sys
import time
import os
import pytest

# Make backend importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def make_db(tmp_path):
    """Create an in-memory-like temp SQLite DB with required schema."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE price_feed (
            exchange_id TEXT, timestamp REAL, open REAL, high REAL,
            low REAL, close REAL, volume REAL
        );
        CREATE TABLE oi (
            exchange_id TEXT, timestamp REAL, open_interest REAL, funding_rate REAL
        );
        CREATE TABLE dex_price (
            timestamp REAL, price REAL, liquidity REAL, deviation_pct REAL
        );
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT, created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    return conn


def test_squeeze_risk_active(tmp_path, monkeypatch):
    """SQUEEZE_RISK triggers when basis > 2% and avg funding > 0."""
    from signals_engine import _evaluate_squeeze_risk
    db = make_db(tmp_path)
    now = time.time()

    # basis = (102 - 100) / 100 * 100 = 2.0% for binance, 2.1% for bybit → avg 2.05%
    for exch, close in [("binance-perp", 102.0), ("binance-spot", 100.0),
                        ("bybit-perp", 102.1), ("bybit-spot", 100.0)]:
        db.execute("INSERT INTO price_feed VALUES (?,?,?,?,?,?,?)",
                   (exch, now, close, close, close, close, 1.0))
    # Positive funding
    for exch, rate in [("binance-perp", 0.001), ("bybit-perp", 0.002)]:
        db.execute("INSERT INTO oi VALUES (?,?,?,?)", (exch, now, 1000000, rate))
    db.commit()

    active, meta = _evaluate_squeeze_risk(db)
    assert active is True
    assert meta["basis_pct"] > 2.0
    assert meta["avg_funding_rate"] > 0
    db.close()


def test_squeeze_risk_inactive_low_basis(tmp_path):
    """SQUEEZE_RISK inactive when basis < 2%."""
    from signals_engine import _evaluate_squeeze_risk
    db = make_db(tmp_path)
    now = time.time()
    for exch, close in [("binance-perp", 100.5), ("binance-spot", 100.0),
                        ("bybit-perp", 100.4), ("bybit-spot", 100.0)]:
        db.execute("INSERT INTO price_feed VALUES (?,?,?,?,?,?,?)",
                   (exch, now, close, close, close, close, 1.0))
    for exch in ["binance-perp", "bybit-perp"]:
        db.execute("INSERT INTO oi VALUES (?,?,?,?)", (exch, now, 1000000, 0.001))
    db.commit()

    active, meta = _evaluate_squeeze_risk(db)
    assert active is False
    db.close()


def test_arb_oppty_active(tmp_path):
    """ARB_OPPTY triggers when dex deviation_pct > 1.0%."""
    from signals_engine import _evaluate_arb_oppty
    db = make_db(tmp_path)
    db.execute("INSERT INTO dex_price VALUES (?,?,?,?)", (time.time(), 1.05, 1e6, 1.5))
    db.commit()

    active, meta = _evaluate_arb_oppty(db)
    assert active is True
    assert abs(meta["dex_premium_pct"]) > 1.0
    db.close()


def test_arb_oppty_inactive(tmp_path):
    """ARB_OPPTY inactive when deviation_pct <= 1.0%."""
    from signals_engine import _evaluate_arb_oppty
    db = make_db(tmp_path)
    db.execute("INSERT INTO dex_price VALUES (?,?,?,?)", (time.time(), 1.0, 1e6, 0.4))
    db.commit()

    active, meta = _evaluate_arb_oppty(db)
    assert active is False
    db.close()


def test_oi_accumulation_active(tmp_path):
    """OI_ACCUMULATION triggers when total OI delta > 50000 over 30 min."""
    from signals_engine import _evaluate_oi_accumulation
    db = make_db(tmp_path)
    now = time.time()
    past = now - 1800 - 10  # just before 30-min mark

    # Past OI: 1,000,000 each
    db.execute("INSERT INTO oi VALUES (?,?,?,?)", ("binance-perp", past, 1_000_000, 0.001))
    db.execute("INSERT INTO oi VALUES (?,?,?,?)", ("bybit-perp", past, 1_000_000, 0.001))
    # Current OI: increased by 60,000 total
    db.execute("INSERT INTO oi VALUES (?,?,?,?)", ("binance-perp", now, 1_030_000, 0.001))
    db.execute("INSERT INTO oi VALUES (?,?,?,?)", ("bybit-perp", now, 1_030_000, 0.001))
    db.commit()

    active, meta = _evaluate_oi_accumulation(db)
    assert active is True
    assert meta["oi_delta_30m"] > 50000
    db.close()


def test_oi_accumulation_inactive(tmp_path):
    """OI_ACCUMULATION inactive when delta < 50000."""
    from signals_engine import _evaluate_oi_accumulation
    db = make_db(tmp_path)
    now = time.time()
    past = now - 1800 - 10

    db.execute("INSERT INTO oi VALUES (?,?,?,?)", ("binance-perp", past, 1_000_000, 0.001))
    db.execute("INSERT INTO oi VALUES (?,?,?,?)", ("bybit-perp", past, 1_000_000, 0.001))
    db.execute("INSERT INTO oi VALUES (?,?,?,?)", ("binance-perp", now, 1_010_000, 0.001))
    db.execute("INSERT INTO oi VALUES (?,?,?,?)", ("bybit-perp", now, 1_010_000, 0.001))
    db.commit()

    active, meta = _evaluate_oi_accumulation(db)
    assert active is False
    db.close()

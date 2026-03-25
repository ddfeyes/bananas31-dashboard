"""Module 2: DEX Integration tests."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_sqrt_price_decode():
    """Test that sqrtPriceX96 → price math works for known values."""
    # For a token at price ~0.000022 BUSD:
    # sqrt(0.000022) * 2^96 ≈ sqrt(0.000022) * 79228162514264337593543950336
    import math
    target_price = 2.2e-5
    sqrt_price_x96 = int(math.sqrt(target_price) * (2 ** 96))
    decoded = (sqrt_price_x96 / (2 ** 96)) ** 2
    # Should be within 0.01% of target
    assert abs(decoded - target_price) / target_price < 0.001, f"Price decode error: {decoded} vs {target_price}"


def test_dex_price_persistence(tmp_path):
    """Test dex_price table writes."""
    import os
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    import importlib
    import config as cfg
    importlib.reload(cfg)
    import db
    importlib.reload(db)
    db.init_db()

    conn = db.get_db()
    conn.execute(
        "INSERT INTO dex_price(timestamp,price,liquidity,deviation_pct) VALUES(?,?,?,?)",
        (1000.0, 2.2e-5, 1234567890, -0.5),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM dex_price ORDER BY timestamp DESC LIMIT 1").fetchone()
    conn.close()

    assert row is not None
    assert abs(row["price"] - 2.2e-5) < 1e-10
    assert row["deviation_pct"] == -0.5
    assert row["liquidity"] == 1234567890.0


def test_bsc_collector_instantiation():
    """Test BSCPancakeSwapCollector can be instantiated."""
    from collectors import BSCPancakeSwapCollector

    async def dummy_on_tick(tick):
        pass

    col = BSCPancakeSwapCollector(on_tick=dummy_on_tick)
    assert col.running is False
    assert col.last_price is None
    assert col.last_liquidity is None

"""Basic smoke tests for Module 1 — no external connections needed."""
import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_types():
    import config
    assert isinstance(config.API_HOST, str)
    assert isinstance(config.API_PORT, int)
    assert isinstance(config.OHLCV_INTERVAL_SECS, int)
    assert isinstance(config.DB_PATH, str)
    assert isinstance(config.RING_BUFFER_MAX_TICKS, int)
    assert config.API_PORT > 0
    assert config.OHLCV_INTERVAL_SECS > 0


def test_tick_dataclass():
    import time
    from ring_buffer import Tick
    t = Tick(source="binance-spot", price=0.01234, volume=100.0, is_buy=True)
    assert t.source == "binance-spot"
    assert t.price == 0.01234
    assert t.volume == 100.0
    assert t.is_buy is True
    assert isinstance(t.timestamp, float)
    assert t.timestamp <= time.time()


def test_ring_buffer_add_get():
    from ring_buffer import RingBuffer, Tick

    async def run():
        buf = RingBuffer(maxlen=10)
        assert await buf.size() == 0

        t1 = Tick(source="binance-spot", price=1.0, volume=10.0, is_buy=True)
        t2 = Tick(source="bybit-perp", price=2.0, volume=20.0, is_buy=False)
        await buf.add_tick(t1)
        await buf.add_tick(t2)

        assert await buf.size() == 2

        all_ticks = await buf.get_ticks()
        assert len(all_ticks) == 2

        spot_ticks = await buf.get_ticks("binance-spot")
        assert len(spot_ticks) == 1
        assert spot_ticks[0].price == 1.0

        perp_ticks = await buf.get_ticks("bybit-perp")
        assert len(perp_ticks) == 1
        assert perp_ticks[0].is_buy is False

    asyncio.run(run())


def test_ring_buffer_maxlen():
    from ring_buffer import RingBuffer, Tick

    async def run():
        buf = RingBuffer(maxlen=3)
        for i in range(5):
            await buf.add_tick(Tick(source="test", price=float(i), volume=1.0, is_buy=True))
        assert await buf.size() == 3
        ticks = await buf.get_ticks()
        assert ticks[0].price == 2.0  # oldest kept after overflow

    asyncio.run(run())


def test_db_init(tmp_path):
    import os
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    # Reload config with new DB_PATH
    import importlib
    import config as cfg
    importlib.reload(cfg)
    import db
    importlib.reload(db)

    db.init_db()
    conn = db.get_db()
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    for expected in ("exchanges", "price_feed", "trades", "oi", "liquidations", "funding_rates"):
        assert expected in tables, f"Missing table: {expected}"

    # Check exchanges seeded
    conn = db.get_db()
    cursor = conn.execute("SELECT id FROM exchanges")
    ids = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert "binance-spot" in ids
    assert "bybit-perp" in ids
    assert "bsc-pancakeswap" in ids

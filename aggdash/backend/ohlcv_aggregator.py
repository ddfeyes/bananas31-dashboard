"""OHLCV bar aggregator — builds 1-minute (configurable) bars from ticks."""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional

from db import get_db
from ring_buffer import RingBuffer, Tick

logger = logging.getLogger(__name__)

SPOT_SOURCES = ("binance-spot",)
PERP_SOURCES = ("binance-perp", "bybit-perp")


@dataclass
class OHLCVBar:
    exchange_id: str
    interval_secs: int
    bar_start: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    tick_count: int = 0

    def update(self, price: float, volume: float) -> None:
        if self.tick_count == 0:
            self.open = self.high = self.low = self.close = price
        else:
            self.high = max(self.high, price)
            self.low = min(self.low, price)
            self.close = price
        self.volume += volume
        self.tick_count += 1


class OHLCVAggregator:
    """Aggregates ticks into OHLCV bars and flushes completed bars to DB."""

    def __init__(self, ring_buffer: RingBuffer, interval_secs: int) -> None:
        self._ring = ring_buffer
        self._interval = interval_secs
        self.current_bars: Dict[str, OHLCVBar] = {}
        self._lock = asyncio.Lock()

    def _bar_start(self, ts: float) -> float:
        return ts - (ts % self._interval)

    async def process_tick(self, tick: Tick) -> None:
        async with self._lock:
            bar_start = self._bar_start(tick.timestamp)
            bar = self.current_bars.get(tick.source)

            if bar is None or bar.bar_start != bar_start:
                # Flush old bar if exists
                if bar is not None:
                    self._write_bar(bar)
                bar = OHLCVBar(
                    exchange_id=tick.source,
                    interval_secs=self._interval,
                    bar_start=bar_start,
                    open=tick.price,
                    high=tick.price,
                    low=tick.price,
                    close=tick.price,
                )
                self.current_bars[tick.source] = bar

            bar.update(tick.price, tick.volume)

    async def flush_incomplete_bars(self) -> None:
        """Write current open bars to DB (for periodic flush)."""
        async with self._lock:
            for bar in self.current_bars.values():
                if bar.tick_count > 0:
                    self._write_bar(bar)

    def _write_bar(self, bar: OHLCVBar) -> None:
        try:
            conn = get_db()
            conn.execute(
                """INSERT INTO price_feed
                   (exchange_id, timestamp, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (bar.exchange_id, bar.bar_start, bar.open, bar.high,
                 bar.low, bar.close, bar.volume),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error("Failed to write bar: %s", exc)

    async def get_current_price(self, source: str) -> Optional[float]:
        async with self._lock:
            bar = self.current_bars.get(source)
            return bar.close if bar and bar.tick_count > 0 else None

    async def get_aggregated_spot_price(self) -> Optional[float]:
        return await self._vwap(SPOT_SOURCES)

    async def get_aggregated_perp_price(self) -> Optional[float]:
        return await self._vwap(PERP_SOURCES)

    async def _vwap(self, sources: tuple) -> Optional[float]:
        """Volume-weighted average price from in-memory ring buffer (last 60s)."""
        cutoff = time.time() - 60
        ticks = await self._ring.get_ticks()
        subset = [t for t in ticks if t.source in sources and t.timestamp >= cutoff]

        total_vol = sum(t.volume for t in subset)
        if total_vol == 0:
            # Fall back to simple average of last prices
            prices = []
            async with self._lock:
                for src in sources:
                    bar = self.current_bars.get(src)
                    if bar and bar.tick_count > 0:
                        prices.append(bar.close)
            return sum(prices) / len(prices) if prices else None

        return sum(t.price * t.volume for t in subset) / total_vol

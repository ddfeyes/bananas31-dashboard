"""In-memory ring buffer for raw tick data."""
import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional

from config import RING_BUFFER_MAX_TICKS


@dataclass
class Tick:
    """A single trade tick from any source."""
    source: str
    price: float
    volume: float
    is_buy: bool
    timestamp: float = field(default_factory=time.time)


class RingBuffer:
    """Thread-safe async ring buffer holding the last RING_BUFFER_MAX_TICKS ticks."""

    def __init__(self, maxlen: int = RING_BUFFER_MAX_TICKS) -> None:
        self._buf: deque[Tick] = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()

    async def add_tick(self, tick: Tick) -> None:
        async with self._lock:
            self._buf.append(tick)

    async def get_ticks(self, source: Optional[str] = None) -> List[Tick]:
        async with self._lock:
            if source is None:
                return list(self._buf)
            return [t for t in self._buf if t.source == source]

    async def size(self) -> int:
        async with self._lock:
            return len(self._buf)

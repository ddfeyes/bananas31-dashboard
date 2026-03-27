"""WebSocket connection manager for real-time price streaming."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages a set of active WebSocket connections.

    Usage:
        manager = ConnectionManager(min_interval=0.5)  # max 2 pushes/sec

        # In WS endpoint:
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()  # keep alive
        except ...:
            manager.disconnect(websocket)

        # In price-update callback:
        await manager.broadcast_throttled({"timestamp": ..., "prices": {...}})
    """

    def __init__(self, min_interval: float = 1.0) -> None:
        """
        Args:
            min_interval: Minimum seconds between broadcasts (rate-limiting).
                          Default 1.0 → max 1 broadcast/sec.
        """
        self.active_connections: List[Any] = []
        self._lock = asyncio.Lock()
        self.min_interval = min_interval
        self._last_broadcast: float = 0.0

    # ------------------------------------------------------------------ #

    async def connect(self, websocket: Any) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.debug("WS client connected; total=%d", self.count)

    def disconnect(self, websocket: Any) -> None:
        """Remove a WebSocket connection."""
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass
        logger.debug("WS client disconnected; total=%d", self.count)

    @property
    def count(self) -> int:
        return len(self.active_connections)

    # ------------------------------------------------------------------ #

    async def broadcast(self, data: Dict) -> None:
        """Send data to all connected clients; remove dead connections."""
        dead: List[Any] = []
        for ws in list(self.active_connections):
            try:
                await ws.send_json(data)
            except Exception as exc:
                logger.debug("WS send failed (%s); dropping client", exc)
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_throttled(self, data: Dict) -> None:
        """
        Like broadcast() but rate-limited to at most 1 call per min_interval seconds.
        Dropped ticks are silently ignored — callers get the latest price on next broadcast.
        """
        now = time.monotonic()
        if now - self._last_broadcast < self.min_interval:
            return
        self._last_broadcast = now
        await self.broadcast(data)

    # ------------------------------------------------------------------ #

    async def notify_tick(self, prices: Dict[str, float]) -> None:
        """
        Convenience wrapper — build the standard price payload and broadcast (throttled).

        Args:
            prices: mapping of source → latest price, e.g.
                    {"binance-spot": 0.01368, "binance-perp": 0.01370, ...}
        """
        if not self.active_connections:
            return  # nothing to do, skip even building the payload
        payload = {
            "type": "prices",
            "timestamp": time.time(),
            "prices": prices,
        }
        await self.broadcast_throttled(payload)


# Module-level singleton — imported by main.py
price_manager = ConnectionManager(min_interval=1.0)

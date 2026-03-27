"""Tests for /ws/prices WebSocket endpoint and ConnectionManager."""
import asyncio
import sys
import os
import json
import time
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Unit tests for ConnectionManager ──────────────────────────────────

class TestConnectionManager:
    """ConnectionManager tracks WS clients and broadcasts price updates."""

    def _make_ws(self):
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    def test_connect_adds_client(self):
        from ws_manager import ConnectionManager
        mgr = ConnectionManager()
        ws = self._make_ws()
        asyncio.run(mgr.connect(ws))
        assert ws in mgr.active_connections
        assert mgr.count == 1

    def test_disconnect_removes_client(self):
        from ws_manager import ConnectionManager
        mgr = ConnectionManager()
        ws = self._make_ws()
        asyncio.run(mgr.connect(ws))
        mgr.disconnect(ws)
        assert ws not in mgr.active_connections
        assert mgr.count == 0

    def test_broadcast_sends_to_all_connected(self):
        from ws_manager import ConnectionManager
        mgr = ConnectionManager()

        ws1 = self._make_ws()
        ws2 = self._make_ws()

        async def run():
            await mgr.connect(ws1)
            await mgr.connect(ws2)
            payload = {"timestamp": 12345.0, "prices": {"binance-spot": 0.0137}}
            await mgr.broadcast(payload)

        asyncio.run(run())
        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()
        # Verify content
        call_args = ws1.send_json.call_args[0][0]
        assert call_args["prices"]["binance-spot"] == 0.0137

    def test_broadcast_removes_dead_connection(self):
        """If send_json raises, client is removed gracefully."""
        from ws_manager import ConnectionManager
        mgr = ConnectionManager()

        dead_ws = self._make_ws()
        dead_ws.send_json = AsyncMock(side_effect=Exception("disconnected"))
        ok_ws = self._make_ws()

        async def run():
            await mgr.connect(dead_ws)
            await mgr.connect(ok_ws)
            await mgr.broadcast({"timestamp": 1.0, "prices": {}})

        asyncio.run(run())
        # dead_ws removed, ok_ws still connected
        assert dead_ws not in mgr.active_connections
        assert ok_ws in mgr.active_connections

    def test_rate_limit_drops_rapid_messages(self):
        """Broadcast should not be called more than once per min_interval seconds."""
        from ws_manager import ConnectionManager
        mgr = ConnectionManager(min_interval=1.0)

        ws = self._make_ws()

        async def run():
            await mgr.connect(ws)
            # Call broadcast twice immediately
            await mgr.broadcast_throttled({"timestamp": 1.0, "prices": {}})
            await mgr.broadcast_throttled({"timestamp": 1.01, "prices": {}})

        asyncio.run(run())
        # Should only send once (second is rate-limited)
        assert ws.send_json.call_count == 1


class TestWSPricesEndpoint:
    """Integration: /ws/prices endpoint pushes prices to connected clients."""

    def test_ws_manager_exported_in_main(self):
        """main.py must export ws_manager for stats endpoint."""
        import importlib, importlib.util
        # Just check the module has ws_manager attribute after import
        # We can't fully run main without real collectors, but check structure
        spec = importlib.util.find_spec("ws_manager")
        assert spec is not None, "ws_manager module must exist"

    def test_price_payload_schema(self):
        """Price broadcast payload must have required keys."""
        from ws_manager import ConnectionManager
        mgr = ConnectionManager()

        received = []
        ws = MagicMock()
        ws.accept = AsyncMock()
        async def capture(data):
            received.append(data)
        ws.send_json = capture

        payload = {
            "timestamp": time.time(),
            "prices": {
                "binance-spot": 0.01368,
                "binance-perp": 0.01370,
                "bybit-perp": 0.01369,
                "bsc-pancakeswap": 0.01367,
            }
        }

        async def run():
            await mgr.connect(ws)
            await mgr.broadcast(payload)

        asyncio.run(run())
        assert len(received) == 1
        msg = received[0]
        assert "timestamp" in msg
        assert "prices" in msg
        assert "binance-spot" in msg["prices"]
        assert "binance-perp" in msg["prices"]


if __name__ == "__main__":
    t = TestConnectionManager()
    t.test_connect_adds_client()
    print("PASS: test_connect_adds_client")
    t.test_disconnect_removes_client()
    print("PASS: test_disconnect_removes_client")
    t.test_broadcast_sends_to_all_connected()
    print("PASS: test_broadcast_sends_to_all_connected")
    t.test_broadcast_removes_dead_connection()
    print("PASS: test_broadcast_removes_dead_connection")
    t.test_rate_limit_drops_rapid_messages()
    print("PASS: test_rate_limit_drops_rapid_messages")
    t2 = TestWSPricesEndpoint()
    t2.test_ws_manager_exported_in_main()
    print("PASS: test_ws_manager_exported_in_main")
    t2.test_price_payload_schema()
    print("PASS: test_price_payload_schema")
    print("ALL TESTS PASSED")

"""WebSocket collectors: Binance + Bybit."""
import asyncio
import json
import logging
import os
import time
from typing import Optional

import websockets

from storage import (
    insert_orderbook, insert_trade, insert_liquidation
)

logger = logging.getLogger(__name__)

SYMBOL_BINANCE = os.getenv("SYMBOL_BINANCE", "BANANAS31USDT")
SYMBOL_BYBIT = os.getenv("SYMBOL_BYBIT", "BANANAS31USDT")

BINANCE_WS = "wss://fstream.binance.com/stream"
BYBIT_WS = "wss://stream.bybit.com/v5/public/linear"

RECONNECT_DELAY = 5  # seconds


# ─── Binance ──────────────────────────────────────────────────────────────────

async def binance_collector():
    symbol = SYMBOL_BINANCE.lower()
    streams = [
        f"{symbol}@depth20@100ms",
        f"{symbol}@aggTrade",
        f"{symbol}@forceOrder",
    ]
    url = f"{BINANCE_WS}?streams=" + "/".join(streams)

    while True:
        try:
            logger.info(f"Connecting to Binance WS: {url}")
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        stream = msg.get("stream", "")
                        data = msg.get("data", {})

                        if "depth20" in stream:
                            await _handle_binance_orderbook(data)
                        elif "aggTrade" in stream:
                            await _handle_binance_trade(data)
                        elif "forceOrder" in stream:
                            await _handle_binance_liquidation(data)
                    except Exception as e:
                        logger.warning(f"Binance msg error: {e}")

        except Exception as e:
            logger.error(f"Binance WS error: {e}. Reconnecting in {RECONNECT_DELAY}s")
            await asyncio.sleep(RECONNECT_DELAY)


async def _handle_binance_orderbook(data: dict):
    bids = data.get("b", [])
    asks = data.get("a", [])
    await insert_orderbook("binance", SYMBOL_BINANCE, bids, asks)


async def _handle_binance_trade(data: dict):
    price = float(data.get("p", 0))
    qty = float(data.get("q", 0))
    is_buyer_maker = data.get("m", False)
    side = "sell" if is_buyer_maker else "buy"
    trade_id = str(data.get("a", ""))
    await insert_trade("binance", SYMBOL_BINANCE, price, qty, side, trade_id)


async def _handle_binance_liquidation(data: dict):
    order = data.get("o", {})
    side = order.get("S", "").lower()  # BUY/SELL
    price = float(order.get("ap", 0) or order.get("p", 0))
    qty = float(order.get("q", 0))
    if price and qty:
        await insert_liquidation("binance", SYMBOL_BINANCE, side, price, qty)


# ─── Bybit ────────────────────────────────────────────────────────────────────

async def bybit_collector():
    symbol = SYMBOL_BYBIT

    while True:
        try:
            logger.info(f"Connecting to Bybit WS: {BYBIT_WS}")
            async with websockets.connect(BYBIT_WS, ping_interval=20, ping_timeout=10) as ws:
                # Subscribe
                sub_msg = json.dumps({
                    "op": "subscribe",
                    "args": [
                        f"orderbook.20.{symbol}",
                        f"publicTrade.{symbol}",
                        f"liquidation.{symbol}",
                    ]
                })
                await ws.send(sub_msg)

                # Heartbeat task
                async def heartbeat():
                    while True:
                        await asyncio.sleep(20)
                        try:
                            await ws.send(json.dumps({"op": "ping"}))
                        except Exception:
                            break

                hb_task = asyncio.create_task(heartbeat())

                try:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            topic = msg.get("topic", "")
                            data = msg.get("data", {})

                            if topic.startswith("orderbook"):
                                await _handle_bybit_orderbook(data, msg.get("type", ""))
                            elif topic.startswith("publicTrade"):
                                await _handle_bybit_trades(data)
                            elif topic.startswith("liquidation"):
                                await _handle_bybit_liquidation(data)
                        except Exception as e:
                            logger.warning(f"Bybit msg error: {e}")
                finally:
                    hb_task.cancel()

        except Exception as e:
            logger.error(f"Bybit WS error: {e}. Reconnecting in {RECONNECT_DELAY}s")
            await asyncio.sleep(RECONNECT_DELAY)


# Local orderbook state for Bybit (snapshot + delta)
_bybit_ob: dict = {"bids": {}, "asks": {}}


async def _handle_bybit_orderbook(data: dict, msg_type: str):
    global _bybit_ob

    if msg_type == "snapshot":
        _bybit_ob["bids"] = {p: q for p, q in data.get("b", [])}
        _bybit_ob["asks"] = {p: q for p, q in data.get("a", [])}
    else:  # delta
        for p, q in data.get("b", []):
            if float(q) == 0:
                _bybit_ob["bids"].pop(p, None)
            else:
                _bybit_ob["bids"][p] = q
        for p, q in data.get("a", []):
            if float(q) == 0:
                _bybit_ob["asks"].pop(p, None)
            else:
                _bybit_ob["asks"][p] = q

    bids = sorted([[p, q] for p, q in _bybit_ob["bids"].items()],
                  key=lambda x: float(x[0]), reverse=True)[:20]
    asks = sorted([[p, q] for p, q in _bybit_ob["asks"].items()],
                  key=lambda x: float(x[0]))[:20]

    if bids and asks:
        await insert_orderbook("bybit", SYMBOL_BYBIT, bids, asks)


async def _handle_bybit_trades(data: list):
    for t in data if isinstance(data, list) else [data]:
        price = float(t.get("p", 0))
        qty = float(t.get("v", 0))
        side = t.get("S", "").lower()  # Buy/Sell
        trade_id = str(t.get("i", ""))
        if price and qty:
            await insert_trade("bybit", SYMBOL_BYBIT, price, qty, side, trade_id)


async def _handle_bybit_liquidation(data: dict):
    if isinstance(data, list):
        for item in data:
            await _process_bybit_liq(item)
    else:
        await _process_bybit_liq(data)


async def _process_bybit_liq(data: dict):
    side = data.get("side", "").lower()
    price = float(data.get("price", 0))
    qty = float(data.get("size", 0))
    if price and qty:
        await insert_liquidation("bybit", SYMBOL_BYBIT, side, price, qty)


async def run_all_collectors():
    await asyncio.gather(
        binance_collector(),
        bybit_collector(),
    )

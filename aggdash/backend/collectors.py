"""WebSocket + REST collectors for all data sources.

Collectors:
- BinanceSpotCollector
- BinancePerpCollector
- BybitSpotCollector
- BybitPerpCollector
- BSCPancakeSwapCollector
- OIFundingPoller
"""
import asyncio
import json
import logging
import time
from typing import Callable, Dict, Optional

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosedError, WebSocketException

from config import BSC_HTTP_RPC, BSC_POOL
from db import get_db
from ring_buffer import Tick

logger = logging.getLogger(__name__)

RECONNECT_DELAY = 3  # seconds between reconnect attempts
RECONNECT_BASE = 2   # exponential backoff base (seconds)
RECONNECT_MAX = 30   # max backoff delay (seconds)


# ─── helpers ────────────────────────────────────────────────────────────────

def _log_liquidation(source: str, symbol: str, side: str, qty: float, price: float) -> None:
    ts = time.time()
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO liquidations(timestamp,source,symbol,side,quantity,price) VALUES(?,?,?,?,?,?)",
            (ts, source, symbol, side, qty, price),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error("Failed to log liquidation: %s", exc)


# ─── Binance Spot ────────────────────────────────────────────────────────────

class BinanceSpotCollector:
    """Streams BANANAS31USDT aggTrade from Binance spot."""

    WS_URL = "wss://stream.binance.com:9443/ws/bananas31usdt@aggTrade"
    NAME = "binance_spot"

    def __init__(self, on_tick: Callable) -> None:
        self._on_tick = on_tick
        self._stop = asyncio.Event()
        self.running = False
        self.status: str = "disconnected"
        self.last_connected_at: Optional[float] = None
        self.disconnected_at: Optional[float] = None
        self._backoff = RECONNECT_BASE

    async def start(self) -> None:
        self.running = True
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.WS_URL, ping_interval=20) as ws:
                    logger.info("BinanceSpot connected")
                    self.status = "connected"
                    self.last_connected_at = time.time()
                    self.disconnected_at = None
                    self._backoff = RECONNECT_BASE
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                            tick = Tick(
                                source="binance-spot",
                                price=float(msg["p"]),
                                volume=float(msg["q"]),
                                is_buy=not msg["m"],  # m=True means buyer is maker (sell)
                                timestamp=msg["T"] / 1000.0,
                            )
                            await self._on_tick(tick)
                        except Exception as exc:
                            logger.debug("BinanceSpot parse error: %s", exc)
            except (ConnectionClosedError, WebSocketException, OSError) as exc:
                logger.warning("BinanceSpot disconnected: %s — reconnecting in %ds", exc, self._backoff)
            except Exception as exc:
                logger.error("BinanceSpot unexpected error: %s", exc)
            if not self._stop.is_set():
                self.status = "disconnected"
                if self.disconnected_at is None:
                    self.disconnected_at = time.time()
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, RECONNECT_MAX)
        self.running = False

    async def stop(self) -> None:
        self._stop.set()


# ─── Binance Perp ────────────────────────────────────────────────────────────

class BinancePerpCollector:
    """Streams BANANAS31USDT aggTrade + forceOrder from Binance futures."""

    WS_URL = (
        "wss://fstream.binance.com/stream?streams="
        "bananas31usdt@aggTrade/bananas31usdt@forceOrder"
    )
    NAME = "binance_perp"

    def __init__(self, on_tick: Callable, on_liquidation: Optional[Callable] = None) -> None:
        self._on_tick = on_tick
        self._on_liquidation = on_liquidation
        self._stop = asyncio.Event()
        self.running = False
        self.status: str = "disconnected"
        self.last_connected_at: Optional[float] = None
        self.disconnected_at: Optional[float] = None
        self._backoff = RECONNECT_BASE

    async def start(self) -> None:
        self.running = True
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.WS_URL, ping_interval=20) as ws:
                    logger.info("BinancePerp connected")
                    self.status = "connected"
                    self.last_connected_at = time.time()
                    self.disconnected_at = None
                    self._backoff = RECONNECT_BASE
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            wrapper = json.loads(raw)
                            stream = wrapper.get("stream", "")
                            data = wrapper.get("data", wrapper)

                            if "aggTrade" in stream:
                                tick = Tick(
                                    source="binance-perp",
                                    price=float(data["p"]),
                                    volume=float(data["q"]),
                                    is_buy=not data["m"],
                                    timestamp=data["T"] / 1000.0,
                                )
                                await self._on_tick(tick)

                            elif "forceOrder" in stream:
                                o = data.get("o", {})
                                _log_liquidation(
                                    "binance-perp",
                                    o.get("s", "BANANAS31USDT"),
                                    o.get("S", ""),
                                    float(o.get("q", 0)),
                                    float(o.get("p", 0)),
                                )
                                if self._on_liquidation:
                                    await self._on_liquidation(data)

                        except Exception as exc:
                            logger.debug("BinancePerp parse error: %s", exc)
            except (ConnectionClosedError, WebSocketException, OSError) as exc:
                logger.warning("BinancePerp disconnected: %s — reconnecting in %ds", exc, self._backoff)
            except Exception as exc:
                logger.error("BinancePerp unexpected error: %s", exc)
            if not self._stop.is_set():
                self.status = "disconnected"
                if self.disconnected_at is None:
                    self.disconnected_at = time.time()
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, RECONNECT_MAX)
        self.running = False

    async def stop(self) -> None:
        self._stop.set()


# ─── Bybit Spot ──────────────────────────────────────────────────────────────

class BybitSpotCollector:
    """Streams BANANAS31USDT trades from Bybit spot WS v5."""

    WS_URL = "wss://stream.bybit.com/v5/public/spot"
    TOPIC = "publicTrade.BANANAS31USDT"
    NAME = "bybit_spot"

    def __init__(self, on_tick: Callable) -> None:
        self._on_tick = on_tick
        self._stop = asyncio.Event()
        self.running = False
        self.status: str = "disconnected"
        self.last_connected_at: Optional[float] = None
        self.disconnected_at: Optional[float] = None
        self._backoff = RECONNECT_BASE

    async def start(self) -> None:
        self.running = True
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.WS_URL, ping_interval=20) as ws:
                    await ws.send(json.dumps({"op": "subscribe", "args": [self.TOPIC]}))
                    logger.info("BybitSpot connected")
                    self.status = "connected"
                    self.last_connected_at = time.time()
                    self.disconnected_at = None
                    self._backoff = RECONNECT_BASE
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                            if msg.get("topic") == self.TOPIC:
                                for trade in msg.get("data", []):
                                    tick = Tick(
                                        source="bybit-spot",
                                        price=float(trade["p"]),
                                        volume=float(trade["v"]),
                                        is_buy=trade.get("S", "Buy") == "Buy",
                                        timestamp=trade["T"] / 1000.0,
                                    )
                                    await self._on_tick(tick)
                        except Exception as exc:
                            logger.debug("BybitSpot parse error: %s", exc)
            except (ConnectionClosedError, WebSocketException, OSError) as exc:
                logger.warning("BybitSpot disconnected: %s — reconnecting in %ds", exc, self._backoff)
            except Exception as exc:
                logger.error("BybitSpot unexpected error: %s", exc)
            if not self._stop.is_set():
                self.status = "disconnected"
                if self.disconnected_at is None:
                    self.disconnected_at = time.time()
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, RECONNECT_MAX)
        self.running = False

    async def stop(self) -> None:
        self._stop.set()


# ─── Bybit Perp ──────────────────────────────────────────────────────────────

class BybitPerpCollector:
    """Streams BANANAS31USDT trades + liquidations from Bybit linear WS v5.

    Falls back to polling Bybit REST ticker every 10s when no WS trade arrives for 30s
    (BANANAS31 has low trade frequency on Bybit — WS connects but stays silent).
    """

    WS_URL = "wss://stream.bybit.com/v5/public/linear"
    TRADE_TOPIC = "publicTrade.BANANAS31USDT"
    LIQ_TOPIC = "liquidation.BANANAS31USDT"
    REST_TICKER_URL = "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BANANAS31USDT"
    REST_POLL_INTERVAL = 10  # seconds
    STALE_THRESHOLD = 30     # seconds without WS tick → emit REST tick

    NAME = "bybit_perp"

    def __init__(self, on_tick: Callable, on_liquidation: Optional[Callable] = None) -> None:
        self._on_tick = on_tick
        self._on_liquidation = on_liquidation
        self._stop = asyncio.Event()
        self.running = False
        self._last_ws_tick_at: float = 0.0
        self.status: str = "disconnected"
        self.last_connected_at: Optional[float] = None
        self.disconnected_at: Optional[float] = None
        self._backoff = RECONNECT_BASE

    async def _rest_poll_loop(self) -> None:
        """Poll Bybit REST ticker and emit ticks when WS is silent."""
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.REST_POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass
            if self._stop.is_set():
                break
            stale = (time.time() - self._last_ws_tick_at) > self.STALE_THRESHOLD
            if not stale:
                continue
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        self.REST_TICKER_URL,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        data = await resp.json()
                items = data.get("result", {}).get("list", [])
                if items:
                    item = items[0]
                    price = float(item["lastPrice"])
                    volume = float(item.get("volume24h", 0)) / 86400  # approx per-second vol
                    tick = Tick(
                        source="bybit-perp",
                        price=price,
                        volume=volume,
                        is_buy=True,
                        timestamp=time.time(),
                    )
                    await self._on_tick(tick)
                    logger.debug("BybitPerp REST fallback tick: %.8f", price)
            except Exception as exc:
                logger.warning("BybitPerp REST poll error: %s", exc)

    async def start(self) -> None:
        self.running = True
        # Start REST poll loop in background
        rest_task = asyncio.ensure_future(self._rest_poll_loop())
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.WS_URL, ping_interval=20) as ws:
                    await ws.send(json.dumps({
                        "op": "subscribe",
                        "args": [self.TRADE_TOPIC, self.LIQ_TOPIC],
                    }))
                    logger.info("BybitPerp connected")
                    self.status = "connected"
                    self.last_connected_at = time.time()
                    self.disconnected_at = None
                    self._backoff = RECONNECT_BASE
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                            topic = msg.get("topic", "")

                            if topic == self.TRADE_TOPIC:
                                for trade in msg.get("data", []):
                                    self._last_ws_tick_at = time.time()
                                    tick = Tick(
                                        source="bybit-perp",
                                        price=float(trade["p"]),
                                        volume=float(trade["v"]),
                                        is_buy=trade.get("S", "Buy") == "Buy",
                                        timestamp=trade["T"] / 1000.0,
                                    )
                                    await self._on_tick(tick)

                            elif topic == self.LIQ_TOPIC:
                                d = msg.get("data", {})
                                _log_liquidation(
                                    "bybit-perp",
                                    d.get("symbol", "BANANAS31USDT"),
                                    d.get("side", ""),
                                    float(d.get("size", 0)),
                                    float(d.get("price", 0)),
                                )
                                if self._on_liquidation:
                                    await self._on_liquidation(d)

                        except Exception as exc:
                            logger.debug("BybitPerp parse error: %s", exc)
            except (ConnectionClosedError, WebSocketException, OSError) as exc:
                logger.warning("BybitPerp disconnected: %s — reconnecting in %ds", exc, self._backoff)
            except Exception as exc:
                logger.error("BybitPerp unexpected error: %s", exc)
            if not self._stop.is_set():
                self.status = "disconnected"
                if self.disconnected_at is None:
                    self.disconnected_at = time.time()
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, RECONNECT_MAX)
        rest_task.cancel()
        self.running = False

    async def stop(self) -> None:
        self._stop.set()


# ─── BSC PancakeSwap V3 ───────────────────────────────────────────────────────

# ABI for slot0() (minimal)
SLOT0_SELECTOR = "0x3850c7bd"  # keccak256("slot0()") first 4 bytes

def _decode_sqrt_price(hex_result: str) -> float:
    """Decode sqrtPriceX96 from eth_call result and return price."""
    # Result is 32-byte padded uint256
    raw = int(hex_result, 16)
    # sqrtPriceX96 is the first 32 bytes of the slot0 return tuple
    # but eth_call returns ABI-encoded tuple; first word = sqrtPriceX96
    sqrt_price_x96 = raw
    # price = (sqrtPriceX96 / 2^96)^2
    price = (sqrt_price_x96 / (2 ** 96)) ** 2
    return price


async def _fetch_bnb_price_usd() -> Optional[float]:
    """Fetch BNB/USDT price from Binance REST (cheap, fast, reliable)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": "BNBUSDT"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                data = await resp.json()
                return float(data["price"])
    except Exception as exc:
        logger.debug("BNB price fetch error: %s", exc)
        return None


class BSCPancakeSwapCollector:
    """Polls PancakeSwap V3 pool slot0 every 30s to get current price + liquidity.

    Also writes to dex_price table with deviation_pct relative to CEX spot average.
    Falls back to The Graph subgraph if RPC fails.
    Collects real swap volume via eth_getLogs on PancakeSwap V3 Swap events.
    """

    POLL_INTERVAL = 30  # seconds
    SUBGRAPH_URL = (
        "https://proxy-worker.pancake-swap.workers.dev/bsc-exchange"
    )
    SUBGRAPH_FALLBACK_URL = (
        "https://api.thegraph.com/subgraphs/name/pancakeswap/exchange-v3-bsc"
    )
    POOL_ADDR = BSC_POOL
    # PancakeSwap V3 Swap event topic0 (different from Uniswap V3)
    # keccak256("Swap(address,address,int256,int256,uint160,int24,uint128,uint128)")
    PCS_V3_SWAP_TOPIC = "0x19b47279256b2a23a1665c810c8d55a1758940ee09377d4f8d26497a3577dc83"
    # BANANAS31 token decimals (BEP-20 standard = 18)
    TOKEN0_DECIMALS = 18

    NAME = "pancake"

    def __init__(self, on_tick: Callable, get_cex_spot: Optional[Callable] = None) -> None:
        self._on_tick = on_tick
        self._get_cex_spot = get_cex_spot  # optional callback to get CEX spot avg
        self._stop = asyncio.Event()
        self.running = False
        self.last_price: Optional[float] = None
        self.last_liquidity: Optional[int] = None
        self.last_sqrt_price_x96: Optional[int] = None  # for liquidity_usd calc (#15)
        self.last_bnb_usd: Optional[float] = None
        self._last_log_block: Optional[int] = None  # last block scanned for swap events
        self.status: str = "disconnected"
        self.last_connected_at: Optional[float] = None
        self.disconnected_at: Optional[float] = None

    async def start(self) -> None:
        self.running = True
        self.status = "connected"
        self.last_connected_at = time.time()
        self.disconnected_at = None
        logger.info("BSCPancakeSwap poller started (poll every %ds)", self.POLL_INTERVAL)
        while not self._stop.is_set():
            try:
                result = await self._fetch_slot0()
                if result:
                    price, liquidity = result

                    # Sanity-check: BANANAS31 valid USD range 0.001–1.0
                    # Reject if BNB/USD conversion failed or price is raw sqrtPriceX96
                    if price < 0.001 or price > 1.0:
                        logger.warning(
                            "BSC price sanity check failed: %.8f — skipping persist (likely unconverted)", price
                        )
                        continue

                    self.last_price = price
                    self.last_liquidity = liquidity

                    # Fetch real swap volume since last poll (~30s window, ~10 blocks)
                    swap_volume_token0 = await self._fetch_swap_volume_since_last()

                    # Calculate deviation from CEX spot avg if available
                    deviation_pct = None
                    if self._get_cex_spot:
                        try:
                            cex_spot = await self._get_cex_spot()
                            if cex_spot and cex_spot > 0:
                                deviation_pct = (price - cex_spot) / cex_spot * 100
                        except Exception:
                            pass

                    # Write to dex_price table
                    self._persist_dex_price(price, liquidity, deviation_pct)

                    tick = Tick(
                        source="bsc-pancakeswap",
                        price=price,
                        volume=swap_volume_token0,  # real volume in BANANAS31 tokens
                        is_buy=True,
                        timestamp=time.time(),
                    )
                    await self._on_tick(tick)
                    logger.debug(
                        "BSC price: %.8f liquidity: %s dev: %s%% vol_token0: %.2f",
                        price, liquidity,
                        f"{deviation_pct:.4f}" if deviation_pct is not None else "N/A",
                        swap_volume_token0,
                    )
                else:
                    # RPC failed — try subgraph fallback
                    fallback_price = await self._fetch_subgraph_price()
                    if fallback_price:
                        self.last_price = fallback_price
                        self._persist_dex_price(fallback_price, None, None)
                        tick = Tick(
                            source="bsc-pancakeswap",
                            price=fallback_price,
                            volume=0.0,
                            is_buy=True,
                            timestamp=time.time(),
                        )
                        await self._on_tick(tick)
                        logger.info("BSC fallback (subgraph) price: %.8f", fallback_price)

            except Exception as exc:
                logger.warning("BSCPancakeSwap poll error: %s", exc)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass

        self.running = False

    async def _fetch_swap_volume_since_last(self) -> float:
        """Fetch real swap volume (BANANAS31 token0 units) since last poll via eth_getLogs.

        Scans Swap events in blocks since self._last_log_block (or last ~10 blocks if first poll).
        Returns total absolute token0 amount across all swaps.
        """
        try:
            async with aiohttp.ClientSession() as session:
                # Get latest block number
                async with session.post(
                    BSC_HTTP_RPC,
                    json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    data = await resp.json()
                latest_block = int(data["result"], 16)

                # From block: last scanned +1, or fallback to ~10 blocks back
                from_block = (self._last_log_block + 1) if self._last_log_block else (latest_block - 10)
                from_block = max(from_block, latest_block - 200)  # cap at 200 blocks (~10min)

                # eth_getLogs for PCS V3 Swap events in this window
                async with session.post(
                    BSC_HTTP_RPC,
                    json={
                        "jsonrpc": "2.0", "id": 2, "method": "eth_getLogs",
                        "params": [{
                            "address": self.POOL_ADDR,
                            "topics": [self.PCS_V3_SWAP_TOPIC],
                            "fromBlock": hex(from_block),
                            "toBlock": hex(latest_block),
                        }],
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    log_data = await resp.json()

            self._last_log_block = latest_block

            logs = log_data.get("result", [])
            if not logs or "error" in log_data:
                return 0.0

            total_volume = 0.0
            for log in logs:
                # PCS V3 Swap data layout (non-indexed):
                # [0:64]   amount0 (int256, token0 = BANANAS31)
                # [64:128] amount1 (int256, token1 = WBNB)
                # remaining: sqrtPriceX96, tick, protocolFees...
                raw = log.get("data", "0x")[2:]
                if len(raw) < 128:
                    continue
                amount0_hex = raw[0:64]
                v = int(amount0_hex, 16)
                # int256: if >= 2^255 it's negative (two's complement)
                if v >= 2 ** 255:
                    v -= 2 ** 256
                # Volume = absolute amount0, normalized by 18 decimals
                total_volume += abs(v) / (10 ** self.TOKEN0_DECIMALS)

            logger.debug("DEX swap volume (token0, blocks %d-%d): %.2f", from_block, latest_block, total_volume)
            return total_volume

        except Exception as exc:
            logger.debug("DEX swap volume fetch error: %s", exc)
            return 0.0

    async def _fetch_slot0(self) -> Optional[tuple]:
        """Fetch slot0 + liquidity from PancakeSwap V3 pool. Returns (price, liquidity) or None."""
        # Call slot0() and liquidity() in one batch
        batch = [
            {
                "jsonrpc": "2.0", "id": 1, "method": "eth_call",
                "params": [{"to": self.POOL_ADDR, "data": SLOT0_SELECTOR}, "latest"],
            },
            {
                "jsonrpc": "2.0", "id": 2, "method": "eth_call",
                "params": [{"to": self.POOL_ADDR, "data": "0x1a686502"}, "latest"],  # liquidity()
            },
        ]
        async with aiohttp.ClientSession() as session:
            async with session.post(
                BSC_HTTP_RPC,
                json=batch,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                results = await resp.json()

        if not isinstance(results, list) or len(results) < 1:
            return None

        # Parse slot0
        slot0_res = next((r for r in results if r.get("id") == 1), None)
        if not slot0_res:
            return None

        hex_data = slot0_res.get("result", "0x")
        if not hex_data or hex_data == "0x":
            return None

        hex_data = hex_data[2:] if hex_data.startswith("0x") else hex_data
        if len(hex_data) < 64:
            return None

        sqrt_price_x96 = int(hex_data[:64], 16)
        if sqrt_price_x96 == 0:
            return None

        # price = WBNB per BANANAS31 (token0=BANANAS31, token1=WBNB, both 18 dec)
        price_wbnb = (sqrt_price_x96 / (2 ** 96)) ** 2

        # Convert to USD using BNB/USDT from Binance
        bnb_usd = await _fetch_bnb_price_usd()
        price = price_wbnb * bnb_usd if bnb_usd else price_wbnb

        # Store for liquidity_usd computation (fix #15)
        self.last_sqrt_price_x96 = sqrt_price_x96
        self.last_bnb_usd = bnb_usd

        # Parse liquidity
        liq_res = next((r for r in results if r.get("id") == 2), None)
        liquidity = None
        if liq_res:
            liq_hex = liq_res.get("result", "0x")
            if liq_hex and liq_hex != "0x":
                liq_hex = liq_hex[2:] if liq_hex.startswith("0x") else liq_hex
                if liq_hex:
                    liquidity = int(liq_hex, 16)

        return price, liquidity

    async def _fetch_subgraph_price(self) -> Optional[float]:
        """Fallback: get price from The Graph subgraph for PancakeSwap V3."""
        query = {
            "query": """
            {
              pool(id: "%s") {
                token0Price
                token1Price
                liquidity
              }
            }
            """ % self.POOL_ADDR.lower()
        }
        for url in [self.SUBGRAPH_URL, self.SUBGRAPH_FALLBACK_URL]:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=query,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        data = await resp.json()
                pool = data.get("data", {}).get("pool")
                if pool:
                    # token0Price = price of token0 in terms of token1 (BANANAS31/BUSD)
                    price = float(pool.get("token0Price", 0))
                    if price > 0:
                        return price
            except Exception as exc:
                logger.debug("Subgraph %s error: %s", url, exc)
        return None

    def _persist_dex_price(
        self, price: float, liquidity: Optional[int], deviation_pct: Optional[float]
    ) -> None:
        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO dex_price(timestamp,price,liquidity,deviation_pct) VALUES(?,?,?,?)",
                (time.time(), price, float(liquidity) if liquidity is not None else None, deviation_pct),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error("Persist dex_price error: %s", exc)

    async def stop(self) -> None:
        self._stop.set()


# ─── OI + Funding Poller ─────────────────────────────────────────────────────

class OIFundingPoller:
    """Polls Open Interest and Funding Rates from Binance and Bybit REST APIs."""

    NAME = "oi_funding"

    def __init__(self, oi_interval_secs: int = 30, funding_interval_secs: int = 60) -> None:
        self._oi_interval = oi_interval_secs
        self._funding_interval = funding_interval_secs
        self._stop = asyncio.Event()
        self.running = False

        # Latest data caches
        self._oi: Dict[str, float] = {}
        self._funding: Dict[str, Dict] = {}

    async def start(self) -> None:
        self.running = True
        logger.info("OIFundingPoller started")
        await asyncio.gather(
            self._oi_loop(),
            self._funding_loop(),
        )
        self.running = False

    async def stop(self) -> None:
        self._stop.set()

    async def _oi_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._poll_oi()
            except Exception as exc:
                logger.warning("OI poll error: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._oi_interval)
            except asyncio.TimeoutError:
                pass

    async def _funding_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._poll_funding()
            except Exception as exc:
                logger.warning("Funding poll error: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._funding_interval)
            except asyncio.TimeoutError:
                pass

    async def _poll_oi(self) -> None:
        async with aiohttp.ClientSession() as session:
            # Binance OI
            try:
                async with session.get(
                    "https://fapi.binance.com/fapi/v1/openInterest",
                    params={"symbol": "BANANAS31USDT"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    oi_val = float(data.get("openInterest", 0))
                    self._oi["binance-perp"] = oi_val
                    self._persist_oi("binance-perp", oi_val)
            except Exception as exc:
                logger.debug("Binance OI error: %s", exc)

            # Bybit OI
            try:
                async with session.get(
                    "https://api.bybit.com/v5/market/open-interest",
                    params={
                        "category": "linear",
                        "symbol": "BANANAS31USDT",
                        "intervalTime": "5min",
                        "limit": 1,
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    items = data.get("result", {}).get("list", [])
                    if items:
                        oi_val = float(items[0].get("openInterest", 0))
                        self._oi["bybit-perp"] = oi_val
                        self._persist_oi("bybit-perp", oi_val)
            except Exception as exc:
                logger.debug("Bybit OI error: %s", exc)

    async def _poll_funding(self) -> None:
        async with aiohttp.ClientSession() as session:
            # Binance funding
            try:
                async with session.get(
                    "https://fapi.binance.com/fapi/v1/fundingRate",
                    params={"symbol": "BANANAS31USDT", "limit": 1},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    if data:
                        rate = float(data[0].get("fundingRate", 0))
                        self._funding["binance-perp"] = {"rate_8h": rate, "rate_1h": rate / 8}
                        self._persist_funding("binance-perp", rate, rate / 8)
            except Exception as exc:
                logger.debug("Binance funding error: %s", exc)

            # Bybit funding
            try:
                async with session.get(
                    "https://api.bybit.com/v5/market/funding/history",
                    params={
                        "category": "linear",
                        "symbol": "BANANAS31USDT",
                        "limit": 1,
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    items = data.get("result", {}).get("list", [])
                    if items:
                        rate = float(items[0].get("fundingRate", 0))
                        self._funding["bybit-perp"] = {"rate_8h": rate, "rate_1h": rate / 8}
                        self._persist_funding("bybit-perp", rate, rate / 8)
            except Exception as exc:
                logger.debug("Bybit funding error: %s", exc)

    def _persist_oi(self, exchange_id: str, oi: float) -> None:
        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO oi(exchange_id,timestamp,open_interest) VALUES(?,?,?)",
                (exchange_id, time.time(), oi),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error("Persist OI error: %s", exc)

    def _persist_funding(self, exchange_id: str, rate_8h: float, rate_1h: float) -> None:
        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO funding_rates(exchange_id,timestamp,rate_8h,rate_1h) VALUES(?,?,?,?)",
                (exchange_id, time.time(), rate_8h, rate_1h),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error("Persist funding error: %s", exc)

    def get_latest_oi(self) -> Dict[str, float]:
        return dict(self._oi)

    def get_aggregated_oi(self) -> float:
        return sum(self._oi.values())

    def get_latest_funding(self) -> Dict[str, Dict]:
        return dict(self._funding)

"""REST pollers: OI and funding rate from Binance and Bybit (every 1s)."""
import asyncio
import logging
import os
import time

import httpx

from storage import insert_oi, insert_funding

logger = logging.getLogger(__name__)

SYMBOL_BINANCE = os.getenv("SYMBOL_BINANCE", "BANANAS31USDT")
SYMBOL_BYBIT = os.getenv("SYMBOL_BYBIT", "BANANAS31USDT")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1"))

BINANCE_OI_URL = "https://fapi.binance.com/fapi/v1/openInterest"
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
BYBIT_OI_URL = "https://api.bybit.com/v5/market/open-interest"
BYBIT_FUNDING_URL = "https://api.bybit.com/v5/market/tickers"


async def poll_binance_oi(client: httpx.AsyncClient):
    try:
        r = await client.get(BINANCE_OI_URL, params={"symbol": SYMBOL_BINANCE}, timeout=5)
        r.raise_for_status()
        data = r.json()
        oi_value = float(data.get("openInterest", 0))
        await insert_oi("binance", SYMBOL_BINANCE, oi_value)
    except Exception as e:
        logger.warning(f"Binance OI poll error: {e}")


async def poll_binance_funding(client: httpx.AsyncClient):
    try:
        r = await client.get(BINANCE_FUNDING_URL, params={"symbol": SYMBOL_BINANCE}, timeout=5)
        r.raise_for_status()
        data = r.json()
        rate = float(data.get("lastFundingRate", 0))
        next_ts = float(data.get("nextFundingTime", 0)) / 1000
        await insert_funding("binance", SYMBOL_BINANCE, rate, next_ts)
    except Exception as e:
        logger.warning(f"Binance funding poll error: {e}")


async def poll_bybit_oi(client: httpx.AsyncClient):
    try:
        r = await client.get(
            BYBIT_OI_URL,
            params={"category": "linear", "symbol": SYMBOL_BYBIT, "intervalTime": "5min", "limit": 1},
            timeout=5
        )
        r.raise_for_status()
        data = r.json()
        result = data.get("result", {}).get("list", [])
        if result:
            oi_value = float(result[0].get("openInterest", 0))
            await insert_oi("bybit", SYMBOL_BYBIT, oi_value)
    except Exception as e:
        logger.warning(f"Bybit OI poll error: {e}")


async def poll_bybit_funding(client: httpx.AsyncClient):
    try:
        r = await client.get(
            BYBIT_FUNDING_URL,
            params={"category": "linear", "symbol": SYMBOL_BYBIT},
            timeout=5
        )
        r.raise_for_status()
        data = r.json()
        result = data.get("result", {}).get("list", [])
        if result:
            item = result[0]
            rate = float(item.get("fundingRate", 0))
            next_ts_str = item.get("nextFundingTime", "0")
            next_ts = float(next_ts_str) / 1000 if next_ts_str else 0
            await insert_funding("bybit", SYMBOL_BYBIT, rate, next_ts)
    except Exception as e:
        logger.warning(f"Bybit funding poll error: {e}")


async def poller_loop():
    """Poll OI and funding from both exchanges every POLL_INTERVAL seconds."""
    logger.info("Starting REST pollers")
    async with httpx.AsyncClient() as client:
        while True:
            t0 = time.time()
            await asyncio.gather(
                poll_binance_oi(client),
                poll_binance_funding(client),
                poll_bybit_oi(client),
                poll_bybit_funding(client),
                return_exceptions=True
            )
            elapsed = time.time() - t0
            sleep_time = max(0, POLL_INTERVAL - elapsed)
            await asyncio.sleep(sleep_time)

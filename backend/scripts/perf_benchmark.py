#!/usr/bin/env python3
"""
perf_benchmark.py — Simple HTTP timing benchmark for svc-dash endpoints.

Usage (against running backend):
    python3 backend/scripts/perf_benchmark.py [--host http://localhost:8766] [--symbol BANANAS31USDT]

Prints per-endpoint latency (cold + warm/cached) and flags anything >500ms.
Exit code 1 if any cold request exceeds 2000ms (acceptance criterion).
"""

import argparse
import asyncio
import sys
import time

try:
    import httpx
except ImportError:
    print("httpx required: pip install httpx")
    sys.exit(1)

# Endpoints to benchmark, with optional query params
ENDPOINTS = [
    "/api/symbols",
    "/api/health",
    "/api/stats/summary",
    "/api/freshness",
    "/api/cvd/history",
    "/api/volume-profile",
    "/api/volume-profile/adaptive",
    "/api/oi/history",
    "/api/funding/history",
    "/api/liquidations/recent",
    "/api/aggressor-ratio",
    "/api/aggressor-streak",
    "/api/tape-speed",
    "/api/tape-speed-tps",
    "/api/correlations",
    "/api/correlations/heatmap",
    "/api/market-regime",
    "/api/market-regime/all",
    "/api/multi-summary",
    "/api/ohlcv",
    "/api/trades/recent",
    "/api/orderbook/latest",
    "/api/market-depth",
    "/api/oi-spike",
    "/api/funding-momentum",
    "/api/vwap-deviation",
]

SLOW_WARN_MS = 500
SLOW_FAIL_MS = 2000


async def bench(host: str, symbol: str) -> bool:
    """Run benchmark. Returns True if all cold requests pass the 2s target."""
    params = f"?symbol={symbol}"
    results = []

    async with httpx.AsyncClient(base_url=host, timeout=30) as client:
        for endpoint in ENDPOINTS:
            url = endpoint + params
            times = []
            status = None
            for i in range(2):  # 2 runs: cold + warm
                t0 = time.monotonic()
                try:
                    r = await client.get(url)
                    elapsed_ms = (time.monotonic() - t0) * 1000
                    status = r.status_code
                    # Prefer server-reported time if available
                    if "x-response-time" in r.headers:
                        srv = r.headers["x-response-time"]
                        if srv.endswith("ms"):
                            elapsed_ms = float(srv[:-2])
                except Exception as e:
                    elapsed_ms = (time.monotonic() - t0) * 1000
                    status = f"ERR:{e}"
                times.append(elapsed_ms)
                await asyncio.sleep(0.05)  # brief pause between calls

            cold, warm = times[0], times[1]
            results.append((endpoint, cold, warm, status))

    # Print table
    header = f"{'Endpoint':<45}  {'Cold':>8}  {'Warm':>8}  {'Status':>6}"
    print(header)
    print("-" * len(header))

    failed = False
    for endpoint, cold, warm, status in results:
        cold_flag = " ⚠️ SLOW" if cold > SLOW_WARN_MS else ""
        warm_flag = " ⚠️ SLOW" if warm > SLOW_WARN_MS else ""
        if cold > SLOW_FAIL_MS:
            cold_flag = " ❌ >2s"
            failed = True
        print(
            f"{endpoint:<45}  {cold:>7.0f}ms  {warm:>7.0f}ms  {status!s:>6}"
            f"{cold_flag}{warm_flag}"
        )

    print()
    slow = [(ep, c) for ep, c, _, _ in results if c > SLOW_WARN_MS]
    if slow:
        print(f"Slow endpoints (>{SLOW_WARN_MS}ms cold):")
        for ep, ms in sorted(slow, key=lambda x: -x[1]):
            print(f"  {ms:>7.0f}ms  {ep}")
    else:
        print("All endpoints responded within 500ms on cold call. ✓")

    return not failed


def main():
    parser = argparse.ArgumentParser(description="svc-dash endpoint latency benchmark")
    parser.add_argument(
        "--host", default="http://localhost:8766", help="Backend base URL"
    )
    parser.add_argument(
        "--symbol", default="BANANAS31USDT", help="Symbol for query params"
    )
    args = parser.parse_args()

    print(f"Benchmarking {args.host} (symbol={args.symbol})\n")
    ok = asyncio.run(bench(args.host, args.symbol))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

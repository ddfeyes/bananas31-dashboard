"""
Funding Rate Arbitrage Scanner — Wave 23 Task 5 (Issue #119).

Simulates funding rates across three exchanges (Binance, Bybit, OKX) and finds
the best cash-and-carry arbitrage opportunities:
  - Scan all symbols for cross-exchange funding rate spreads
  - Long where funding rate is lowest (pay least / receive most when long)
  - Short where funding rate is highest (receive most when short)
  - Spread = short_rate - long_rate (both in %)
  - APR = spread_pct * FUNDING_INTERVALS_PER_DAY * 365
  - Flag extreme imbalances (spread > EXTREME_MULTIPLIER × avg_spread)
  - Return top 3 pairs by spread

Data source: seeded mock — deterministic per (symbol, exchange), no live API.
"""

import random
import time
from typing import Dict, List, Optional

# ── Constants ──────────────────────────────────────────────────────────────────

EXCHANGES = ("binance", "bybit", "okx")

SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "AVAXUSDT",
)

# Funding rate distribution (realistic: most rates near 0.01% per 8h interval)
RATE_MEAN = 0.01  # 0.01% mean (slight contango typical in bull markets)
RATE_STD = 0.04  # 0.04% standard deviation

# Hard bounds: exchanges enforce ±0.15% max funding per interval
RATE_MIN = -0.15
RATE_MAX = 0.15

# Funding is paid every 8 hours → 3 intervals per day
FUNDING_INTERVALS_PER_DAY = 3
DAYS_PER_YEAR = 365

# Pair marked extreme when spread > EXTREME_MULTIPLIER × average spread
EXTREME_MULTIPLIER = 2.0

# Number of top pairs to include in summary
TOP_N = 3


# ── Helpers ────────────────────────────────────────────────────────────────────


def _symbol_exchange_seed(symbol: str, exchange: str) -> int:
    """Deterministic seed derived from (symbol, exchange) pair."""
    combined = symbol + "|" + exchange
    return sum(ord(c) * (i + 1) for i, c in enumerate(combined)) + 137


# ── Core Functions ─────────────────────────────────────────────────────────────


def scan_funding_rates(symbols: Optional[List[str]] = None) -> List[Dict]:
    """
    Simulate current funding rates for all (symbol, exchange) combinations.

    Returns list of dicts:
        symbol   (str):   trading pair
        exchange (str):   exchange name
        rate_pct (float): funding rate per 8h interval, in percent
    """
    syms: List[str] = list(symbols) if symbols is not None else list(SYMBOLS)
    results: List[Dict] = []

    for symbol in syms:
        for exchange in EXCHANGES:
            seed = _symbol_exchange_seed(symbol, exchange)
            rng = random.Random(seed)
            rate = rng.gauss(RATE_MEAN, RATE_STD)
            rate = max(RATE_MIN, min(RATE_MAX, rate))
            results.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "rate_pct": round(rate, 6),
                }
            )

    return results


def compute_arb_pairs(rates: List[Dict]) -> List[Dict]:
    """
    Identify best cash-and-carry pair per symbol.

    Strategy:
        - Long the exchange with the lowest funding rate (pay least or receive most)
        - Short the exchange with the highest funding rate (receive most)
        - Spread = short_rate_pct - long_rate_pct
        - spread_bps = spread_pct * 100
        - estimated_apr_pct = spread_pct * FUNDING_INTERVALS_PER_DAY * DAYS_PER_YEAR

    Returns list sorted by spread_bps descending.
    """
    # Group by symbol
    by_symbol: Dict[str, List[Dict]] = {}
    for r in rates:
        by_symbol.setdefault(r["symbol"], []).append(r)

    pairs: List[Dict] = []

    for symbol, exchange_rates in by_symbol.items():
        if len(exchange_rates) < 2:
            continue

        sorted_rates = sorted(exchange_rates, key=lambda x: x["rate_pct"])
        long_ex = sorted_rates[0]  # lowest rate → go long here
        short_ex = sorted_rates[-1]  # highest rate → go short here

        long_rate = long_ex["rate_pct"]
        short_rate = short_ex["rate_pct"]

        spread_pct = short_rate - long_rate
        spread_bps = round(spread_pct * 100, 2)
        estimated_apr_pct = round(
            spread_pct * FUNDING_INTERVALS_PER_DAY * DAYS_PER_YEAR, 2
        )

        pairs.append(
            {
                "symbol": symbol,
                "long_exchange": long_ex["exchange"],
                "short_exchange": short_ex["exchange"],
                "long_rate_pct": round(long_rate, 6),
                "short_rate_pct": round(short_rate, 6),
                "spread_bps": spread_bps,
                "estimated_apr_pct": estimated_apr_pct,
                "is_extreme": False,  # filled by flag_extreme_pairs
            }
        )

    return sorted(pairs, key=lambda x: x["spread_bps"], reverse=True)


def flag_extreme_pairs(pairs: List[Dict]) -> List[Dict]:
    """
    Mark pairs where spread_bps > EXTREME_MULTIPLIER × avg_spread_bps as extreme.

    Mutates pairs in-place; returns the same list.
    """
    if not pairs:
        return pairs

    avg_spread = sum(p["spread_bps"] for p in pairs) / len(pairs)
    threshold = avg_spread * EXTREME_MULTIPLIER

    for pair in pairs:
        pair["is_extreme"] = pair["spread_bps"] > threshold

    return pairs


def compute_funding_arb_scanner(symbols: Optional[List[str]] = None) -> Dict:
    """
    Main entry point: scan funding rates and return arbitrage opportunities.

    Returns:
        top_pairs (list[dict]):  top TOP_N arb pairs by spread_bps
        all_pairs (list[dict]):  all symbol pairs sorted by spread_bps descending
        avg_spread_bps (float):  mean spread across all symbols
        extreme_count (int):     number of extreme imbalance pairs
        timestamp (float):       unix epoch seconds
    """
    rates = scan_funding_rates(symbols)
    pairs = compute_arb_pairs(rates)
    pairs = flag_extreme_pairs(pairs)

    avg_spread_bps = (
        round(sum(p["spread_bps"] for p in pairs) / len(pairs), 2) if pairs else 0.0
    )
    extreme_count = sum(1 for p in pairs if p["is_extreme"])

    # Assign sequential ranks (1 = best)
    for i, pair in enumerate(pairs):
        pair["rank"] = i + 1

    top_pairs = [dict(p) for p in pairs[:TOP_N]]

    return {
        "top_pairs": top_pairs,
        "all_pairs": pairs,
        "avg_spread_bps": avg_spread_bps,
        "extreme_count": extreme_count,
        "timestamp": time.time(),
    }

"""Core analytics engine for aggdash.

Computes:
- CVD (Cumulative Volume Delta) per source + aggregated
- Basis (perp_price - spot_price) per exchange + aggregated
- DEX vs CEX spread
- OI delta (per-minute change)
- Funding rate aggregation
- Liquidation aggregation
"""
import asyncio
import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ring_buffer import RingBuffer, Tick

logger = logging.getLogger(__name__)

# Source classification
SPOT_SOURCES = ["binance-spot"]
PERP_SOURCES = ["binance-perp", "bybit-perp"]
DEX_SOURCES = ["bsc-pancakeswap"]
ALL_CEX_SPOT = ["binance-spot"]
ALL_CEX_PERP = ["binance-perp", "bybit-perp"]

# Exchange mapping (exchange name → spot source, perp source)
# Bybit only has perp for BANANAS31USDT (no spot)
EXCHANGE_MAP = {
    "binance": ("binance-spot", "binance-perp"),
}


class AnalyticsEngine:
    """Computes real-time analytics from ring buffer and OI/funding data."""

    def __init__(self, ring_buffer: RingBuffer, oi_funding_poller=None):
        self.ring_buffer = ring_buffer
        self.oi_funding_poller = oi_funding_poller

        # In-memory OI history for delta computation
        # {source: [(timestamp, oi_value), ...]}  — last 120 points
        self._oi_history: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
        self._oi_history_limit = 120

        self.lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # CVD                                                                  #
    # ------------------------------------------------------------------ #

    async def compute_cvd(
        self,
        source: Optional[str] = None,
        window_secs: int = 3600,
    ) -> Dict:
        """
        Compute Cumulative Volume Delta.
        CVD = sum(buy_volume) - sum(sell_volume) over the window.
        Returns per-source dict and an aggregated value.
        """
        all_ticks = await self.ring_buffer.get_ticks(source)
        cutoff = time.time() - window_secs
        ticks = [t for t in all_ticks if t.timestamp >= cutoff]

        if source:
            # Single source
            cvd = _cvd_from_ticks(ticks)
            return {"source": source, "cvd": cvd, "tick_count": len(ticks)}

        # Multi-source
        by_source: Dict[str, List[Tick]] = defaultdict(list)
        for t in ticks:
            by_source[t.source].append(t)

        per_source = {}
        for src, src_ticks in by_source.items():
            per_source[src] = {
                "cvd": _cvd_from_ticks(src_ticks),
                "tick_count": len(src_ticks),
            }

        # Aggregated: sum across all sources
        agg_cvd = sum(v["cvd"] for v in per_source.values())

        # Exchange-level breakdown
        exchange_cvd = {}
        for exchange, (spot_src, perp_src) in EXCHANGE_MAP.items():
            spot = per_source.get(spot_src, {}).get("cvd", 0.0)
            perp = per_source.get(perp_src, {}).get("cvd", 0.0)
            exchange_cvd[exchange] = {
                "spot_cvd": spot,
                "perp_cvd": perp,
                "total_cvd": spot + perp,
            }

        return {
            "per_source": per_source,
            "exchange_cvd": exchange_cvd,
            "aggregated_cvd": agg_cvd,
            "window_secs": window_secs,
        }

    async def compute_cvd_series(
        self,
        interval_secs: int = 60,
        window_secs: int = 3600,
        source: Optional[str] = None,
    ) -> Dict:
        """
        Compute CVD as a time-series (cumulative sum of per-bar VD).
        Returns {source: [{timestamp, cvd}, ...], aggregated: [...]}
        """
        all_ticks = await self.ring_buffer.get_ticks(source)
        cutoff = time.time() - window_secs
        ticks = [t for t in all_ticks if t.timestamp >= cutoff]

        if not ticks:
            return {"per_source": {}, "aggregated": []}

        # Bucket ticks into bars
        def bucket_key(ts: float) -> int:
            return int(ts // interval_secs) * interval_secs

        # Group by (source, bar_timestamp)
        bars: Dict[str, Dict[int, List[Tick]]] = defaultdict(lambda: defaultdict(list))
        all_bar_keys = set()
        for t in ticks:
            bk = bucket_key(t.timestamp)
            src = t.source if not source else source
            bars[src][bk].append(t)
            all_bar_keys.add(bk)

        sorted_keys = sorted(all_bar_keys)

        per_source_series: Dict[str, List[dict]] = {}
        aggregated_by_bar: Dict[int, float] = defaultdict(float)

        for src, bar_dict in bars.items():
            series = []
            cumulative = 0.0
            for bk in sorted_keys:
                bar_ticks = bar_dict.get(bk, [])
                delta = _cvd_from_ticks(bar_ticks)
                cumulative += delta
                series.append({"timestamp": bk, "cvd": cumulative, "delta": delta})
                aggregated_by_bar[bk] += delta
            per_source_series[src] = series

        # Aggregate series
        agg_series = []
        agg_cum = 0.0
        for bk in sorted_keys:
            agg_cum += aggregated_by_bar[bk]
            agg_series.append({"timestamp": bk, "cvd": agg_cum, "delta": aggregated_by_bar[bk]})

        return {
            "per_source": per_source_series,
            "aggregated": agg_series,
            "interval_secs": interval_secs,
            "window_secs": window_secs,
        }

    # ------------------------------------------------------------------ #
    # Basis                                                                #
    # ------------------------------------------------------------------ #

    async def compute_basis(self) -> Dict:
        """
        Compute basis = perp_price - spot_price.
        Returns per-exchange and aggregated basis.
        """
        all_ticks = await self.ring_buffer.get_ticks()
        # Get latest price per source from most recent ticks
        latest: Dict[str, float] = {}
        for t in reversed(all_ticks):
            if t.source not in latest:
                latest[t.source] = t.price
            if len(latest) >= 6:  # all sources covered
                break

        per_exchange = {}
        for exchange, (spot_src, perp_src) in EXCHANGE_MAP.items():
            spot = latest.get(spot_src)
            perp = latest.get(perp_src)
            if spot is not None and perp is not None:
                basis = perp - spot
                basis_pct = (basis / spot * 100) if spot else None
                per_exchange[exchange] = {
                    "spot_price": spot,
                    "perp_price": perp,
                    "basis": basis,
                    "basis_pct": basis_pct,
                }

        # Aggregated basis: avg spot vs avg perp
        spot_prices = [latest[s] for s in ALL_CEX_SPOT if s in latest]
        perp_prices = [latest[s] for s in ALL_CEX_PERP if s in latest]

        agg_spot = sum(spot_prices) / len(spot_prices) if spot_prices else None
        agg_perp = sum(perp_prices) / len(perp_prices) if perp_prices else None
        agg_basis = (agg_perp - agg_spot) if (agg_spot and agg_perp) else None
        agg_basis_pct = (agg_basis / agg_spot * 100) if (agg_spot and agg_basis is not None) else None

        return {
            "per_exchange": per_exchange,
            "aggregated": {
                "spot_price": agg_spot,
                "perp_price": agg_perp,
                "basis": agg_basis,
                "basis_pct": agg_basis_pct,
            },
        }

    async def compute_basis_series(
        self,
        interval_secs: int = 60,
        window_secs: int = 3600,
    ) -> Dict:
        """
        Compute basis as time-series from OHLCV bars.
        Returns per-exchange + aggregated [{timestamp, basis, basis_pct}]
        """
        from db import get_latest_ohlcv
        cutoff_minutes = window_secs // 60

        # Fetch OHLCV close prices per source
        source_bars: Dict[str, Dict[int, float]] = {}
        for src in ALL_CEX_SPOT + ALL_CEX_PERP:
            bars = get_latest_ohlcv(src, minutes=cutoff_minutes)
            source_bars[src] = {b["timestamp"]: b["close"] for b in bars}

        # Collect all timestamps
        all_ts: set = set()
        for bars in source_bars.values():
            all_ts.update(bars.keys())
        sorted_ts = sorted(all_ts)

        per_exchange: Dict[str, List[dict]] = {ex: [] for ex in EXCHANGE_MAP}
        agg_series: List[dict] = []

        for ts in sorted_ts:
            # Per-exchange basis
            for exchange, (spot_src, perp_src) in EXCHANGE_MAP.items():
                spot = source_bars.get(spot_src, {}).get(ts)
                perp = source_bars.get(perp_src, {}).get(ts)
                if spot is not None and perp is not None:
                    basis = perp - spot
                    per_exchange[exchange].append({
                        "timestamp": ts,
                        "basis": basis,
                        "basis_pct": basis / spot * 100 if spot else None,
                    })

            # Aggregated basis
            spot_vals = [source_bars.get(s, {}).get(ts) for s in ALL_CEX_SPOT]
            perp_vals = [source_bars.get(s, {}).get(ts) for s in ALL_CEX_PERP]
            spot_vals = [v for v in spot_vals if v is not None]
            perp_vals = [v for v in perp_vals if v is not None]
            if spot_vals and perp_vals:
                agg_s = sum(spot_vals) / len(spot_vals)
                agg_p = sum(perp_vals) / len(perp_vals)
                agg_series.append({
                    "timestamp": ts,
                    "basis": agg_p - agg_s,
                    "basis_pct": (agg_p - agg_s) / agg_s * 100 if agg_s else None,
                })

        return {
            "per_exchange": per_exchange,
            "aggregated": agg_series,
            "interval_secs": interval_secs,
            "window_secs": window_secs,
        }

    # ------------------------------------------------------------------ #
    # DEX vs CEX spread                                                    #
    # ------------------------------------------------------------------ #

    async def compute_dex_cex_spread(self) -> Dict:
        """
        Compute DEX price vs CEX spot average.
        spread = dex_price - cex_spot_avg
        """
        all_ticks = await self.ring_buffer.get_ticks()
        latest: Dict[str, float] = {}
        for t in reversed(all_ticks):
            if t.source not in latest:
                latest[t.source] = t.price
            if len(latest) >= 6:
                break

        dex_prices = [latest[s] for s in DEX_SOURCES if s in latest]
        spot_prices = [latest[s] for s in ALL_CEX_SPOT if s in latest]

        dex_avg = sum(dex_prices) / len(dex_prices) if dex_prices else None
        cex_spot_avg = sum(spot_prices) / len(spot_prices) if spot_prices else None

        spread = (dex_avg - cex_spot_avg) if (dex_avg and cex_spot_avg) else None
        spread_pct = (spread / cex_spot_avg * 100) if (spread is not None and cex_spot_avg) else None

        return {
            "dex_price": dex_avg,
            "cex_spot_avg": cex_spot_avg,
            "spread": spread,
            "spread_pct": spread_pct,
            "per_dex": {s: latest[s] for s in DEX_SOURCES if s in latest},
            "per_cex_spot": {s: latest[s] for s in ALL_CEX_SPOT if s in latest},
        }

    async def compute_dex_cex_spread_series(
        self,
        interval_secs: int = 60,
        window_secs: int = 3600,
    ) -> List[dict]:
        """Time-series of DEX vs CEX spread."""
        from db import get_latest_ohlcv
        cutoff_minutes = window_secs // 60

        source_bars: Dict[str, Dict[int, float]] = {}
        for src in DEX_SOURCES + ALL_CEX_SPOT:
            bars = get_latest_ohlcv(src, minutes=cutoff_minutes)
            source_bars[src] = {b["timestamp"]: b["close"] for b in bars}

        all_ts: set = set()
        for bars in source_bars.values():
            all_ts.update(bars.keys())
        sorted_ts = sorted(all_ts)

        series = []
        for ts in sorted_ts:
            dex_vals = [source_bars.get(s, {}).get(ts) for s in DEX_SOURCES]
            cex_vals = [source_bars.get(s, {}).get(ts) for s in ALL_CEX_SPOT]
            dex_vals = [v for v in dex_vals if v is not None]
            cex_vals = [v for v in cex_vals if v is not None]
            if dex_vals and cex_vals:
                dex_avg = sum(dex_vals) / len(dex_vals)
                cex_avg = sum(cex_vals) / len(cex_vals)
                series.append({
                    "timestamp": ts,
                    "dex_price": dex_avg,
                    "cex_spot_avg": cex_avg,
                    "spread": dex_avg - cex_avg,
                    "spread_pct": (dex_avg - cex_avg) / cex_avg * 100 if cex_avg else None,
                })

        return series

    # ------------------------------------------------------------------ #
    # OI delta                                                             #
    # ------------------------------------------------------------------ #

    async def compute_oi_delta(self) -> Dict:
        """
        Compute OI delta = current OI - OI 1 minute ago, per source and aggregated.
        Uses in-memory OI history tracked by update_oi_history().
        """
        async with self.lock:
            result = {}
            agg_current = 0.0
            agg_prev = 0.0
            has_agg = False

            for source, history in self._oi_history.items():
                if len(history) < 2:
                    result[source] = {"oi": history[-1][1] if history else None, "delta": None, "delta_pct": None}
                    continue

                current_ts, current_oi = history[-1]
                # Find entry ~60s ago
                target_ts = current_ts - 60
                prev = min(history[:-1], key=lambda x: abs(x[0] - target_ts))
                prev_oi = prev[1]

                delta = current_oi - prev_oi
                delta_pct = (delta / prev_oi * 100) if prev_oi else None
                result[source] = {
                    "oi": current_oi,
                    "delta": delta,
                    "delta_pct": delta_pct,
                }
                agg_current += current_oi
                agg_prev += prev_oi
                has_agg = True

            agg_delta = agg_current - agg_prev if has_agg else None
            agg_delta_pct = (agg_delta / agg_prev * 100) if (agg_prev and agg_delta is not None) else None

            return {
                "per_source": result,
                "aggregated": {
                    "oi": agg_current if has_agg else None,
                    "delta": agg_delta,
                    "delta_pct": agg_delta_pct,
                },
            }

    async def update_oi_history(self, source: str, oi: float):
        """Record a new OI snapshot into the internal history (called by poller)."""
        async with self.lock:
            history = self._oi_history[source]
            history.append((time.time(), oi))
            # Keep last N entries
            if len(history) > self._oi_history_limit:
                self._oi_history[source] = history[-self._oi_history_limit:]

    async def get_oi_delta_series(self, window_secs: int = 3600) -> Dict:
        """Time-series of per-minute OI deltas."""
        from db import get_latest_oi_history
        cutoff = time.time() - window_secs

        per_source: Dict[str, List[dict]] = {}
        agg_by_ts: Dict[int, float] = defaultdict(float)

        for src in ["binance-perp", "bybit-perp"]:
            history = get_latest_oi_history(src, limit=int(window_secs / 30) + 10)
            # Filter by window
            history = [h for h in history if h["timestamp"] >= cutoff]
            history.sort(key=lambda x: x["timestamp"])

            series = []
            for i in range(1, len(history)):
                prev = history[i - 1]
                curr = history[i]
                delta = curr["oi"] - prev["oi"]
                ts = int(curr["timestamp"])
                bar_ts = (ts // 60) * 60
                series.append({
                    "timestamp": curr["timestamp"],
                    "oi": curr["oi"],
                    "delta": delta,
                })
                agg_by_ts[bar_ts] += delta

            per_source[src] = series

        agg_series = [{"timestamp": ts, "delta": delta} for ts, delta in sorted(agg_by_ts.items())]
        return {"per_source": per_source, "aggregated": agg_series, "window_secs": window_secs}

    # ------------------------------------------------------------------ #
    # Funding aggregation                                                  #
    # ------------------------------------------------------------------ #

    async def get_funding_summary(self) -> Dict:
        """Aggregate funding rates across sources."""
        if not self.oi_funding_poller:
            return {"error": "OI/funding poller not available"}

        rates = self.oi_funding_poller.get_latest_funding()
        values = [v for v in rates.values() if v is not None]
        avg_rate = sum(values) / len(values) if values else None
        annualized = avg_rate * 3 * 365 * 100 if avg_rate is not None else None  # 3 periods/day

        return {
            "per_source": rates,
            "average_rate": avg_rate,
            "annualized_pct": annualized,
        }

    # ------------------------------------------------------------------ #
    # Full analytics snapshot                                              #
    # ------------------------------------------------------------------ #

    async def snapshot(self) -> Dict:
        """Return a full analytics snapshot (all metrics, current values)."""
        try:
            cvd = await self.compute_cvd()
        except Exception as e:
            cvd = {"error": str(e)}

        try:
            basis = await self.compute_basis()
        except Exception as e:
            basis = {"error": str(e)}

        try:
            spread = await self.compute_dex_cex_spread()
        except Exception as e:
            spread = {"error": str(e)}

        try:
            oi_delta = await self.compute_oi_delta()
        except Exception as e:
            oi_delta = {"error": str(e)}

        try:
            funding = await self.get_funding_summary()
        except Exception as e:
            funding = {"error": str(e)}

        return {
            "timestamp": time.time(),
            "cvd": cvd,
            "basis": basis,
            "dex_cex_spread": spread,
            "oi_delta": oi_delta,
            "funding": funding,
        }


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _cvd_from_ticks(ticks: List[Tick]) -> float:
    """
    Compute CVD from a list of ticks.
    CVD = Σ(buy_volume) - Σ(sell_volume)
    """
    cvd = 0.0
    for t in ticks:
        if t.is_buy:
            cvd += t.volume
        else:
            cvd -= t.volume
    return cvd

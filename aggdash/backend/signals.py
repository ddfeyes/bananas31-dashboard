"""
signals.py — Real-time signal detection for bananas31-dashboard.

Signals:
  - squeeze_risk: basis > 2% AND funding > 0 → longs stacking, squeeze risk
  - arb_opportunity: DEX price deviation > 1% from CEX avg → arbitrage opportunity
  - oi_accumulation: OI delta > 5% AND price flat → accumulation
  - deleveraging: OI delta < -5% AND price delta < -1% → deleveraging
"""
import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Thresholds — calibrated for BANANAS31 (low-cap, typical basis 0.03–0.3%)
SQUEEZE_BASIS_THRESHOLD = 0.002      # 0.2% (was 2% — too high for BANANAS31)
SQUEEZE_FUNDING_THRESHOLD = 0.0      # funding > 0
ARB_DEVIATION_THRESHOLD = 0.003      # 0.3% (was 1% — DEX/CEX spread rarely exceeds 0.5%)
OI_ACCUMULATION_THRESHOLD = 0.03     # 3% OI spike (was 5%)
OI_DELEVERAGE_THRESHOLD = -0.03      # -3% OI drop (was -5%)
PRICE_FLAT_THRESHOLD = 0.005         # price change < 0.5% = "flat"
PRICE_DOWN_THRESHOLD = -0.005        # price change < -0.5% = "down" (was -1%)
MIN_DATA_WINDOW_SECS = 60            # 60s minimum before firing signals (DB has enough history after restart)


class SignalEngine:
    """Compute real-time signals from analytics snapshot."""

    def __init__(self, ring_buffer=None):
        # ring_buffer reserved for future tick-level signal logic (e.g. CVD divergence)
        self._ring_buffer = ring_buffer
        self._start_time = time.time()

    def _has_enough_data(self) -> bool:
        """Require at least 5 minutes of data before emitting signals."""
        return (time.time() - self._start_time) >= MIN_DATA_WINDOW_SECS

    def compute_signals(self, snapshot: Dict) -> List[Dict]:
        """
        Given an analytics snapshot dict, return list of active signals.
        Returns empty list if not enough data yet.
        """
        if not self._has_enough_data():
            return []

        signals = []

        try:
            sig = self._squeeze_risk(snapshot)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.warning("squeeze_risk error: %s", e)

        try:
            sig = self._arb_opportunity(snapshot)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.warning("arb_opportunity error: %s", e)

        try:
            sig = self._oi_accumulation(snapshot)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.warning("oi_accumulation error: %s", e)

        try:
            sig = self._deleveraging(snapshot)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.warning("deleveraging error: %s", e)

        return signals

    # ------------------------------------------------------------------ #
    # Individual signals                                                   #
    # ------------------------------------------------------------------ #

    def _squeeze_risk(self, snapshot: Dict) -> Optional[Dict]:
        """
        basis > 2% AND funding > 0 → squeeze risk signal.
        Uses aggregated basis and average funding rate.
        """
        basis_data = snapshot.get("basis", {})
        funding_data = snapshot.get("funding", {})

        # Aggregated basis — snapshot uses basis_data["aggregated"]["basis_pct"]
        agg_basis_pct = None
        aggregated = basis_data.get("aggregated", {})
        if aggregated:
            agg_basis_pct = aggregated.get("basis_pct")
        # Fallback: legacy flat keys
        if agg_basis_pct is None:
            agg_basis_pct = basis_data.get("agg_basis_pct")
        if agg_basis_pct is None:
            return None
        # Convert from percent (0.09%) to fraction (0.0009) for threshold comparison
        agg_basis = agg_basis_pct / 100.0 if agg_basis_pct > 1 else agg_basis_pct / 100.0
        # Note: basis_pct is already in % units (e.g. 0.09 means 0.09%), threshold is 2% = 0.02 fraction
        agg_basis = agg_basis_pct / 100.0

        # Average funding rate across exchanges
        avg_funding = _extract_avg_funding(funding_data)

        if agg_basis is None or avg_funding is None:
            return None

        if agg_basis > SQUEEZE_BASIS_THRESHOLD and avg_funding > SQUEEZE_FUNDING_THRESHOLD:
            return {
                "id": "squeeze_risk",
                "name": "Squeeze Risk",
                "severity": "alert",
                "message": f"Basis {agg_basis*100:.2f}% + funding {avg_funding*100:.4f}% → longs stacking, squeeze risk",
                "value": agg_basis,
                "threshold": SQUEEZE_BASIS_THRESHOLD,
            }
        return None

    def _arb_opportunity(self, snapshot: Dict) -> Optional[Dict]:
        """
        DEX price deviation > 1% from CEX avg → arbitrage opportunity.
        """
        spread_data = snapshot.get("dex_cex_spread", {})

        # Snapshot uses "spread_pct" not "deviation_pct"
        deviation_pct = spread_data.get("deviation_pct") or spread_data.get("spread_pct")
        if deviation_pct is None:
            return None

        # spread_pct is in percent units (e.g. 0.037 means 0.037%)
        # Convert to fraction for threshold (ARB_DEVIATION_THRESHOLD = 0.01 = 1%)
        abs_dev = abs(deviation_pct) / 100.0

        if abs_dev > ARB_DEVIATION_THRESHOLD:
            direction = "premium" if deviation_pct > 0 else "discount"
            return {
                "id": "arb_opportunity",
                "name": "DEX Arbitrage",
                "severity": "warning",
                "message": f"DEX {direction} {abs_dev*100:.2f}% vs CEX avg → arbitrage opportunity",
                "value": abs_dev,
                "threshold": ARB_DEVIATION_THRESHOLD,
            }
        return None

    def _oi_accumulation(self, snapshot: Dict) -> Optional[Dict]:
        """
        OI delta > 5% AND price flat → accumulation signal.
        """
        oi_data = snapshot.get("oi_delta", {})
        basis_data = snapshot.get("basis", {})

        # snapshot oi_delta uses aggregated.delta_pct not total_delta_pct
        oi_delta_pct = oi_data.get("total_delta_pct")
        if oi_delta_pct is None:
            agg = oi_data.get("aggregated", {}) or {}
            oi_delta_pct = agg.get("delta_pct")
        if oi_delta_pct is None:
            return None

        # Price change: use basis trend as proxy (flat spot price)
        price_delta_pct = _extract_price_delta(basis_data)

        if oi_delta_pct > OI_ACCUMULATION_THRESHOLD:
            is_flat = price_delta_pct is None or abs(price_delta_pct) < PRICE_FLAT_THRESHOLD
            if not is_flat:
                return None  # price moving, not pure accumulation
            price_info = f", price flat ({price_delta_pct*100:.2f}%)" if price_delta_pct is not None else ""

            return {
                "id": "oi_accumulation",
                "name": "OI Accumulation",
                "severity": "info",
                "message": f"OI spike +{oi_delta_pct*100:.1f}%{price_info} → possible accumulation",
                "value": oi_delta_pct,
                "threshold": OI_ACCUMULATION_THRESHOLD,
            }
        return None

    def _deleveraging(self, snapshot: Dict) -> Optional[Dict]:
        """
        OI delta < -5% AND price delta < -1% → deleveraging signal.
        """
        oi_data = snapshot.get("oi_delta", {})
        basis_data = snapshot.get("basis", {})

        oi_delta_pct = oi_data.get("total_delta_pct")
        if oi_delta_pct is None:
            agg = oi_data.get("aggregated", {}) or {}
            oi_delta_pct = agg.get("delta_pct")
        if oi_delta_pct is None:
            return None

        price_delta_pct = _extract_price_delta(basis_data)

        if (
            oi_delta_pct < OI_DELEVERAGE_THRESHOLD
            and price_delta_pct is not None
            and price_delta_pct < PRICE_DOWN_THRESHOLD
        ):
            return {
                "id": "deleveraging",
                "name": "Deleveraging",
                "severity": "warning",
                "message": f"OI {oi_delta_pct*100:.1f}% + price {price_delta_pct*100:.2f}% → deleveraging",
                "value": oi_delta_pct,
                "threshold": OI_DELEVERAGE_THRESHOLD,
            }
        return None


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _extract_avg_funding(funding_data: Dict) -> Optional[float]:
    """Extract average funding rate from funding summary."""
    if not funding_data or "error" in funding_data:
        return None

    # snapshot funding uses per_source not per_exchange
    per_source = funding_data.get("per_source") or funding_data.get("per_exchange", {})
    if per_source:
        rates = []
        for ex, data in per_source.items():
            if isinstance(data, dict):
                # rate_8h key (from OIFundingPoller)
                rate = data.get("rate_8h") or data.get("funding_rate")
                if rate is not None:
                    rates.append(float(rate))
        if rates:
            return sum(rates) / len(rates)

    # Fallback: average_rate already computed
    rate = funding_data.get("average_rate") or funding_data.get("funding_rate")
    if rate is not None:
        return float(rate)

    return None


def _extract_price_delta(basis_data: Dict) -> Optional[float]:
    """
    Extract price delta pct from basis data.
    Uses spot_price_change_pct if available, else None.
    """
    if not basis_data or "error" in basis_data:
        return None
    return basis_data.get("spot_price_change_pct")

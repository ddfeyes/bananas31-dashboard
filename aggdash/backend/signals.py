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

# Thresholds
SQUEEZE_BASIS_THRESHOLD = 0.02       # 2%
SQUEEZE_FUNDING_THRESHOLD = 0.0      # funding > 0
ARB_DEVIATION_THRESHOLD = 0.01       # 1%
OI_ACCUMULATION_THRESHOLD = 0.05     # 5% OI spike
OI_DELEVERAGE_THRESHOLD = -0.05      # -5% OI drop
PRICE_FLAT_THRESHOLD = 0.005         # price change < 0.5% = "flat"
PRICE_DOWN_THRESHOLD = -0.01         # price change < -1% = "down"
MIN_DATA_WINDOW_SECS = 300           # 5 minutes minimum before firing signals


class SignalEngine:
    """Compute real-time signals from analytics snapshot."""

    def __init__(self, ring_buffer=None):
        self.ring_buffer = ring_buffer
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
            logger.debug("squeeze_risk error: %s", e)

        try:
            sig = self._arb_opportunity(snapshot)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.debug("arb_opportunity error: %s", e)

        try:
            sig = self._oi_accumulation(snapshot)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.debug("oi_accumulation error: %s", e)

        try:
            sig = self._deleveraging(snapshot)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.debug("deleveraging error: %s", e)

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

        # Aggregated basis (perp - spot) / spot
        agg_basis = basis_data.get("agg_basis_pct")
        if agg_basis is None:
            # Try to compute from raw basis value
            agg_basis_raw = basis_data.get("agg_basis")
            spot_price = basis_data.get("spot_price")
            if agg_basis_raw is not None and spot_price and spot_price > 0:
                agg_basis = agg_basis_raw / spot_price
            else:
                return None

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

        deviation_pct = spread_data.get("deviation_pct")
        if deviation_pct is None:
            return None

        # deviation_pct is already a percentage (0.02 = 2%)
        abs_dev = abs(deviation_pct)

        if abs_dev > ARB_DEVIATION_THRESHOLD:
            direction = "premium" if deviation_pct > 0 else "discount"
            return {
                "id": "arb_opportunity",
                "name": "DEX Arbitrage",
                "severity": "warning",
                "message": f"DEX {direction} {abs_dev*100:.2f}% vs CEX avg → arbitrage opportunity",
                "value": deviation_pct,
                "threshold": ARB_DEVIATION_THRESHOLD,
            }
        return None

    def _oi_accumulation(self, snapshot: Dict) -> Optional[Dict]:
        """
        OI delta > 5% AND price flat → accumulation signal.
        """
        oi_data = snapshot.get("oi_delta", {})
        basis_data = snapshot.get("basis", {})

        oi_delta_pct = oi_data.get("total_delta_pct")
        if oi_delta_pct is None:
            return None

        # Price change: use basis trend as proxy (flat spot price)
        price_delta_pct = _extract_price_delta(basis_data)

        if oi_delta_pct > OI_ACCUMULATION_THRESHOLD:
            price_info = ""
            if price_delta_pct is not None:
                is_flat = abs(price_delta_pct) < PRICE_FLAT_THRESHOLD
                if not is_flat:
                    return None  # price moving, not pure accumulation
                price_info = f", price flat ({price_delta_pct*100:.2f}%)"

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

    # Try per_exchange dict
    per_exchange = funding_data.get("per_exchange", {})
    if per_exchange:
        rates = []
        for ex, data in per_exchange.items():
            if isinstance(data, dict):
                rate = data.get("funding_rate")
                if rate is not None:
                    rates.append(float(rate))
        if rates:
            return sum(rates) / len(rates)

    # Fallback: top-level funding_rate
    rate = funding_data.get("funding_rate")
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

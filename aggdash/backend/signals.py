"""
signals.py — Real-time signal detection for bananas31-dashboard.

Signals:
  - squeeze_watch: basis 0.1-0.2% + funding > 0 → early squeeze warning (ℹ️)
  - squeeze_risk: basis > 0.2% AND funding > 0 → longs stacking, squeeze risk (🚨)
  - arb_opportunity: DEX price deviation > 0.3% from CEX avg → arbitrage opportunity
  - oi_accumulation: OI delta > 3% AND price flat → accumulation
  - deleveraging: OI delta < -3% AND price delta < -0.5% → deleveraging
"""
import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Thresholds — calibrated for BANANAS31 (low-cap, typical basis 0.03–0.3%)
SQUEEZE_WATCH_BASIS_THRESHOLD = 0.001  # 0.1% — early warning (pattern fires at 0.1%)
SQUEEZE_BASIS_THRESHOLD = 0.002       # 0.2% — full squeeze risk (was 2% — too high)
SQUEEZE_FUNDING_THRESHOLD = 0.0       # funding > 0
ARB_DEVIATION_THRESHOLD = 0.003      # 0.3% (was 1% — DEX/CEX spread rarely exceeds 0.5%)
OI_ACCUMULATION_THRESHOLD = 0.03     # 3% OI spike (was 5%)
OI_DELEVERAGE_THRESHOLD = -0.03      # -3% OI drop (was -5%)
PRICE_FLAT_THRESHOLD = 0.005         # price change < 0.5% = "flat"
PRICE_DOWN_THRESHOLD = -0.005        # price change < -0.5% = "down" (was -1%)
MIN_DATA_WINDOW_SECS = 60            # 60s minimum before firing signals (DB has enough history after restart)

# Thresholds for new signals
BASIS_FLIP_THRESHOLD = None  # Any sign change fires; no numeric threshold
CONTANGO_BASIS_THRESHOLD = -0.001  # -0.1%
CONTANGO_OI_STABLE_THRESHOLD = 0.02  # ±2% OI change = "stable"


class SignalEngine:
    """Compute real-time signals from analytics snapshot."""

    def __init__(self, ring_buffer=None):
        # ring_buffer reserved for future tick-level signal logic (e.g. CVD divergence)
        self._ring_buffer = ring_buffer
        self._start_time = time.time()
        self._prev_agg_basis: Optional[float] = None

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
            sig = self._squeeze_watch(snapshot)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.warning("squeeze_watch error: %s", e)

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

        try:
            sig = self._negative_basis(snapshot)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.warning("negative_basis error: %s", e)

        try:
            sig = self._basis_flip(snapshot)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.warning("basis_flip error: %s", e)

        try:
            sig = self._contango_flip(snapshot)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.warning("contango_flip error: %s", e)

        return signals

    # ------------------------------------------------------------------ #
    # Individual signals                                                   #
    # ------------------------------------------------------------------ #

    def _squeeze_watch(self, snapshot: Dict) -> Optional[Dict]:
        """
        basis > 0.1% AND funding > 0 → early squeeze warning (0.1-0.2% zone).
        Fires before the full squeeze_risk signal (which triggers at 0.2%+).
        """
        basis_data = snapshot.get("basis", {})
        funding_data = snapshot.get("funding", {})

        agg_basis_pct = None
        aggregated = basis_data.get("aggregated", {})
        if aggregated:
            agg_basis_pct = aggregated.get("basis_pct")
        if agg_basis_pct is None:
            agg_basis_pct = basis_data.get("agg_basis_pct")
        if agg_basis_pct is None:
            return None

        # Convert from percent to fraction
        agg_basis = agg_basis_pct / 100.0
        avg_funding = _extract_avg_funding(funding_data)

        if avg_funding is None:
            return None

        # Watch fires in the 0.1-0.2% zone (above watch threshold, below full squeeze threshold)
        if agg_basis > SQUEEZE_WATCH_BASIS_THRESHOLD and agg_basis <= SQUEEZE_BASIS_THRESHOLD and avg_funding > SQUEEZE_FUNDING_THRESHOLD:
            return {
                "id": "squeeze_watch",
                "name": "Squeeze Watch",
                "severity": "info",
                "message": f"Basis {agg_basis*100:.3f}% + funding {avg_funding*100:.4f}% — early squeeze warning",
                "value": agg_basis,
                "threshold": SQUEEZE_WATCH_BASIS_THRESHOLD,
            }
        return None

    def _squeeze_risk(self, snapshot: Dict) -> Optional[Dict]:
        """
        basis > 0.2% AND funding > 0 → squeeze risk signal.
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
        # Convert from percent (e.g. 0.139%) to fraction (0.00139) for threshold comparison
        agg_basis = agg_basis_pct / 100.0

        # Average funding rate across exchanges
        avg_funding = _extract_avg_funding(funding_data)

        if agg_basis is None or avg_funding is None:
            return None

        if agg_basis > SQUEEZE_BASIS_THRESHOLD and avg_funding > SQUEEZE_FUNDING_THRESHOLD:
            return {
                "id": "squeeze_risk",
                "name": "Squeeze Risk",
                "direction": "short",
                "severity": "alert",
                "message": f"Basis {agg_basis*100:.2f}% + funding {avg_funding*100:.4f}% → SHORT (funding decay → liquidation cascade risk)",
                "value": agg_basis,
                "threshold": SQUEEZE_BASIS_THRESHOLD,
            }
        return None

    def _negative_basis(self, snapshot: Dict) -> Optional[Dict]:
        """
        Negative basis (perp below spot) → potential long opportunity.
        Mechanism: perp trading below spot = underpriced relative to spot = mean reversion.
        """
        basis_data = snapshot.get("basis", {})
        aggregated = basis_data.get("aggregated", {})
        agg_basis_pct = aggregated.get("basis_pct")
        if agg_basis_pct is None:
            agg_basis_pct = basis_data.get("agg_basis_pct")
        if agg_basis_pct is None:
            return None

        agg_basis = agg_basis_pct / 100.0

        # Fire when basis is negative (perp below spot)
        if agg_basis < -0.0005:  # < -0.05%
            return {
                "id": "negative_basis",
                "name": "Negative Basis",
                "direction": "long",
                "severity": "info",
                "message": f"Basis {agg_basis*100:.2f}% → LONG (perp underpriced vs spot, mean reversion)",
                "value": agg_basis,
                "threshold": -0.0005,
            }
        return None

    def _basis_flip(self, snapshot: Dict) -> Optional[Dict]:
        """
        basis_flip: fires when agg_basis_pct changes sign (positive→negative or negative→positive).
        Uses _prev_agg_basis to detect the transition. Updates _prev_agg_basis on each call.
        """
        basis_data = snapshot.get("basis", {})
        aggregated = basis_data.get("aggregated", {})
        agg_basis_pct = aggregated.get("basis_pct")
        if agg_basis_pct is None:
            agg_basis_pct = basis_data.get("agg_basis_pct")
        if agg_basis_pct is None:
            return None

        # Convert % to fraction for comparison
        current_basis = agg_basis_pct / 100.0

        # Fire only if we have a previous value AND sign changed
        if self._prev_agg_basis is not None:
            prev_sign = 1 if self._prev_agg_basis >= 0 else -1
            curr_sign = 1 if current_basis >= 0 else -1
            if prev_sign != curr_sign:
                direction = "positive→negative" if curr_sign < 0 else "negative→positive"
                prev_basis = self._prev_agg_basis  # capture before overwriting
                self._prev_agg_basis = current_basis
                return {
                    "id": "basis_flip",
                    "name": "Basis Flip",
                    "severity": "warning",
                    "message": f"Basis flipped {direction} ({prev_basis*100:.3f}%→{current_basis*100:.3f}%) — regime change",
                    "value": current_basis,
                    "prev_value": prev_basis,
                }

        # Always update prev after first non-None value
        self._prev_agg_basis = current_basis
        return None

    def _contango_flip(self, snapshot: Dict) -> Optional[Dict]:
        """
        contango_flip: fires when basis < -0.1% AND OI stable.
        OI stability: |oi_delta_pct| < 2%.
        """
        basis_data = snapshot.get("basis", {})
        aggregated = basis_data.get("aggregated", {})
        agg_basis_pct = aggregated.get("basis_pct")
        if agg_basis_pct is None:
            agg_basis_pct = basis_data.get("agg_basis_pct")
        if agg_basis_pct is None:
            return None

        current_basis = agg_basis_pct / 100.0

        if current_basis >= CONTANGO_BASIS_THRESHOLD:
            return None  # not in contango regime

        # Check OI stability
        oi_data = snapshot.get("oi_delta", {})
        oi_delta_pct = oi_data.get("total_delta_pct")
        if oi_delta_pct is None:
            agg = oi_data.get("aggregated", {}) or {}
            oi_delta_pct = agg.get("delta_pct")
        if oi_delta_pct is None:
            return None

        if abs(oi_delta_pct) >= CONTANGO_OI_STABLE_THRESHOLD:
            return None  # OI not stable

        return {
            "id": "contango_flip",
            "name": "Contango Flip",
            "severity": "info",
            "message": f"Basis {current_basis*100:.2f}% + OI Δ {oi_delta_pct*100:.1f}% → contango regime (OI stable)",
            "value": current_basis,
            "threshold": CONTANGO_BASIS_THRESHOLD,
        }

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

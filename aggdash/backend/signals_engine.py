"""Signals engine: evaluates market conditions and writes to signals table."""
import asyncio
import json
import logging
import time

from db import get_db

logger = logging.getLogger(__name__)

SIGNAL_TYPES = ["SQUEEZE_RISK", "ARB_OPPTY", "OI_ACCUMULATION"]
EVAL_INTERVAL_SECS = 60


def _evaluate_squeeze_risk(db) -> tuple[bool, dict]:
    """SQUEEZE_RISK: aggregate basis > 2% AND avg funding_rate > 0."""
    try:
        # Latest basis from analytics: use price_feed to compute basis
        # basis = perp_close - spot_close / spot_close * 100
        row = db.execute("""
            SELECT
                (SELECT close FROM price_feed WHERE exchange_id='binance-perp' ORDER BY timestamp DESC LIMIT 1) AS bp,
                (SELECT close FROM price_feed WHERE exchange_id='binance-spot' ORDER BY timestamp DESC LIMIT 1) AS bs,
                (SELECT close FROM price_feed WHERE exchange_id='bybit-perp' ORDER BY timestamp DESC LIMIT 1) AS yp,
                (SELECT close FROM price_feed WHERE exchange_id='bybit-spot' ORDER BY timestamp DESC LIMIT 1) AS ys
        """).fetchone()

        if not row or not row["bs"] or not row["ys"]:
            return False, {"reason": "no price data"}

        bp, bs, yp, ys = row["bp"], row["bs"], row["yp"], row["ys"]
        basis_binance = ((bp - bs) / bs * 100) if bs else 0.0
        basis_bybit = ((yp - ys) / ys * 100) if ys else 0.0
        avg_basis = (basis_binance + basis_bybit) / 2.0

        # Latest funding rates
        funding_rows = db.execute("""
            SELECT exchange_id, funding_rate
            FROM oi
            WHERE exchange_id IN ('binance-perp', 'bybit-perp')
            GROUP BY exchange_id
            HAVING timestamp = MAX(timestamp)
        """).fetchall()

        funding_rates = {r["exchange_id"]: r["funding_rate"] for r in funding_rows}
        avg_funding = sum(funding_rates.values()) / len(funding_rates) if funding_rates else 0.0

        active = avg_basis > 2.0 and avg_funding > 0
        meta = {
            "basis_pct": round(avg_basis, 4),
            "basis_binance_pct": round(basis_binance, 4),
            "basis_bybit_pct": round(basis_bybit, 4),
            "avg_funding_rate": avg_funding,
            "funding_rates": funding_rates,
        }
        return active, meta
    except Exception as e:
        logger.error("Error evaluating SQUEEZE_RISK: %s", e)
        return False, {"error": str(e)}


def _evaluate_arb_oppty(db) -> tuple[bool, dict]:
    """ARB_OPPTY: latest dex_price deviation_pct > 1.0%."""
    try:
        row = db.execute("""
            SELECT deviation_pct, price, timestamp
            FROM dex_price
            ORDER BY timestamp DESC
            LIMIT 1
        """).fetchone()

        if not row:
            return False, {"reason": "no dex data"}

        deviation = row["deviation_pct"] if row["deviation_pct"] is not None else 0.0
        active = abs(deviation) > 1.0
        meta = {
            "dex_premium_pct": round(deviation, 4),
            "dex_price": row["price"],
        }
        return active, meta
    except Exception as e:
        logger.error("Error evaluating ARB_OPPTY: %s", e)
        return False, {"error": str(e)}


def _evaluate_oi_accumulation(db) -> tuple[bool, dict]:
    """OI_ACCUMULATION: sum of OI delta over last 30 min > 50000."""
    try:
        ts_30m_ago = time.time() - 1800

        # Current OI
        current = db.execute("""
            SELECT exchange_id, open_interest
            FROM oi
            WHERE exchange_id IN ('binance-perp', 'bybit-perp')
            GROUP BY exchange_id
            HAVING timestamp = MAX(timestamp)
        """).fetchall()

        # OI 30 min ago
        past = db.execute("""
            SELECT exchange_id, open_interest
            FROM oi
            WHERE exchange_id IN ('binance-perp', 'bybit-perp')
              AND timestamp <= ?
            GROUP BY exchange_id
            HAVING timestamp = MAX(timestamp)
        """, (ts_30m_ago,)).fetchall()

        current_map = {r["exchange_id"]: r["open_interest"] for r in current}
        past_map = {r["exchange_id"]: r["open_interest"] for r in past}

        total_delta = 0.0
        per_exchange = {}
        for exch in ["binance-perp", "bybit-perp"]:
            cur = current_map.get(exch, 0) or 0
            prv = past_map.get(exch, cur)
            delta = cur - prv
            per_exchange[exch] = round(delta, 2)
            total_delta += delta

        active = total_delta > 50000
        meta = {
            "oi_delta_30m": round(total_delta, 2),
            "per_exchange": per_exchange,
        }
        return active, meta
    except Exception as e:
        logger.error("Error evaluating OI_ACCUMULATION: %s", e)
        return False, {"error": str(e)}


async def run_signals_loop():
    """Background loop: evaluates signals every EVAL_INTERVAL_SECS seconds."""
    while True:
        try:
            await evaluate_and_store_signals()
        except Exception as e:
            logger.error("Signals loop error: %s", e)
        await asyncio.sleep(EVAL_INTERVAL_SECS)


def evaluate_and_store_signals():
    """Synchronously evaluate all signals and write to DB."""
    db = get_db()
    try:
        evaluators = [
            ("SQUEEZE_RISK", _evaluate_squeeze_risk),
            ("ARB_OPPTY", _evaluate_arb_oppty),
            ("OI_ACCUMULATION", _evaluate_oi_accumulation),
        ]
        for sig_type, evaluator in evaluators:
            active, meta = evaluator(db)
            db.execute(
                "INSERT INTO signals (type, active, metadata_json) VALUES (?, ?, ?)",
                (sig_type, int(active), json.dumps(meta))
            )
        db.commit()
        logger.debug("Signals evaluated and stored")
    except Exception as e:
        logger.error("Error storing signals: %s", e)
        db.rollback()
    finally:
        db.close()


def get_current_signals() -> dict:
    """Return latest state of all 3 signals."""
    db = get_db()
    try:
        result = []
        for sig_type in SIGNAL_TYPES:
            row = db.execute("""
                SELECT type, active, metadata_json, created_at
                FROM signals
                WHERE type = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (sig_type,)).fetchone()

            if row:
                meta = json.loads(row["metadata_json"] or "{}")
                entry = {
                    "type": row["type"],
                    "active": bool(row["active"]),
                    "ts": row["created_at"],
                }
                entry.update(meta)
            else:
                entry = {
                    "type": sig_type,
                    "active": False,
                    "ts": None,
                }
            result.append(entry)

        from datetime import datetime, timezone
        return {
            "signals": result,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        db.close()

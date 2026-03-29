# bananas31-dashboard

Real-time multi-exchange CEX+DEX trading dashboard for the **BANANAS31** token (BSC).

Tracks Binance/Bybit spot & perp prices, open interest, funding rates, liquidations, PancakeSwap V3 DEX data — all in one live terminal view with WebSocket price streaming, signal alerts, and Telegram notifications.

**Live:** https://bananas31-dashboard.111miniapp.com

---

## Features

- **5 price lines** — Binance spot/perp, Bybit perp, DEX (PancakeSwap V3), aggregated
- **Basis chart** — per-exchange basis % + 7-day MA overlay (SPEC §5)
- **OI chart** — aggregated + per-exchange open interest (Binance + Bybit)
- **CVD / Volume charts** — cumulative volume delta + per-bar volume
- **Funding rate chart** — 8h funding rate time series (BN yellow, BB purple)
- **Liquidations chart** — long/short liq histogram (red/green)
- **Header stats** — live prices, 24h change %, funding rates, DEX TVL, VOL-24H, OI/24H
- **Signals bar** — real-time alerts (SQUEEZE_RISK, ARB, OI_ACCUM, DELEVERAGE) + last alert
- **Patterns** — structural pattern detection (BASIS_SQUEEZE, DEX_PREMIUM, OI_ACCUMULATION, LIQUIDATION_CASCADE)
- **Telegram alerts** — signals + BASIS_SQUEEZE pattern → topic 7135, 30-min dedup, DB-persisted
- **WebSocket streaming** — `/ws/prices` live tick broadcast (<100ms latency)
- **Timeframes** — 15M / 30M / 1H / 4H / 1D / 1W / 1M / 3M / 1Y with DB resampling
- **Alert history** — persistent DB log of all fired alerts survives restarts

---

## Architecture

```
aggdash-frontend (nginx :8769)
        |  HTTP proxy /api/* and /ws/* -> backend
aggdash-backend (FastAPI :8768)
        |  WebSocket collectors (Binance WS / Bybit WS / BSC RPC)
        |  SQLite (aggdash-data volume)
        |  Telegram alert loop (5min interval)
aggdash-autoheal
        |  Monitors healthcheck -> auto-restarts unhealthy containers
```

**Stack:** Python 3.12 · FastAPI · uvicorn · aiohttp · websockets · SQLite · nginx:alpine · Docker Compose

---

## Quick Start

### Prerequisites
- Docker + Docker Compose v2
- Git

### Run locally

```bash
git clone https://github.com/ddfeyes/bananas31-dashboard.git
cd bananas31-dashboard
docker compose up -d --build
```

Backend: `http://localhost:8768`  
Frontend: `http://localhost:8769`

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `API_PORT` | `8768` | Backend listen port |
| `FRONTEND_PORT` | `8769` | Frontend nginx port |
| `LOG_LEVEL` | `INFO` | Log verbosity (DEBUG/INFO/WARNING/ERROR) |
| `BSC_HTTP_RPC` | NodeReal endpoint | BSC HTTP RPC URL |
| `BSC_WSS_RPC` | NodeReal WSS | BSC WebSocket RPC URL |
| `BSC_POOL` | PancakeSwap V3 pool address | Pool contract address |
| `DB_PATH` | `/app/data/aggdash.db` | SQLite database path |
| `OHLCV_INTERVAL_SECS` | `60` | OHLCV candle interval in seconds |

---

## API Reference

### Health & Status

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe — `{"status": "ok"}` |
| GET | `/api/status` | Exchange + DB status (legacy) |
| GET | `/api/stats` | Concise health: collectors, DB row counts, `vol_24h`, `oi_change_24h_pct` |

### Price Data

| Method | Path | Description |
|---|---|---|
| GET | `/api/prices` | Latest price per exchange |
| GET | `/api/aggregated-prices` | Volume-weighted aggregated spot/perp |
| GET | `/api/ticks` | Recent raw tick data |
| GET | `/api/price-change` | 24h price change % per exchange (vs closest price 24h ago ±30min) |

### WebSocket

| Protocol | Path | Description |
|---|---|---|
| WS | `/ws/prices` | Live price broadcast — `{source: price}` dict, throttled to 1/sec |

Connect example:
```js
const ws = new WebSocket('wss://bananas31-dashboard.111miniapp.com/ws/prices');
ws.onmessage = e => console.log(JSON.parse(e.data));
```

### DEX

| Method | Path | Description |
|---|---|---|
| GET | `/api/dex` | Latest DEX price + liquidity |
| GET | `/api/dex/history` | Historical DEX price series |

### Open Interest & Funding

| Method | Path | Description |
|---|---|---|
| GET | `/api/oi` | Latest OI per exchange |
| GET | `/api/funding` | Latest funding rates |
| GET | `/api/liquidations` | Recent liquidation events |
| GET | `/api/liquidations/series?minutes=60&bucket_secs=60` | Liquidations bucketed by minute — `{sell_usd, buy_usd, sell_count, buy_count}` |

### Analytics

| Method | Path | Description |
|---|---|---|
| GET | `/api/analytics/snapshot` | Full analytics snapshot |
| GET | `/api/analytics/cvd` | Current CVD value |
| GET | `/api/analytics/cvd/series` | CVD time series |
| GET | `/api/analytics/basis` | Current basis per exchange |
| GET | `/api/analytics/basis/series?interval_secs=60&window_secs=3600` | Basis time series |
| GET | `/api/analytics/basis/ma7d` | 7-day rolling MA of hourly basis_pct (168-bar window) |
| GET | `/api/analytics/dex-cex-spread` | DEX/CEX spread |
| GET | `/api/analytics/dex-cex-spread/series` | Spread time series |
| GET | `/api/analytics/oi-delta` | OI delta |
| GET | `/api/analytics/oi-delta/series` | OI delta time series |
| GET | `/api/analytics/funding` | Aggregated funding analytics |
| GET | `/api/analytics/funding/series?window_secs=86400&interval_secs=300` | Funding rate time series per exchange |
| GET | `/api/analytics/volume/series` | Volume time series |
| GET | `/api/analytics/price-change` | 24h price change analytics |

### OHLCV

| Method | Path | Description |
|---|---|---|
| GET | `/api/ohlcv?source=binance-spot&minutes=1440&interval=1h` | OHLCV with auto-resampling — interval: `1m/5m/15m/30m/1h/4h/1d` |

### Signals & Patterns

| Method | Path | Description |
|---|---|---|
| GET | `/api/signals` | Active signals (SQUEEZE_RISK, ARB_OPPORTUNITY, OI_ACCUMULATION, DELEVERAGING) |
| GET | `/api/patterns` | Structural pattern detection (BASIS_SQUEEZE, DEX_PREMIUM, OI_ACCUMULATION, LIQUIDATION_CASCADE, VOLUME_DIVERGENCE) |

**Signal thresholds (calibrated for BANANAS31):**
- SQUEEZE_RISK: basis > 0.2% + positive funding
- ARB_OPPORTUNITY: DEX deviation > 0.3%
- OI_ACCUMULATION: OI delta > 3% with flat price
- DELEVERAGING: OI delta < -3% + price < -0.5%

**Pattern thresholds (calibrated for BANANAS31):**
- BASIS_SQUEEZE: basis > 0.1% + positive funding
- DEX_PREMIUM: DEX > CEX × 1.003 (0.3% premium)
- OI_ACCUMULATION: OI > 1.5% in 4h with flat price
- LIQUIDATION_CASCADE: > 5 liquidations in any 5-min window

### Alerts

| Method | Path | Description |
|---|---|---|
| GET | `/api/alerts/history?limit=50` | Recent fired alerts from persistent DB — kind, name, severity, message, sent_telegram |

---

## Telegram Alerts

The backend runs a background task (`_telegram_signal_alert_loop`) every **5 minutes** that:
1. Computes signals + checks BASIS_SQUEEZE pattern
2. For each new alert (not in DB within last 30 min), sends to **Telegram topic 7135**
3. Logs the alert to the `alerts` table (survives restarts)

**Dedup:** DB-based via `get_last_alert_ts(name, kind)` — no duplicate alerts across container restarts.

---

## Monitoring

### Healthcheck
Docker Compose healthcheck on `aggdash-backend`: `GET /health` every 30s, timeout 10s, retries 3.

### Auto-restart
`aggdash-autoheal` sidecar: checks every 60s, restarts containers with `unhealthy` status.

### Log rotation
- Backend: `json-file`, 10 MB max, 5 files
- Frontend: `json-file`, 5 MB max, 3 files

### Structured logging
```json
{"timestamp": "2026-03-27T06:00:00", "logger": "main", "level": "INFO", "message": "All collectors started"}
```

```bash
docker compose logs -f aggdash-backend
```

---

## Production Deployment (Hetzner)

```bash
cd /home/user3/bananas31-dashboard
git pull origin master
docker compose up -d --build
docker compose logs --tail=20 aggdash-backend
```

---

## Changelog

| Module | PR | What |
|---|---|---|
| M30: Pattern alerts | #90 | `/api/patterns` logs to DB; Telegram alerts for BASIS_SQUEEZE |
| M29: Alert history | #88 | `alerts` table + `/api/alerts/history` + DB-based Telegram dedup |
| M28: Pattern calibration | #86 | Thresholds: OI 5%→1.5%, DEX 1%→0.3%, BASIS 0.3%→0.1% |
| M27: Header stats | #83+#84 | VOL-24H + OI/24H change % in top bar |
| M26: Basis MA7D | #80+#81 | 7-day rolling MA line on basis chart (SPEC §5) |
| M25: Liquidations chart | #78 | Liq histogram + Telegram alerts + calibrated signal thresholds |
| M24: Funding chart | #76 | `/api/analytics/funding/series` + time series chart panel |
| M23: 24h price change | #74 | `/api/price-change` + change % under each price in header |
| M22: DEX TVL + conn-dot | #72 | PancakeSwap V3 TVL in header, WebSocket status indicator |
| M21: WebSocket prices | #70 | `/ws/prices` live broadcast, <100ms latency |
| M19: Resampling perf | #66 | 1Y query: 17s → 1.6s (10x, window functions) |
| M18: OHLCV resampling | #64 | 1m/5m/15m/30m/1h/4h/1d intervals, 1M/3M/1Y buttons |
| M17: Historical backfill | #62 | 1,075,983 bars, 1 year Binance history |
| M16: Auto-zoom fix | #60 | `_suppressSync` prevents periodic setData from resetting zoom |

---

## Data Sources

- **Binance** — WebSocket streams: aggTrade, forceOrder (liquidations)
- **Bybit** — WebSocket streams: publicTrade, liquidation
- **BSC / PancakeSwap V3** — NodeReal RPC: slot0 reads, liquidity snapshots every 30s
- **OI + Funding** — REST pollers: Binance/Bybit every 30s/60s

---

## License

Internal project — not for public distribution.

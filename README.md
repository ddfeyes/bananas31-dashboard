# bananas31-dashboard

Real-time multi-exchange CEX+DEX trading dashboard for the **BANANAS31** token (BSC).

Tracks Binance/Bybit spot & perp prices, open interest, funding rates, liquidations, and PancakeSwap V3 DEX data — all in one live view.

---

## Architecture

```
aggdash-frontend (nginx :8769)
        |  HTTP proxy /api/* -> backend
aggdash-backend (FastAPI :8768)
        |  WebSocket collectors
Binance WS / Bybit WS / BSC RPC (NodeReal)
        |  SQLite (aggdash-data volume)
aggdash-autoheal
        |  Monitors healthcheck -> auto-restarts unhealthy containers
```

**Stack:** Python 3.12 · FastAPI · uvicorn · aiohttp · SQLite · nginx:alpine · Docker Compose

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

All variables are optional — defaults target BANANAS31 on BSC mainnet.

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

Create a `.env` file in the repo root to override defaults.

---

## API Endpoints

### Health & Status

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe — `{"status": "ok"}` |
| GET | `/api/status` | Exchange + DB status |

### Price Data

| Method | Path | Description |
|---|---|---|
| GET | `/api/prices` | Latest price per exchange |
| GET | `/api/aggregated-prices` | Volume-weighted aggregated spot/perp |
| GET | `/api/ticks` | Recent raw tick data |

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

### Analytics

| Method | Path | Description |
|---|---|---|
| GET | `/api/analytics/snapshot` | Full analytics snapshot |
| GET | `/api/analytics/cvd` | Current CVD value |
| GET | `/api/analytics/cvd/series` | CVD time series |
| GET | `/api/analytics/basis` | Current basis per exchange |
| GET | `/api/analytics/basis/series` | Basis time series |
| GET | `/api/analytics/dex-cex-spread` | DEX/CEX spread |
| GET | `/api/analytics/dex-cex-spread/series` | Spread time series |
| GET | `/api/analytics/oi-delta` | OI delta |
| GET | `/api/analytics/oi-delta/series` | OI delta time series |
| GET | `/api/analytics/funding` | Aggregated funding analytics |

### Signals

| Method | Path | Description |
|---|---|---|
| GET | `/api/signals` | Active signals: SQUEEZE_RISK, ARBITRAGE_OPPTY, ACCUMULATION |

---

## Monitoring

### Healthcheck
Docker Compose built-in healthcheck on `aggdash-backend`:
- Probes `GET /health` every **30 seconds**
- Timeout: 10s, retries: 3, start period: 30s

### Auto-restart on failure
`aggdash-autoheal` sidecar monitors all containers:
- Checks every **60 seconds**
- Auto-restarts containers with `unhealthy` status

### Log rotation
`json-file` Docker logging driver with rotation:
- Backend: 10 MB max, 5 files retained
- Frontend: 5 MB max, 3 files retained

### Structured Logging
Backend emits JSON-formatted logs to stdout:
```json
{"timestamp": "2026-03-25T22:00:00", "logger": "main", "level": "INFO", "message": "Starting up aggdash backend..."}
```

View live logs:
```bash
docker compose logs -f aggdash-backend
```

---

## Production Deployment (Hetzner)

Live at: **https://bananas31-dashboard.111miniapp.com** (HTTP Basic Auth required)

```bash
cd /home/user3/bananas31-dashboard
git pull origin master
docker compose build aggdash-backend
docker compose up -d
```

---

## Data Sources

- **Binance** — WebSocket streams: trades, bookTicker, markPriceUpdate
- **Bybit** — WebSocket streams: publicTrade, tickers, klines
- **BSC / PancakeSwap V3** — NodeReal RPC: slot0 reads, liquidity snapshots every 30s

---

## License

Internal project — not for public distribution.

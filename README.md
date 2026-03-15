


## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Docker Compose                                                  │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐           │
│  │  backend (FastAPI :8765)                         │           │
│  │                                                  │           │
│  │  collectors.py ──────── WebSocket to Binance     │           │
│  │                    └─── WebSocket to Bybit       │           │
│  │  pollers.py ─────────── REST poll OI + Funding   │           │
│  │  storage.py ─────────── SQLite WAL (7d retention)│           │
│  │  metrics.py ─────────── CVD, Vol Profile, Phase  │           │
│  │  api.py ─────────────── REST + WebSocket API     │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐           │
│  │  frontend (nginx :8766)                          │           │
│  │  index.html ─ Chart.js + native WebSocket        │           │
│  └──────────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

## Features

### Real-time Data (via WebSocket)
- **Price** — live mid-price from orderbook
- **Market Depth Chart** — cumulative bid/ask depth curve, updates at 1s
- **Orderbook** — top 10 bid/ask levels, live via WS
- **Phase Classifier v2** — multi-window (1/5/15min), confidence smoothing

### Charts (5s polling)
- **CVD** — Cumulative Volume Delta (1h)
- **Open Interest History** — Binance + Bybit
- **Funding Rate** — with annotation (longs/shorts pay signal)
- **Volume Profile** — POC, VAH, VAL, horizontal histogram
- **Liquidations** — recent list + per-minute bar chart

### Alerts Card
- **Liquidation Cascade** — >$50k liquidated in 60s = 🚨
- **OI Spike** — >3% OI change in 5min = alert
- **Delta Divergence** — price up + CVD down (bearish) or vice versa

### Utilities
- **Symbol Tabs** — switch between tracked symbols in-header
- **CSV Export** — download any metric: `/api/export/{trades|oi|funding|liquidations|cvd}`

## API Endpoints

```
GET  /api/symbols                          — list tracked symbols
GET  /api/metrics/summary?symbol=X        — full summary snapshot
WS   /api/ws/{symbol}                     — live 1s push (summary + depth + orderbook)
GET  /api/orderbook/latest?symbol=X       — latest orderbook
GET  /api/trades/recent?symbol=X          — recent trades
GET  /api/oi/history?symbol=X             — OI history
GET  /api/funding/history?symbol=X        — funding rate history
GET  /api/liquidations/recent?symbol=X    — recent liquidations
GET  /api/cvd/history?window=3600&symbol=X
GET  /api/volume-profile?window=3600&bins=50&symbol=X
GET  /api/market-depth?symbol=X           — cumulative depth curve
GET  /api/delta-divergence?window=300&symbol=X
GET  /api/large-trades?window=300&min_usd=10000&symbol=X
GET  /api/oi-spike?window=300&threshold=3&symbol=X
GET  /api/liq-cascade?window=60&threshold_usd=50000&symbol=X
GET  /api/export/{metric}?symbol=X&window=3600  — CSV download
```

## Config

Symbols are configured via `.env`:
```env
SYMBOLS=BANANAS31USDT,COSUSDT,DEXEUSDT,LYNUSDT
```

Or override in `docker-compose.yml` under `environment`.

## Run

```bash
# Start
docker compose up -d --build

# Logs
docker logs bananas31-backend -f

# Stop
docker compose down
```

Frontend: http://localhost:8766  
Backend API: http://localhost:8765

## Storage

SQLite at `/app/data/bananas31.db` (Docker volume: `bananas31-data`)
- WAL mode, NORMAL sync
- 7-day retention (hourly cleanup)
- Orderbook: 1-hour retention (high frequency)
- Indexes on `(symbol, ts)` for fast queries

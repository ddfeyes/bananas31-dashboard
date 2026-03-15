# BANANAS31/USDT Dashboard

Production-grade crypto dashboard for BANANAS31_USDT perpetual futures.

## Features
- **Real-time data** via WebSockets (Binance + Bybit)
  - Order book depth (20 levels, 100ms updates)
  - Aggregated trades
  - Force orders (liquidations)
- **REST pollers** (every 1s): Open Interest + Funding Rate
- **Computed metrics**: CVD, Volume Imbalance, OI Momentum
- **Phase Classifier**: Accumulation / Distribution / Markup / Markdown
- **SQLite storage** with WAL mode for concurrent access
- **Single-page frontend** with Chart.js, auto-refreshes every 5s

## Architecture

```
backend/
  main.py         — FastAPI app + lifespan (starts collectors + pollers)
  collectors.py   — WebSocket collectors (Binance + Bybit)
  pollers.py      — REST pollers (OI + funding, every 1s)
  storage.py      — SQLite CRUD via aiosqlite
  metrics.py      — CVD, imbalance, OI momentum, phase classifier
  api.py          — REST endpoints

frontend/
  index.html      — Single-page dashboard (Chart.js, auto-refresh 5s)
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/orderbook/latest` | Latest orderbook snapshot |
| `GET /api/trades/recent` | Recent trades |
| `GET /api/oi/history` | Open interest history |
| `GET /api/funding/history` | Funding rate history |
| `GET /api/liquidations/recent` | Recent liquidations |
| `GET /api/cvd/history` | CVD time series |
| `GET /api/metrics/summary` | Full metrics summary + phase |
| `GET /health` | Health check |

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Set up secrets (keys loaded from ~/.lain-secrets/.env automatically)
cp .env.example .env
# Edit .env with your API keys

# Run
cd backend
python main.py
```

Open [http://localhost:8000](http://localhost:8000)

## Market Phase Classifier

| Phase | Signal |
|-------|--------|
| **Markup** | Price ↑ + OI ↑ + CVD strongly positive |
| **Markdown** | Price ↓ + CVD strongly negative |
| **Accumulation** | Price flat + OI ↑ + CVD slightly positive |
| **Distribution** | Price flat/up + OI ↑ + CVD diverging negative |

## Data Retention
- Orderbook snapshots: 1 hour
- All other data: 7 days
- Cleanup runs every hour

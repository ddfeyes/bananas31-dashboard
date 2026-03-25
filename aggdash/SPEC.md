# SPEC.md — L3-013-aggdash

## Project
Multi-exchange aggregated dashboard for BANANAS31USDT.
Goal: understand behavioral patterns across all venues for predictive analysis.

## Stack
- Backend: FastAPI + asyncio, SQLite (aggregated 1-min OHLCV + ring buffers)
- Frontend: TradingView Lightweight Charts + Chart.js
- Deploy: Docker on Hetzner 94.130.65.86:2203, subdomain aggdash.111miniapp.com
- Repo: github.com/ddfeyes/aggdash (new)

## Data Sources

### CEX
| Exchange | Market | Type |
|---|---|---|
| Binance | BANANAS31USDT | Perp (fstream.binance.com) |
| Binance | BANANAS31USDT | Spot (stream.binance.com) |
| Bybit | BANANAS31USDT | Perp (stream.bybit.com/v5/public/linear) |
| Bybit | BANANAS31USDT | Spot (stream.bybit.com/v5/public/spot) |

### DEX — BSC PancakeSwap V3
- Pool: 0x7f51bbf34156ba802deb0e38b7671dc4fa32041d
- HTTP RPC: https://bsc-mainnet.nodereal.io/v1/4138a0b4c2044d54aca77d92d0bc7947
- WSS RPC: wss://bsc-mainnet.nodereal.io/ws/v1/4138a0b4c2044d54aca77d92d0bc7947
- Decode Swap events, compute price from sqrtPriceX96

## Modules

### Module 1: Backend collectors
- Binance perp WS: aggTrade, forceOrder (liquidations), OI REST poll 30s
- Binance spot WS: aggTrade
- Bybit perp WS: trade, liquidation, OI REST poll 30s
- Bybit spot WS: trade
- BSC WS: subscribe to Swap events on pool address, decode sqrtPriceX96 → price, amount0/amount1 → volume
- Storage: 1-min OHLCV per source in SQLite; in-memory ring buffer last 60min raw ticks
- Aggregated price = volume-weighted avg across all spot sources; same for perp

### Module 2: Core analytics engine
- CVD (cumulative volume delta) per source + aggregated
- Basis = perp_price - spot_price per exchange + aggregated basis
- DEX vs CEX spread = dex_price - cex_spot_avg
- OI aggregated (Binance perp + Bybit perp)
- OI delta (change per minute)
- Funding rate per exchange (REST poll every 60s)
- Liquidation feed (aggregated)
- Multi-exchange CVD split (who's buying where)

### Module 3: Frontend charts
Chart 1 — Price panel (4 lines):
  - Binance spot, Binance perp, Bybit spot, Bybit perp + DEX price
  - Aggregated spot avg (thick line), aggregated perp avg (thick dashed)
Chart 2 — Basis panel: perp - spot per exchange + aggregated
Chart 3 — Volume panel: stacked bars per source (dual scale spot/perp), exchange filter toggles
Chart 4 — OI panel: aggregated OI + OI delta bars
Chart 5 — CVD panel: per-source CVD lines
Chart 6 — DEX spread panel: DEX price vs CEX spot avg
Chart 7 — Liquidations feed + heatmap bars
Chart 8 — Funding rate panel

All charts: timeframe selector (1m/5m/15m/1h), exchange toggles, dark theme

### Module 4: Alerts
- Basis divergence alert (|basis| > threshold)
- OI spike alert (OI delta > X%)
- DEX vs CEX spread alert (|spread| > threshold)
- Liquidation cascade alert (liquidations > X in 1 min)
- WebSocket push to frontend

### Module 5: Docker + deploy
- Dockerfile for backend (Python 3.11)
- Dockerfile for frontend (nginx)
- docker-compose.yml
- nginx vhost for gateway-nginx: aggdash.111miniapp.com → aggdash-frontend:80
- Deploy script: sshpass to Hetzner, docker compose up -d

## Acceptance Criteria
- [ ] All 4 CEX feeds connected and receiving data
- [ ] BSC Swap events decoded, price computable from sqrtPriceX96
- [ ] Aggregated price displayed in realtime
- [ ] Basis chart showing per-exchange + aggregated
- [ ] OI aggregated updating every 30s
- [ ] Funding rates shown
- [ ] Liquidations shown
- [ ] CVD per source shown
- [ ] All charts render in browser
- [ ] Exchange toggles work
- [ ] Deployed at aggdash.111miniapp.com
- [ ] No errors in 10 min of uptime

## Secrets
- BSC RPC credentials: use env vars BSC_HTTP_RPC and BSC_WSS_RPC (values in workspace secrets file)
- Hetzner SSH: use sshpass (password from MEMORY.md user3 jEW6Kqr9sGFA9KOKtrEgu)

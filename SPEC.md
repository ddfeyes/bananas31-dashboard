# SPEC.md — L3-013-bananas31-dashboard MVP

## Project
Multi-exchange, multi-asset CEX+DEX real-time dashboard for BANANAS31 (BSC token).  
Focus: understand spot/perp basis, liquidation risk, volume flow, DEX arbitrage signals.

## Target Exchanges
- **CEX spot:** Binance BANANAS31USDT, Bybit BANANAS31USDT
- **CEX perp:** Binance BANANAS31USDT, Bybit BANANAS31USDT
- **DEX (BSC):** PancakeSwap V3 (0x7f51bbf34156ba802deb0e38b7671dc4fa32041d)

## RPC
- **NodeReal BSC:** `https://bsc-mainnet.nodereal.io/v1/4138a0b4c2044d54aca77d92d0bc7947`
- **WSS:** `wss://bsc-mainnet.nodereal.io/ws/v1/4138a0b4c2044d54aca77d92d0bc7947`

## MVP Feature Set

### 1. Real-Time Price Feeds
- **Line 1:** Binance spot
- **Line 2:** Binance perp
- **Line 3:** Bybit spot
- **Line 4:** Bybit perp
- **Line 5:** DEX BANANAS31/BUSD price from Uniswap subgraph or direct pool reads
- **Aggregated spot:** Volume-weighted average of spot exchanges
- **Aggregated perp:** Volume-weighted average of perp exchanges
- **Basis chart (separate):** Perp price − spot price per exchange + aggregate

### 2. Volume (Dual-Axis)
- **Left:** Spot volume per exchange (stacked bars, color-coded)
- **Right:** Perp volume per exchange
- **Filters:** By exchange, direction (BUY/SELL)
- **Signal:** spot vol >> perp vol = organic demand. perp vol >> spot = speculation/liquidation-driven

### 3. Open Interest (Perps Only)
- **Aggregated OI:** Sum of Binance + Bybit
- **Per-exchange breakdown:** Separate lines or bars
- **OI spike patterns:** OI ↑ without price move = accumulation. OI ↓ + price ↓ = deleveraging.

### 4. TVL/Liquidity (DEX)
- **From PancakeSwap V3:** Current liquidity in pool
- **Price deviation:** (DEX price − CEX avg) / CEX avg
- **Signal:** DEX premium > 1% = arbitrage opportunity

### 5. Killer Feature: Basis Dashboard
- **Real-time basis per exchange:** Binance basis, Bybit basis, aggregate
- **Basis trend:** 7-day MA
- **Funding rate (perps):** 8h funding + 1h funding, per exchange
- **Signal:** basis > 2% + funding positive = longs stacking → squeeze risk

### 6. CVD / Volume Flow (optional for MVP, prioritize if time)
- Cumulative volume delta (buys − sells) for CEX perps
- Helps spot directional exhaustion

---

## MVP Modules (in order)

### Module 1: Foundation (FastAPI + Collectors)
- FastAPI + aiohttp collectors for Binance/Bybit spot + perp
- WebSocket streams (trades, orderbook)
- REST pollers for OI, funding, recent trades
- SQLite schema: `exchanges` (meta), `price_feed` (OHLCV), `trades` (raw), `oi` (open interest), `funding` (funding rates)
- Cleanup: 7-day rolling window, hourly aggregation

### Module 2: DEX Integration (Ethers.py + Uniswap V3)
- Deploy contract interaction (read slot0, liquidity snapshots)
- REST poller every 30s
- Store in `dex_price`, `dex_liquidity` tables
- Fallback to Uniswap subgraph if RPC lags

### Module 3: Frontend (React + TradingView Lightweight Charts)
- 5 price lines (spot/perp by exchange + aggregate)
- Dual-axis volume (left=spot, right=perp)
- OI area chart (aggregated + per-exchange breakdown)
- Basis subplot (separate chart below prices)
- Filter panel: exchanges (checkboxes), timeframe (1m/5m/1h), direction (all/buy/sell)
- Real-time updates via WebSocket

### Module 4: Alerts & Signals (optional for MVP)
- Basis > 2% + positive funding = "SQUEEZE RISK"
- DEX premium > 1% = "ARBITRAGE OPPTY"
- OI spike (30-min delta > 50k) = "ACCUMULATION"
- Post to topic 7135 every 5 min

### Module 5: Deployment + Monitoring
- Docker Compose: nginx, FastAPI, frontend
- Deploy to Hetzner (port 8767 frontend, 8768 backend)
- Nginx config for 111miniapp.com subdomain
- Health check: /api/status returns {exchange_status, dex_status, db_status}

---

## MVP Exclusions
- Historical data import (start fresh from now)
- Advanced charting (Lightweight Charts only)
- Multi-asset (BANANAS31 only)
- Mobile responsive (desktop first)
- User auth / persistence
- Backtesting / simulation

---

## Success Criteria
- All 5 price lines updating in real time
- Volume dual-axis rendering correctly
- OI aggregate + per-exchange visible
- Basis chart working
- Live endpoint stable >30 min
- No data staleness >5 sec

## Database Schema (sketch)

```
exchanges:
  - id, name (binance-spot, binance-perp, bybit-spot, bybit-perp, dex)
  - enabled (bool)

price_feed:
  - exchange_id, timestamp, open, high, low, close, volume
  - indexed on (exchange_id, timestamp)

trades:
  - exchange_id, timestamp, side, price, amount, buyer_maker
  - index on (exchange_id, timestamp) for recent queries

oi:
  - exchange_id, timestamp, open_interest, funding_rate
  - poll every 30s

dex_price:
  - timestamp, price, liquidity, deviation_pct

funding_rates:
  - exchange_id, timestamp, rate_8h, rate_1h
```

---

## Deliverables
1. GitHub repo with full source
2. Running Docker Compose on Hetzner
3. Frontend at bananas31-dashboard.111miniapp.com
4. Admin topic: 7135 (status + alerts)
5. README with architecture, API docs, deployment steps

/**
 * BANANAS31 API client — Lightweight Charts edition
 */

const API_BASE = '';

async function apiGet(path) {
  try {
    const res = await fetch(API_BASE + path);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    window._apiErrors = 0;
    setConnected(true);
    return data;
  } catch (err) {
    window._apiErrors = (window._apiErrors || 0) + 1;
    if (window._apiErrors > 2) setConnected(false);
    console.warn('[api]', path, err.message);
    return null;
  }
}

function setConnected(ok) {
  const dot = document.getElementById('conn-dot');
  const label = document.getElementById('conn-label');
  if (dot) dot.className = 'conn-dot ' + (ok ? 'connected' : 'error');
  if (label) label.textContent = ok ? 'Live' : 'Disconnected';
}

// ── Data fetchers ────────────────────────────────────────────────────

async function fetchOHLCV(exchangeId, minutes) {
  const data = await apiGet(`/api/analytics/ohlcv?exchange_id=${encodeURIComponent(exchangeId)}&minutes=${minutes}`);
  if (!data || !data.bars || !data.bars.length) return [];
  return data.bars
    .sort((a, b) => a.timestamp - b.timestamp)
    .map(b => ({
      time: b.timestamp,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
      value: b.volume,
    }));
}

async function fetchBasisSeries(windowSecs) {
  const data = await apiGet(`/api/analytics/basis/series?window=${windowSecs}`);
  if (!data) return { binance: [], bybit: [], agg: [] };
  const mapPts = arr => (arr || [])
    .sort((a, b) => a.timestamp - b.timestamp)
    .map(p => ({ time: p.timestamp, value: p.basis_pct }));
  return {
    binance: mapPts((data.per_exchange || {}).binance),
    bybit: mapPts((data.per_exchange || {}).bybit),
    agg: mapPts(data.aggregated),
  };
}

async function fetchOISeries(minutes) {
  const data = await apiGet(`/api/oi/series?minutes=${minutes}`);
  if (!data) return { agg: [], binance: [], bybit: [] };
  const mapPts = arr => (arr || [])
    .sort((a, b) => a.timestamp - b.timestamp)
    .map(p => ({ time: p.timestamp, value: p.open_interest }));
  return {
    agg: mapPts(data.aggregated),
    binance: mapPts((data.per_exchange || {})['binance-perp']),
    bybit: mapPts((data.per_exchange || {})['bybit-perp']),
  };
}

async function fetchCVDSeries(windowSecs) {
  // NOTE: endpoint returns {per_source, aggregated, ...} — NOT {cvd_series}
  const data = await apiGet(`/api/analytics/cvd/series?window_secs=${windowSecs}&interval_secs=60`);
  if (!data) return { agg: [], bnPerp: [], bbPerp: [], bnSpot: [] };
  const mapPts = arr => (arr || [])
    .sort((a, b) => a.timestamp - b.timestamp)
    .map(p => ({ time: p.timestamp, value: p.cvd }));
  const ps = data.per_source || {};
  return {
    agg:    mapPts(data.aggregated),
    bnPerp: mapPts(ps['binance-perp']),
    bbPerp: mapPts(ps['bybit-perp']),
    bnSpot: mapPts(ps['binance-spot']),
  };
}

async function fetchVolumeSeries(windowSecs) {
  const data = await apiGet(`/api/analytics/volume/series?window_secs=${windowSecs}&interval_secs=60`);
  if (!data) return { bnSpot: [], bnPerp: [], bbPerp: [] };
  const mapPts = (arr, colorFn) => (arr || [])
    .sort((a, b) => a.timestamp - b.timestamp)
    .map(p => ({ time: p.timestamp, value: p.volume, color: colorFn(p.volume) }));
  const pe = data.per_exchange || {};
  return {
    bnSpot: mapPts(pe['binance-spot'] || [],  () => 'rgba(240,185,11,0.5)'),
    bnPerp: mapPts(pe['binance-perp'] || [],  () => 'rgba(255,122,53,0.5)'),
    bbPerp: mapPts(pe['bybit-perp']   || [],  () => 'rgba(157,111,255,0.5)'),
  };
}

async function fetchLiquidations(minutes) {
  // Returns recent liquidations from DB — use limit based on timeframe
  const limit = Math.min(minutes * 2, 500);
  const data = await apiGet(`/api/liquidations?limit=${limit}`);
  if (!data || !data.liquidations) return [];
  return data.liquidations
    .sort((a, b) => a.timestamp - b.timestamp)
    .filter(l => l.timestamp >= Date.now() / 1000 - minutes * 60);
}

async function fetchPrices() {
  return apiGet('/api/prices');
}

async function fetchFunding() {
  return apiGet('/api/funding');
}

async function fetchDexPrice() {
  return apiGet('/api/dex/price');
}

async function fetchOI() {
  return apiGet('/api/oi');
}

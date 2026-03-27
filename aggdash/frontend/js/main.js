/**
 * BANANAS31 main controller — Lightweight Charts edition
 */

let currentMinutes = 1440; // default 1D — show full history on load

// ── Real-time candle state ────────────────────────────────────────────
// Track intra-minute OHLC so .update() merges into current bar correctly.
let _rtBar = null;  // { minuteTs, open, high, low, close }

// ── WebSocket price stream ────────────────────────────────────────────
let _ws = null;
let _wsRetryDelay = 1000;  // ms, doubles on each failure (max 30s)
let _wsActive = false;     // true when WS connected and working

function initWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/ws/prices`;
  try {
    _ws = new WebSocket(url);
  } catch (e) {
    console.warn('WS: failed to create', e);
    return;
  }

  _ws.onopen = () => {
    console.log('WS: connected to', url);
    _wsActive = true;
    _wsRetryDelay = 1000;  // reset backoff
    // Update connection indicator
    const dot = document.getElementById('conn-dot');
    const label = document.getElementById('conn-label');
    if (dot) dot.className = 'conn-dot connected';
    if (label) label.textContent = 'WS Live';
  };

  _ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'prices' && msg.prices) {
        updateRealtimeFromPrices(msg.prices, msg.timestamp);
      }
      // ping: no-op (keepalive from server)
    } catch (e) {
      // ignore parse errors
    }
  };

  _ws.onclose = () => {
    _wsActive = false;
    _ws = null;
    console.log(`WS: closed, reconnecting in ${_wsRetryDelay}ms`);
    // Show polling fallback state — amber dot, not red (we still get data via polling)
    const dot = document.getElementById('conn-dot');
    const label = document.getElementById('conn-label');
    if (dot) dot.className = 'conn-dot polling';
    if (label) label.textContent = 'Polling';
    setTimeout(() => {
      _wsRetryDelay = Math.min(_wsRetryDelay * 2, 30000);
      initWebSocket();
    }, _wsRetryDelay);
  };

  _ws.onerror = (err) => {
    console.warn('WS: error', err);
    // onclose will fire after onerror
  };
}

// ── Formatting helpers ───────────────────────────────────────────────

function fmtPrice(v) {
  if (v == null) return '--';
  return v.toFixed(6);
}

function fmtPct(v) {
  if (v == null) return '--';
  const s = v.toFixed(4) + '%';
  return v >= 0 ? '+' + s : s;
}

function fmtLarge(v) {
  if (v == null) return '--';
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return sign + (abs / 1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return sign + (abs / 1e6).toFixed(2) + 'M';
  if (abs >= 1e3) return sign + (abs / 1e3).toFixed(1) + 'K';
  return sign + abs.toFixed(2);
}

// ── Stats bar update ─────────────────────────────────────────────────

async function updateStatsBar() {
  const [pricesData, fundingData, oiData, dexData] = await Promise.all([
    fetchPrices(), fetchFunding(), fetchOI(), fetchDexPrice(),
  ]);

  if (pricesData && pricesData.prices) {
    const p = pricesData.prices;
    setText('stat-bn-spot', fmtPrice(p['binance-spot']));
    setText('stat-bn-perp', fmtPrice(p['binance-perp']));
    setText('stat-bb-perp', fmtPrice(p['bybit-perp']));
    setText('stat-dex', fmtPrice(p['bsc-pancakeswap']));
  }

  if (fundingData && fundingData.rates) {
    const rates = fundingData.rates;
    const bnRate = rates['binance-perp'];
    const bbRate = rates['bybit-perp'];
    const setFundEl = (id, rate) => {
      const el = document.getElementById(id);
      if (el && rate != null) {
        const v = rate.rate_8h * 100;
        el.textContent = (v >= 0 ? '+' : '') + v.toFixed(4) + '%';
        el.className = 'stat-value ' + (v >= 0 ? 'positive' : 'negative');
      }
    };
    if (bnRate) setFundEl('stat-bn-fund', bnRate);
    if (bbRate) setFundEl('stat-bb-fund', bbRate);
  }

  if (oiData) {
    setText('stat-oi', fmtLarge(oiData.total_oi || oiData.aggregated || 0));
  }

  if (dexData && dexData.deviation_pct != null) {
    const el = document.getElementById('stat-dex-spread');
    if (el) {
      // deviation_pct is already in % (e.g. -0.2 means -0.2%), don't divide by 100
      const v = dexData.deviation_pct;
      const sign = v >= 0 ? '+' : '';
      el.textContent = sign + v.toFixed(4) + '%';
      el.className = 'stat-value ' + (v >= 0 ? 'positive' : 'negative');
    }
  }

  // DEX TVL — liquidity in USD from PancakeSwap V3 pool (SPEC Section 4)
  if (dexData && dexData.liquidity_usd != null) {
    const el = document.getElementById('stat-dex-tvl');
    if (el) {
      el.textContent = '$' + fmtLarge(dexData.liquidity_usd);
    }
  }
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

// ── Load historical data ─────────────────────────────────────────────

async function loadAllData(minutes) {
  _rtBar = null; // reset real-time bar tracker on full reload
  const windowSecs = minutes * 60;

  const [spotBars, perpBars, bbBars, dexBars, basis, oi, cvd, vol] = await Promise.all([
    fetchOHLCV('binance-spot', minutes),
    fetchOHLCV('binance-perp', minutes),
    fetchOHLCV('bybit-perp', minutes),
    fetchOHLCV('bsc-pancakeswap', minutes),
    fetchBasisSeries(windowSecs),
    fetchOISeries(minutes),
    fetchCVDSeries(windowSecs),
    fetchVolumeSeries(windowSecs),
  ]);

  // Price chart: candles from binance-spot, overlays from others
  if (spotBars.length) {
    candleSeries.setData(spotBars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
    volumeSeries.setData(spotBars.map(b => ({
      time: b.time,
      value: b.value,
      color: b.close >= b.open ? 'rgba(0,201,122,0.3)' : 'rgba(255,61,92,0.3)',
    })));
  }

  // Overlay lines: close prices from other exchanges
  if (perpBars.length) bnPerpLine.setData(perpBars.map(b => ({ time: b.time, value: b.close })));
  if (bbBars.length)   bbPerpLine.setData(bbBars.map(b => ({ time: b.time, value: b.close })));
  if (dexBars.length)  dexLine.setData(dexBars.map(b => ({ time: b.time, value: b.close })));

  // Basis chart
  if (basis.binance.length) bnBasisLine.setData(basis.binance);
  if (basis.bybit.length)   bbBasisLine.setData(basis.bybit);
  if (basis.agg.length)     aggBasisLine.setData(basis.agg);

  // OI chart
  if (oi.agg.length)     aggOISeries.setData(oi.agg);
  if (oi.binance.length) bnOISeries.setData(oi.binance);
  if (oi.bybit.length)   bbOISeries.setData(oi.bybit);

  // CVD chart
  if (cvdChart) {
    if (cvd.agg.length)    aggCVDLine.setData(cvd.agg);
    if (cvd.bnPerp.length) bnPerpCVDLine.setData(cvd.bnPerp);
    if (cvd.bbPerp.length) bbPerpCVDLine.setData(cvd.bbPerp);
  }

  // Volume chart
  if (volChart) {
    if (vol.bnSpot.length) bnSpotVolSeries.setData(vol.bnSpot);
    if (vol.bnPerp.length) bnPerpVolSeries.setData(vol.bnPerp);
    if (vol.bbPerp.length) bbPerpVolSeries.setData(vol.bbPerp);
  }

  // Fit content
  priceChart.timeScale().fitContent();
  basisChart.timeScale().fitContent();
  oiChart.timeScale().fitContent();
  if (cvdChart) cvdChart.timeScale().fitContent();
  if (volChart) volChart.timeScale().fitContent();
}

// ── Real-time updates ────────────────────────────────────────────────

function updateRealtimeFromPrices(p, t) {
  if (!p) return;
  if (t == null) t = Date.now() / 1000;

  // Minute-bucket timestamp — LW Charts v4 candles must use aligned time
  // so repeated .update() calls within the same minute merge into one bar.
  const minuteTs = Math.floor(t / 60) * 60;

  // Update stats bar inline
  setText('stat-bn-spot', fmtPrice(p['binance-spot']));
  setText('stat-bn-perp', fmtPrice(p['binance-perp']));
  setText('stat-bb-perp', fmtPrice(p['bybit-perp']));
  setText('stat-dex', fmtPrice(p['bsc-pancakeswap']));

  // Update current minute candle with proper OHLC tracking
  const price = p['binance-spot'];
  if (price != null && candleSeries) {
    if (!_rtBar || _rtBar.minuteTs !== minuteTs) {
      // New minute: open = first price seen this minute
      _rtBar = { minuteTs, open: price, high: price, low: price, close: price };
    } else {
      // Same minute: extend OHLC
      _rtBar.close = price;
      if (price > _rtBar.high) _rtBar.high = price;
      if (price < _rtBar.low)  _rtBar.low  = price;
    }
    candleSeries.update({
      time: minuteTs,
      open: _rtBar.open, high: _rtBar.high,
      low: _rtBar.low,   close: _rtBar.close,
    });
  }

  // Update overlay lines (minute-bucketed time for crosshair alignment)
  if (p['binance-perp'] != null)    bnPerpLine.update({ time: minuteTs, value: p['binance-perp'] });
  if (p['bybit-perp'] != null)      bbPerpLine.update({ time: minuteTs, value: p['bybit-perp'] });
  if (p['bsc-pancakeswap'] != null) dexLine.update({ time: minuteTs, value: p['bsc-pancakeswap'] });
}

async function updateRealtime() {
  // Skip polling if WebSocket is active — WS already handles real-time updates
  if (_wsActive) return;
  const data = await fetchPrices();
  if (!data || !data.prices) return;
  updateRealtimeFromPrices(data.prices, data.timestamp);
}

async function updateBasis() {
  const windowSecs = currentMinutes * 60;
  const basis = await fetchBasisSeries(windowSecs);
  window._suppressSync = true;
  if (basis.binance.length) bnBasisLine.setData(basis.binance);
  if (basis.bybit.length)   bbBasisLine.setData(basis.bybit);
  if (basis.agg.length)     aggBasisLine.setData(basis.agg);
  window._suppressSync = false;
}

async function updateOI() {
  const oi = await fetchOISeries(currentMinutes);
  window._suppressSync = true;
  if (oi.agg.length)     aggOISeries.setData(oi.agg);
  if (oi.binance.length) bnOISeries.setData(oi.binance);
  if (oi.bybit.length)   bbOISeries.setData(oi.bybit);
  window._suppressSync = false;
}

async function updateCVD() {
  if (!cvdChart) return;
  const windowSecs = currentMinutes * 60;
  const cvd = await fetchCVDSeries(windowSecs);
  window._suppressSync = true;
  if (cvd.agg.length)    aggCVDLine.setData(cvd.agg);
  if (cvd.bnPerp.length) bnPerpCVDLine.setData(cvd.bnPerp);
  if (cvd.bbPerp.length) bbPerpCVDLine.setData(cvd.bbPerp);
  window._suppressSync = false;
}

async function updateVolume() {
  if (!volChart) return;
  const windowSecs = currentMinutes * 60;
  const vol = await fetchVolumeSeries(windowSecs);
  window._suppressSync = true;
  if (vol.bnSpot.length) bnSpotVolSeries.setData(vol.bnSpot);
  if (vol.bnPerp.length) bnPerpVolSeries.setData(vol.bnPerp);
  if (vol.bbPerp.length) bbPerpVolSeries.setData(vol.bbPerp);
  window._suppressSync = false;
}

// ── Crosshair Tooltip ────────────────────────────────────────────────

function fmtTs(unix) {
  const d = new Date(unix * 1000);
  return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
}

function initPriceTooltip() {
  const tooltip = document.getElementById('price-tooltip');
  if (!tooltip) return;
  const panel = document.getElementById('panel-price');

  // Build lookup maps from loaded series data
  // We'll rebuild them when data loads; store as module-level
  window._perpByTime   = {};  // time → {bnPerp, bbPerp, dex}

  priceChart.subscribeCrosshairMove(param => {
    if (!param || !param.time || !param.point) {
      tooltip.style.display = 'none';
      return;
    }

    const candle = param.seriesData.get(candleSeries);
    if (!candle) { tooltip.style.display = 'none'; return; }

    const bnPerpVal = param.seriesData.get(bnPerpLine);
    const bbPerpVal = param.seriesData.get(bbPerpLine);
    const dexVal    = param.seriesData.get(dexLine);

    const isUp = candle.close >= candle.open;
    const clr  = isUp ? 'up' : 'dn';

    tooltip.innerHTML = `
      <div class="tt-time">${fmtTs(param.time)}</div>
      <div class="tt-row"><span class="tt-label">O</span><span class="tt-val">${candle.open.toFixed(6)}</span></div>
      <div class="tt-row"><span class="tt-label">H</span><span class="tt-val ${clr}">${candle.high.toFixed(6)}</span></div>
      <div class="tt-row"><span class="tt-label">L</span><span class="tt-val ${clr}">${candle.low.toFixed(6)}</span></div>
      <div class="tt-row"><span class="tt-label">C</span><span class="tt-val ${clr}">${candle.close.toFixed(6)}</span></div>
      ${bnPerpVal ? `<div class="tt-row"><span class="tt-label" style="color:#ff7a35">BN-P</span><span class="tt-val">${bnPerpVal.value.toFixed(6)}</span></div>` : ''}
      ${bbPerpVal ? `<div class="tt-row"><span class="tt-label" style="color:#9d6fff">BB-P</span><span class="tt-val">${bbPerpVal.value.toFixed(6)}</span></div>` : ''}
      ${dexVal    ? `<div class="tt-row"><span class="tt-label" style="color:#00c8f5">DEX</span><span class="tt-val">${dexVal.value.toFixed(6)}</span></div>` : ''}
    `;

    // Position tooltip near cursor, keep within panel
    const panelRect = panel.getBoundingClientRect();
    let left = param.point.x + 15;
    let top  = param.point.y + 15;
    const ttW = 190, ttH = 140;
    if (left + ttW > panelRect.width)  left = param.point.x - ttW - 5;
    if (top  + ttH > panelRect.height) top  = param.point.y - ttH - 5;

    tooltip.style.left    = left + 'px';
    tooltip.style.top     = top  + 'px';
    tooltip.style.display = 'block';
  });
}

// ── Live panel value labels ───────────────────────────────────────────

async function updateLiveLabels() {
  // BASIS live value
  const basisEl = document.getElementById('live-basis');
  if (basisEl) {
    const data = await apiGet('/api/analytics/basis');
    if (data && data.aggregated) {
      const v = data.aggregated.basis_pct;
      if (v != null) {
        basisEl.textContent = (v >= 0 ? '+' : '') + v.toFixed(4) + '%';
        basisEl.style.color = v >= 0 ? '#00c97a' : '#ff3d5c';
      }
    }
  }

  // OI live value
  const oiEl = document.getElementById('live-oi');
  if (oiEl) {
    const data = await apiGet('/api/oi');
    if (data) {
      const total = data.total_oi || data.aggregated || 0;
      oiEl.textContent = fmtLarge(total);
      oiEl.style.color = '#4a8fff';
    }
  }

  // CVD live value
  const cvdEl = document.getElementById('live-cvd');
  if (cvdEl) {
    const data = await apiGet('/api/analytics/cvd?window_secs=3600');
    if (data) {
      const v = data.aggregated_cvd;
      if (v != null) {
        cvdEl.textContent = (v >= 0 ? '+' : '') + fmtLarge(v);
        cvdEl.style.color = v >= 0 ? '#00c97a' : '#ff3d5c';
      }
    }
  }

  // Volume live value (last 60s vol from stats bar data)
  const volEl = document.getElementById('live-vol');
  if (volEl) {
    const data = await apiGet('/api/analytics/volume/series?window_secs=120&interval_secs=60');
    if (data && data.per_exchange) {
      const pe = data.per_exchange;
      const last = (arr) => arr && arr.length ? arr[arr.length - 1].volume : 0;
      const total = last(pe['binance-spot']) + last(pe['binance-perp']) + last(pe['bybit-perp']);
      volEl.textContent = fmtLarge(total) + '/m';
      volEl.style.color = '#f0b90b';
    }
  }
}

// ── Liquidation markers on price chart ──────────────────────────────

const SIGNAL_CLASSES = {
  squeeze_risk:     { cls: 'badge-squeeze',    icon: '🔴', label: 'SQUEEZE RISK' },
  arb_opportunity:  { cls: 'badge-arb',        icon: '🟡', label: 'ARB OPPTY'   },
  oi_accumulation:  { cls: 'badge-accum',      icon: '🔵', label: 'OI ACCUM'    },
  deleveraging:     { cls: 'badge-deleverage', icon: '🟠', label: 'DELEVERAGE'  },
};

const PATTERN_LABELS = {
  OI_ACCUMULATION:    '📈 OI ACCUM',
  LIQUIDATION_CASCADE:'💥 LIQ CASCADE',
  DEX_PREMIUM:        '↔️ DEX PREMIUM',
  BASIS_SQUEEZE:      '⚡ BASIS SQUEEZE',
};

async function updateSignals() {
  const data = await fetchSignals();
  const el = document.getElementById('signals-content');
  if (!el) return;
  if (!data || !data.signals || data.signals.length === 0) {
    el.innerHTML = '<span class="badge-quiet">No active signals</span>';
    return;
  }
  el.innerHTML = data.signals.map(s => {
    const cfg = SIGNAL_CLASSES[s.type] || { cls: 'badge-accum', icon: '⚪', label: s.type };
    const detail = s.value != null ? ` ${s.value > 0 ? '+' : ''}${s.value.toFixed(2)}%` : '';
    return `<span class="alert-badge ${cfg.cls}">${cfg.icon} ${cfg.label}${detail}</span>`;
  }).join(' ');
}

async function updatePatterns() {
  const data = await fetchPatterns();
  const el = document.getElementById('patterns-content');
  if (!el) return;
  if (!data || !data.patterns || data.patterns.length === 0) {
    el.innerHTML = '<span class="badge-quiet">—</span>';
    return;
  }
  el.innerHTML = data.patterns.map(p => {
    const label = PATTERN_LABELS[p.name] || p.name;
    return `<span class="alert-badge badge-pattern">${label}</span>`;
  }).join(' ');
}

async function updateLiquidationMarkers() {
  const liqs = await fetchLiquidations(currentMinutes);
  if (!liqs.length) return;

  const markers = liqs.map(l => ({
    time: l.timestamp,
    position: l.side === 'BUY' ? 'belowBar' : 'aboveBar',
    color: l.side === 'BUY' ? '#ff3d5c' : '#00c97a',
    shape: l.side === 'BUY' ? 'arrowUp' : 'arrowDown',
    text: fmtLarge(l.quantity * l.price) + '$',
  }));

  candleSeries.setMarkers(markers);
}

// ── Timeframe buttons ────────────────────────────────────────────────

function setupTimeframeButtons() {
  document.querySelectorAll('.tf-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentMinutes = parseInt(btn.dataset.minutes, 10);
      loadAllData(currentMinutes);
    });
  });
}

// ── Bootstrap ────────────────────────────────────────────────────────

function boot() {
  // Measure combined topbar + alert-bar height so charts-container fills remaining viewport
  const measureHeaderHeight = () => {
    const topBar = document.querySelector('.top-bar');
    const alertBar = document.getElementById('alert-bar');
    const h = (topBar ? topBar.getBoundingClientRect().height : 0)
            + (alertBar ? alertBar.getBoundingClientRect().height : 0);
    document.documentElement.style.setProperty('--topbar-h', h + 'px');
  };
  measureHeaderHeight();
  const ro = new ResizeObserver(measureHeaderHeight);
  const topBar = document.querySelector('.top-bar');
  const alertBar = document.getElementById('alert-bar');
  if (topBar) ro.observe(topBar);
  if (alertBar) ro.observe(alertBar);

  initAllCharts();
  setupTimeframeButtons();

  // Tooltip (must be after initAllCharts)
  initPriceTooltip();

  // Initial load
  loadAllData(currentMinutes);
  updateStatsBar();
  updateLiquidationMarkers();
  updateSignals();
  updatePatterns();
  updateLiveLabels();

  // WebSocket for real-time price streaming (falls back to polling if WS unavailable)
  initWebSocket();

  // Polling — updateRealtime is no-op when WS is active
  setInterval(updateRealtime, 2000);
  setInterval(updateBasis, 5000);
  setInterval(updateOI, 5000);
  setInterval(updateCVD, 10000);
  setInterval(updateVolume, 10000);
  setInterval(updateStatsBar, 5000);
  setInterval(updateLiquidationMarkers, 30000);
  setInterval(updateSignals, 10000);
  setInterval(updatePatterns, 30000);
  setInterval(updateLiveLabels, 5000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

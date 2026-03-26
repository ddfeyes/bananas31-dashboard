/**
 * BANANAS31 main controller — Lightweight Charts edition
 */

let currentMinutes = 60; // default 1H

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
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

// ── Load historical data ─────────────────────────────────────────────

async function loadAllData(minutes) {
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

async function updateRealtime() {
  const data = await fetchPrices();
  if (!data || !data.prices) return;
  const p = data.prices;
  const t = data.timestamp;

  // Update stats bar inline
  setText('stat-bn-spot', fmtPrice(p['binance-spot']));
  setText('stat-bn-perp', fmtPrice(p['binance-perp']));
  setText('stat-bb-perp', fmtPrice(p['bybit-perp']));
  setText('stat-dex', fmtPrice(p['bsc-pancakeswap']));

  // Update last candle (binance-spot)
  if (p['binance-spot'] != null) {
    candleSeries.update({ time: t, open: p['binance-spot'], high: p['binance-spot'], low: p['binance-spot'], close: p['binance-spot'] });
  }

  // Update overlay lines
  if (p['binance-perp'] != null) bnPerpLine.update({ time: t, value: p['binance-perp'] });
  if (p['bybit-perp'] != null)   bbPerpLine.update({ time: t, value: p['bybit-perp'] });
  if (p['bsc-pancakeswap'] != null) dexLine.update({ time: t, value: p['bsc-pancakeswap'] });
}

async function updateBasis() {
  const windowSecs = currentMinutes * 60;
  const basis = await fetchBasisSeries(windowSecs);
  if (basis.binance.length) bnBasisLine.setData(basis.binance);
  if (basis.bybit.length)   bbBasisLine.setData(basis.bybit);
  if (basis.agg.length)     aggBasisLine.setData(basis.agg);
}

async function updateOI() {
  const oi = await fetchOISeries(currentMinutes);
  if (oi.agg.length)     aggOISeries.setData(oi.agg);
  if (oi.binance.length) bnOISeries.setData(oi.binance);
  if (oi.bybit.length)   bbOISeries.setData(oi.bybit);
}

async function updateCVD() {
  if (!cvdChart) return;
  const windowSecs = currentMinutes * 60;
  const cvd = await fetchCVDSeries(windowSecs);
  if (cvd.agg.length)    aggCVDLine.setData(cvd.agg);
  if (cvd.bnPerp.length) bnPerpCVDLine.setData(cvd.bnPerp);
  if (cvd.bbPerp.length) bbPerpCVDLine.setData(cvd.bbPerp);
}

async function updateVolume() {
  if (!volChart) return;
  const windowSecs = currentMinutes * 60;
  const vol = await fetchVolumeSeries(windowSecs);
  if (vol.bnSpot.length) bnSpotVolSeries.setData(vol.bnSpot);
  if (vol.bnPerp.length) bnPerpVolSeries.setData(vol.bnPerp);
  if (vol.bbPerp.length) bbPerpVolSeries.setData(vol.bbPerp);
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

  // Initial load
  loadAllData(currentMinutes);
  updateStatsBar();
  updateLiquidationMarkers();
  updateSignals();
  updatePatterns();

  // Polling
  setInterval(updateRealtime, 2000);
  setInterval(updateBasis, 5000);
  setInterval(updateOI, 5000);
  setInterval(updateCVD, 10000);
  setInterval(updateVolume, 10000);
  setInterval(updateStatsBar, 5000);
  setInterval(updateLiquidationMarkers, 30000);
  setInterval(updateSignals, 10000);
  setInterval(updatePatterns, 30000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

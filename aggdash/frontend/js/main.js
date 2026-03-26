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

  if (fundingData) {
    const el = document.getElementById('stat-funding');
    const avg = fundingData.average_rate;
    if (el && avg != null) {
      el.textContent = (avg * 100).toFixed(4) + '%';
      el.className = 'stat-value ' + (avg >= 0 ? 'positive' : 'negative');
    }
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
  initAllCharts();
  setupTimeframeButtons();

  // Initial load
  loadAllData(currentMinutes);
  updateStatsBar();
  updateLiquidationMarkers();

  // Polling
  setInterval(updateRealtime, 2000);
  setInterval(updateBasis, 5000);
  setInterval(updateOI, 5000);
  setInterval(updateCVD, 10000);
  setInterval(updateVolume, 10000);
  setInterval(updateStatsBar, 5000);
  setInterval(updateLiquidationMarkers, 30000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

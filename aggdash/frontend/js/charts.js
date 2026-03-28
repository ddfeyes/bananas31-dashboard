/**
 * BANANAS31 charts — TradingView Lightweight Charts v4
 */

const CHART_THEME = {
  layout: { background: { color: '#070a10' }, textColor: '#dde4f0', fontFamily: "'JetBrains Mono', monospace", fontSize: 10 },
  grid: { vertLines: { color: '#1c2438' }, horzLines: { color: '#1c2438' } },
  crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  rightPriceScale: { borderColor: '#253047' },
  timeScale: {
    borderColor: '#253047',
    timeVisible: true,
    secondsVisible: false,
    rightOffset: 10,
    barSpacing: 6,
    fixRightEdge: false,
    fixLeftEdge: false,
    lockVisibleTimeRangeOnResize: true,
  },
  handleScroll: {
    mouseWheel: true,
    pressedMouseMove: true,
    horzTouchDrag: true,
    vertTouchDrag: false,
  },
  handleScale: {
    mouseWheel: true,
    pinch: true,
    axisPressedMouseMove: { time: true, price: true },
  },
};

const PRICE_FMT = { type: 'price', precision: 6, minMove: 0.000001 };

// ── Price + Volume Panel ─────────────────────────────────────────────

let priceChart, candleSeries, volumeSeries, bnPerpLine, bbPerpLine, dexLine;

function initPriceChart() {
  const container = document.getElementById('panel-price');
  priceChart = LightweightCharts.createChart(container, {
    ...CHART_THEME,
    autoSize: true,
  });

  candleSeries = priceChart.addCandlestickSeries({
    upColor: '#00c97a', downColor: '#ff3d5c',
    borderUpColor: '#00c97a', borderDownColor: '#ff3d5c',
    wickUpColor: '#00c97a', wickDownColor: '#ff3d5c',
    priceFormat: PRICE_FMT,
  });

  volumeSeries = priceChart.addHistogramSeries({
    color: '#4a8fff',
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  });
  priceChart.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.8, bottom: 0 },
    drawTicks: false,
  });

  bnPerpLine = priceChart.addLineSeries({
    color: '#ff7a35', lineWidth: 1, priceFormat: PRICE_FMT,
    lastValueVisible: false, priceLineVisible: false,
  });

  bbPerpLine = priceChart.addLineSeries({
    color: '#9d6fff', lineWidth: 1, priceFormat: PRICE_FMT,
    lastValueVisible: false, priceLineVisible: false,
  });

  dexLine = priceChart.addLineSeries({
    color: '#00c8f5', lineWidth: 1, priceFormat: PRICE_FMT,
    lastValueVisible: false, priceLineVisible: false,
  });
}

// ── Basis Panel ──────────────────────────────────────────────────────

let basisChart, bnBasisLine, bbBasisLine, aggBasisLine, ma7dBasisLine;

function initBasisChart() {
  const container = document.getElementById('panel-basis');
  basisChart = LightweightCharts.createChart(container, {
    ...CHART_THEME,
    autoSize: true,
  });

  const BASIS_FMT = { type: 'price', precision: 4, minMove: 0.0001 };

  bnBasisLine = basisChart.addLineSeries({
    color: '#f0b90b', lineWidth: 1,
    lastValueVisible: false, priceLineVisible: false,
    priceFormat: BASIS_FMT,
  });

  bbBasisLine = basisChart.addLineSeries({
    color: '#9d6fff', lineWidth: 1,
    lastValueVisible: false, priceLineVisible: false,
    priceFormat: BASIS_FMT,
  });

  aggBasisLine = basisChart.addLineSeries({
    color: '#00c8f5', lineWidth: 2,
    lastValueVisible: true, priceLineVisible: false,
    priceFormat: BASIS_FMT,
  });

  // 7-day MA line — dashed white/gray (SPEC §5)
  ma7dBasisLine = basisChart.addLineSeries({
    color: 'rgba(200,210,230,0.7)',
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    lastValueVisible: true,
    priceLineVisible: false,
    priceFormat: BASIS_FMT,
    title: 'MA7D',
  });
}

// ── OI Panel ─────────────────────────────────────────────────────────

let oiChart, aggOISeries, bnOISeries, bbOISeries;

function initOIChart() {
  const container = document.getElementById('panel-oi');
  oiChart = LightweightCharts.createChart(container, {
    ...CHART_THEME,
    autoSize: true,
  });

  aggOISeries = oiChart.addAreaSeries({
    topColor: 'rgba(74,143,255,0.3)', bottomColor: 'rgba(74,143,255,0.0)',
    lineColor: '#4a8fff', lineWidth: 2,
    lastValueVisible: true, priceLineVisible: false,
  });

  bnOISeries = oiChart.addLineSeries({
    color: '#f0b90b', lineWidth: 1,
    lastValueVisible: false, priceLineVisible: false,
  });

  bbOISeries = oiChart.addLineSeries({
    color: '#9d6fff', lineWidth: 1,
    lastValueVisible: false, priceLineVisible: false,
  });
}

// ── CVD Panel ─────────────────────────────────────────────────────────

let cvdChart, aggCVDLine, bnPerpCVDLine, bbPerpCVDLine;

function initCVDChart() {
  const container = document.getElementById('panel-cvd');
  if (!container) return;
  cvdChart = LightweightCharts.createChart(container, {
    ...CHART_THEME,
    autoSize: true,
  });

  const VOL_FMT = { type: 'volume', precision: 0, minMove: 1 };

  // Aggregated CVD as filled area
  aggCVDLine = cvdChart.addAreaSeries({
    topColor: 'rgba(0,201,122,0.25)', bottomColor: 'rgba(255,61,92,0.25)',
    lineColor: '#00c97a', lineWidth: 2,
    lastValueVisible: true, priceLineVisible: false,
    priceFormat: VOL_FMT,
  });

  bnPerpCVDLine = cvdChart.addLineSeries({
    color: '#f0b90b', lineWidth: 1,
    lastValueVisible: false, priceLineVisible: false,
    priceFormat: VOL_FMT,
  });

  bbPerpCVDLine = cvdChart.addLineSeries({
    color: '#9d6fff', lineWidth: 1,
    lastValueVisible: false, priceLineVisible: false,
    priceFormat: VOL_FMT,
  });
}

// ── Volume Panel ─────────────────────────────────────────────────────

let volChart, bnSpotVolSeries, bnPerpVolSeries, bbPerpVolSeries;

function initVolumeChart() {
  const container = document.getElementById('panel-volume');
  if (!container) return;
  volChart = LightweightCharts.createChart(container, {
    ...CHART_THEME,
    autoSize: true,
  });

  bnSpotVolSeries = volChart.addHistogramSeries({
    color: 'rgba(240,185,11,0.6)',
    priceFormat: { type: 'volume' },
    priceScaleId: 'left',
    lastValueVisible: false,
  });
  volChart.priceScale('left').applyOptions({
    scaleMargins: { top: 0.1, bottom: 0 },
    drawTicks: false,
  });

  bnPerpVolSeries = volChart.addHistogramSeries({
    color: 'rgba(255,122,53,0.6)',
    priceFormat: { type: 'volume' },
    priceScaleId: 'right',
    lastValueVisible: false,
  });

  bbPerpVolSeries = volChart.addHistogramSeries({
    color: 'rgba(157,111,255,0.6)',
    priceFormat: { type: 'volume' },
    priceScaleId: 'right',
    lastValueVisible: false,
  });
  volChart.priceScale('right').applyOptions({
    scaleMargins: { top: 0.1, bottom: 0 },
    drawTicks: false,
  });
}

// ── Funding Rate Chart ───────────────────────────────────────────────

let fundingChart, bnFundingSeries, bbFundingSeries, bn1hFundingSeries, bb1hFundingSeries;

function initFundingChart() {
  const container = document.getElementById('panel-funding');
  if (!container) return;
  fundingChart = LightweightCharts.createChart(container, {
    ...CHART_THEME,
    autoSize: true,
  });

  bnFundingSeries = fundingChart.addLineSeries({
    color: '#f0b90b',
    lineWidth: 1,
    priceFormat: { type: 'custom', formatter: v => (v * 100).toFixed(5) + '%' },
    lastValueVisible: true,
    priceLineVisible: false,
    title: 'BN 8H',
  });

  bbFundingSeries = fundingChart.addLineSeries({
    color: '#9d6fff',
    lineWidth: 1,
    priceFormat: { type: 'custom', formatter: v => (v * 100).toFixed(5) + '%' },
    lastValueVisible: true,
    priceLineVisible: false,
    title: 'BB 8H',
  });

  // 1h funding rate series (dashed lines)
  bn1hFundingSeries = fundingChart.addLineSeries({
    color: '#f0b90b',
    lineWidth: 1,
    lineStyle: 2, // dashed
    priceFormat: { type: 'custom', formatter: v => (v * 100).toFixed(5) + '%' },
    lastValueVisible: false,
    priceLineVisible: false,
    title: 'BN 1H',
  });

  bb1hFundingSeries = fundingChart.addLineSeries({
    color: '#9d6fff',
    lineWidth: 1,
    lineStyle: 2, // dashed
    priceFormat: { type: 'custom', formatter: v => (v * 100).toFixed(5) + '%' },
    lastValueVisible: false,
    priceLineVisible: false,
    title: 'BB 1H',
  });
}

// ── Liquidations Panel ────────────────────────────────────────────────

let liqChart, liqSellSeries, liqBuySeries;

function initLiquidationsChart() {
  const container = document.getElementById('panel-liquidations');
  liqChart = LightweightCharts.createChart(container, {
    ...CHART_THEME,
    autoSize: true,
  });

  // SELL side = long liquidations (price drops → longs get liquidated) → red
  liqSellSeries = liqChart.addHistogramSeries({
    color: '#ff3d5c',
    priceFormat: { type: 'custom', formatter: v => fmtLarge(v) },
    priceScaleId: 'liq',
  });

  // BUY side = short liquidations → green (positive bars)
  liqBuySeries = liqChart.addHistogramSeries({
    color: '#00c97a',
    priceFormat: { type: 'custom', formatter: v => fmtLarge(v) },
    priceScaleId: 'liq',
  });

  liqChart.priceScale('liq').applyOptions({
    scaleMargins: { top: 0.1, bottom: 0.1 },
  });
}

// ── Sync visible range across all charts ─────────────────────────────

// Set window._suppressSync = true before any programmatic setData() that
// should NOT trigger a user-visible zoom change, then false after.
window._suppressSync = false;

function syncTimeScales() {
  // Use TIME-based range sync so all panels show identical timestamps.
  // IMPORTANT: Only priceChart is the SOURCE of sync (it has full data range).
  // fundingChart and liqChart have limited data — they must NEVER shrink priceChart.
  const otherCharts = [basisChart, oiChart, cvdChart, volChart, fundingChart, liqChart].filter(Boolean);
  let _syncing = false;
  // Only priceChart triggers sync — all others just receive
  if (priceChart) {
    priceChart.timeScale().subscribeVisibleTimeRangeChange(range => {
      if (!range || _syncing) return;
      _syncing = true;
      otherCharts.forEach(dst => {
        if (dst !== priceChart) {
          try { dst.timeScale().setVisibleRange(range); } catch (_) {}
        }
      });
      _syncing = false;
    });
  }
}

// ── Init all ─────────────────────────────────────────────────────────

function initAllCharts() {
  initPriceChart();
  initBasisChart();
  initOIChart();
  initCVDChart();
  initVolumeChart();
  initFundingChart();
  initLiquidationsChart();
  syncTimeScales();
}

/**
 * BANANAS31 charts — TradingView Lightweight Charts v4
 */

const CHART_THEME = {
  layout: { background: { color: '#070a10' }, textColor: '#dde4f0', fontFamily: "'JetBrains Mono', monospace", fontSize: 10 },
  grid: { vertLines: { color: '#1c2438' }, horzLines: { color: '#1c2438' } },
  crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  rightPriceScale: { borderColor: '#253047' },
  timeScale: { borderColor: '#253047', timeVisible: true, secondsVisible: false },
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

let basisChart, bnBasisLine, bbBasisLine, aggBasisLine;

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

// ── Sync visible range across all charts ─────────────────────────────

function syncTimeScales() {
  // Use TIME-based range sync (not logical index) so all panels show identical
  // calendar timestamps regardless of how many bars each chart has.
  const charts = [priceChart, basisChart, oiChart, cvdChart, volChart].filter(Boolean);
  let _syncing = false;
  charts.forEach(src => {
    src.timeScale().subscribeVisibleTimeRangeChange(range => {
      if (!range || _syncing) return;
      _syncing = true;
      charts.forEach(dst => {
        if (dst !== src) {
          try { dst.timeScale().setVisibleRange(range); } catch (_) {}
        }
      });
      _syncing = false;
    });
  });
}

// ── Init all ─────────────────────────────────────────────────────────

function initAllCharts() {
  initPriceChart();
  initBasisChart();
  initOIChart();
  initCVDChart();
  initVolumeChart();
  syncTimeScales();
}

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

// ── Sync visible range across charts ─────────────────────────────────

function syncTimeScales() {
  const charts = [priceChart, basisChart, oiChart];
  charts.forEach(src => {
    src.timeScale().subscribeVisibleLogicalRangeChange(range => {
      if (!range) return;
      charts.forEach(dst => {
        if (dst !== src) dst.timeScale().setVisibleLogicalRange(range);
      });
    });
  });
}

// ── Init all ─────────────────────────────────────────────────────────

function initAllCharts() {
  initPriceChart();
  initBasisChart();
  initOIChart();
  syncTimeScales();
}

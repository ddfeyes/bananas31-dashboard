/**
 * BANANAS31 charts v2.0 — TradingView Lightweight Charts v4
 * Updated for redesigned layout (chart-body containers, new theme)
 */

const CHART_THEME = {
  layout: {
    background:  { color: '#090c14' },
    textColor:   '#3d4a60',
    fontFamily:  "'JetBrains Mono', monospace",
    fontSize:    9,
  },
  grid: {
    vertLines:  { color: 'rgba(255,255,255,0.025)' },
    horzLines:  { color: 'rgba(255,255,255,0.04)' },
  },
  crosshair: {
    mode: LightweightCharts.CrosshairMode.Normal,
    vertLine: { color: 'rgba(120,150,200,0.3)', labelBackgroundColor: '#111828' },
    horzLine: { color: 'rgba(120,150,200,0.3)', labelBackgroundColor: '#111828' },
  },
  rightPriceScale: {
    borderColor:   'rgba(255,255,255,0.06)',
    textColor:     '#3d4a60',
    scaleMargins:  { top: 0.08, bottom: 0.08 },
  },
  timeScale: {
    borderColor:              'rgba(255,255,255,0.06)',
    timeVisible:              true,
    secondsVisible:           false,
    rightOffset:              8,
    barSpacing:               6,
    fixRightEdge:             false,
    fixLeftEdge:              false,
    lockVisibleTimeRangeOnResize: true,
    tickMarkFormatter: (time) => {
      const d = new Date(time * 1000);
      return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
    },
  },
  handleScroll: {
    mouseWheel:      true,
    pressedMouseMove: true,
    horzTouchDrag:   true,
    vertTouchDrag:   false,
  },
  handleScale: {
    mouseWheel:  true,
    pinch:       true,
    axisPressedMouseMove: { time: true, price: true },
  },
};

// Sub-panel theme — no time scale (shown only on price panel)
const SUB_CHART_THEME = {
  ...CHART_THEME,
  timeScale: { ...CHART_THEME.timeScale, visible: false },
};

const PRICE_FMT = { type: 'price', precision: 6, minMove: 0.000001 };

// ── Price + Volume Panel ─────────────────────────────────────────────

let priceChart, candleSeries, volumeSeries, bnPerpLine, bbPerpLine, dexLine;

function initPriceChart() {
  const container = document.getElementById('chart-price-body');
  priceChart = LightweightCharts.createChart(container, {
    ...CHART_THEME,
    autoSize: true,
  });

  candleSeries = priceChart.addCandlestickSeries({
    upColor:       '#00c97a',
    downColor:     '#ff3d5c',
    borderUpColor: '#00c97a',
    borderDownColor: '#ff3d5c',
    wickUpColor:   '#00c97a',
    wickDownColor: '#ff3d5c',
    priceFormat:   PRICE_FMT,
  });

  volumeSeries = priceChart.addHistogramSeries({
    color:       'rgba(74,143,255,0.35)',
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  });
  priceChart.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.82, bottom: 0 },
    drawTicks: false,
    visible: false,
  });

  // Binance perp line — lighter gold
  bnPerpLine = priceChart.addLineSeries({
    color: 'rgba(240,208,96,0.7)',
    lineWidth: 1,
    priceFormat: PRICE_FMT,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  // Bybit perp line — light orange
  bbPerpLine = priceChart.addLineSeries({
    color: 'rgba(255,157,107,0.7)',
    lineWidth: 1,
    priceFormat: PRICE_FMT,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  // DEX line — cyan
  dexLine = priceChart.addLineSeries({
    color: 'rgba(0,200,245,0.7)',
    lineWidth: 1,
    priceFormat: PRICE_FMT,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  // Tooltip
  priceChart.subscribeCrosshairMove(param => {
    updatePriceTooltip(param, container);
  });

  // Clear skeleton when chart has data
  priceChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    hideSkeleton('skel-price');
  });
}

function updatePriceTooltip(param, container) {
  const tooltip = document.getElementById('price-tooltip');
  if (!tooltip) return;

  if (!param || !param.time || !param.seriesData || param.seriesData.size === 0) {
    tooltip.style.display = 'none';
    return;
  }

  const candle = param.seriesData.get(candleSeries);
  if (!candle) { tooltip.style.display = 'none'; return; }

  const d = new Date(param.time * 1000);
  const ts = d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });

  const oc = candle.close >= candle.open ? 'up' : 'dn';

  tooltip.innerHTML = `
    <div class="tt-time">${ts}</div>
    <div class="tt-row"><span class="tt-label">O</span><span class="tt-val ${oc}">${candle.open.toFixed(6)}</span></div>
    <div class="tt-row"><span class="tt-label">H</span><span class="tt-val up">${candle.high.toFixed(6)}</span></div>
    <div class="tt-row"><span class="tt-label">L</span><span class="tt-val dn">${candle.low.toFixed(6)}</span></div>
    <div class="tt-row"><span class="tt-label">C</span><span class="tt-val ${oc}">${candle.close.toFixed(6)}</span></div>
  `;

  const rect = container.getBoundingClientRect();
  let x = param.point.x + 12;
  let y = param.point.y - 10;
  const ttW = 170, ttH = 100;
  if (x + ttW > rect.width) x = param.point.x - ttW - 8;
  if (y + ttH > rect.height) y = rect.height - ttH - 10;

  tooltip.style.left = x + 'px';
  tooltip.style.top  = y + 'px';
  tooltip.style.display = 'block';
}

// ── Basis Panel ──────────────────────────────────────────────────────

let basisChart, bnBasisLine, bbBasisLine, aggBasisLine, ma7dBasisLine;

function initBasisChart() {
  const container = document.getElementById('chart-basis-body');
  basisChart = LightweightCharts.createChart(container, {
    ...SUB_CHART_THEME,
    autoSize: true,
  });

  const BASIS_FMT = { type: 'price', precision: 4, minMove: 0.0001 };

  // Zero reference line
  const zeroLine = basisChart.addLineSeries({
    color: 'rgba(255,255,255,0.07)',
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    lastValueVisible: false,
    priceLineVisible: false,
    priceFormat: BASIS_FMT,
    crosshairMarkerVisible: false,
  });
  // Store for later use when we know time range
  window._basisZeroLine = zeroLine;

  bnBasisLine = basisChart.addLineSeries({
    color: 'rgba(240,185,11,0.7)',
    lineWidth: 1,
    lastValueVisible: false,
    priceLineVisible: false,
    priceFormat: BASIS_FMT,
  });

  bbBasisLine = basisChart.addLineSeries({
    color: 'rgba(157,111,255,0.7)',
    lineWidth: 1,
    lastValueVisible: false,
    priceLineVisible: false,
    priceFormat: BASIS_FMT,
  });

  aggBasisLine = basisChart.addLineSeries({
    color: '#4a8fff',
    lineWidth: 2,
    lastValueVisible: true,
    priceLineVisible: false,
    priceFormat: BASIS_FMT,
  });

  ma7dBasisLine = basisChart.addLineSeries({
    color: 'rgba(200,210,230,0.45)',
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    lastValueVisible: true,
    priceLineVisible: false,
    priceFormat: BASIS_FMT,
    title: 'MA7D',
  });

  basisChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    hideSkeleton('skel-basis');
  });
}

// ── OI Panel ─────────────────────────────────────────────────────────

let oiChart, aggOISeries, bnOISeries, bbOISeries;

function initOIChart() {
  const container = document.getElementById('chart-oi-body');
  oiChart = LightweightCharts.createChart(container, {
    ...SUB_CHART_THEME,
    autoSize: true,
  });

  aggOISeries = oiChart.addAreaSeries({
    topColor:    'rgba(74,143,255,0.18)',
    bottomColor: 'rgba(74,143,255,0.0)',
    lineColor:   '#4a8fff',
    lineWidth:   2,
    lastValueVisible: true,
    priceLineVisible: false,
  });

  bnOISeries = oiChart.addLineSeries({
    color: 'rgba(240,185,11,0.7)',
    lineWidth: 1,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  bbOISeries = oiChart.addLineSeries({
    color: 'rgba(157,111,255,0.7)',
    lineWidth: 1,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  oiChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    hideSkeleton('skel-oi');
  });
}

// ── CVD Panel ─────────────────────────────────────────────────────────

let cvdChart, aggCVDLine, bnPerpCVDLine, bbPerpCVDLine;

function initCVDChart() {
  const container = document.getElementById('chart-cvd-body');
  if (!container) return;
  cvdChart = LightweightCharts.createChart(container, {
    ...SUB_CHART_THEME,
    autoSize: true,
  });

  const VOL_FMT = { type: 'volume', precision: 0, minMove: 1 };

  aggCVDLine = cvdChart.addAreaSeries({
    topColor:    'rgba(0,201,122,0.15)',
    bottomColor: 'rgba(255,61,92,0.10)',
    lineColor:   '#00c97a',
    lineWidth:   2,
    lastValueVisible: true,
    priceLineVisible: false,
    priceFormat: VOL_FMT,
  });

  bnPerpCVDLine = cvdChart.addLineSeries({
    color: 'rgba(240,185,11,0.6)',
    lineWidth: 1,
    lastValueVisible: false,
    priceLineVisible: false,
    priceFormat: VOL_FMT,
  });

  bbPerpCVDLine = cvdChart.addLineSeries({
    color: 'rgba(157,111,255,0.6)',
    lineWidth: 1,
    lastValueVisible: false,
    priceLineVisible: false,
    priceFormat: VOL_FMT,
  });

  cvdChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    hideSkeleton('skel-cvd');
  });
}

// ── Volume Panel ─────────────────────────────────────────────────────

let volChart, bnSpotVolSeries, bnPerpVolSeries, bbPerpVolSeries;

function initVolumeChart() {
  const container = document.getElementById('chart-volume-body');
  if (!container) return;
  volChart = LightweightCharts.createChart(container, {
    ...SUB_CHART_THEME,
    autoSize: true,
  });

  bnSpotVolSeries = volChart.addHistogramSeries({
    color:        'rgba(240,185,11,0.55)',
    priceFormat:  { type: 'volume' },
    priceScaleId: 'left',
    lastValueVisible: false,
  });
  volChart.priceScale('left').applyOptions({
    scaleMargins: { top: 0.1, bottom: 0 },
    drawTicks: false,
  });

  bnPerpVolSeries = volChart.addHistogramSeries({
    color:        'rgba(255,122,53,0.55)',
    priceFormat:  { type: 'volume' },
    priceScaleId: 'right',
    lastValueVisible: false,
  });

  bbPerpVolSeries = volChart.addHistogramSeries({
    color:        'rgba(157,111,255,0.55)',
    priceFormat:  { type: 'volume' },
    priceScaleId: 'right',
    lastValueVisible: false,
  });
  volChart.priceScale('right').applyOptions({
    scaleMargins: { top: 0.1, bottom: 0 },
    drawTicks: false,
  });

  volChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    hideSkeleton('skel-vol');
  });
}

// ── Funding Rate Chart ───────────────────────────────────────────────

let fundingChart, bnFundingSeries, bbFundingSeries, bn1hFundingSeries, bb1hFundingSeries;

function initFundingChart() {
  const container = document.getElementById('chart-funding-body');
  if (!container) return;
  fundingChart = LightweightCharts.createChart(container, {
    ...SUB_CHART_THEME,
    autoSize: true,
  });

  const FUND_FMT = { type: 'custom', formatter: v => (v * 100).toFixed(5) + '%' };

  bnFundingSeries = fundingChart.addLineSeries({
    color: '#f0b90b',
    lineWidth: 1,
    priceFormat: FUND_FMT,
    lastValueVisible: true,
    priceLineVisible: false,
    title: 'BN 8H',
  });

  bbFundingSeries = fundingChart.addLineSeries({
    color: '#9d6fff',
    lineWidth: 1,
    priceFormat: FUND_FMT,
    lastValueVisible: true,
    priceLineVisible: false,
    title: 'BB 8H',
  });

  bn1hFundingSeries = fundingChart.addLineSeries({
    color: 'rgba(240,185,11,0.5)',
    lineWidth: 1,
    lineStyle: 2,
    priceFormat: FUND_FMT,
    lastValueVisible: false,
    priceLineVisible: false,
    title: 'BN 1H',
  });

  bb1hFundingSeries = fundingChart.addLineSeries({
    color: 'rgba(157,111,255,0.5)',
    lineWidth: 1,
    lineStyle: 2,
    priceFormat: FUND_FMT,
    lastValueVisible: false,
    priceLineVisible: false,
    title: 'BB 1H',
  });

  fundingChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    hideSkeleton('skel-fund');
  });
}

// ── Liquidations Panel ────────────────────────────────────────────────

let liqChart, liqSellSeries, liqBuySeries;

function initLiquidationsChart() {
  const container = document.getElementById('chart-liq-body');
  if (!container) return;
  liqChart = LightweightCharts.createChart(container, {
    ...SUB_CHART_THEME,
    autoSize: true,
  });

  liqSellSeries = liqChart.addHistogramSeries({
    color: '#ff3d5c',
    priceFormat: { type: 'custom', formatter: v => fmtLarge(v) },
    priceScaleId: 'liq',
  });

  liqBuySeries = liqChart.addHistogramSeries({
    color: '#00c97a',
    priceFormat: { type: 'custom', formatter: v => fmtLarge(v) },
    priceScaleId: 'liq',
  });

  liqChart.priceScale('liq').applyOptions({
    scaleMargins: { top: 0.1, bottom: 0.1 },
  });

  liqChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    hideSkeleton('skel-liq');
  });
}

// ── Skeleton helpers ─────────────────────────────────────────────────

function hideSkeleton(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('visible');
}

function showSkeleton(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('visible');
}

// ── Sync visible range across all charts ─────────────────────────────

window._suppressSync = false;

function syncTimeScales() {
  const otherCharts = [basisChart, oiChart, cvdChart, volChart, fundingChart, liqChart].filter(Boolean);
  let _syncing = false;
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

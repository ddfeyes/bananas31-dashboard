/**
 * aggdash main controller
 * Handles state, polling, chart updates, header stats
 */

// TF_SECS is defined in api.js (shared)
const POLL_FAST_MS = 2000;   // prices, liquidations
const POLL_SLOW_MS = 10000;  // series charts, OI, funding

const SOURCES_ALL = ['binance-spot', 'binance-perp', 'bybit-spot', 'bybit-perp', 'bsc-pancakeswap', 'agg-spot', 'agg-perp'];

class Dashboard {
  constructor() {
    this.timeframe = '5m';
    this.activeFilters = [...SOURCES_ALL];
    this.charts = {};
    this.feed = null;
    this.fundingPanel = null;
    this.lastPrices = {};
    this.ohlcvCache = {};
    this.pollTimers = {};
    this.initialized = false;
  }

  init() {
    this.setupControls();
    this.setupCharts();
    this.startPolling();
    this.initialized = true;

    // Connection status
    window.api.on('connected', connected => {
      const dot = document.getElementById('conn-dot');
      const label = document.getElementById('conn-label');
      if (dot) dot.className = 'connection-dot ' + (connected ? 'connected' : 'error');
      if (label) label.textContent = connected ? 'Live' : 'Disconnected';
    });
  }

  setupControls() {
    // Timeframe buttons
    document.querySelectorAll('[data-tf]').forEach(btn => {
      btn.addEventListener('click', () => {
        this.timeframe = btn.dataset.tf;
        document.querySelectorAll('[data-tf]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.refreshSeries();
      });
    });

    // Exchange toggles
    document.querySelectorAll('[data-source]').forEach(btn => {
      const src = btn.dataset.source;
      btn.classList.add('active');
      btn.addEventListener('click', () => {
        const idx = this.activeFilters.indexOf(src);
        if (idx >= 0) {
          this.activeFilters.splice(idx, 1);
          btn.classList.remove('active');
        } else {
          this.activeFilters.push(src);
          btn.classList.add('active');
        }
        this.refreshAll();
      });
    });
  }

  setupCharts() {
    const canvas = id => document.getElementById(id);

    this.charts.price  = new PriceChart(canvas('chart-price'));
    this.charts.basis  = new BasisChart(canvas('chart-basis'));
    this.charts.volume = new VolumeChart(canvas('chart-volume'));
    this.charts.oi     = new OIChart(canvas('chart-oi'));
    this.charts.cvd    = new CVDChart(canvas('chart-cvd'));
    this.charts.spread = new SpreadChart(canvas('chart-spread'));

    this.feed = new LiqFeed(
      document.getElementById('liq-feed'),
      document.getElementById('liq-heatmap')
    );

    this.fundingPanel = new FundingPanel(document.getElementById('funding-grid'));
  }

  startPolling() {
    // Fast polls: prices + liquidations
    this.fastPoll();
    setInterval(() => this.fastPoll(), POLL_FAST_MS);

    // Slow polls: series data
    this.slowPoll();
    setInterval(() => this.slowPoll(), POLL_SLOW_MS);
  }

  async fastPoll() {
    const [prices, aggPrices, liqs] = await Promise.all([
      window.api.getPrices(),
      window.api.getAggPrices(),
      window.api.getLiquidations(50),
    ]);

    if (prices) this.updateHeaderPrices(prices, aggPrices);
    if (liqs)   this.feed.update(liqs);
  }

  async slowPoll() {
    const windowSecs = TF_SECS[this.timeframe] * 12; // 12x timeframe window
    const intervalSecs = TF_SECS[this.timeframe];

    const [basisSeries, cvdSeries, spreadSeries, oiDeltaSeries, funding, oi] = await Promise.all([
      window.api.getBasisSeries(intervalSecs, windowSecs),
      window.api.getCVDSeries(intervalSecs, windowSecs),
      window.api.getDexCexSpreadSeries(intervalSecs, windowSecs),
      window.api.getOIDeltaSeries(windowSecs),
      window.api.getFundingSummary(),
      window.api.getOI(),
    ]);

    if (basisSeries)  this.charts.basis.update(basisSeries);
    if (cvdSeries)    this.charts.cvd.update(cvdSeries, this.activeFilters);
    if (spreadSeries) this.charts.spread.update(spreadSeries);
    if (oiDeltaSeries) this.charts.oi.update(oiDeltaSeries);
    if (funding)      this.fundingPanel.update(funding);

    // Update header stats from OI / funding
    if (oi)      this.updateOIStats(oi);
    if (funding) this.updateFundingStats(funding);

    // Rebuild price + volume charts from OHLCV data
    await this.refreshOHLCV(intervalSecs, windowSecs);
  }

  async refreshOHLCV(intervalSecs, windowSecs) {
    // We'll query the individual price endpoints + build synthetic OHLCV from ticks
    // For now use the ticks endpoint to build per-source OHLCV
    const srcList = ['binance-spot', 'binance-perp', 'bybit-spot', 'bybit-perp', 'bsc-pancakeswap'];
    const ohlcvBySrc = {};

    for (const src of srcList) {
      const ticks = await window.api.get(`/api/ticks?source=${encodeURIComponent(src)}`);
      if (ticks && ticks.ticks && ticks.ticks.length) {
        ohlcvBySrc[src] = buildOHLCV(ticks.ticks, intervalSecs, windowSecs);
      }
    }

    // Add aggregated lines from basis series
    const basisSeries = await window.api.getBasisSeries(intervalSecs, windowSecs);
    if (basisSeries) {
      // Reconstruct agg-spot + agg-perp time series from basis aggregated
      if (basisSeries.aggregated && basisSeries.aggregated.length) {
        // We don't have raw agg OHLCV but we can use the spot price from prices endpoint
        // So skip these for now — they'll show up as separate datasets when we have DB OHLCV
      }
    }

    this.ohlcvCache = ohlcvBySrc;
    this.charts.price.update(ohlcvBySrc, this.activeFilters);
    this.charts.volume.update(ohlcvBySrc, this.activeFilters);
  }

  refreshSeries() {
    // Re-trigger slow poll with new timeframe
    this.slowPoll();
  }

  refreshAll() {
    // Re-render all charts with current filter
    this.charts.price.update(this.ohlcvCache, this.activeFilters);
    this.charts.volume.update(this.ohlcvCache, this.activeFilters);
  }

  updateHeaderPrices(prices, aggPrices) {
    const p = prices.prices || {};

    // Show aggregated spot price in header
    const aggSpot = aggPrices && aggPrices.spot_price;
    const aggPerp = aggPrices && aggPrices.perp_price;

    const el = id => document.getElementById(id);

    if (el('header-price-val') && aggSpot) {
      el('header-price-val').textContent = fmtPrice(aggSpot);
    }

    // Per-source prices in mini stats
    const statMap = {
      'bn-spot': p['binance-spot'],
      'bn-perp': p['binance-perp'],
      'bb-spot': p['bybit-spot'],
      'bb-perp': p['bybit-perp'],
      'dex':     p['bsc-pancakeswap'],
      'basis':   aggPrices && aggPrices.basis,
    };

    for (const [id, val] of Object.entries(statMap)) {
      const el2 = document.getElementById('stat-' + id);
      if (el2) {
        el2.textContent = (id === 'basis') ? fmtBasis(val) : fmtPrice(val);
        if (id === 'basis' && val !== null) {
          el2.className = 'stat-value ' + (val >= 0 ? 'positive' : 'negative');
        }
      }
    }

    this.lastPrices = p;
  }

  updateOIStats(oi) {
    const agg = oi.aggregated || 0;
    const el = document.getElementById('stat-oi');
    if (el) el.textContent = fmtLarge(agg);
  }

  updateFundingStats(funding) {
    const avg = funding.average_rate;
    const el = document.getElementById('stat-funding');
    if (el) {
      el.textContent = avg !== null ? (avg * 100).toFixed(4) + '%' : '–';
      el.className = 'stat-value ' + (avg >= 0 ? 'positive' : 'negative');
    }
  }
}

// Build OHLCV bars from raw ticks
function buildOHLCV(ticks, intervalSecs, windowSecs) {
  const now = Date.now() / 1000;
  const cutoff = now - windowSecs;
  const filtered = ticks.filter(t => t.timestamp >= cutoff);

  const bars = {};
  for (const t of filtered) {
    const bk = Math.floor(t.timestamp / intervalSecs) * intervalSecs;
    if (!bars[bk]) {
      bars[bk] = { timestamp: bk, open: t.price, high: t.price, low: t.price, close: t.price, volume: 0 };
    } else {
      const b = bars[bk];
      b.high = Math.max(b.high, t.price);
      b.low  = Math.min(b.low, t.price);
      b.close = t.price;
      b.volume += t.volume;
    }
  }

  return Object.values(bars).sort((a, b) => a.timestamp - b.timestamp);
}

// Bootstrap on DOM ready (handle case where DOMContentLoaded already fired)
function _initDashboard() {
  window.dashboard = new Dashboard();
  window.dashboard.init();
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _initDashboard);
} else {
  _initDashboard();
}

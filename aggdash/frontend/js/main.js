/**
 * aggdash main controller
 * Handles state, polling, chart updates, header stats
 */

// TF_SECS is defined in api.js (shared)
const POLL_FAST_MS = 2000;   // prices, liquidations
const POLL_SLOW_MS = 10000;  // series charts, OI, funding

const SOURCES_ALL = ['binance-spot', 'binance-perp', 'bybit-perp', 'bsc-pancakeswap', 'agg-spot', 'agg-perp'];

class Dashboard {
  constructor() {
    this.timeframe = '5m';
    this.chartRangeMinutes = 1440; // default 1D
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

    // Chart range buttons (Bug 9)
    document.querySelectorAll('[data-range]').forEach(btn => {
      btn.addEventListener('click', () => {
        this.chartRangeMinutes = parseInt(btn.dataset.range, 10);
        document.querySelectorAll('[data-range]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.refreshPriceChart();
        this.slowPoll(); // sync series charts (basis/OI/CVD) to new range
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

  updateSignalsBanner(data) {
    const banner = document.getElementById('signals-banner');
    if (!banner) return;
    const sigs = data.signals || [];
    if (sigs.length === 0) {
      banner.classList.add('hidden');
      banner.textContent = '';
      return;
    }
    banner.classList.remove('hidden');
    // Build DOM nodes to avoid innerHTML injection from API content
    banner.textContent = '';
    const label = document.createElement('span');
    label.className = 'signals-banner-label';
    label.textContent = '⚡ Signals';
    banner.appendChild(label);
    for (const s of sigs) {
      const item = document.createElement('span');
      // severity is constrained to info/warning/alert by API schema
      const safeClass = ['info', 'warning', 'alert'].includes(s.severity) ? s.severity : 'info';
      item.className = 'signal-item ' + safeClass;
      const dot = document.createElement('span');
      dot.className = 'signal-dot';
      item.appendChild(dot);
      // name and message are set as textContent (no HTML injection)
      item.appendChild(document.createTextNode(
        String(s.name || '').slice(0, 64) + ': ' + String(s.message || '').slice(0, 128)
      ));
      banner.appendChild(item);
    }
  }

  updatePatternsBar(data) {
    const bar = document.getElementById('patterns-bar');
    if (!bar) return;
    const patterns = data.patterns || [];
    if (patterns.length === 0) {
      bar.classList.add('hidden');
      bar.textContent = '';
      return;
    }
    bar.classList.remove('hidden');
    bar.textContent = '';
    const label = document.createElement('span');
    label.className = 'patterns-bar-label';
    label.textContent = 'Patterns';
    bar.appendChild(label);
    for (const p of patterns) {
      const badge = document.createElement('span');
      const sev = ['high', 'medium', 'low'].includes(p.severity) ? p.severity : 'low';
      badge.className = 'pattern-badge ' + sev;
      badge.textContent = String(p.name || '').slice(0, 32) + (p.description ? ': ' + String(p.description).slice(0, 80) : '');
      bar.appendChild(badge);
    }
  }

  async refreshPriceChart() {
    const minutes = this.chartRangeMinutes;
    const srcList = ['binance-spot', 'binance-perp', 'bybit-perp', 'bsc-pancakeswap'];
    const ohlcvBySrc = {};
    const results = await Promise.all(
      srcList.map(src =>
        window.api.get(`/api/analytics/ohlcv?exchange_id=${encodeURIComponent(src)}&minutes=${minutes}`)
          .then(data => [src, data])
      )
    );
    for (const [src, data] of results) {
      if (data && Array.isArray(data) && data.length) {
        ohlcvBySrc[src] = data;
      } else if (data && data.bars && data.bars.length) {
        ohlcvBySrc[src] = data.bars;
      }
    }
    // Fallback: if OHLCV endpoint doesn't return data, use cached ticks
    if (Object.keys(ohlcvBySrc).length === 0 && Object.keys(this.ohlcvCache).length > 0) {
      this.charts.price.update(this.ohlcvCache, this.activeFilters);
      return;
    }
    this.ohlcvCache = ohlcvBySrc;
    this.charts.price.update(ohlcvBySrc, this.activeFilters);
    this.charts.volume.update(ohlcvBySrc, this.activeFilters);
  }

  async slowPoll() {
    // Use chartRangeMinutes for window so series charts match the price chart range
    const windowSecs = (this.chartRangeMinutes || 1440) * 60;
    const intervalSecs = TF_SECS[this.timeframe];

    const [basisSeries, cvdSeries, spreadSeries, oiDeltaSeries, funding, oi, signals, patterns] = await Promise.all([
      window.api.getBasisSeries(intervalSecs, windowSecs),
      window.api.getCVDSeries(intervalSecs, windowSecs),
      window.api.getDexCexSpreadSeries(intervalSecs, windowSecs),
      window.api.getOIDeltaSeries(windowSecs),
      window.api.getFundingSummary(),
      window.api.getOI(),
      window.api.getSignals(),
      window.api.getPatterns(),
    ]);

    if (basisSeries)  this.charts.basis.update(basisSeries);
    if (cvdSeries)    this.charts.cvd.update(cvdSeries, this.activeFilters);
    if (spreadSeries) this.charts.spread.update(spreadSeries);
    if (oiDeltaSeries) this.charts.oi.update(oiDeltaSeries);
    if (funding)      this.fundingPanel.update(funding);
    if (signals)      this.updateSignalsBanner(signals);
    if (patterns)     this.updatePatternsBar(patterns);

    // Update header stats from OI / funding
    if (oi)      this.updateOIStats(oi);
    if (funding) this.updateFundingStats(funding);

    // Rebuild price + volume charts from OHLCV data
    await this.refreshOHLCV(intervalSecs, windowSecs);
  }

  async refreshOHLCV(intervalSecs, windowSecs) {
    // Use DB OHLCV endpoint with current chart range
    const minutes = this.chartRangeMinutes || Math.ceil(windowSecs / 60);
    const srcList = ['binance-spot', 'binance-perp', 'bybit-perp', 'bsc-pancakeswap'];
    const ohlcvBySrc = {};

    const results = await Promise.all(
      srcList.map(src =>
        window.api.get(`/api/analytics/ohlcv?exchange_id=${encodeURIComponent(src)}&minutes=${minutes}`)
      )
    );
    for (let i = 0; i < srcList.length; i++) {
      const data = results[i];
      if (data && data.bars && data.bars.length) {
        ohlcvBySrc[srcList[i]] = data.bars;
      }
    }

    // Fallback to tick-based OHLCV if DB has no data
    if (Object.keys(ohlcvBySrc).length === 0) {
      for (const src of srcList) {
        const ticks = await window.api.get(`/api/ticks?source=${encodeURIComponent(src)}`);
        if (ticks && ticks.ticks && ticks.ticks.length) {
          ohlcvBySrc[src] = buildOHLCV(ticks.ticks, intervalSecs, windowSecs);
        }
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
    // BB Basis = bybit_perp - binance_spot (Bug 1)
    const bbBasis = (p['bybit-perp'] != null && p['binance-spot'] != null)
      ? p['bybit-perp'] - p['binance-spot'] : null;
    const statMap = {
      'bn-spot': p['binance-spot'],
      'bn-perp': p['binance-perp'],
      'bb-basis': bbBasis,
      'bb-perp': p['bybit-perp'],
      'dex':     p['bsc-pancakeswap'],
      'basis':   aggPrices && aggPrices.basis,
    };

    for (const [id, val] of Object.entries(statMap)) {
      const el2 = document.getElementById('stat-' + id);
      if (el2) {
        const isBasisLike = (id === 'basis' || id === 'bb-basis');
        el2.textContent = isBasisLike ? fmtBasis(val) : fmtPrice(val);
        if (isBasisLike && val !== null) {
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

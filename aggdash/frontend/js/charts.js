/**
 * aggdash chart management — Chart.js powered
 */

const COLORS = {
  'binance-spot':  '#f0b90b',
  'binance-perp':  '#f0d060',
  'bybit-spot':    '#ff6b2b',
  'bybit-perp':    '#ffaa80',
  'bsc-pancakeswap': '#00d4ff',
  'agg-spot':      '#00d084',
  'agg-perp':      '#80e8c0',
  basis_binance:   '#3d87ff',
  basis_bybit:     '#a855f7',
  basis_agg:       '#ffd24d',
  oi_total:        '#3d87ff',
  oi_delta:        '#ff4d6a',
  spread:          '#00d4ff',
};

const LABEL_MAP = {
  'binance-spot':  'BN Spot',
  'binance-perp':  'BN Perp',
  'bybit-spot':    'BB Spot',
  'bybit-perp':    'BB Perp',
  'bsc-pancakeswap': 'DEX',
  'agg-spot':      'Agg Spot',
  'agg-perp':      'Agg Perp',
};

const CHART_DEFAULTS = {
  animation: false,
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: {
      display: true,
      position: 'top',
      align: 'end',
      labels: {
        color: '#8892a4',
        font: { size: 10, family: "'JetBrains Mono', monospace" },
        boxWidth: 10,
        boxHeight: 2,
        padding: 8,
      }
    },
    tooltip: {
      backgroundColor: 'rgba(17,19,24,0.95)',
      borderColor: '#2a3047',
      borderWidth: 1,
      titleColor: '#8892a4',
      bodyColor: '#e8eaf0',
      titleFont: { size: 10, family: "'JetBrains Mono', monospace" },
      bodyFont: { size: 10, family: "'JetBrains Mono', monospace" },
      padding: 8,
    }
  },
  scales: {
    x: {
      type: 'time',
      time: { unit: 'minute', tooltipFormat: 'HH:mm', displayFormats: { minute: 'HH:mm', hour: 'HH:mm' } },
      grid: { color: '#1f2433', drawBorder: false },
      ticks: { color: '#4d566a', font: { size: 9 }, maxRotation: 0, autoSkipPadding: 20 },
    },
    y: {
      position: 'right',
      grid: { color: '#1f2433', drawBorder: false },
      ticks: { color: '#8892a4', font: { size: 9, family: "'JetBrains Mono', monospace" } },
    }
  }
};

function makeChartConfig(type, datasets, yFormat, extraScales) {
  const cfg = JSON.parse(JSON.stringify(CHART_DEFAULTS));
  cfg.type = type || 'line';
  cfg.data = { datasets: [] };
  cfg.options = {
    ...cfg,
    plugins: CHART_DEFAULTS.plugins,
    scales: {
      ...CHART_DEFAULTS.scales,
      ...(extraScales || {}),
    }
  };
  if (yFormat) {
    cfg.options.scales.y = {
      ...CHART_DEFAULTS.scales.y,
      ticks: {
        ...CHART_DEFAULTS.scales.y.ticks,
        callback: yFormat,
      }
    };
  }
  return cfg;
}

// ── Chart: Price Panel ────────────────────────────────────────────────

class PriceChart {
  constructor(canvas) {
    this.chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets: [] },
      options: {
        ...deepMerge({}, CHART_DEFAULTS),
        plugins: {
          ...CHART_DEFAULTS.plugins,
          tooltip: {
            ...CHART_DEFAULTS.plugins.tooltip,
            callbacks: {
              label: ctx => ` ${ctx.dataset.label}: ${fmtPrice(ctx.parsed.y)}`
            }
          }
        },
        scales: {
          x: CHART_DEFAULTS.scales.x,
          y: {
            ...CHART_DEFAULTS.scales.y,
            ticks: {
              ...CHART_DEFAULTS.scales.y.ticks,
              callback: v => fmtPrice(v),
            }
          }
        }
      }
    });
    this.dataBySrc = {};
  }

  update(ohlcvBySource, activeFilters) {
    const sources = ['binance-spot', 'binance-perp', 'bybit-spot', 'bybit-perp', 'bsc-pancakeswap', 'agg-spot', 'agg-perp'];
    const datasets = [];

    for (const src of sources) {
      if (!activeFilters.includes(src)) continue;
      const bars = ohlcvBySource[src];
      if (!bars || !bars.length) continue;
      const isAgg = src.startsWith('agg-');
      const isDex = src === 'bsc-pancakeswap';
      datasets.push({
        label: LABEL_MAP[src] || src,
        data: bars.map(b => ({ x: b.timestamp * 1000, y: b.close })),
        borderColor: COLORS[src],
        backgroundColor: 'transparent',
        borderWidth: isAgg ? 2.5 : 1.5,
        borderDash: src.endsWith('-perp') && isAgg ? [4, 2] : [],
        pointRadius: 0,
        tension: 0.1,
        order: isAgg ? 1 : 2,
      });
    }

    this.chart.data.datasets = datasets;
    this.chart.update('none');
  }
}

// ── Chart: Basis Panel ────────────────────────────────────────────────

class BasisChart {
  constructor(canvas) {
    this.chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets: [] },
      options: {
        ...deepMerge({}, CHART_DEFAULTS),
        scales: {
          x: CHART_DEFAULTS.scales.x,
          y: {
            ...CHART_DEFAULTS.scales.y,
            ticks: { ...CHART_DEFAULTS.scales.y.ticks, callback: v => fmtBasis(v) }
          }
        }
      }
    });
  }

  update(basisSeries) {
    if (!basisSeries) return;
    const datasets = [];

    for (const [exchange, series] of Object.entries(basisSeries.per_exchange || {})) {
      if (!series.length) continue;
      const key = 'basis_' + exchange;
      datasets.push({
        label: exchange.charAt(0).toUpperCase() + exchange.slice(1) + ' Basis',
        data: series.map(p => ({ x: p.timestamp * 1000, y: p.basis })),
        borderColor: COLORS[key] || '#888',
        backgroundColor: 'transparent',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.1,
      });
    }

    if (basisSeries.aggregated && basisSeries.aggregated.length) {
      datasets.push({
        label: 'Agg Basis',
        data: basisSeries.aggregated.map(p => ({ x: p.timestamp * 1000, y: p.basis })),
        borderColor: COLORS.basis_agg,
        backgroundColor: 'transparent',
        borderWidth: 2.5,
        pointRadius: 0,
        tension: 0.1,
        order: 1,
      });
    }

    this.chart.data.datasets = datasets;
    this.chart.update('none');
  }
}

// ── Chart: Volume Panel ───────────────────────────────────────────────

class VolumeChart {
  constructor(canvas) {
    this.chart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: { datasets: [] },
      options: {
        ...deepMerge({}, CHART_DEFAULTS),
        plugins: {
          ...CHART_DEFAULTS.plugins,
          legend: { ...CHART_DEFAULTS.plugins.legend },
        },
        scales: {
          x: { ...CHART_DEFAULTS.scales.x, stacked: false },
          y: {
            ...CHART_DEFAULTS.scales.y,
            stacked: false,
            ticks: { ...CHART_DEFAULTS.scales.y.ticks, callback: v => fmtVolume(v) }
          }
        }
      }
    });
  }

  update(ohlcvBySource, activeFilters) {
    const spotSrcs = ['binance-spot', 'bybit-spot', 'bsc-pancakeswap'];
    const perpSrcs = ['binance-perp', 'bybit-perp'];
    const datasets = [];

    for (const src of [...spotSrcs, ...perpSrcs]) {
      if (!activeFilters.includes(src)) continue;
      const bars = ohlcvBySource[src];
      if (!bars || !bars.length) continue;
      datasets.push({
        label: LABEL_MAP[src] || src,
        data: bars.map(b => ({ x: b.timestamp * 1000, y: b.volume })),
        backgroundColor: hexAlpha(COLORS[src], 0.65),
        borderColor: COLORS[src],
        borderWidth: 0.5,
        barPercentage: 0.7,
        categoryPercentage: 0.8,
      });
    }

    this.chart.data.datasets = datasets;
    this.chart.update('none');
  }
}

// ── Chart: OI Panel ───────────────────────────────────────────────────

class OIChart {
  constructor(canvas) {
    this.chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets: [] },
      options: {
        ...deepMerge({}, CHART_DEFAULTS),
        scales: {
          x: CHART_DEFAULTS.scales.x,
          y: {
            ...CHART_DEFAULTS.scales.y,
            id: 'oi',
            ticks: { ...CHART_DEFAULTS.scales.y.ticks, callback: v => fmtLarge(v) }
          },
          yDelta: {
            position: 'left',
            grid: { display: false },
            ticks: { color: COLORS.oi_delta, font: { size: 9, family: "'JetBrains Mono', monospace" }, callback: v => fmtLarge(v) }
          }
        }
      }
    });
  }

  update(oiSeries) {
    if (!oiSeries) return;
    const datasets = [];
    const agg = oiSeries.aggregated || [];

    if (agg.length) {
      datasets.push({
        label: 'Total OI',
        data: agg.map(p => ({ x: p.timestamp * 1000, y: p.oi || 0 })),
        borderColor: COLORS.oi_total,
        backgroundColor: hexAlpha(COLORS.oi_total, 0.08),
        fill: true,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.2,
        yAxisID: 'y',
        order: 1,
      });

      datasets.push({
        label: 'OI Delta',
        data: agg.map(p => ({ x: p.timestamp * 1000, y: p.delta || 0 })),
        type: 'bar',
        backgroundColor: agg.map(p => (p.delta >= 0 ? hexAlpha(COLORS.oi_total, 0.6) : hexAlpha(COLORS.oi_delta, 0.6))),
        borderWidth: 0,
        yAxisID: 'yDelta',
        order: 2,
      });
    }

    this.chart.data.datasets = datasets;
    this.chart.update('none');
  }
}

// ── Chart: CVD Panel ──────────────────────────────────────────────────

class CVDChart {
  constructor(canvas) {
    this.chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets: [] },
      options: {
        ...deepMerge({}, CHART_DEFAULTS),
        scales: {
          x: CHART_DEFAULTS.scales.x,
          y: {
            ...CHART_DEFAULTS.scales.y,
            ticks: { ...CHART_DEFAULTS.scales.y.ticks, callback: v => fmtLarge(v) }
          }
        }
      }
    });
  }

  update(cvdSeries, activeFilters) {
    if (!cvdSeries) return;
    const datasets = [];
    const perSrc = cvdSeries.per_source || {};

    for (const [src, series] of Object.entries(perSrc)) {
      if (!activeFilters.includes(src)) continue;
      if (!series || !series.length) continue;
      datasets.push({
        label: LABEL_MAP[src] || src,
        data: series.map(p => ({ x: p.timestamp * 1000, y: p.cvd })),
        borderColor: COLORS[src] || '#888',
        backgroundColor: 'transparent',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.1,
      });
    }

    if (cvdSeries.aggregated && cvdSeries.aggregated.length) {
      datasets.push({
        label: 'Agg CVD',
        data: cvdSeries.aggregated.map(p => ({ x: p.timestamp * 1000, y: p.cvd })),
        borderColor: COLORS['agg-spot'],
        backgroundColor: 'transparent',
        borderWidth: 2.5,
        pointRadius: 0,
        tension: 0.1,
        order: 1,
      });
    }

    this.chart.data.datasets = datasets;
    this.chart.update('none');
  }
}

// ── Chart: DEX Spread Panel ───────────────────────────────────────────

class SpreadChart {
  constructor(canvas) {
    this.chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets: [] },
      options: {
        ...deepMerge({}, CHART_DEFAULTS),
        scales: {
          x: CHART_DEFAULTS.scales.x,
          y: {
            ...CHART_DEFAULTS.scales.y,
            ticks: { ...CHART_DEFAULTS.scales.y.ticks, callback: v => fmtBasis(v) }
          }
        }
      }
    });
  }

  update(spreadSeries) {
    if (!spreadSeries || !spreadSeries.length) return;
    const datasets = [
      {
        label: 'DEX Price',
        data: spreadSeries.map(p => ({ x: p.timestamp * 1000, y: p.dex_price })),
        borderColor: COLORS['bsc-pancakeswap'],
        backgroundColor: 'transparent',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.1,
      },
      {
        label: 'CEX Spot Avg',
        data: spreadSeries.map(p => ({ x: p.timestamp * 1000, y: p.cex_spot_avg })),
        borderColor: COLORS['agg-spot'],
        backgroundColor: 'transparent',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.1,
      },
      {
        label: 'Spread',
        data: spreadSeries.map(p => ({ x: p.timestamp * 1000, y: p.spread })),
        borderColor: COLORS.spread,
        backgroundColor: hexAlpha(COLORS.spread, 0.08),
        fill: true,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.1,
        yAxisID: 'ySpread',
        order: 1,
      }
    ];

    this.chart.options.scales.ySpread = {
      position: 'left',
      grid: { display: false },
      ticks: { color: COLORS.spread, font: { size: 9, family: "'JetBrains Mono', monospace" }, callback: v => fmtBasis(v) }
    };

    this.chart.data.datasets = datasets;
    this.chart.update('none');
  }
}

// ── Liquidation Feed ──────────────────────────────────────────────────

class LiqFeed {
  constructor(feedEl, heatmapEl) {
    this.feedEl = feedEl;
    this.heatmapEl = heatmapEl;
    this.seen = new Set();
    this.heatmapData = {};
  }

  update(liqs) {
    if (!liqs || !liqs.liquidations) return;
    const items = liqs.liquidations.slice(0, 50);
    let newCount = 0;

    for (const liq of items.slice(0, 20)) {
      const key = `${liq.timestamp}-${liq.source}-${liq.side}-${liq.price}`;
      if (this.seen.has(key)) continue;
      this.seen.add(key);
      newCount++;

      const div = document.createElement('div');
      div.className = 'liq-item';
      const side = liq.side === 'buy' ? 'LONG' : 'SHORT'; // liquidated longs = buy orders
      div.innerHTML = `
        <span class="liq-side ${liq.side === 'sell' ? 'long' : 'short'}">${side}</span>
        <span class="liq-exchange">${liq.source.replace('-perp','').replace('-spot','')}</span>
        <span class="liq-price">${fmtPrice(liq.price)}</span>
        <span class="liq-qty">${fmtLarge(liq.quantity)}</span>
        <span class="liq-time">${fmtTime(liq.timestamp)}</span>
      `;
      this.feedEl.insertBefore(div, this.feedEl.firstChild);
    }

    // Trim feed
    while (this.feedEl.children.length > 60) {
      this.feedEl.removeChild(this.feedEl.lastChild);
    }

    // Heatmap: aggregate by exchange+side in last 100 events
    const counts = {};
    for (const liq of items) {
      const key = `${liq.source}|${liq.side}`;
      counts[key] = (counts[key] || 0) + 1;
    }
    this.renderHeatmap(counts, items.length);
  }

  renderHeatmap(counts, total) {
    if (!total) return;
    const sources = ['binance-perp', 'bybit-perp'];
    let html = '<div class="liq-heatmap-title">Liq Distribution</div>';
    for (const src of sources) {
      const longs = counts[`${src}|sell`] || 0;  // sell = long liquidated
      const shorts = counts[`${src}|buy`] || 0;
      const name = src.replace('-perp','');
      html += `
        <div style="margin-bottom:8px">
          <div class="liq-bar-label" style="margin-bottom:3px">${name}</div>
          <div class="liq-bar-item">
            <div class="liq-bar-label" style="color:#ff4d6a;font-size:9px">LONG</div>
            <div class="liq-bar-track"><div class="liq-bar-fill long" style="width:${(longs/Math.max(total,1)*100).toFixed(0)}%"></div></div>
            <span style="font-family:monospace;font-size:9px;color:#8892a4;width:20px;text-align:right">${longs}</span>
          </div>
          <div class="liq-bar-item" style="margin-top:2px">
            <div class="liq-bar-label" style="color:#00d084;font-size:9px">SHORT</div>
            <div class="liq-bar-track"><div class="liq-bar-fill short" style="width:${(shorts/Math.max(total,1)*100).toFixed(0)}%"></div></div>
            <span style="font-family:monospace;font-size:9px;color:#8892a4;width:20px;text-align:right">${shorts}</span>
          </div>
        </div>
      `;
    }
    this.heatmapEl.innerHTML = html;
  }
}

// ── Funding Panel ─────────────────────────────────────────────────────

class FundingPanel {
  constructor(el) {
    this.el = el;
  }

  update(funding) {
    if (!funding) return;
    const rates = funding.per_source || {};
    const cells = {
      'binance-perp': { label: 'Binance Perp', rate: rates['binance-perp'] },
      'bybit-perp':   { label: 'Bybit Perp',   rate: rates['bybit-perp'] },
    };

    let html = '';
    for (const [src, info] of Object.entries(cells)) {
      const r = info.rate;
      const cls = r === null ? '' : (r >= 0 ? 'positive' : 'negative');
      const annual = r !== null ? (r * 3 * 365 * 100).toFixed(1) + '% p.a.' : '–';
      html += `
        <div class="funding-cell">
          <div class="funding-exchange">${info.label}</div>
          <div class="funding-rate ${cls}">${r !== null ? (r * 100).toFixed(4) + '%' : '–'}</div>
          <div class="funding-annual">${annual}</div>
        </div>
      `;
    }

    // Avg
    const avg = funding.average_rate;
    const avgCls = avg === null ? '' : (avg >= 0 ? 'positive' : 'negative');
    const avgAnnual = avg !== null ? (avg * 3 * 365 * 100).toFixed(1) + '% p.a.' : '–';
    html += `
      <div class="funding-cell" style="grid-column:1/-1;background:#111318">
        <div class="funding-exchange">Average</div>
        <div class="funding-rate ${avgCls}">${avg !== null ? (avg * 100).toFixed(4) + '%' : '–'}</div>
        <div class="funding-annual">${avgAnnual}</div>
      </div>
    `;

    this.el.innerHTML = html;
  }
}

// ── Utilities ─────────────────────────────────────────────────────────

function fmtPrice(v) {
  if (v === null || v === undefined) return '–';
  return v.toFixed(4);
}

function fmtBasis(v) {
  if (v === null || v === undefined) return '–';
  const s = v.toFixed(4);
  return v >= 0 ? '+' + s : s;
}

function fmtLarge(v) {
  if (v === null || v === undefined) return '–';
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return sign + (abs / 1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return sign + (abs / 1e6).toFixed(2) + 'M';
  if (abs >= 1e3) return sign + (abs / 1e3).toFixed(1) + 'K';
  return sign + abs.toFixed(2);
}

function fmtVolume(v) { return fmtLarge(v); }

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function hexAlpha(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function deepMerge(target, source) {
  for (const key of Object.keys(source)) {
    if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
      target[key] = deepMerge(target[key] || {}, source[key]);
    } else {
      target[key] = source[key];
    }
  }
  return target;
}

// Export for use in main.js
window.PriceChart = PriceChart;
window.BasisChart = BasisChart;
window.VolumeChart = VolumeChart;
window.OIChart = OIChart;
window.CVDChart = CVDChart;
window.SpreadChart = SpreadChart;
window.LiqFeed = LiqFeed;
window.FundingPanel = FundingPanel;
window.COLORS = COLORS;
window.fmtPrice = fmtPrice;
window.fmtBasis = fmtBasis;
window.fmtLarge = fmtLarge;

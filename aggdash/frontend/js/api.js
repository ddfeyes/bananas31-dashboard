/**
 * aggdash API client
 * Polls backend REST endpoints and caches data for charts.
 */

// Use relative URLs so the nginx frontend proxy handles routing (works behind any reverse proxy)
const API_BASE = '';

// Timeframe → seconds
const TF_SECS = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600 };

class AggdashAPI {
  constructor() {
    this.baseUrl = API_BASE;
    this.cache = {};
    this.errorCount = 0;
    this.connected = false;
    this.listeners = {};
  }

  on(event, fn) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(fn);
  }

  emit(event, data) {
    (this.listeners[event] || []).forEach(fn => fn(data));
  }

  async get(path) {
    try {
      const res = await fetch(this.baseUrl + path);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      this.errorCount = 0;
      this.connected = true;
      this.emit('connected', true);
      return data;
    } catch (err) {
      this.errorCount++;
      if (this.errorCount > 2) {
        this.connected = false;
        this.emit('connected', false);
      }
      console.warn('[api] GET', path, 'failed:', err.message);
      return null;
    }
  }

  // Core endpoints
  async getPrices() { return this.get('/api/prices'); }
  async getAggPrices() { return this.get('/api/aggregated-prices'); }
  async getOI() { return this.get('/api/oi'); }
  async getFunding() { return this.get('/api/funding'); }
  async getLiquidations(limit = 50) { return this.get(`/api/liquidations?limit=${limit}`); }

  // DEX
  async getDex() { return this.get('/api/dex'); }
  async getDexHistory(limit = 100) { return this.get(`/api/dex/history?limit=${limit}`); }

  // Analytics
  async getSnapshot() { return this.get('/api/analytics/snapshot'); }
  async getCVD(windowSecs) { return this.get(`/api/analytics/cvd?window_secs=${windowSecs}`); }
  async getCVDSeries(intervalSecs, windowSecs) {
    return this.get(`/api/analytics/cvd/series?interval_secs=${intervalSecs}&window_secs=${windowSecs}`);
  }
  async getBasis() { return this.get('/api/analytics/basis'); }
  async getBasisSeries(intervalSecs, windowSecs) {
    return this.get(`/api/analytics/basis/series?interval_secs=${intervalSecs}&window_secs=${windowSecs}`);
  }
  async getDexCexSpread() { return this.get('/api/analytics/dex-cex-spread'); }
  async getDexCexSpreadSeries(intervalSecs, windowSecs) {
    return this.get(`/api/analytics/dex-cex-spread/series?interval_secs=${intervalSecs}&window_secs=${windowSecs}`);
  }
  async getOIDelta() { return this.get('/api/analytics/oi-delta'); }
  async getOIDeltaSeries(windowSecs) {
    return this.get(`/api/analytics/oi-delta/series?window_secs=${windowSecs}`);
  }
  async getFundingSummary() { return this.get('/api/analytics/funding'); }
}

window.api = new AggdashAPI();

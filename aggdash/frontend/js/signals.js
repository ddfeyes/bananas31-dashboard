/**
 * signals.js — Module 4: Alerts & Signals panel
 * Polls /api/signals every 60s and renders status cards.
 */

const SIGNAL_ICONS = {
  SQUEEZE_RISK: '🔴',
  ARB_OPPTY: '🟡',
  OI_ACCUMULATION: '🟢',
};

const SIGNAL_COLORS = {
  SQUEEZE_RISK: '#ff4444',
  ARB_OPPTY: '#ffaa00',
  OI_ACCUMULATION: '#44cc44',
};

function formatSignalDetail(sig) {
  switch (sig.type) {
    case 'SQUEEZE_RISK':
      return sig.basis_pct != null
        ? `basis ${Number(sig.basis_pct).toFixed(2)}% | funding ${sig.avg_funding_rate != null ? Number(sig.avg_funding_rate).toFixed(5) : '–'}`
        : '';
    case 'ARB_OPPTY':
      return sig.dex_premium_pct != null
        ? `DEX dev ${Number(sig.dex_premium_pct).toFixed(2)}%`
        : '';
    case 'OI_ACCUMULATION':
      return sig.oi_delta_30m != null
        ? `OI Δ30m ${Number(sig.oi_delta_30m).toLocaleString()}`
        : '';
    default:
      return '';
  }
}

function renderSignals(data) {
  const signals = data.signals || [];
  signals.forEach((sig) => {
    const card = document.getElementById(`sig-${sig.type}`);
    if (!card) return;

    card.classList.remove('loading', 'active', 'inactive');

    const detail = formatSignalDetail(sig);
    const statusEl = card.querySelector('.signal-status');

    if (sig.active) {
      card.classList.add('active');
      card.style.borderColor = SIGNAL_COLORS[sig.type] || '#888';
      card.style.boxShadow = `0 0 8px ${SIGNAL_COLORS[sig.type]}88`;
      statusEl.textContent = detail || 'ACTIVE';
    } else {
      card.classList.add('inactive');
      card.style.borderColor = '#333';
      card.style.boxShadow = 'none';
      statusEl.textContent = detail || 'inactive';
    }
  });
}

async function fetchAndRenderSignals() {
  try {
    const res = await fetch('/api/signals');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderSignals(data);
  } catch (err) {
    console.warn('Signals fetch error:', err);
  }
}

// Initial load + poll every 60s
fetchAndRenderSignals();
setInterval(fetchAndRenderSignals, 60000);

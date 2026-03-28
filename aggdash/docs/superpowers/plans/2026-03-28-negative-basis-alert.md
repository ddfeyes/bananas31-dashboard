# Negative Basis Alert — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `basis_flip` and `contango_flip` signals, calibrate squeeze thresholds from issue #162 data, and display signal history in frontend.

**Architecture:** Create `backend/signals.py` with a `SignalDetector` class that tracks basis history and OI stability. Signals are evaluated on every `compute_basis()` call and stored in a signal history buffer. Expose via new REST endpoint `/api/signals` polled by frontend.

**Tech Stack:** FastAPI, Python asyncio, SQLite for signal history, vanilla JS frontend panel.

---

## Signal Definitions

### basis_flip
- Triggers when aggregated basis crosses zero (positive → negative or negative → positive)
- Stores: timestamp, signal_type="basis_flip", direction ("positive_to_negative" | "negative_to_positive"), basis_pct

### contango_flip
- Triggers when: aggregated basis < -0.1% AND OI delta is stable (|delta_pct| < 5%)
- Stores: timestamp, signal_type="contango_flip", basis_pct, oi_delta_pct

### Squeeze threshold calibration (review only, no new signals)
- Issue #162 data: Bybit basis went to -0.015%, aggregate basis to +0.045%
- Current squeeze_watch/squeeze_risk thresholds need review — document what they are and whether they're appropriate

---

## File Map

| Action | File |
|--------|------|
| Create | `backend/signals.py` |
| Modify | `backend/main.py` |
| Create | `backend/db.py` signal history table + helper functions |
| Modify | `frontend/index.html` — add signals panel |
| Modify | `frontend/js/main.js` — add SignalsPanel class |
| Modify | `frontend/js/api.js` — add `getSignals()` API method |

---

## Tasks

### Task 1: Signal data model and storage

**Files:**
- Modify: `backend/db.py`

- [ ] **Step 1: Add signal history table schema to db.py**

Add this near the top of `db.py`, after existing table schemas:

```python
CREATE_SIGNALS_TABLE = """
CREATE TABLE IF NOT EXISTS signal_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    signal_type TEXT NOT NULL,        -- 'basis_flip' | 'contango_flip'
    direction TEXT,                    -- 'positive_to_negative' | 'negative_to_positive' | NULL
    basis_pct REAL,
    oi_delta_pct REAL,                -- NULL for basis_flip
    exchange TEXT,                     -- 'aggregated' | per-exchange
    metadata TEXT                      -- JSON extra data
);
CREATE INDEX IF NOT EXISTS idx_signal_timestamp ON signal_history(timestamp DESC);
"""
```

- [ ] **Step 2: Add signal insert helper**

Add to `db.py`:

```python
def insert_signal(signal_type: str, direction: str | None, basis_pct: float,
                  oi_delta_pct: float | None, exchange: str = "aggregated",
                  metadata: dict | None = None):
    """Insert a signal into signal_history table."""
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO signal_history
           (timestamp, signal_type, direction, basis_pct, oi_delta_pct, exchange, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (time.time(), signal_type, direction, basis_pct, oi_delta_pct, exchange,
         json.dumps(metadata) if metadata else None)
    )
    conn.commit()
    return cursor.lastrowid


def get_signal_history(limit: int = 50, signal_type: str | None = None) -> List[dict]:
    """Fetch recent signals, most recent first."""
    conn = get_db()
    if signal_type:
        rows = conn.execute(
            """SELECT * FROM signal_history
               WHERE signal_type = ? ORDER BY timestamp DESC LIMIT ?""",
            (signal_type, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM signal_history ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 3: Ensure init_db calls CREATE_SIGNALS_TABLE**

Find where other CREATE TABLE statements are executed and add `CREATE_SIGNALS_TABLE` execution there. Search for `CREATE_TABLE` in db.py to find the init function.

---

### Task 2: Signal detection engine

**Files:**
- Create: `backend/signals.py`

- [ ] **Step 1: Write signals.py**

Create `backend/signals.py`:

```python
"""Signal detection for basis_flip and contango_flip.

Signals are emitted when:
- basis_flip: aggregated basis crosses zero (positive → negative or vice versa)
- contango_flip: basis < -0.1% AND OI delta is stable (|delta_pct| < 5%)
"""
import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from db import insert_signal

logger = logging.getLogger(__name__)

SignalType = Literal["basis_flip", "contango_flip"]


@dataclass
class Signal:
    timestamp: float
    signal_type: SignalType
    direction: str | None  # "positive_to_negative" | "negative_to_positive" | None (contango)
    basis_pct: float
    oi_delta_pct: float | None = None
    exchange: str = "aggregated"


@dataclass
class SignalConfig:
    # contango_flip threshold: basis must be below this (negative)
    contango_basis_threshold_pct: float = -0.1
    # OI stability: |oi_delta_pct| must be below this
    contango_oi_stable_threshold_pct: float = 5.0
    # History buffer size
    basis_history_size: int = 10


class SignalDetector:
    """Tracks basis and OI history, emits signals on threshold crossings."""

    def __init__(self, config: SignalConfig | None = None):
        self.config = config or SignalConfig()
        # basis history as a deque of (timestamp, basis_pct)
        self._basis_history: deque = deque(maxlen=self.config.basis_history_size)
        # last known basis sign: 1 = positive, -1 = negative, 0 = zero
        self._last_basis_sign: int = 0
        self._lock = asyncio.Lock()
        # track last emitted signals to avoid duplicates
        self._last_flip_time: float = 0
        self._last_contango_time: float = 0

    async def update_basis(self, basis_pct: float) -> list[Signal]:
        """Call when new basis is computed. Returns list of new signals."""
        async with self._lock:
            return await self._check_signals(basis_pct)

    async def _check_signals(self, basis_pct: float) -> list[Signal]:
        signals = []
        now = time.time()

        # Store in history
        self._basis_history.append((now, basis_pct))

        # Determine current sign
        if basis_pct > 0:
            current_sign = 1
        elif basis_pct < 0:
            current_sign = -1
        else:
            current_sign = 0

        # Check basis_flip: crossing zero
        if current_sign != 0 and self._last_basis_sign != 0 and current_sign != self._last_basis_sign:
            direction = (
                "positive_to_negative" if current_sign == -1 else "negative_to_positive"
            )
            # Debounce: don't fire if we fired within last 60s
            if now - self._last_flip_time > 60:
                signal = Signal(
                    timestamp=now,
                    signal_type="basis_flip",
                    direction=direction,
                    basis_pct=basis_pct,
                )
                signals.append(signal)
                self._last_flip_time = now
                # Persist
                insert_signal(
                    signal_type="basis_flip",
                    direction=direction,
                    basis_pct=basis_pct,
                    oi_delta_pct=None,
                )
                logger.info(f"basis_flip: {direction}, basis_pct={basis_pct:.4f}%")

        self._last_basis_sign = current_sign
        return signals

    async def check_contango_flip(self, basis_pct: float, oi_delta_pct: float | None) -> Signal | None:
        """Check contango_flip condition. Call after OI delta is available."""
        if oi_delta_pct is None:
            return None

        async with self._lock:
            cfg = self.config
            now = time.time()

            # Condition: basis < -0.1% AND |oi_delta_pct| < 5%
            if (basis_pct < cfg.contango_basis_threshold_pct and
                    abs(oi_delta_pct) < cfg.contango_oi_stable_threshold_pct):

                # Debounce: 5 min minimum between contango signals
                if now - self._last_contango_time > 300:
                    self._last_contango_time = now
                    insert_signal(
                        signal_type="contango_flip",
                        direction=None,
                        basis_pct=basis_pct,
                        oi_delta_pct=oi_delta_pct,
                    )
                    logger.info(
                        f"contango_flip: basis_pct={basis_pct:.4f}%, "
                        f"oi_delta_pct={oi_delta_pct:.4f}%"
                    )
                    return Signal(
                        timestamp=now,
                        signal_type="contango_flip",
                        direction=None,
                        basis_pct=basis_pct,
                        oi_delta_pct=oi_delta_pct,
                    )
        return None

    def get_basis_history(self) -> list[tuple[float, float]]:
        """Return basis history as list of (timestamp, basis_pct)."""
        return list(self._basis_history)
```

- [ ] **Step 2: Add signal_evaluator to analytics engine**

In `backend/analytics_engine.py`, add a `SignalEvaluator` that wraps `SignalDetector` and is called from `snapshot()`.

Add at the bottom of the `AnalyticsEngine` class in analytics_engine.py:

```python
    # ------------------------------------------------------------------ #
    # Signals                                                              #
    # ------------------------------------------------------------------ #

    async def evaluate_signals(self, signal_detector: SignalDetector) -> Dict:
        """
        Evaluate basis_flip and contango_flip signals from current state.
        Called after compute_basis() and compute_oi_delta().
        Returns dict with triggered signals and current signal history.
        """
        try:
            basis_data = await self.compute_basis()
        except Exception as e:
            return {"error": f"basis compute failed: {e}"}

        try:
            oi_delta_data = await self.compute_oi_delta()
        except Exception as e:
            oi_delta_data = {"aggregated": {"delta_pct": None}}

        basis_pct = basis_data.get("aggregated", {}).get("basis_pct")
        oi_delta_pct = oi_delta_data.get("aggregated", {}).get("delta_pct")

        new_signals = []

        # Check basis_flip
        if basis_pct is not None:
            flip_signals = await signal_detector.update_basis(basis_pct)
            new_signals.extend(flip_signals)

            # Check contango_flip
            if oi_delta_pct is not None:
                contango = await signal_detector.check_contango_flip(basis_pct, oi_delta_pct)
                if contango:
                    new_signals.append(contango)

        return {
            "new_signals": [
                {"timestamp": s.timestamp, "signal_type": s.signal_type,
                 "direction": s.direction, "basis_pct": s.basis_pct,
                 "oi_delta_pct": s.oi_delta_pct}
                for s in new_signals
            ],
            "basis_pct": basis_pct,
            "oi_delta_pct": oi_delta_pct,
        }
```

- [ ] **Step 3: Update main.py to wire up SignalDetector**

In `backend/main.py`, near where `analytics_engine` is created, add:

```python
from signals import SignalDetector, SignalConfig

signal_detector = SignalDetector(SignalConfig())
```

Then add the signals endpoint after the analytics endpoints:

```python
@app.get("/api/signals")
async def get_signals(limit: int = 50, signal_type: str | None = None):
    """Return recent signal history."""
    from db import get_signal_history
    return {"signals": get_signal_history(limit=limit, signal_type=signal_type)}


@app.get("/api/signals/evaluate")
async def evaluate_signals():
    """Trigger signal evaluation against current basis and OI state."""
    result = await analytics_engine.evaluate_signals(signal_detector)
    return result
```

- [ ] **Step 4: Commit**

```bash
git add backend/signals.py backend/db.py backend/main.py
git commit -m "feat(signals): add basis_flip and contango_flip detection engine"
```

---

### Task 3: Squeeze threshold calibration review

**Files:**
- Modify: `backend/signals.py` (config values)

- [ ] **Step 1: Document squeeze thresholds from issue #162 data**

Issue #162 data:
- Binance basis: +0.1051%
- Bybit basis: **-0.0150%** (negative!)
- Aggregate basis: +0.0450%
- perp/s ratio: 4.649 (was 5.28 at 05:00 UTC, declining ~0.058/h)
- LIQ-1H: 3

**Analysis:** The negative Bybit basis (-0.015%) was an isolated observation. Aggregate basis stayed positive (+0.045%). This suggests the squeeze_watch threshold (if it was set near 0%) would have caught Bybit's flip. 

The appropriate thresholds based on this data:
- `basis_flip` fires at 0% (crossing zero — correct)
- `contango_flip` fires at -0.1% — this is a 10x multiple of the observed -0.015%, so it's appropriately conservative
- squeeze thresholds: if existing squeeze_watch was set at +0.1% for positive side, the negative equivalent should be symmetric at -0.1% to catch similar magnitude events

Add to `signals.py` SignalConfig:

```python
@dataclass
class SignalConfig:
    # basis_flip fires at zero crossing (always)
    contango_basis_threshold_pct: float = -0.1   # Issue #162: observed -0.015% on Bybit, -0.1% is safe buffer
    contango_oi_stable_threshold_pct: float = 5.0
    basis_history_size: int = 10
    # Squeeze review notes (informational only, no code change):
    # - Issue #162: Bybit negative basis was -0.015%, aggregate +0.045%
    # - squeeze_watch on positive side should mirror: symmetric threshold at ~0.1%
    # - squeeze_risk threshold should be ~2x observed max: ~0.2%
```

- [ ] **Step 2: Commit**

```bash
git commit -m "docs(signals): calibrate contango threshold from issue #162 data"
```

---

### Task 4: Frontend signals panel

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/js/api.js`
- Modify: `frontend/js/main.js`

- [ ] **Step 1: Add signals panel HTML**

Add after the Funding panel (Chart 8) in `index.html`, before the closing `</div><!-- /dashboard -->`:

```html
    <!-- Signals Panel -->
    <div class="panel full-width" style="min-height:180px">
      <div class="panel-header">
        <span class="panel-title">Signal History</span>
        <div class="panel-stats">
          <div class="panel-stat">
            <span class="panel-stat-label">Latest</span>
            <span class="panel-stat-value" id="ps-signal-latest">–</span>
          </div>
        </div>
      </div>
      <div class="signals-panel" id="signals-panel">
        <div class="signals-empty">Waiting for signals…</div>
      </div>
    </div>
```

- [ ] **Step 2: Add getSignals to api.js**

Add after the existing API methods in `AggdashAPI`:

```javascript
  async getSignals(limit = 50) {
    return this.get(`/api/signals?limit=${limit}`);
  }
```

- [ ] **Step 3: Add SignalsPanel class to main.js**

Add after the `LiqFeed` class definition (search for `class LiqFeed` to find the right spot to insert):

```javascript
class SignalsPanel {
  constructor(container) {
    this.container = container;
    this.signals = [];
  }

  update(signals) {
    if (!signals || !signals.length) return;
    this.signals = signals.slice(0, 20); // keep last 20

    const latest = signals[0];
    const latestEl = document.getElementById('ps-signal-latest');
    if (latestEl) {
      const label = latest.signal_type === 'basis_flip'
        ? `Basis Flip (${latest.direction})`
        : `Contango (basis: ${latest.basis_pct?.toFixed(4)}%)`;
      latestEl.textContent = label;
      latestEl.className = 'panel-stat-value ' +
        (latest.signal_type === 'basis_flip' ? 'warning' : 'alert');
    }

    this.container.innerHTML = signals.map(s => {
      const time = new Date(s.timestamp * 1000).toLocaleTimeString();
      const typeClass = s.signal_type === 'basis_flip' ? 'signal-flip' : 'signal-contango';
      const typeLabel = s.signal_type === 'basis_flip'
        ? `Flip (${s.direction})`
        : 'Contango';
      const extras = s.oi_delta_pct != null
        ? `<span class="signal-extra">OI Δ: ${s.oi_delta_pct.toFixed(2)}%</span>`
        : '';
      return `<div class="signal-item ${typeClass}">
        <span class="signal-time">${time}</span>
        <span class="signal-type">${typeLabel}</span>
        <span class="signal-basis">basis: ${s.basis_pct?.toFixed(4)}%</span>
        ${extras}
      </div>`;
    }).join('');
  }
}
```

- [ ] **Step 4: Add polling for signals in Dashboard class**

In `main.js`, add to `Dashboard.setupCharts()`:

```javascript
    this.charts.signals = new SignalsPanel(document.getElementById('signals-panel'));
```

Add to `Dashboard.startPolling()` after the fast poll setup:

```javascript
    // Signals poll (slow, every 30s)
    this.pollSignals();
    setInterval(() => this.pollSignals(), 30000);
```

Add the method:

```javascript
  async pollSignals() {
    const data = await window.api.getSignals(20);
    if (data && data.signals) {
      this.charts.signals.update(data.signals);
    }
  }
```

- [ ] **Step 5: Add CSS for signals panel**

Add to `frontend/css/dashboard.css`:

```css
.signals-panel {
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 140px;
  overflow-y: auto;
}
.signals-empty {
  color: #666;
  font-size: 13px;
  font-family: 'JetBrains Mono', monospace;
  padding: 8px;
}
.signal-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 5px 8px;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}
.signal-flip {
  background: rgba(255, 183, 0, 0.12);
  border-left: 3px solid #ffb700;
}
.signal-contango {
  background: rgba(255, 80, 80, 0.12);
  border-left: 3px solid #ff5050;
}
.signal-time { color: #888; min-width: 70px; }
.signal-type { font-weight: 600; }
.signal-basis { color: #ccc; }
.signal-extra { color: #888; }
```

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html frontend/js/api.js frontend/js/main.js frontend/css/dashboard.css
git commit -m "feat(frontend): add signal history panel"
```

---

## Verification

1. Run `pytest` or start the backend and verify no import errors
2. Visit the dashboard and verify the Signals panel appears
3. Manually trigger a basis flip by checking `/api/signals/evaluate`
4. Check `/api/signals` returns the expected JSON structure

---

## Spec Coverage Check

| Requirement | Task |
|-------------|------|
| basis_flip signal | Task 2 |
| contango_flip signal | Task 2 |
| Squeeze threshold calibration from #162 | Task 3 |
| Signal history panel in frontend | Task 4 |

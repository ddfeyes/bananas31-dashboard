# Negative Basis Alert Implementation Plan (Issue #165)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `basis_flip` and `contango_flip` signals to detect regime changes in aggregate basis.

**Architecture:** Two new signals added to `SignalEngine`. `_prev_agg_basis` instance var tracks previous basis for flip detection. Both signals use the same snapshot data (basis aggregated + OI delta).

**Tech Stack:** Python signals engine, pytest, analytics snapshot dict format.

---

## File Map

- Modify: `aggdash/backend/signals.py` — add `_prev_agg_basis`, two new signal methods, update `compute_signals()` dispatch
- Modify: `aggdash/backend/tests/test_signals.py` — add tests for `basis_flip` and `contango_flip`

## Tasks

### Task 1: Add `basis_flip` signal

**Files:**
- Modify: `aggdash/backend/signals.py:19-30`
- Modify: `aggdash/backend/tests/test_signals.py:1-50`

- [ ] **Step 1: Add `_prev_agg_basis` instance var and thresholds**

In `SignalEngine.__init__`, add after `self._prev_agg_basis: Optional[float] = None`:

```python
# Thresholds for new signals
BASIS_FLIP_THRESHOLD = None  # Any sign change fires; no numeric threshold
CONTANGO_BASIS_THRESHOLD = -0.001  # -0.1%
CONTANGO_OI_STABLE_THRESHOLD = 0.02  # ±2% OI change = "stable"
```

- [ ] **Step 2: Add `_basis_flip()` method**

Add after `_negative_basis()`:

```python
def _basis_flip(self, snapshot: Dict) -> Optional[Dict]:
    """
    basis_flip: fires when agg_basis_pct changes sign (positive→negative or negative→positive).
    Uses _prev_agg_basis to detect the transition. Updates _prev_agg_basis on each call.
    """
    basis_data = snapshot.get("basis", {})
    aggregated = basis_data.get("aggregated", {})
    agg_basis_pct = aggregated.get("basis_pct")
    if agg_basis_pct is None:
        agg_basis_pct = basis_data.get("agg_basis_pct")
    if agg_basis_pct is None:
        return None

    # Convert % to fraction for comparison
    current_basis = agg_basis_pct / 100.0

    # Fire only if we have a previous value AND sign changed
    if self._prev_agg_basis is not None:
        prev_sign = 1 if self._prev_agg_basis >= 0 else -1
        curr_sign = 1 if current_basis >= 0 else -1
        if prev_sign != curr_sign:
            direction = "positive→negative" if curr_sign < 0 else "negative→positive"
            self._prev_agg_basis = current_basis
            return {
                "id": "basis_flip",
                "name": "Basis Flip",
                "severity": "warning",
                "message": f"Basis flipped {direction} ({self._prev_agg_basis*100:.3f}%→{current_basis*100:.3f}%) — regime change",
                "value": current_basis,
                "prev_value": self._prev_agg_basis,
            }

    # Always update prev after first non-None value
    self._prev_agg_basis = current_basis
    return None
```

- [ ] **Step 3: Add `_contango_flip()` method**

```python
def _contango_flip(self, snapshot: Dict) -> Optional[Dict]:
    """
    contango_flip: fires when basis < -0.1% AND OI stable.
    OI stability: |oi_delta_pct| < 2%.
    """
    basis_data = snapshot.get("basis", {})
    aggregated = basis_data.get("aggregated", {})
    agg_basis_pct = aggregated.get("basis_pct")
    if agg_basis_pct is None:
        agg_basis_pct = basis_data.get("agg_basis_pct")
    if agg_basis_pct is None:
        return None

    current_basis = agg_basis_pct / 100.0

    if current_basis >= CONTANGO_BASIS_THRESHOLD:
        return None  # not in contango regime

    # Check OI stability
    oi_data = snapshot.get("oi_delta", {})
    oi_delta_pct = oi_data.get("total_delta_pct")
    if oi_delta_pct is None:
        agg = oi_data.get("aggregated", {}) or {}
        oi_delta_pct = agg.get("delta_pct")
    if oi_delta_pct is None:
        return None

    if abs(oi_delta_pct) >= CONTANGO_OI_STABLE_THRESHOLD:
        return None  # OI not stable

    return {
        "id": "contango_flip",
        "name": "Contango Flip",
        "severity": "info",
        "message": f"Basis {current_basis*100:.2f}% + OI Δ {oi_delta_pct*100:.1f}% → contango regime (OI stable)",
        "value": current_basis,
        "threshold": CONTANGO_BASIS_THRESHOLD,
    }
```

- [ ] **Step 4: Wire both signals into `compute_signals()`**

Add after the `_negative_basis` call block in `compute_signals()`:

```python
try:
    sig = self._basis_flip(snapshot)
    if sig:
        signals.append(sig)
except Exception as e:
    logger.warning("basis_flip error: %s", e)

try:
    sig = self._contango_flip(snapshot)
    if sig:
        signals.append(sig)
except Exception as e:
    logger.warning("contango_flip error: %s", e)
```

- [ ] **Step 5: Write failing tests**

In `tests/test_signals.py`, add:

```python
def test_basis_flip_positive_to_negative():
    """basis_flip fires when basis crosses from positive to negative."""
    engine = make_engine()
    # First call with positive basis - should NOT fire (no prev value yet)
    snap1 = make_snap(basis_pct=0.15)
    sigs1 = engine.compute_signals(snap1)
    ids1 = [s["id"] for s in sigs1]
    assert "basis_flip" not in ids1, "basis_flip should NOT fire on first call (no prev)"
    # Second call with negative basis - SHOULD fire
    snap2 = make_snap(basis_pct=-0.15)
    sigs2 = engine.compute_signals(snap2)
    ids2 = [s["id"] for s in sigs2]
    assert "basis_flip" in ids2, f"basis_flip should fire on positive→negative flip, got {ids2}"

def test_basis_flip_negative_to_positive():
    """basis_flip fires when basis crosses from negative to positive."""
    engine = make_engine()
    snap1 = make_snap(basis_pct=-0.15)
    engine.compute_signals(snap1)  # init prev
    snap2 = make_snap(basis_pct=0.15)
    sigs2 = engine.compute_signals(snap2)
    ids2 = [s["id"] for s in sigs2]
    assert "basis_flip" in ids2, f"basis_flip should fire on negative→positive flip, got {ids2}"

def test_basis_flip_no_fire_same_sign():
    """basis_flip does NOT fire when basis stays same sign."""
    engine = make_engine()
    snap1 = make_snap(basis_pct=0.10)
    engine.compute_signals(snap1)
    snap2 = make_snap(basis_pct=0.15)
    sigs2 = engine.compute_signals(snap2)
    ids2 = [s["id"] for s in sigs2]
    assert "basis_flip" not in ids2, f"basis_flip should NOT fire for same-sign change, got {ids2}"

def test_contango_flip_fires():
    """contango_flip fires when basis < -0.1% AND OI stable."""
    engine = make_engine()
    snap = make_snap(basis_pct=-0.15, oi_delta_frac=0.01)  # -0.15% basis, +1% OI (stable)
    sigs = engine.compute_signals(snap)
    ids = [s["id"] for s in sigs]
    assert "contango_flip" in ids, f"contango_flip should fire for basis=-0.15%+OI=+1%, got {ids}"

def test_contango_flip_no_fire_unstable_oi():
    """contango_flip does NOT fire when OI moves > 2%."""
    engine = make_engine()
    snap = make_snap(basis_pct=-0.15, oi_delta_frac=0.03)  # OI too volatile
    sigs = engine.compute_signals(snap)
    ids = [s["id"] for s in sigs]
    assert "contango_flip" not in ids, f"contango_flip should NOT fire with unstable OI, got {ids}"

def test_contango_flip_no_fire_high_basis():
    """contango_flip does NOT fire when basis > -0.1%."""
    engine = make_engine()
    snap = make_snap(basis_pct=-0.05, oi_delta_frac=0.005)  # basis not low enough
    sigs = engine.compute_signals(snap)
    ids = [s["id"] for s in sigs]
    assert "contango_flip" not in ids, f"contango_flip should NOT fire when basis > -0.1%, got {ids}"
```

- [ ] **Step 6: Run tests to verify they fail (TDD red)**

Run: `cd aggdash/backend && python -m pytest tests/test_signals.py -v -k "basis_flip or contango_flip"`

Expected: test failures (methods don't exist yet or logic not wired)

- [ ] **Step 7: Run full test suite to ensure no regressions**

Run: `cd aggdash/backend && python -m pytest tests/test_signals.py -v`

Expected: all tests pass (existing + new)

- [ ] **Step 8: Commit**

```bash
git add aggdash/backend/signals.py aggdash/backend/tests/test_signals.py
git commit -m "feat: add basis_flip and contango_flip signals (fixes #165)"
```

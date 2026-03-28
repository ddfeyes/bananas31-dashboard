# DESIGN.md — BANANAS31 Dashboard Redesign

**Author:** Mika (Visual Director)  
**Date:** 2026-03-28  
**Version:** v2.0 Full Redesign

---

## Problem Statement

The current dashboard has severe usability and visual quality issues:

1. **7 stacked panels with no height management** — CVD, Funding, Liquidations panels are ~50–80px each, charts are unreadable
2. **Stats bar overflows** — 17 metrics in one row, wraps into 2–3 lines on any screen < 1600px
3. **Zero visual hierarchy** — every element is the same weight, nothing communicates priority
4. **Legend/price label collision** — TradingView right-side labels overlap legends in each panel
5. **No loading states** — TV watermarks visible while data loads
6. **Flat developer aesthetic** — functional but zero product polish

---

## Design Direction

**Aesthetic:** Premium dark terminal — not raw dev tool, not generic crypto dashboard.  
Reference visual language: Bloomberg Terminal meets Linear.app dark mode.  
**Personality:** Precise. Dense. Readable. Fast.

Core principle: **every pixel earns its place**. No decorative chrome.

---

## Design Tokens

```css
:root {
  /* Backgrounds */
  --bg-void:     #06080e;   /* page background */
  --bg-base:     #090c14;   /* chart backgrounds */
  --bg-surface:  #0d1220;   /* panels, header */
  --bg-raised:   #111828;   /* hover states, active buttons */
  --bg-overlay:  #151d2e;   /* tooltips, dropdowns */

  /* Borders */
  --border-dim:    rgba(255,255,255,0.04);
  --border-subtle: rgba(255,255,255,0.07);
  --border-mild:   rgba(255,255,255,0.11);
  --border-accent: rgba(74,143,255,0.25);

  /* Text */
  --text-primary:   #eef0f5;
  --text-secondary: #7a8499;
  --text-muted:     #3d4a60;
  --text-ghost:     #222d3f;

  /* Signal colors */
  --green:   #00c97a;
  --red:     #ff3d5c;
  --yellow:  #f0c040;
  --blue:    #4a8fff;
  --purple:  #9d6fff;
  --cyan:    #00c8f5;
  --orange:  #ff7a35;

  /* Exchange brand colors */
  --binance:  #f0b90b;
  --bybit:    #ff6b2b;
  --dex:      #00c8f5;
  --agg:      #4a8fff;

  /* Chart panel accent for basis squeeze state */
  --squeeze-glow: rgba(255,61,92,0.12);

  /* Spacing scale */
  --s1: 4px;
  --s2: 8px;
  --s3: 12px;
  --s4: 16px;
  --s5: 20px;
  --s6: 24px;

  /* Font */
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
  --font-ui:   'Inter', system-ui, sans-serif;

  /* Radius */
  --r-xs: 2px;
  --r-sm: 4px;
  --r-md: 6px;
  --r-lg: 10px;
}
```

---

## Typography Scale

| Use | Font | Size | Weight | Color |
|-----|------|------|--------|-------|
| Logo / identifier | Mono | 14px | 700 | #4a8fff |
| Stat value (primary) | Mono | 13px | 600 | var(--text-primary) |
| Stat value (price) | Mono | 13px | 600 | var(--text-primary) |
| Stat label | UI | 9px | 500 | var(--text-muted) |
| Stat change % | Mono | 10px | 600 | green/red |
| Panel label | UI | 10px | 600 | var(--text-secondary) |
| Panel live value | Mono | 12px | 700 | contextual |
| Legend item | Mono | 9px | 400 | var(--text-secondary) |
| TF button | Mono | 11px | 500 | var(--text-secondary) |
| Alert badge text | Mono | 10px | 700 | signal color |
| Axis labels | Mono | 9px | 400 | var(--text-muted) |

---

## Layout Architecture

### Zone structure (top → bottom)

```
┌─────────────────────────────────────────────────────┐
│  HEADER (40px)                                       │
│  Logo · Primary prices · Connection status           │
├─────────────────────────────────────────────────────┤
│  STATS ROW (scrollable, 36px)                       │
│  Secondary metrics (OI, Funding, Spreads, Volumes)  │
├─────────────────────────────────────────────────────┤
│  CONTROLS BAR (32px)                                │
│  TF selector · Exchange toggles · Signal summary    │
├──────────────────────────────────┬──────────────────┤
│  PRICE + VOLUME (flex: 5)        │                  │
│  Main chart — always primary     │  SIGNAL          │
│                                  │  SIDEBAR         │
├──────────────────────────────────┤  (200px)         │
│  BASIS % + MA7D (flex: 1.5)      │                  │
│                                  │  Squeeze         │
├──────────────────────────────────┤  risk panel      │
│  OPEN INTEREST (flex: 1.5)       │  + probability   │
│                                  │  stats           │
├──────────────────────────────────┤                  │
│  CVD · VOL · FUND · LIQ (flex:1) │                  │
│  4-panel row, each 25% width     │                  │
├──────────────────────────────────┴──────────────────┤
│  LIQUIDATION FEED (collapsible, 180px)              │
│  Real-time liq table + heatmap                      │
└─────────────────────────────────────────────────────┘
```

### Key layout changes vs v1

1. **Header split into 2 rows** — primary prices in header, secondary stats in scrollable strip below
2. **Signal sidebar** (right column, 200px) — takes squeeze/signal data OUT of chart area
3. **Bottom 4 panels become a horizontal row** — CVD / Volume / Funding / Liquidations at equal 25% width, readable height
4. **Liquidation feed** — collapsible via toggle, not always-visible scroll area

---

## Header (Row 1, 40px)

**Left:** `BANANAS31` logo + tagline `REAL-TIME TERMINAL`  
**Center:** 4 primary prices — BN-SPOT · BN-PERP · BB-PERP · DEX — each with price + 24h% change  
**Right:** Connection indicator + WS status + last-update timestamp

Primary prices get **large treatment** — 15px mono, 600 weight. This is the first thing traders look at.

```
BANANAS31                 BN-SPOT  0.01310  −1.60%   BN-PERP  0.01312  −1.58%   BB-PERP  0.01311  −1.62%   DEX  0.01310  −1.57%             ● WS Live
REAL-TIME TERMINAL
```

---

## Stats Strip (Row 2, 36px, horizontal scroll)

Secondary metrics — horizontally scrollable, never wraps:

```
BN-FUND +0.0114%  ·  BB-FUND +0.0050%  ·  OI 3.43B  ·  DEX-SPREAD +0.005%  ·  DEX-TVL $4.07M  ·  VOL-24H 1.73B  ·  OI-TOT 3.43B  ·  24H-H 0.01344  ·  24H-L 0.01230  ·  LIQ-1H $0  ·  PERP/S 4.5×
```

Each metric: `9px label / 12px value` stacked, 48px min-width cell, separated by 1px border.  
Horizontal scroll on overflow — no wrap.

---

## Controls Bar (Row 3, 32px)

```
TF: [1m] [5m] [15m] [1H] [4H●] [1D] [1W]    SOURCES: [BN-S●] [BN-P●] [BB-P●] [DEX●]    SIGNALS: [● SQUEEZE_WATCH +0.12%] [● ARB] [quiet]
```

TF buttons: compact, monospace. Active state: blue background.  
Exchange toggles: color-coded per exchange.  
Signal summary: live badge — clicking scrolls to signal sidebar.

---

## Chart Area

### Panel height distribution (flex values)

```
Price + Volume:    flex: 5       (largest — always dominant)
Basis %:           flex: 2       (critical panel — squeeze signals here)
Open Interest:     flex: 1.5
Bottom row (×4):   flex: 1 each  (in a 4-column grid row)
```

### Bottom 4-panel row (horizontal grid)

Instead of 4 tiny stacked panels, arrange them in a 2×2 or 1×4 grid:

```
┌────────────┬────────────┬────────────┬────────────┐
│  CVD        │  VOLUME    │  FUNDING   │  LIQ        │
│  (25%)      │  (25%)     │  (25%)     │  (25%)      │
└────────────┴────────────┴────────────┴────────────┘
```

Each 25% column gets full readable height (~100–120px minimum).  
This is the primary fix for the "unreadable sub-panels" problem.

### Panel header design

Each panel has a **4px top border line** in its accent color (identity color per panel):
- Price: --blue
- Basis: --red (squeeze context)
- OI: --blue  
- CVD: --green
- Volume: --yellow
- Funding: --yellow
- Liquidations: --red

Panel header (24px): `[label left] [live value center] [legend right]`

Legend items move to a **compact inline format** — not the current floating absolute positioned boxes.

---

## Signal Sidebar (Right, 200px)

New element — right column alongside Price + Basis panels.

Contains:
1. **Active signal alert** — large, prominent. RED background flash if squeeze active.
2. **Basis squeeze probability widget** — histogram-style. Shows 30m/1h/2h outcome %.
3. **Last 5 alerts** — compact feed with timestamps.
4. **Pattern detection** — text list of active patterns.

When no signals: muted gray, shows `NO ACTIVE SIGNALS` centered.

When squeeze active:
- Background flashes `var(--squeeze-glow)` 
- Basis % in red
- Probability bars rendered in color

---

## Liquidation Feed (Bottom, collapsible 180px)

Toggle button in controls bar: `[LIQ FEED ▾]`

When expanded:
- Left: real-time liq table (side, exchange, price, qty, time)
- Right: 24h liq heatmap by exchange

Feed rows: flash animation on new entry. Green for SHORT liq, red for LONG liq.

When collapsed: shows only `LIQ-1H $0 | 24H $XXX` summary in 24px strip.

---

## Chart Visual Improvements

### Price + Volume panel
- Remove TradingView default watermark via CSS: `.tv-lightweight-charts > canvas + div { display: none; }`
- Legend: compact absolute-positioned strip at top-right inside chart, NOT overlapping price scale
- Volume series: scale margin increased, more breathing room

### Basis panel
- **Zero line** at 0.0% drawn explicitly as a reference line (dashed, var(--text-ghost))
- When basis > 0.1%: panel top-border changes to --red, glow applied
- MA7D line remains dashed white

### All panels
- Crosshair enabled + synced
- Time scale visible only on Price panel (removes redundancy)
- Y-axis: right-aligned, minimal labels (3 ticks max per panel)
- Grid: horizontal only (no vertical lines except time markers on price panel)

---

## Color Coding — Exchange Identity

Consistent across ALL panels and stats:

| Source | Color | Code |
|--------|-------|------|
| Binance Spot | Gold | `#f0b90b` |
| Binance Perp | Gold lighter | `#f0d060` |
| Bybit Spot | Orange-red | `#ff6b2b` |
| Bybit Perp | Orange lighter | `#ff9d6b` |
| DEX | Cyan | `#00c8f5` |
| Aggregated | Blue | `#4a8fff` |

Long liquidations: `--red`  
Short liquidations: `--green`  
Positive funding: `--green`  
Negative funding: `--red`

---

## Hover & Interaction States

### TF buttons
```css
default: bg transparent, color --text-secondary, border --border-subtle
hover:   bg --bg-raised, color --text-primary
active:  bg rgba(74,143,255,0.15), border --border-accent, color --blue
```

### Exchange toggles
```css
inactive: bg transparent, border --border-subtle, color --text-muted
active:   bg rgba(exchange-color, 0.12), border exchange-color, color exchange-color
```

### Panel resize
- Price panel has a drag handle at its bottom edge — allows user to resize it vertically
- Persisted to localStorage

---

## Responsive Strategy

**Desktop first.** Mobile is not a target (as per SPEC).

Breakpoints:
- `> 1440px` — full layout with sidebar
- `1200–1440px` — sidebar collapses into a drawer (toggle button)
- `900–1200px` — 4-panel bottom row becomes 2×2 grid
- `< 900px` — show notice: "Best viewed on desktop"

---

## Loading States

Each panel shows a skeleton state while waiting for data:
- Animated shimmer over the chart area (CSS animation)
- No TradingView watermark visible in empty state
- Stats show `—` (en-dash), not `--`

```css
.panel-loading::after {
  content: '';
  position: absolute; inset: 0;
  background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.03) 50%, transparent 100%);
  animation: shimmer 1.5s ease infinite;
  background-size: 200% 100%;
}
@keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
```

---

## File Changes Required

### Modified files
- `aggdash/frontend/index.html` — full rewrite (layout restructure)
- `aggdash/frontend/css/dashboard.css` — full rewrite (new token system)
- `aggdash/frontend/js/charts.js` — chart theme update + panel height logic
- `aggdash/frontend/js/main.js` — sidebar logic, 4-panel row init, liq feed toggle

### New files
- `aggdash/frontend/css/tokens.css` — design token definitions
- `aggdash/frontend/css/components.css` — reusable component styles

### Backend: no changes required

---

## Implementation Phases

### Phase 1 — Layout & Structure (this PR)
1. New header (2-row)
2. Stats strip (horizontal scroll)
3. Controls bar restructure
4. 4-panel bottom row (horizontal grid)
5. Signal sidebar placeholder
6. New CSS token system

### Phase 2 — Visual polish (follow-up PR)
1. Panel top-border accent colors
2. Squeeze state animations (sidebar + basis panel glow)
3. Loading skeletons
4. Resize handle on price panel

### Phase 3 — Mobile defense (follow-up)
1. Desktop-only notice for < 900px
2. Sidebar collapse for 1200–1440px

---

## Success Criteria

- [ ] All 7 chart panels readable at 1440px viewport
- [ ] Stats bar never wraps — horizontal scroll only
- [ ] Bottom 4 panels have minimum 100px chart height each
- [ ] Signal sidebar visible without scrolling
- [ ] Liquidation feed collapsible
- [ ] Zero layout overflow on 1440×900
- [ ] Exchange colors consistent across all panels
- [ ] Loading shimmer in place of TV watermarks on empty panels

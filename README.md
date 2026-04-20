# SPX Calendar Dashboard

A single-page decision dashboard for entering SPX calendar spreads. It reads the full CBOE delayed option chain, computes dealer gamma exposure, locates the zero-gamma flip strike, measures the IV term-structure spread between a short and long leg, and returns an **ENTER / WAIT / AVOID** verdict.

> Uses CBOE **delayed** quotes (~15 min lag). Fine for positioning-based entries; not for scalping.

---

## What it tells you

Three signals, one verdict.

| Signal | Question it answers |
|---|---|
| **Net GEX** (dealer gamma, $ per 1% SPX move) | Is the market currently mean-reverting or trending? |
| **Flip strike** vs spot | Are we *locally* in positive-gamma territory or below it? |
| **IV differential** `IV(short) − IV(long)` at ATM | Is there a term-structure edge to sell against? |

Logic (see [`backend/signals.py`](backend/signals.py)):

- 🔴 **AVOID** — `iv_diff ≤ 0` (no calendar edge) **or** `spot < flip` **and** `GEX < 0` (trend regime)
- 🟢 **ENTER** — positive gamma regime **and** positive IV diff **and** both at/above 50th percentile of 20-day history
- 🟡 **WAIT** — mixed

---

## Run it

```bash
git clone https://github.com/kellychenjia/spx-calendar-dashboard.git
cd spx-calendar-dashboard
./run.sh
```

Then open **http://127.0.0.1:8765**.

`run.sh` creates a venv on first run, installs deps, and launches uvicorn. `Ctrl+C` to stop.

### Dependencies
- Python 3.10+
- `fastapi`, `uvicorn`, `httpx` (auto-installed by `run.sh`)

---

## How to use it (morning workflow)

1. **Glance at the verdict pill** at the top — 3-second read.
2. **Scan the four reason bullets** underneath for *why*.
3. **IV Differential tile** — must be positive. Negative = no trade, full stop.
4. **Spot vs Flip** — spot ≥ flip means you're in a stabilizing dealer flow zone.
5. **Net Gamma by Strike chart** — the tallest green bar above spot is the call wall (upside magnet); tallest red bar below is the put wall (downside marker).
6. **Calendar structure card** — pre-picks short (~7 DTE) and long (~30 DTE) expiries. Dropdowns let you probe any pair; IV diff recomputes live.

One snapshot is persisted per calendar day to `data/snapshots.json`. After ~20 trading days, the History chart populates and percentile context unlocks.

---

## How the numbers are computed

### Net GEX ($ per 1% move)

Standard dealer-assumption convention (dealers long calls, short puts):

```
call_gex = +gamma * OI * 100 * spot^2 * 0.01
put_gex  = -gamma * OI * 100 * spot^2 * 0.01
```

Summed across every strike and expiry in the chain.

### Flip strike

The strike `K*` where the cumulative (low→high) net-GEX curve crosses zero, linear-interpolated between the two bracketing strikes. Approximates the "zero-gamma" level at which dealer hedging flow flips from destabilizing to stabilizing.

### IV differential

At the ATM strike common to both selected expiries:

```
diff = IV(short_expiry) - IV(long_expiry)
```

Positive = **backwardation** (front richer than back) = calendar edge exists.
Negative = **contango** (normal curve) = you'd be paying up for the long, no structural edge.

Historical percentile is computed over the last 20 daily snapshots once enough history accrues.

---

## Layout

```
backend/
  main.py        FastAPI app + /api/snapshot and /api/history endpoints
  cboe.py        CBOE delayed-quote fetcher + option-chain parser
  analytics.py   GEX per-strike, flip strike, IV differential
  signals.py     ENTER/WAIT/AVOID band logic + reason strings
  history.py     Daily snapshot persistence and percentile helper
static/
  index.html     Single-page dashboard
  app.js         Chart.js rendering + refresh logic
  style.css      Dark theme
data/
  snapshots.json (gitignored) daily persisted rows
run.sh           One-shot launcher (creates venv, installs, starts server)
```

---

## Defaults

Configured in [`backend/analytics.py`](backend/analytics.py):

- Short leg bucket: **1–25 DTE**, target 7 DTE
- Long leg bucket: **20–60 DTE**, target 30 DTE
- Strike bins: **25 points**, band **±6% of spot** around the gamma profile chart
- Auto-refresh: **5 minutes** in the browser; **60-second** server-side cache

---

## Disclaimer

Personal research tool. Not investment advice. Delayed data. Trade at your own risk.

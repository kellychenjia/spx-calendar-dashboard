"""FastAPI backend serving the SPX calendar-spread dashboard."""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .analytics import (
    LONG_DTE_RANGE,
    LONG_DTE_TARGET,
    SHORT_DTE_RANGE,
    SHORT_DTE_TARGET,
    gex_profile,
    iv_differential,
)
from .cboe import Chain, expiries_in_range, fetch_chain, pick_expiry
from .history import Snapshot, percentile, recent, record, history
from .signals import evaluate

app = FastAPI(title="SPX Calendar Dashboard")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Simple in-memory cache so multiple endpoint calls within a short window reuse one fetch.
_cache: dict = {"chain": None, "fetched_at": None}
_CACHE_TTL_SEC = 60


async def _get_chain() -> Chain:
    now = datetime.now()
    if _cache["chain"] and _cache["fetched_at"] and (now - _cache["fetched_at"]).total_seconds() < _CACHE_TTL_SEC:
        return _cache["chain"]
    chain = await fetch_chain()
    _cache["chain"] = chain
    _cache["fetched_at"] = now
    return chain


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/snapshot")
async def api_snapshot(
    short_expiry: str | None = Query(None, description="YYYY-MM-DD override for short leg"),
    long_expiry: str | None = Query(None, description="YYYY-MM-DD override for long leg"),
    persist: bool = Query(True, description="Record today's snapshot to history"),
) -> dict:
    chain = await _get_chain()
    gex = gex_profile(chain)

    short_exp = date.fromisoformat(short_expiry) if short_expiry else pick_expiry(chain, *SHORT_DTE_RANGE, SHORT_DTE_TARGET)
    long_exp = date.fromisoformat(long_expiry) if long_expiry else pick_expiry(chain, *LONG_DTE_RANGE, LONG_DTE_TARGET)
    if short_exp is None or long_exp is None:
        raise HTTPException(500, "No expiries available in configured DTE ranges.")
    if long_exp <= short_exp:
        raise HTTPException(400, "Long leg must expire after short leg.")

    iv = iv_differential(chain, short_exp, long_exp)

    # Percentiles based on persisted history.
    gex_pct = percentile(recent("gex_total"), gex.total)
    iv_pct = percentile(recent("iv_diff"), iv.diff if iv else 0.0) if iv else None

    signal = evaluate(gex, iv, chain.spot, gex_pct, iv_pct)

    if persist:
        record(Snapshot(
            asof_date=chain.asof.date().isoformat(),
            asof_time=chain.asof.isoformat(),
            spot=chain.spot,
            gex_total=gex.total,
            gex_short_bucket=gex.short_bucket_total,
            gex_long_bucket=gex.long_bucket_total,
            flip_strike=gex.flip_strike,
            iv_short=iv.short_iv if iv else None,
            iv_long=iv.long_iv if iv else None,
            iv_diff=iv.diff if iv else None,
        ))

    # Aggregate per-strike GEX into wider bins within +/- 6% of spot for a readable bar chart.
    band = 0.06 * chain.spot
    bin_width = 25.0  # pts
    bin_center = round(chain.spot / bin_width) * bin_width
    bins: dict[float, dict[str, float]] = {}
    for p in gex.by_strike:
        if abs(p.strike - chain.spot) > band:
            continue
        key = round((p.strike - bin_center) / bin_width) * bin_width + bin_center
        b = bins.setdefault(key, {"calls": 0.0, "puts": 0.0})
        b["calls"] += p.call_gex
        b["puts"] += p.put_gex
    trimmed = [
        {"strike": k, "calls": v["calls"], "puts": v["puts"], "net": v["calls"] + v["puts"]}
        for k, v in sorted(bins.items())
    ]

    # Expiry picker options: list all expiries in each bucket.
    short_options = [e.isoformat() for e in expiries_in_range(chain, *SHORT_DTE_RANGE)]
    long_options = [e.isoformat() for e in expiries_in_range(chain, *LONG_DTE_RANGE)]

    return {
        "asof": chain.asof.isoformat(),
        "spot": chain.spot,
        "gex": {
            "total": gex.total,
            "short_bucket_total": gex.short_bucket_total,
            "long_bucket_total": gex.long_bucket_total,
            "flip_strike": gex.flip_strike,
            "call_wall": gex.call_wall,
            "put_wall": gex.put_wall,
            "by_strike": trimmed,
            "bin_width": bin_width,
            "percentile": gex_pct,
        },
        "iv_diff": None if iv is None else {
            "short_expiry": iv.short_expiry.isoformat(),
            "long_expiry": iv.long_expiry.isoformat(),
            "short_dte": iv.short_dte,
            "long_dte": iv.long_dte,
            "atm_strike": iv.atm_strike,
            "short_iv": iv.short_iv,
            "long_iv": iv.long_iv,
            "diff": iv.diff,
            "diff_pts": iv.diff_pts,
            "percentile": iv_pct,
        },
        "signal": {
            "verdict": signal.verdict,
            "headline": signal.headline,
            "reasons": signal.reasons,
        },
        "suggested_trade": {
            "short_expiry": short_exp.isoformat(),
            "long_expiry": long_exp.isoformat(),
            "strike": iv.atm_strike if iv else None,
            "description": (
                f"Sell {short_exp.isoformat()} call/put @ {iv.atm_strike:.0f}, "
                f"buy {long_exp.isoformat()} same strike."
            ) if iv else None,
        },
        "expiry_options": {
            "short": short_options,
            "long": long_options,
        },
        "dte_buckets": {
            "short": list(SHORT_DTE_RANGE),
            "long": list(LONG_DTE_RANGE),
        },
    }


@app.get("/api/history")
async def api_history() -> dict:
    rows = history()
    return {"count": len(rows), "rows": rows}

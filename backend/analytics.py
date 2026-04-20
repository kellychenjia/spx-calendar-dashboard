"""GEX + IV differential analytics.

GEX convention (SpotGamma/SqueezeMetrics, dealer assumption = long calls, short puts):
  call_gex = +gamma * OI * 100 * spot^2 * 0.01   (dollar gamma per 1% SPX move)
  put_gex  = -gamma * OI * 100 * spot^2 * 0.01
  total    = sum over all strikes & expiries
Net positive -> dealers long gamma -> mean-reverting (sell rallies, buy dips).
Net negative -> dealers short gamma -> trending/volatile (chase moves).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from .cboe import Chain, Contract, contracts_for_expiry, nearest_strike

# Short leg target ~ 7 DTE within 1-25; long leg target ~ 30 DTE within 20-60.
SHORT_DTE_RANGE = (1, 25)
LONG_DTE_RANGE = (20, 60)
SHORT_DTE_TARGET = 7
LONG_DTE_TARGET = 30
CONTRACT_MULT = 100


def contract_gex(c: Contract, spot: float) -> float:
    """Dealer-assumption dollar gamma per 1% spot move, in $."""
    sign = 1 if c.right == "C" else -1
    return sign * c.gamma * c.open_interest * CONTRACT_MULT * spot * spot * 0.01


@dataclass
class GexByStrike:
    strike: float
    net_gex: float
    call_gex: float
    put_gex: float


@dataclass
class GexProfile:
    total: float
    short_bucket_total: float
    long_bucket_total: float
    flip_strike: float | None
    by_strike: list[GexByStrike]   # full profile, sorted by strike
    call_wall: float | None        # strike with max positive net GEX above spot
    put_wall: float | None         # strike with max negative net GEX below spot


def gex_profile(chain: Chain,
                short_dte: tuple[int, int] = SHORT_DTE_RANGE,
                long_dte: tuple[int, int] = LONG_DTE_RANGE) -> GexProfile:
    spot = chain.spot

    # All contracts across all expiries contribute to total GEX / flip.
    by_strike_calls: dict[float, float] = defaultdict(float)
    by_strike_puts: dict[float, float] = defaultdict(float)

    short_total = 0.0
    long_total = 0.0

    for c in chain.contracts:
        g = contract_gex(c, spot)
        if c.right == "C":
            by_strike_calls[c.strike] += g
        else:
            by_strike_puts[c.strike] += g
        if short_dte[0] <= c.dte <= short_dte[1]:
            short_total += g
        if long_dte[0] <= c.dte <= long_dte[1]:
            long_total += g

    strikes = sorted(set(by_strike_calls) | set(by_strike_puts))
    profile = [
        GexByStrike(
            strike=k,
            call_gex=by_strike_calls.get(k, 0.0),
            put_gex=by_strike_puts.get(k, 0.0),
            net_gex=by_strike_calls.get(k, 0.0) + by_strike_puts.get(k, 0.0),
        )
        for k in strikes
    ]
    total = sum(p.net_gex for p in profile)

    flip = _flip_strike(profile)

    call_wall = None
    put_wall = None
    above = [p for p in profile if p.strike > spot]
    below = [p for p in profile if p.strike < spot]
    if above:
        best = max(above, key=lambda p: p.net_gex)
        if best.net_gex > 0:
            call_wall = best.strike
    if below:
        worst = min(below, key=lambda p: p.net_gex)
        if worst.net_gex < 0:
            put_wall = worst.strike

    return GexProfile(
        total=total,
        short_bucket_total=short_total,
        long_bucket_total=long_total,
        flip_strike=flip,
        by_strike=profile,
        call_wall=call_wall,
        put_wall=put_wall,
    )


def _flip_strike(profile: list[GexByStrike]) -> float | None:
    """Strike K* where cumulative net GEX (low->high) crosses zero.
    Approximation of the 'zero gamma' level."""
    if not profile:
        return None
    running = 0.0
    target = sum(p.net_gex for p in profile) / 2.0  # midpoint of cumulative
    # Another common approach: find where running cumulative == 0 starting
    # from the lowest strike. We'll use that — more intuitive.
    prev_k, prev_cum = None, 0.0
    for p in profile:
        new_cum = running + p.net_gex
        if prev_k is not None and prev_cum * new_cum < 0:
            # linear interpolate between prev_k and p.strike
            frac = -prev_cum / (new_cum - prev_cum) if new_cum != prev_cum else 0.5
            return prev_k + frac * (p.strike - prev_k)
        prev_k, prev_cum = p.strike, new_cum
        running = new_cum
    return None


@dataclass
class IvDiff:
    short_expiry: date
    long_expiry: date
    short_dte: int
    long_dte: int
    atm_strike: float
    short_iv: float         # decimal, e.g. 0.143
    long_iv: float
    diff: float             # short_iv - long_iv, decimal
    diff_pts: float         # diff * 100 (vol points)


def iv_differential(chain: Chain,
                    short_expiry: date,
                    long_expiry: date,
                    strike: float | None = None) -> IvDiff | None:
    short_contracts = contracts_for_expiry(chain, short_expiry)
    long_contracts = contracts_for_expiry(chain, long_expiry)
    if not short_contracts or not long_contracts:
        return None

    target = strike if strike is not None else chain.spot
    common_strikes = {c.strike for c in short_contracts} & {c.strike for c in long_contracts}
    if not common_strikes:
        return None
    atm = min(common_strikes, key=lambda k: abs(k - target))

    # Use call IV at ATM (calls and puts should match near ATM via parity; we use calls).
    def _iv(cs: list[Contract], k: float) -> float | None:
        for c in cs:
            if c.strike == k and c.right == "C" and c.iv > 0:
                return c.iv
        # fallback: average of non-zero C/P IVs at that strike
        ivs = [c.iv for c in cs if c.strike == k and c.iv > 0]
        return sum(ivs) / len(ivs) if ivs else None

    siv = _iv(short_contracts, atm)
    liv = _iv(long_contracts, atm)
    if siv is None or liv is None:
        return None

    diff = siv - liv
    # short_dte / long_dte from a sample contract
    short_dte = short_contracts[0].dte
    long_dte = long_contracts[0].dte
    return IvDiff(
        short_expiry=short_expiry,
        long_expiry=long_expiry,
        short_dte=short_dte,
        long_dte=long_dte,
        atm_strike=atm,
        short_iv=siv,
        long_iv=liv,
        diff=diff,
        diff_pts=diff * 100,
    )

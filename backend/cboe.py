"""CBOE delayed-quote fetcher and option-chain parser."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

import httpx

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
TICKER_RE = re.compile(r"^(SPX|SPXW)(\d{6})([CP])(\d{8})$")


@dataclass(frozen=True)
class Contract:
    root: str          # SPX or SPXW
    expiry: date
    right: str         # "C" or "P"
    strike: float
    dte: int
    bid: float
    ask: float
    mid: float
    iv: float          # decimal (0.15 = 15%)
    delta: float
    gamma: float
    open_interest: int
    volume: int


@dataclass(frozen=True)
class Chain:
    spot: float
    asof: datetime
    contracts: list[Contract]


def parse_ticker(sym: str) -> tuple[str, date, str, float] | None:
    m = TICKER_RE.match(sym)
    if not m:
        return None
    root, yymmdd, right, strike8 = m.groups()
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    try:
        exp = date(2000 + yy, mm, dd)
    except ValueError:
        return None
    return root, exp, right, int(strike8) / 1000.0


async def fetch_chain(today: date | None = None, client: httpx.AsyncClient | None = None) -> Chain:
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        r = await client.get(CBOE_URL, headers={"User-Agent": "spx-cal-dashboard/1.0"})
        r.raise_for_status()
        payload = r.json()
    finally:
        if owns_client:
            await client.aclose()

    data = payload["data"]
    spot = float(data["current_price"])
    asof = datetime.fromisoformat(payload["timestamp"].replace("Z", ""))
    today = today or asof.date()

    contracts: list[Contract] = []
    for row in data["options"]:
        parsed = parse_ticker(row["option"])
        if not parsed:
            continue
        root, expiry, right, strike = parsed
        dte = (expiry - today).days
        if dte < 0:
            continue
        bid = float(row.get("bid") or 0.0)
        ask = float(row.get("ask") or 0.0)
        mid = (bid + ask) / 2.0 if bid and ask else (bid or ask or 0.0)
        contracts.append(Contract(
            root=root,
            expiry=expiry,
            right=right,
            strike=strike,
            dte=dte,
            bid=bid,
            ask=ask,
            mid=mid,
            iv=float(row.get("iv") or 0.0),
            delta=float(row.get("delta") or 0.0),
            gamma=float(row.get("gamma") or 0.0),
            open_interest=int(row.get("open_interest") or 0),
            volume=int(row.get("volume") or 0),
        ))
    return Chain(spot=spot, asof=asof, contracts=contracts)


def expiries_in_range(chain: Chain, dte_min: int, dte_max: int) -> list[date]:
    seen: dict[date, int] = {}
    for c in chain.contracts:
        if dte_min <= c.dte <= dte_max:
            seen.setdefault(c.expiry, c.dte)
    return sorted(seen.keys())


def pick_expiry(chain: Chain, dte_min: int, dte_max: int, target_dte: int) -> date | None:
    """Nearest expiry to target_dte within [dte_min, dte_max]."""
    candidates = expiries_in_range(chain, dte_min, dte_max)
    if not candidates:
        return None
    dte_by_exp = {c.expiry: c.dte for c in chain.contracts}
    return min(candidates, key=lambda e: abs(dte_by_exp[e] - target_dte))


def contracts_for_expiry(chain: Chain, expiry: date) -> list[Contract]:
    return [c for c in chain.contracts if c.expiry == expiry]


def nearest_strike(contracts: Iterable[Contract], target: float) -> float | None:
    strikes = {c.strike for c in contracts}
    if not strikes:
        return None
    return min(strikes, key=lambda k: abs(k - target))

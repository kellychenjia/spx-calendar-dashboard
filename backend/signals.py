"""Entry-signal band logic.

Three tiers:
  ENTER  - positive gamma regime + positive front-IV richness + both at/above median history
  WAIT   - mixed signals, not a clear go/no-go
  AVOID  - negative gamma regime (spot below flip AND total GEX negative)
           OR IV diff <= 0 (no term-structure edge)

Reasons: human-readable bullets rendered in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .analytics import GexProfile, IvDiff

Verdict = Literal["ENTER", "WAIT", "AVOID"]


@dataclass
class Signal:
    verdict: Verdict
    headline: str
    reasons: list[str]
    gex_percentile: float | None
    iv_diff_percentile: float | None


def evaluate(gex: GexProfile,
             iv: IvDiff | None,
             spot: float,
             gex_pct: float | None,
             iv_pct: float | None) -> Signal:
    reasons: list[str] = []

    # Regime diagnosis
    pos_gamma = gex.total > 0
    above_flip = gex.flip_strike is None or spot >= gex.flip_strike
    regime_good = pos_gamma and above_flip
    regime_bad = (not pos_gamma) and (not above_flip)

    # IV diff
    iv_edge = iv is not None and iv.diff > 0
    iv_negative = iv is not None and iv.diff <= 0

    # Percentile filters (only apply when we have history)
    gex_strong = gex_pct is None or gex_pct >= 50
    iv_strong = iv_pct is None or iv_pct >= 50

    if regime_bad or iv_negative:
        verdict: Verdict = "AVOID"
    elif regime_good and iv_edge and gex_strong and iv_strong:
        verdict = "ENTER"
    else:
        verdict = "WAIT"

    # Reasons (positive + negative)
    if pos_gamma:
        reasons.append(f"Net GEX positive (+${gex.total/1e9:.2f}B per 1%) - dealers long gamma, mean-reverting.")
    else:
        reasons.append(f"Net GEX negative (${gex.total/1e9:.2f}B per 1%) - dealers short gamma, trend risk.")

    if gex.flip_strike is not None:
        rel = spot - gex.flip_strike
        pos = "above" if rel >= 0 else "below"
        reasons.append(f"Spot is {abs(rel):.0f} pts {pos} flip strike ({gex.flip_strike:.0f}).")

    if iv is None:
        reasons.append("IV differential unavailable (missing ATM quotes).")
    elif iv.diff > 0:
        reasons.append(
            f"Front IV richer than back by {iv.diff_pts:+.2f} pts "
            f"({iv.short_iv*100:.1f}% @ {iv.short_dte}d vs {iv.long_iv*100:.1f}% @ {iv.long_dte}d) - calendar edge.")
    else:
        reasons.append(
            f"Front IV NOT richer than back ({iv.diff_pts:+.2f} pts) - no term-structure edge today.")

    if gex_pct is not None:
        reasons.append(f"Today's GEX is at {gex_pct:.0f}th percentile of last 20d.")
    if iv_pct is not None:
        reasons.append(f"Today's IV diff is at {iv_pct:.0f}th percentile of last 20d.")
    if gex_pct is None and iv_pct is None:
        reasons.append("Insufficient history for percentile context (need ~20 daily snapshots).")

    headline_map = {
        "ENTER": "Conditions favor a calendar entry today.",
        "WAIT":  "Mixed signals - hold off or size small.",
        "AVOID": "Do not enter calendars today.",
    }
    return Signal(
        verdict=verdict,
        headline=headline_map[verdict],
        reasons=reasons,
        gex_percentile=gex_pct,
        iv_diff_percentile=iv_pct,
    )

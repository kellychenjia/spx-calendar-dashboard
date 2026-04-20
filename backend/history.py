"""Daily snapshot persistence for percentile calculations.

One JSON file on disk. Append one row per calendar day (last write wins).
Kept simple on purpose — the goal is 20-60 day rolling percentiles.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "snapshots.json"
WINDOW = 20


@dataclass
class Snapshot:
    asof_date: str      # YYYY-MM-DD
    asof_time: str      # ISO timestamp
    spot: float
    gex_total: float
    gex_short_bucket: float
    gex_long_bucket: float
    flip_strike: float | None
    iv_short: float | None
    iv_long: float | None
    iv_diff: float | None


def _load() -> list[dict]:
    if not SNAPSHOT_PATH.exists():
        return []
    try:
        return json.loads(SNAPSHOT_PATH.read_text())
    except json.JSONDecodeError:
        return []


def _save(rows: list[dict]) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(rows, indent=2, default=str))


def record(snap: Snapshot) -> None:
    rows = _load()
    # last write wins per calendar day
    rows = [r for r in rows if r.get("asof_date") != snap.asof_date]
    rows.append(asdict(snap))
    rows.sort(key=lambda r: r["asof_date"])
    _save(rows)


def history() -> list[dict]:
    return _load()


def percentile(values: list[float], x: float) -> float | None:
    """Return percentile rank of x within values (0-100). None if insufficient."""
    vs = [v for v in values if v is not None]
    if len(vs) < 3:
        return None
    below = sum(1 for v in vs if v < x)
    equal = sum(1 for v in vs if v == x)
    return 100.0 * (below + 0.5 * equal) / len(vs)


def recent(field: str, window: int = WINDOW) -> list[float]:
    rows = _load()[-window:]
    return [r[field] for r in rows if r.get(field) is not None]

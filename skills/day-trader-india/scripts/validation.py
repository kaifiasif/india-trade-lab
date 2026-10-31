#!/usr/bin/env python3
"""Is an edge real, or luck? Two honest tests shared by both tournaments.

**Better than luck.** A strategy's net result at double costs is compared with
``twins`` (200) random-entry twins: the same number of trades on the same stocks, the
same stop distance, target and exits, but entries chosen at random. The *luck
percentile* is the share of twins the strategy beat. It must be at least
``min_luck_percentile`` (95) to count as proven, which also shows whether the entries
or only the exits do the work.

**Deflated Sharpe ratio** (Bailey and López de Prado, Journal of Portfolio Management
40(5), 2014). Try 40 variants and the best looks good by chance: flip 40 coins and one
lands heads five times. Every variant the tournaments ever test is recorded in
``trials.json``. The per-trade Sharpe ratio is then deflated for that number of trials
and for skew and fat tails. The result is the probability that the true Sharpe is
above what the luckiest of N trials would show. It must be at least ``min_dsr``
(0.95).

Both can only stop a strategy from trading. Neither says anything about the future.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

EULER = 0.5772156649015329
NORMAL = statistics.NormalDist()


def percentile_beaten(value: float, others: list[float]) -> float:
    """Share (0-100) of ``others`` strictly below ``value``; ties count half."""
    if not others:
        return 0.0
    below = sum(other < value for other in others)
    ties = sum(other == value for other in others)
    return round(100 * (below + ties / 2) / len(others), 1)


def sharpe(returns: list[float]) -> float | None:
    if len(returns) < 3:
        return None
    spread = statistics.pstdev(returns)
    return statistics.fmean(returns) / spread if spread > 0 else None


def _moments(returns: list[float]) -> tuple[float, float]:
    """Skew and (non-excess) kurtosis of the returns."""
    mean = statistics.fmean(returns)
    spread = statistics.pstdev(returns)
    if spread == 0:
        return 0.0, 3.0
    count = len(returns)
    skew = sum(((value - mean) / spread) ** 3 for value in returns) / count
    kurt = sum(((value - mean) / spread) ** 4 for value in returns) / count
    return skew, kurt


def deflated_sharpe(
    returns: list[float], trials: int, trial_sharpes: list[float] | None = None
) -> dict[str, Any]:
    """Probability that the true per-trade Sharpe beats the best of ``trials`` by luck."""
    observed = sharpe(returns)
    count = len(returns)
    if observed is None or count < 10:
        return {"dsr": None, "sharpe": observed, "trials": trials, "note": "too few trades"}
    trials = max(1, trials)
    skew, kurt = _moments(returns)
    if trial_sharpes and len(trial_sharpes) >= 2:
        variance = statistics.pvariance(trial_sharpes)
    else:
        variance = (1 + 0.5 * observed**2) / count  # Variance of the Sharpe estimate itself.
    if trials > 1:
        expected_max = math.sqrt(variance) * (
            (1 - EULER) * NORMAL.inv_cdf(1 - 1 / trials)
            + EULER * NORMAL.inv_cdf(1 - 1 / (trials * math.e))
        )
    else:
        expected_max = 0.0
    denominator = 1 - skew * observed + (kurt - 1) / 4 * observed**2
    if denominator <= 0:
        return {"dsr": None, "sharpe": observed, "trials": trials, "note": "returns too irregular"}
    z = (observed - expected_max) * math.sqrt(count - 1) / math.sqrt(denominator)
    return {
        "dsr": round(NORMAL.cdf(z), 4),
        "sharpe": round(observed, 4),
        "expected_max_sharpe_by_luck": round(expected_max, 4),
        "trials": trials,
        "skew": round(skew, 3),
        "kurtosis": round(kurt, 3),
    }


def variant_id(desk: str, strategy: str, assumptions: dict) -> str:
    payload = json.dumps(
        {"desk": desk, "strategy": strategy, "assumptions": assumptions}, sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def record_trials(folder: Path, desk: str, rows: list[dict]) -> dict[str, Any]:
    """Add this run's variants to trials.json; return how many distinct ones this desk has tried."""
    path = folder / "trials.json"
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        registry = {"variants": {}}
    for row in rows:
        entry = registry["variants"].setdefault(row["id"], {"desk": desk, "strategy": row["strategy"],
                                                            "first_seen": dt.date.today().isoformat()})  # fmt: skip
        entry["last_seen"] = dt.date.today().isoformat()
        if row.get("sharpe") is not None:
            entry["sharpe"] = row["sharpe"]
    temporary = path.with_name(".trials.json.tmp")
    temporary.write_text(json.dumps(registry, indent=1) + "\n", encoding="utf-8")
    temporary.replace(path)
    mine = [item for item in registry["variants"].values() if item["desk"] == desk]
    return {
        "trials": len(mine),
        "sharpes": [item["sharpe"] for item in mine if item.get("sharpe") is not None],
    }

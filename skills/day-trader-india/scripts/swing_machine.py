#!/usr/bin/env python3
"""Swing Monte Carlo: thousands of possible next few sessions for one swing plan, in rupees.

The intraday Time Machine replays the rest of one day from five-minute bars. A
swing trade lives across nights, so this replays whole sessions instead.

1. **The pool.** The stock's own last ``lookback`` (250) daily candles from
   ``scan.sqlite``, each turned into four ratios to the close before it: open, high,
   low and close. The open's ratio *is* the overnight gap, so gaps in the replays
   are as big and as frequent as this stock's real ones.
2. **One replay.** Enter at the plan's price. For each session up to the holding
   limit, draw a past day at random and scale it to the current price. The first
   day starts from the entry. Each day:
   - an open at or below the stop exits at the open (a gap through the stop: worse
     than planned);
   - a low at or below the stop exits at the stop (stop first when a day touches
     both);
   - a high at or above the target exits at the target;
   - otherwise the live desk's end-of-day rules apply: breakeven plus costs once the
     close is +1R, then a trail under the last two lows after +1.5R.

   After the last session it exits at the close.
3. **Rupees after costs.** Every exit is converted to profit or loss for the
   quantity the swing book would buy. Both sides pay fees, delivery charges and
   slippage.

It reports the odds of target, stop and time exits, the chance of each by day 1,
2 ... N, and the profit and loss distribution: expected value, median, the middle
half, the 5% worst and best outcomes, and the average of the worst 5%. The seed
(19) makes every run repeatable. It is built from the stock's own history, not a
forecast; a result, a block deal or a market shock can do what that history never
did.
"""

from __future__ import annotations

import datetime as dt
import random
import statistics
from typing import Any

MIN_DAYS = 60
MAX_REPLAYS = 20_000
BINS = 24


def daily_pool(bars: list[dict], lookback: int = 250) -> list[tuple[float, float, float, float]]:
    """Ratios of each day's open, high, low and close to the close before it."""
    recent = bars[-(lookback + 1) :]
    pool = []
    for previous, bar in zip(recent, recent[1:], strict=False):
        base = previous["close"]
        if base <= 0 or min(bar["open"], bar["high"], bar["low"], bar["close"]) <= 0:
            continue
        pool.append(tuple(bar[key] / base for key in ("open", "high", "low", "close")))
    return pool


def _percentile(ordered: list[float], share: float) -> float:
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return ordered[index]


def simulate(
    pool: list[tuple[float, float, float, float]],
    entry: float,
    stop: float,
    target: float,
    hold_days: int,
    qty: int,
    costs: dict,
    replays: int = 5000,
    seed: int = 19,
) -> dict[str, Any]:
    """Odds, day-by-day probabilities and the rupee distribution for one plan. Pure."""
    if len(pool) < MIN_DAYS:
        raise ValueError(f"Need {MIN_DAYS} stored daily candles for this stock; have {len(pool)}")
    if not stop < entry < target:
        raise ValueError("A long swing plan needs stop < entry < target")
    if not 1 <= hold_days <= 20 or qty < 1 or not 200 <= replays <= MAX_REPLAYS:
        raise ValueError("Hold 1-20 sessions, at least one share, 200-20,000 replays")
    rng = random.Random(seed)
    risk = entry - stop
    slip = float(costs.get("slippage_bps", 5)) / 10_000
    fee_rate = float(costs.get("fee_bps", 12)) / 10_000
    fee_flat = float(costs.get("fee_flat_inr", 20))

    exact = bool(costs.get("exact"))

    def fee(price: float, which: str = "buy") -> float:
        if exact:
            import charges

            return charges.fee("delivery", which, price, qty)
        return fee_flat + price * qty * fee_rate

    bought = entry * (1 + slip)
    per_share_costs = (fee(entry, "buy") + fee(entry, "sell")) / qty
    exits = {"target": 0, "stop": 0, "gap stop": 0, "trailing stop": 0, "time": 0}
    target_by = [0] * hold_days
    stop_by = [0] * hold_days
    pnl, r_values = [], []
    for _ in range(replays):
        price, current, prior_low = entry, stop, None
        why, exit_price, day_out = "time", None, hold_days - 1
        for day in range(hold_days):
            o, h, low, c = rng.choice(pool)
            if day == 0:  # The entry day starts from the entry price.
                bar_open, high, bar_low, close = (
                    entry,
                    entry * h / o,
                    entry * low / o,
                    entry * c / o,
                )
            else:
                bar_open, high, bar_low, close = price * o, price * h, price * low, price * c
            if day and bar_open <= current:
                why, exit_price = ("gap stop" if current == stop else "trailing stop"), bar_open
            elif bar_low <= current:
                why, exit_price = ("stop" if current == stop else "trailing stop"), current
            elif high >= target:
                why, exit_price = "target", max(target, bar_open) if day else target
            if exit_price is not None:
                day_out = day
                break
            gained = (close - entry) / risk
            if gained >= 1:
                current = max(current, entry + per_share_costs)
            if gained >= 1.5:
                current = max(
                    current, min(bar_low, prior_low if prior_low is not None else bar_low)
                )
            prior_low, price = bar_low, close
        if exit_price is None:
            exit_price = price
        exits[why] += 1
        if why == "target":
            target_by[day_out] += 1
        elif why != "time":
            stop_by[day_out] += 1
        sold = exit_price * (1 - slip)
        pnl.append((sold - bought) * qty - fee(bought, "buy") - fee(sold, "sell"))
        r_values.append((sold - bought) / risk)
    ordered = sorted(pnl)
    worst = ordered[: max(1, replays // 20)]
    low_edge, high_edge = ordered[0], ordered[-1]
    width = (high_edge - low_edge) / BINS or 1.0
    counts = [0] * BINS
    for value in pnl:
        counts[min(BINS - 1, int((value - low_edge) / width))] += 1
    share = {key: round(100 * value / replays, 1) for key, value in exits.items()}
    cumulative_target, cumulative_stop, running_t, running_s = [], [], 0, 0
    for day in range(hold_days):
        running_t += target_by[day]
        running_s += stop_by[day]
        cumulative_target.append(round(100 * running_t / replays, 1))
        cumulative_stop.append(round(100 * running_s / replays, 1))
    return {
        "replays": replays,
        "seed": seed,
        "days_in_pool": len(pool),
        "hold_days": hold_days,
        "qty": qty,
        "exits_pct": share,
        "target_pct": share["target"],
        "stopped_pct": round(share["stop"] + share["gap stop"] + share["trailing stop"], 1),
        "time_exit_pct": share["time"],
        "by_day": [
            {
                "day": day + 1,
                "target_pct": cumulative_target[day],
                "stopped_pct": cumulative_stop[day],
            }
            for day in range(hold_days)
        ],
        "expected_pnl_inr": round(statistics.fmean(pnl), 2),
        "median_pnl_inr": round(_percentile(ordered, 0.5), 2),
        "p5_pnl_inr": round(_percentile(ordered, 0.05), 2),
        "p25_pnl_inr": round(_percentile(ordered, 0.25), 2),
        "p75_pnl_inr": round(_percentile(ordered, 0.75), 2),
        "p95_pnl_inr": round(_percentile(ordered, 0.95), 2),
        "worst_5pct_avg_inr": round(statistics.fmean(worst), 2),
        "worst_inr": round(ordered[0], 2),
        "profit_pct": round(100 * sum(value > 0 for value in pnl) / replays, 1),
        "average_r": round(statistics.fmean(r_values), 3),
        "histogram": {
            "from_inr": round(low_edge, 2),
            "width_inr": round(width, 2),
            "counts": counts,
        },
        "planned_loss_inr": round(
            (bought - stop * (1 - slip)) * qty + fee(bought, "buy") + fee(stop, "sell"), 2
        ),
        "exact_charges": exact,
    }


def summary(result: dict) -> str:
    """One honest line from the numbers."""
    expected = result["expected_pnl_inr"]
    return (
        f"Expected {'+' if expected >= 0 else '−'}₹{abs(expected):,.0f} a trade after costs over "
        f"{result['replays']:,} replays: {result['target_pct']}% reach the target within "
        f"{result['hold_days']} sessions, {result['stopped_pct']}% are stopped, "
        f"{result['time_exit_pct']}% time out. One in twenty loses "
        f"₹{abs(min(result['p5_pnl_inr'], 0)):,.0f} or more"
        + (
            f"; gaps through the stop in {result['exits_pct']['gap stop']}%."
            if result["exits_pct"]["gap stop"]
            else "."
        )
    )


def for_plan(
    bars: list[dict],
    entry: float,
    stop: float,
    target: float,
    hold_days: int,
    qty: int,
    costs: dict,
    replays: int = 5000,
    seed: int = 19,
) -> dict[str, Any]:
    result = simulate(daily_pool(bars), entry, stop, target, hold_days, qty, costs, replays, seed)
    result["summary"] = summary(result)
    result["as_of"] = bars[-1]["date"] if bars else None
    result["computed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return result

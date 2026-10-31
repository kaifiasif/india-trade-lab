#!/usr/bin/env python3
"""Time Machine: replays every likely outcome of a trade plan before any money is at risk.

Takes ``desk/plan.json`` (entry, stop, target) and asks: if the rest of today plays
out like this stock's own recent sessions, how often does the plan hit the target
first, the stop first, or neither by the square-off?

1. **The pool.** Complete stored NSE sessions for the stock (``history.sqlite``,
   the same 180 days the strategy tournament uses) before the plan's date: all 75
   five-minute bars, 09:15-15:30. Each bar becomes four ratios to the close before
   it: open, high, low and close.
2. **One replay.** Start at the entry. For each bar left until the square-off,
   draw a past bar from the same time of day (plus or minus ``window`` bars) at
   random and scale it to the current price. Bar by bar it checks the stop first,
   then the target. A bar that touches both counts as the stop, and a gap below
   the stop exits at the bar's open (worse than the stop), as the tournament does.
3. **10,000 replays** (seed 19, so anyone can repeat it) give the odds: target
   first, stop first, neither (still open at the square-off), and green (target
   first, or above the entry at the square-off). R is +target_r at the target,
   about -1 at the stop, and otherwise the distance from the entry divided by the risk.
4. **The history.** The plan's own rule (same opening range, stop distance and
   target R) runs again on each past session: what really happened, not a simulation.
5. **The verdict** weighs the target's size. A 2R target only has to come first in
   1 of 3 decided replays to break even, a 1R target in 1 of 2. Within 5 points of
   break-even is "close to a coin flip" (1R) or "close to break-even"; 5-15 points
   "leans"; 15 or more "strongly". Costs are then charged in R.

A simulation built from the stock's own bars, not a prediction. Results, news and
circuit limits can do things those sessions never did. Read only: it never sizes,
places or changes anything.

    python3 time_machine.py run                       # desk/plan.json, 10,000 replays, seed 19
    python3 time_machine.py run --write               # also save desk/timemachine.json
    python3 time_machine.py run --symbol INFY --date 2026-10-29 --entry 1612.4 \
        --stop 1596.2 --target 1644.8 --entry-time 09:45
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
SESSION_BARS = 75  # 09:15-15:30 in five-minute bars.
MIN_SESSIONS = 20
MAX_REPLAYS = 50_000
VERDICTS = {
    "coin_flip": "Close to a coin flip",
    "break_even": "Close to break-even",
    "lean_target": "Leans toward the target",
    "lean_stop": "Leans toward the stop",
    "strong_target": "Strongly toward the target",
    "strong_stop": "Strongly toward the stop",
    "undecided": "Mostly undecided",
}


def pool_from_history(history: Path, symbol: str, before: dt.date) -> list[list[tuple]]:
    """Ratio bars for each complete normal session before ``before``: [[(o, h, l, c), ...]]."""
    import tournament

    if not history.is_file():
        raise ValueError("No stored history yet; load 180 days of history in Setup first")
    sessions = tournament.load(history).get(symbol, [])
    pool = []
    for day in sessions:
        if dt.date.fromisoformat(day["date"]) >= before:
            continue
        bars = day["bars"]
        open_at = day["times"]["open"]
        if len(bars) != SESSION_BARS or any(
            bar["t"] != open_at + index * intraday.BAR for index, bar in enumerate(bars)
        ):
            continue  # Special or partial sessions would mix up times of day.
        pool.append(ratios(bars))
    return pool


def ratios(bars: list[dict]) -> list[tuple[float, float, float, float]]:
    rows = []
    previous = bars[0]["open"]
    for bar in bars:
        rows.append(tuple(bar[key] / previous for key in ("open", "high", "low", "close")))
        previous = bar["close"]
    return rows


def replay(
    pool: list[list[tuple]],
    entry: float,
    stop: float,
    target: float,
    start: int,
    end: int,
    rng: random.Random,
    window: int,
) -> tuple[str, float, list[float]]:
    """One simulated rest-of-session: outcome, exit price and the closes along the way."""
    price, path = entry, []
    for index in range(start, end):
        low_index = max(0, index - window)
        high_index = min(SESSION_BARS - 1, index + window)
        o, h, low, c = rng.choice(pool)[rng.randint(low_index, high_index)]
        bar_open, bar_low, bar_high = price * o, price * low, price * h
        if bar_low <= stop:
            return "stop", min(stop, bar_open), path
        if bar_high >= target:
            return "target", max(target, bar_open), path
        price *= c
        path.append(price)
    return "neither", price, path


def percentile(sorted_values: list[float], share: float) -> float:
    if not sorted_values:
        return float("nan")
    index = min(len(sorted_values) - 1, max(0, round(share * (len(sorted_values) - 1))))
    return sorted_values[index]


def simulate(
    pool: list[list[tuple]],
    plan: dict,
    end: int,
    replays: int = 10_000,
    seed: int = 19,
    window: int = 2,
) -> dict[str, Any]:
    """Odds, R and the fan of prices from ``replays`` simulated sessions. Pure."""
    if not 100 <= replays <= MAX_REPLAYS:
        raise ValueError(f"Replays must be 100-{MAX_REPLAYS:,}")
    if not 0 <= window <= 6:
        raise ValueError("The time-of-day window must be 0-6 bars")
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    if not stop < entry < target:
        raise ValueError("A long plan needs stop < entry < target")
    start = int(plan["entry_bar"])
    if not 3 <= start < end <= SESSION_BARS:
        raise ValueError("The entry must be after the opening range and before the square-off")
    rng = random.Random(seed)
    risk = entry - stop
    counts = {"target": 0, "stop": 0, "neither": 0}
    green, r_values, closes = 0, [], []
    steps = end - start
    bands: list[list[float]] = [[] for _ in range(steps)]
    for _ in range(replays):
        outcome, price, path = replay(pool, entry, stop, target, start, end, rng, window)
        counts[outcome] += 1
        r_values.append((price - entry) / risk)
        if outcome == "target" or (outcome == "neither" and price > entry):
            green += 1
        closes.append(price)
        for step in range(steps):
            # An exited replay holds its exit price for the rest of the fan.
            bands[step].append(path[step] if step < len(path) else price)
    closes.sort()
    fan = []
    for step, values in enumerate(bands):
        values.sort()
        fan.append(
            {
                "bar": start + step,
                **{f"p{int(q * 100)}": round(percentile(values, q), 2) for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
            }
        )  # fmt: skip
    share = {key: round(100 * value / replays, 1) for key, value in counts.items()}
    return {
        "replays": replays,
        "seed": seed,
        "window": window,
        "sessions": len(pool),
        "bars": steps,
        "target_first_pct": share["target"],
        "stop_first_pct": share["stop"],
        "neither_pct": share["neither"],
        "green_pct": round(100 * green / replays, 1),
        "close_median": round(percentile(closes, 0.5), 2),
        "close_p5": round(percentile(closes, 0.05), 2),
        "close_p95": round(percentile(closes, 0.95), 2),
        "average_r": round(statistics.fmean(r_values), 3),
        "fan": fan,
    }


def history(sessions: list[list[dict]], plan: dict, end: int) -> dict[str, Any] | None:
    """The plan's own opening-range rule on each past session (real outcomes)."""
    opening = plan.get("opening_range")
    if plan.get("setup") != "orb" or not opening:
        return None
    size = int(opening.get("minutes", 15)) // 5
    risk_pct = plan["risk_per_share"] / plan["entry"]
    rule = plan.get("stop_rule", "or-low")
    results = {"fired": 0, "target": 0, "stop": 0, "neither": 0}
    r_values = []
    for bars in sessions:
        high = max(bar["high"] for bar in bars[:size])
        low = min(bar["low"] for bar in bars[:size])
        trigger = next(
            (i for i in range(size, min(end, len(bars))) if bars[i]["close"] > high), None
        )
        if trigger is None or trigger + 1 >= end:
            continue
        entry = bars[trigger]["close"]
        if rule == "or-low":
            stop = low
        elif rule == "or-mid":
            stop = (high + low) / 2
        else:
            stop = entry * (1 - risk_pct)  # Same distance as today's plan.
        if not stop < entry:
            continue
        risk = entry - stop
        target = entry + plan["target_r"] * risk
        results["fired"] += 1
        outcome, price = "neither", bars[end - 1]["close"]
        for bar in bars[trigger + 1 : end]:
            if bar["low"] <= stop:
                outcome, price = "stop", min(stop, bar["open"])
                break
            if bar["high"] >= target:
                outcome, price = "target", max(target, bar["open"])
                break
        results[outcome] += 1
        r_values.append((price - entry) / risk)
    results["average_r"] = round(statistics.fmean(r_values), 3) if r_values else None
    results["sessions"] = len(sessions)
    results["stop_rule"] = rule if rule in ("or-low", "or-mid") else "same distance as today"
    return results


def verdict(mc: dict, target_r: float) -> dict[str, Any]:
    decided = mc["target_first_pct"] + mc["stop_first_pct"]
    lines = []
    if decided < 1:
        code = "undecided"
        lines.append(f"{VERDICTS[code]}: almost no replay reached the stop or the target.")
        return {"code": code, "lines": lines}
    share = 100 * mc["target_first_pct"] / decided
    needed = 100 / (1 + target_r)
    gap = share - needed
    if abs(gap) < 5:
        code = "coin_flip" if abs(target_r - 1) < 1e-9 else "break_even"
    elif abs(gap) < 15:
        code = "lean_target" if gap > 0 else "lean_stop"
    else:
        code = "strong_target" if gap > 0 else "strong_stop"
    lines.append(
        f"{VERDICTS[code]}: target first {mc['target_first_pct']}% vs stop first "
        f"{mc['stop_first_pct']}%. At {target_r:g}R the target must come first in "
        f"{needed:.0f}% of the replays that hit a side; it did in {share:.0f}%."
    )
    if mc["neither_pct"] > 40:
        lines.append(
            f"{mc['neither_pct']}% of the replays hit neither by the square-off; the price "
            "then decides those."
        )
    leaning_up = code in ("lean_target", "strong_target")
    leaning_down = code in ("lean_stop", "strong_stop")
    if (leaning_up and mc["average_r"] < 0) or (leaning_down and mc["average_r"] > 0):
        lines.append(f"Average R is {mc['average_r']:+.3f}, against the lean.")
    return {"code": code, "lines": lines}


def cost_in_r(plan: dict, config: dict, qty: int) -> float:
    """Round-trip fees and slippage, in units of the plan's risk."""
    entry, risk = plan["entry"], plan["risk_per_share"]
    qty = max(qty, 1)
    slippage = 2 * entry * float(config.get("slippage_bps", 5)) / 10_000
    if config.get("exact_charges", True):
        import charges

        fees = charges.fee("intraday", "buy", entry, qty) + charges.fee(
            "intraday", "sell", entry, qty
        )
        return round((fees / qty + slippage) / risk, 3)
    per_share = (
        2 * entry * float(config.get("fee_bps", 5)) / 10_000
        + 2 * float(config.get("fee_flat_inr", 10)) / qty
    )
    return round((per_share + slippage) / risk, 3)


def planned_qty(plan: dict, config_path: Path) -> int:
    """Shares the paper book's limits would allow, for the cost estimate only."""
    import decision_pipeline

    try:
        config = intraday.load_config(config_path)
        book = decision_pipeline.read_book(intraday.config_folder(config_path) / config["book"])
        risk_inr = float(book["limits"]["risk"])
        cap_inr = float(book["limits"]["position_limit"])
    except (ValueError, OSError, KeyError, sqlite3.Error):
        risk_inr, cap_inr = 500.0, 30_000.0  # No book yet: the default ₹2 lakh book's limits.
    return max(1, int(min(risk_inr / plan["risk_per_share"], cap_inr / plan["entry"])))


def run(
    plan: dict,
    config_path: Path,
    replays: int = 10_000,
    seed: int = 19,
    window: int = 2,
    until: str | None = None,
) -> dict[str, Any]:
    config = intraday.load_config(config_path)
    day = dt.date.fromisoformat(plan["date"])
    times = intraday.session_times(intraday.sessions_manifest(config_path), day)
    if times is None:
        raise ValueError(f"NSE is closed on {day}")
    stop_at = times["flat_by"]
    if until:
        hours, minutes = (int(part) for part in until.split(":"))
        stop_at = times["open"].replace(hour=hours, minute=minutes)
        if not times["open"] < stop_at <= times["close"]:
            raise ValueError("--until must fall inside the session")
    end = int((stop_at - times["open"]) / intraday.BAR)
    history_path = intraday.config_folder(config_path) / config.get("history_db", "history.sqlite")
    pool = pool_from_history(history_path, plan["symbol"], day)
    if len(pool) < MIN_SESSIONS:
        raise ValueError(
            f"Only {len(pool)} complete sessions of {plan['symbol']} are stored; the Time "
            f"Machine needs {MIN_SESSIONS}. Load history for this stock first"
        )
    mc = simulate(pool, plan, end, replays, seed, window)
    sessions = _sessions(history_path, plan["symbol"], day)
    past = history(sessions, plan, end)
    judged = verdict(mc, plan["target_r"])
    qty = planned_qty(plan, config_path)
    costs = cost_in_r(plan, config, qty)
    net = round(mc["average_r"] - costs, 3)
    judged["lines"].append(
        f"Costs about {costs:.3f}R a trade ({qty} shares, fees and slippage both ways): "
        f"average R after costs {net:+.3f}."
    )
    return {
        "plan": plan,
        "until": stop_at.isoformat(),
        "mc": mc,
        "history": past,
        "verdict": judged,
        "cost_r": costs,
        "average_r_after_costs": net,
        "notice": "Built from this stock's stored sessions; not a prediction.",
    }


def _sessions(history_path: Path, symbol: str, before: dt.date) -> list[list[dict]]:
    import tournament

    days = [
        day
        for day in tournament.load(history_path).get(symbol, [])
        if dt.date.fromisoformat(day["date"]) < before and len(day["bars"]) == SESSION_BARS
    ]
    return [day["bars"] for day in days]


def describe(result: dict) -> str:
    mc, plan = result["mc"], result["plan"]
    until = dt.datetime.fromisoformat(result["until"])
    lines = [
        f"{mc['replays']:,} replays of the rest of the session for {plan['symbol']}, "
        f"to {until:%H:%M} IST ({mc['bars']} five-minute bars), seed {mc['seed']}, "
        f"from {mc['sessions']} stored sessions.",
        f"  target first   {mc['target_first_pct']} %",
        f"  stop first     {mc['stop_first_pct']} %",
        f"  neither        {mc['neither_pct']} %   still open at {until:%H:%M}",
        f"  green          {mc['green_pct']} %   target first, or above the entry at {until:%H:%M}",
        f"  Price at {until:%H:%M}: median ₹{mc['close_median']}, 90% of replays between "
        f"₹{mc['close_p5']} and ₹{mc['close_p95']}.",
        f"  Average R: {mc['average_r']:+.3f}",
    ]
    past = result["history"]
    if past:
        lines.append(
            f"History: the same rule on {past['sessions']} real sessions fired {past['fired']} "
            f"times: {past['target']} target, {past['stop']} stop, {past['neither']} neither."
            + (f" Average R {past['average_r']:+.3f}." if past["average_r"] is not None else "")
        )
    else:
        lines.append("History: only an opening-range plan can be re-run on past sessions.")
    lines.extend(result["verdict"]["lines"])
    lines.append(result["notice"])
    return "\n".join(lines)


def odds_gate(coordinator: Any, symbol: str, ticket: dict, clock: dt.datetime) -> str:
    """Autopilot gate (downgrade only): skip entries the replays lean against. Empty = go."""
    options = {"enabled": False, "replays": 2000, "require_history": False}
    options.update(getattr(coordinator, "config", {}).get("timemachine") or {})
    if not options["enabled"]:
        return ""
    try:
        times = intraday.session_times(
            intraday.sessions_manifest(coordinator.config_path), clock.date()
        )
        if times is None:
            return ""
        entry = float(ticket["price_inr"])
        stop = float(ticket["stop_inr"])
        target = float(ticket["target_inr"])
        quoted = intraday.now_ist(ticket["quote_as_of"])
        bar = int((quoted - times["open"]) / intraday.BAR) + 1
        plan = {
            "symbol": symbol, "date": str(clock.date()), "entry": entry, "stop": stop,
            "target": target, "entry_bar": max(3, bar), "risk_per_share": entry - stop,
            "target_r": (target - entry) / (entry - stop), "setup": "desk",
        }  # fmt: skip
        result = run(plan, coordinator.config_path, int(options["replays"]))
    except ValueError as exc:
        if options["require_history"]:
            return f"time machine could not replay it ({str(exc)[:120]})"
        return ""
    if result["verdict"]["code"] in ("lean_stop", "strong_stop"):
        return "time machine: " + result["verdict"]["lines"][0]
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("run")
    command.add_argument("--plan", type=Path, help="plan.json (default desk/plan.json)")
    command.add_argument("--symbol")
    command.add_argument("--date")
    command.add_argument("--entry", type=float)
    command.add_argument("--stop", type=float)
    command.add_argument("--target", type=float)
    command.add_argument("--entry-time", help="HH:MM IST, when the entry bar closed")
    command.add_argument("--replays", type=int, default=10_000)
    command.add_argument("--seed", type=int, default=19)
    command.add_argument("--window", type=int, default=2)
    command.add_argument("--until", help="HH:MM IST; default the session's square-off")
    command.add_argument("--json", action="store_true")
    command.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    desk = intraday.desk_dir(args.config)
    try:
        if args.symbol:
            if not (args.date and args.entry and args.stop and args.target and args.entry_time):
                raise ValueError("Give --symbol, --date, --entry, --stop, --target, --entry-time")
            day = dt.date.fromisoformat(args.date)
            times = intraday.session_times(intraday.sessions_manifest(args.config), day)
            if times is None:
                raise ValueError(f"NSE is closed on {day}")
            entered = intraday.now_ist(f"{day} {args.entry_time}")
            plan = {
                "symbol": intraday.normalise_symbol(args.symbol), "date": str(day),
                "entry": args.entry, "stop": args.stop, "target": args.target,
                "entry_bar": int((entered - times["open"]) / intraday.BAR),
                "risk_per_share": round(args.entry - args.stop, 2),
                "target_r": round((args.target - args.entry) / (args.entry - args.stop), 2),
                "setup": "manual",
            }  # fmt: skip
        else:
            plan = intraday.read_json(args.plan or desk / "plan.json")
        result = run(plan, args.config, args.replays, args.seed, args.window, args.until)
    except (ValueError, OSError, KeyError, ZeroDivisionError) as exc:
        print(f"Time machine refused: {exc}", file=sys.stderr)
        return 2
    if args.write:
        intraday.write_json(desk / "timemachine.json", result)
    print(json.dumps(result, indent=2) if args.json else describe(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

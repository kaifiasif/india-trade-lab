#!/usr/bin/env python3
"""Exit Planner: sets the stop and the target before the entry, so the exit is decided.

Reads the trigger from ``desk/entry.json`` (or prices you give) and writes
``desk/plan.json`` for the Time Machine, the trade check and Price Alerts.

Stops (long only):

| rule | where it goes |
| --- | --- |
| ``or-low`` (default) | the opening-range low, as the desk's ``orb-v1`` strategy uses |
| ``or-mid`` | the opening-range midpoint: tighter, so more shares for the same risk |
| ``price:X`` | your price |
| ``pct:X`` | X percent under the entry |
| ``atr:K`` | K times the 14-bar ATR of today's five-minute bars up to the entry bar |

The stop rounds down to 5 paise; the target is the entry plus R times the risk
(``target_r`` from pipeline.json, 2 by default), or ``price:X``. It refuses a stop
at or above the entry, a target at or below it, a stop under 0.15% away (noise
would hit it, the desk's own floor), and an entry at or after the entry cutoff.
Square-off is the session's ``flat_by`` (15:05 from 3 Aug 2026, when the closing auction starts at 15:15): no overnight hold.

A stop is a plan, not a guarantee: a gap or a fast market can fill past it.

    python3 exit_planner.py plan --write
    python3 exit_planner.py plan --stop or-mid --target 1.5R --write
    python3 exit_planner.py plan --symbol INFY --entry 1612.4 --or-high 1608 --or-low 1596.2 \
        --entry-time "2026-10-29 09:45"
    python3 exit_planner.py show
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

import intraday

import strategies

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")


def atr(bars: list[dict], length: int = 14) -> tuple[float, int]:
    """Average true range of the bars given (all of them when fewer than ``length``)."""
    if not bars:
        raise ValueError("An ATR stop needs today's bars up to the entry")
    ranges = []
    for index, bar in enumerate(bars):
        previous = bars[index - 1]["close"] if index else bar["open"]
        ranges.append(max(bar["high"], previous) - min(bar["low"], previous))
    used = ranges[-length:]
    return sum(used) / len(used), len(used)


def stop_price(
    rule: str, entry: float, opening: dict | None, bars: list[dict] | None
) -> tuple[float, str]:
    """The stop and a plain description of how it was set."""
    if rule in ("or-low", "or-mid"):
        if not opening:
            raise ValueError(f"A {rule} stop needs the opening range; give --or-high/--or-low")
        if rule == "or-low":
            raw, why = opening["low"], f"opening-range low ₹{opening['low']:.2f}"
        else:
            raw = (opening["high"] + opening["low"]) / 2
            why = f"opening-range midpoint (₹{opening['high']:.2f} + ₹{opening['low']:.2f}) / 2"
    elif match := re.fullmatch(r"price:(\d+(?:\.\d+)?)", rule):
        raw, why = float(match[1]), "your price"
    elif match := re.fullmatch(r"pct:(\d+(?:\.\d+)?)", rule):
        pct = float(match[1])
        if not 0 < pct < 20:
            raise ValueError("A percent stop must be between 0 and 20")
        raw, why = entry * (1 - pct / 100), f"{pct:g}% under the entry"
    elif match := re.fullmatch(r"atr:(\d+(?:\.\d+)?)", rule):
        multiple = float(match[1])
        if not 0 < multiple <= 5:
            raise ValueError("An ATR multiple must be above 0 and at most 5")
        value, count = atr(bars or [])
        raw = entry - multiple * value
        why = f"{multiple:g} × ATR ₹{value:.2f} ({count} five-minute bars)"
    else:
        raise ValueError("Stop must be or-low, or-mid, price:X, pct:X or atr:K")
    return intraday.round_down(raw), why + ", rounded down to 5 paise"


def target_price(rule: str, entry: float, risk: float) -> tuple[float, float, str]:
    if match := re.fullmatch(r"(\d+(?:\.\d+)?)R", rule, re.IGNORECASE):
        multiple = float(match[1])
        if not 0.5 <= multiple <= 10:
            raise ValueError("A target must be 0.5R to 10R")
        price = intraday.round_up(entry + multiple * risk)
        return price, multiple, f"{multiple:g}R ({multiple:g} times the risk)"
    if match := re.fullmatch(r"price:(\d+(?:\.\d+)?)", rule):
        price = float(match[1])
        return price, (price - entry) / risk if risk > 0 else 0.0, "your price"
    raise ValueError("Target must be like 2R, 1.5R or price:X")


def plan(
    symbol: str,
    entry: float,
    entry_time: dt.datetime,
    times: dict[str, dt.datetime],
    stop_rule: str = "or-low",
    target_rule: str = "2R",
    opening: dict | None = None,
    bars: list[dict] | None = None,
    setup: str = "orb",
) -> dict[str, Any]:
    """A checked long plan, or ValueError with the reason and what would fix it."""
    if entry <= 0:
        raise ValueError("Entry must be a positive price")
    if entry_time >= times["entry_cutoff"]:
        raise ValueError(
            f"Entry at {entry_time:%H:%M} is at or after the {times['entry_cutoff']:%H:%M} "
            "entry cutoff; the desk does not open new trades this late"
        )
    upto = [bar for bar in (bars or []) if bar["t"] + intraday.BAR <= entry_time]
    stop, stop_why = stop_price(stop_rule, entry, opening, upto)
    if stop >= entry:
        raise ValueError(f"Stop ₹{stop:.2f} is not below the entry ₹{entry:.2f}")
    risk = round(entry - stop, 2)
    risk_pct = 100 * risk / entry
    if risk_pct < strategies.MIN_STOP_PCT:
        raise ValueError(
            f"Stop only {risk_pct:.2f}% away; normal noise would hit it. Use a wider stop "
            f"(at least {strategies.MIN_STOP_PCT}%)"
        )
    target, multiple, target_why = target_price(target_rule, entry, risk)
    if target <= entry:
        raise ValueError(f"Target ₹{target:.2f} is not above the entry ₹{entry:.2f}")
    return {
        "symbol": symbol,
        "side": "long",
        "date": str(entry_time.date()),
        "setup": setup,
        "entry": round(entry, 2),
        "entry_time": entry_time.isoformat(),
        "entry_bar": int((entry_time - times["open"]) / intraday.BAR),
        "stop": stop,
        "stop_rule": stop_rule,
        "stop_why": stop_why,
        "target": target,
        "target_r": round(multiple, 2),
        "target_why": target_why,
        "risk_per_share": risk,
        "risk_pct": round(risk_pct, 2),
        "reward_risk": round((target - entry) / risk, 2),
        "flat_by": times["flat_by"].isoformat(),
        "opening_range": opening,
    }


def describe(result: dict) -> str:
    flat = dt.datetime.fromisoformat(result["flat_by"])
    entered = dt.datetime.fromisoformat(result["entry_time"])
    return "\n".join(
        [
            f"Exit plan: {result['symbol']} long, {result['date']}, {result['setup']} on "
            "five-minute bars",
            f"  Entry         ₹{result['entry']:.2f} at {entered:%H:%M} IST "
            f"(bar {result['entry_bar']})",
            f"  Stop          ₹{result['stop']:.2f}  {result['stop_why']}",
            f"  Target        ₹{result['target']:.2f}  {result['target_why']}",
            f"  Risk a share  ₹{result['risk_per_share']:.2f} ({result['risk_pct']}% of the entry)",
            f"  Reward:risk   {result['reward_risk']}",
            f"  Flat by       {flat:%H:%M} IST, win or lose: no overnight hold",
            "A stop is a plan, not a guarantee: a gap can fill past it. Nothing was placed.",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("plan")
    make.add_argument("--from", dest="source", type=Path, help="entry.json (default desk/)")
    make.add_argument("--symbol")
    make.add_argument("--entry", type=float)
    make.add_argument("--entry-time", help='"YYYY-MM-DD HH:MM" IST, the entry bar close')
    make.add_argument("--or-high", type=float)
    make.add_argument("--or-low", type=float)
    make.add_argument("--stop", default="or-low")
    make.add_argument("--target")
    make.add_argument("--bars", type=Path, help="saved Kite candles for an atr:K stop")
    make.add_argument("--json", action="store_true")
    make.add_argument("--write", action="store_true")
    sub.add_parser("show")
    args = parser.parse_args(argv)
    desk = intraday.desk_dir(args.config)
    try:
        if args.command == "show":
            print(describe(intraday.read_json(desk / "plan.json")))
            return 0
        config = intraday.load_config(args.config)
        trigger: dict[str, Any] = {}
        source = args.source or desk / "entry.json"
        if not (args.symbol and args.entry and args.entry_time) and source.is_file():
            trigger = intraday.read_json(source)
            if trigger.get("status") != "TRIGGERED" and not args.entry:
                raise ValueError("entry.json has not triggered; give --entry to plan ahead")
        symbol = intraday.normalise_symbol(args.symbol or trigger.get("symbol", ""))
        entry = args.entry or trigger.get("price")
        stamp = args.entry_time or trigger.get("time")
        if not entry or not stamp:
            raise ValueError("Give --entry and --entry-time, or run entry_timer.py check first")
        entry_time = intraday.now_ist(stamp)
        opening = trigger.get("opening_range")
        if args.or_high and args.or_low:
            opening = {"high": args.or_high, "low": args.or_low}
        times = intraday.session_times(intraday.sessions_manifest(args.config), entry_time.date())
        if times is None:
            raise ValueError(f"NSE is closed on {entry_time.date()}")
        bars = None
        if args.stop.startswith("atr:"):
            bars = (
                intraday.read_bars_file(args.bars, entry_time.date())
                if args.bars
                else intraday.today_bars(args.config, symbol, entry_time + intraday.BAR)
            )
        target = args.target or f"{float(config.get('target_r', '2')):g}R"
        result = plan(
            symbol, float(entry), entry_time, times, args.stop, target, opening, bars,
            trigger.get("setup", "orb" if opening else "level"),
        )  # fmt: skip
    except (ValueError, OSError, KeyError) as exc:
        print(f"Exit plan refused: {exc}", file=sys.stderr)
        return 2
    if args.write:
        intraday.write_json(desk / "plan.json", result)
    print(json.dumps(result, indent=2) if args.json else describe(result))
    print("Next: replay it with time_machine.py run, then size and check it with trade_check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

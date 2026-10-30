#!/usr/bin/env python3
"""Entry Timer: watches a setup bar by bar and says the moment to get in.

Reads today's completed five-minute NSE bars (Kite, your login, read-only), builds
the opening range (09:15-09:30 by default) and calls the entry on the first
completed bar that CLOSES above the range high, or above a level you give it (a
20-day high from the scan, for example), with an optional volume check. A wick
above the level is not an entry, and a bar that has not finished never counts.

Statuses: CLOSED (no NSE session), NOT_OPEN, FORMING (the range is still being
built), WAITING (and how far), TRIGGERED (time and price), EXPIRED (no trigger by
the entry cutoff, 14:30 on a normal day). Long side only, matching the desk.

It writes ``desk/entry.json`` for the Exit Planner. It never places an order:
the paper autopilot and the paper book decide what is recorded.

    python3 entry_timer.py check INFY
    python3 entry_timer.py check INFY --write
    python3 entry_timer.py check INFY --setup level --level 1612.40 --min-volume-x 1.5
    python3 entry_timer.py watch INFY            # one line per closed bar; exit 0 on the trigger
    python3 entry_timer.py check INFY --bars saved.json --now "2026-10-29 10:05"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")


def check(
    symbol: str,
    bars: list[dict],
    times: dict[str, dt.datetime] | None,
    clock: dt.datetime,
    setup: str = "orb",
    level: float | None = None,
    or_minutes: int = 15,
    min_volume_x: float | None = None,
) -> dict[str, Any]:
    """The entry status for one symbol from today's completed bars. Pure: no I/O."""
    if setup not in ("orb", "level"):
        raise ValueError("Setup must be orb or level")
    if setup == "level" and (level is None or level <= 0):
        raise ValueError("A level setup needs --level, a positive price")
    if or_minutes % 5 or not 5 <= or_minutes <= 60:
        raise ValueError("The opening range must be 5-60 minutes, in steps of 5")
    base: dict[str, Any] = {
        "symbol": symbol,
        "setup": setup,
        "date": str(clock.date()),
        "checked_at": clock.isoformat(),
        "interval": "5minute",
    }
    if times is None:
        return {**base, "status": "CLOSED", "message": "NSE is closed today."}
    if clock < times["open"]:
        opens = times["open"].strftime("%H:%M")
        return {**base, "status": "NOT_OPEN", "message": f"The market opens at {opens} IST."}
    bars = intraday.completed([bar for bar in bars if bar["t"] >= times["open"]], clock)
    size = or_minutes // 5
    range_end = times["open"] + dt.timedelta(minutes=or_minutes)
    if len(bars) < size:
        return {
            **base,
            "status": "FORMING",
            "message": f"The opening range is still forming until {range_end:%H:%M} IST.",
        }
    opening = bars[:size]
    high = max(bar["high"] for bar in opening)
    low = min(bar["low"] for bar in opening)
    base["opening_range"] = {
        "high": high,
        "low": low,
        "minutes": or_minutes,
        "ends": range_end.isoformat(),
    }
    target_level = high if setup == "orb" else float(level)
    base["level"] = target_level
    average = sum(bar["volume"] for bar in opening) / size
    for index, bar in enumerate(bars[size:], start=size + 1):
        closes_at = bar["t"] + intraday.BAR
        if closes_at > times["entry_cutoff"]:
            break
        if bar["close"] <= target_level:
            continue
        ratio = bar["volume"] / average if average > 0 else None
        if min_volume_x is not None and (ratio is None or ratio < min_volume_x):
            continue
        late = len(bars) - index
        return {
            **base,
            "status": "TRIGGERED",
            "time": closes_at.isoformat(),
            "bar": index,
            "price": bar["close"],
            "volume_x": round(ratio, 2) if ratio is not None else None,
            "bars_since": late,
            "message": (
                f"TRIGGERED {closes_at:%H:%M} IST at ₹{bar['close']:.2f}: the "
                f"{bar['t']:%H:%M} bar closed above ₹{target_level:.2f} "
                f"(+{100 * (bar['close'] / target_level - 1):.2f}%)."
                + (
                    f" That was {late} bar(s) ago: a late entry is a different trade."
                    if late
                    else ""
                )
                + " Nothing was placed."
            ),
        }
    if clock >= times["entry_cutoff"]:
        return {
            **base,
            "status": "EXPIRED",
            "message": f"No close above ₹{target_level:.2f} before the "
            f"{times['entry_cutoff']:%H:%M} entry cutoff.",
        }
    last = bars[-1]
    gap = target_level - last["close"]
    return {
        **base,
        "status": "WAITING",
        "last_close": last["close"],
        "distance": round(gap, 2),
        "message": f"WAITING: last close ₹{last['close']:.2f} ({last['t']:%H:%M} bar), "
        f"₹{gap:.2f} under ₹{target_level:.2f} ({-100 * gap / target_level:.2f}%).",
    }


def _times(config: Path, clock: dt.datetime) -> dict | None:
    return intraday.session_times(intraday.sessions_manifest(config), clock.date())


def _bars(args: argparse.Namespace, symbol: str, clock: dt.datetime) -> list[dict]:
    if args.bars:
        return intraday.read_bars_file(args.bars, clock.date())
    return intraday.today_bars(args.config, symbol, clock)


def watch(
    args: argparse.Namespace,
    symbol: str,
    fetch: Callable[[dt.datetime], list[dict]],
    clock: Callable[[], dt.datetime],
    sleep: Callable[[float], None] = time.sleep,
    times: dict | None = None,
) -> int:
    """Print one line per newly closed bar until TRIGGERED (exit 0) or EXPIRED/CLOSED (1)."""
    seen = -1
    while True:
        now = clock()
        result = check(
            symbol, fetch(now), times, now, args.setup, args.level, args.or_minutes,
            args.min_volume_x,
        )  # fmt: skip
        bars = result.get("bar") or 0
        if result["status"] != "WAITING" or bars != seen:
            print(f"{now:%H:%M} {result['message']}", flush=True)
        if result["status"] == "TRIGGERED":
            intraday.write_json(intraday.desk_dir(args.config) / "entry.json", result)
            return 0
        if result["status"] in ("EXPIRED", "CLOSED"):
            return 1
        seen = bars
        if times is None:
            return 1
        elapsed = (now - times["open"]).total_seconds() % 300
        sleep(max(5.0, 300 - elapsed + 20))  # Just after the next bar closes.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "watch"):
        command = sub.add_parser(name)
        command.add_argument("symbol")
        command.add_argument("--setup", choices=("orb", "level"), default="orb")
        command.add_argument("--level", type=float)
        command.add_argument("--or-minutes", type=int, default=15)
        command.add_argument("--min-volume-x", type=float)
        command.add_argument("--bars", type=Path, help="saved Kite candles instead of Kite")
        command.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" IST')
        command.add_argument("--json", action="store_true")
        command.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        symbol = intraday.normalise_symbol(args.symbol)
        clock = intraday.now_ist(args.now)
        times = _times(args.config, clock)
        if args.command == "watch":
            pinned = args.now is not None
            state = {"clock": clock}

            def tick() -> dt.datetime:
                return state["clock"] if pinned else intraday.now_ist()

            def advance(seconds: float) -> None:
                if pinned:  # A replay walks the day without waiting.
                    state["clock"] += dt.timedelta(seconds=seconds)
                else:
                    time.sleep(seconds)

            return watch(args, symbol, lambda now: _bars(args, symbol, now), tick, advance, times)
        bars = _bars(args, symbol, clock) if times and clock >= times["open"] else []
        result = check(
            symbol, bars, times, clock, args.setup, args.level, args.or_minutes, args.min_volume_x
        )
    except (ValueError, OSError, KeyError) as exc:
        print(f"Entry timer refused: {exc}", file=sys.stderr)
        return 2
    if args.write:
        intraday.write_json(intraday.desk_dir(args.config) / "entry.json", result)
    print(json.dumps(result, indent=2) if args.json else result["message"])
    if result["status"] == "TRIGGERED":
        print("Next: set the stop and target before anything is bought: exit_planner.py plan")
    return 0 if result["status"] == "TRIGGERED" else 1


if __name__ == "__main__":
    sys.exit(main())

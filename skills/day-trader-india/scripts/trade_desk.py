#!/usr/bin/env python3
"""The trade desk agent: runs the trade tools on its own, every tick of the session loop.

The session worker (``market_service.py``) calls :func:`tick` after the
coordinator and the paper autopilot. For each of today's judge picks it:

1. **Entry Timer**: has a completed five-minute bar closed above the opening range?
2. On a new trigger, once per stock per day: **Exit Planner** (stop at the
   opening-range low, target at ``target_r``), the **Time Machine** (replays from the
   stock's stored sessions) and the **trade check** (budget and risk against the paper
   book). The trigger is logged and emailed when alerts email is on.
3. **Price Alerts**: checks every rule for today (the autopilot adds a stop, target
   and square-off alert to every paper entry it records).

It writes one card per pick to ``desk/<date>/<SYMBOL>.json`` and a summary to
``desk/today.json`` for the dashboard. It records nothing in the paper book: the
autopilot does that under the journal's rules, and the Time Machine can veto an
autopilot entry (``"timemachine": {"enabled": true}``). Downgrade only, paper only.

    python3 trade_desk.py --once          # one pass now, as the worker would
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import entry_timer
import exit_planner
import intraday
import price_alerts
import time_machine
import trade_check

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")


def _bars_for(coordinator: Any, symbol: str, clock: dt.datetime) -> list[dict]:
    """Today's completed bars: the worker's refreshed bars file first, else Kite."""
    import india_research

    try:
        rows = india_research.bars_from_csv(coordinator.path("bars"))
        today = [
            {**row, "t": row["t"].astimezone(intraday.IST)}
            for row in rows
            if row["symbol"] == symbol and row["t"].astimezone(intraday.IST).date() == clock.date()
        ]
        if today:
            return intraday.completed(today, clock)
    except (ValueError, OSError, KeyError):
        pass
    return intraday.today_bars(coordinator.config_path, symbol, clock)


def _book(coordinator: Any) -> dict | None:
    import decision_pipeline

    try:
        return decision_pipeline.read_book(coordinator.path("book"))
    except (ValueError, OSError, KeyError, sqlite3.Error):
        return None


def work_up(coordinator: Any, entry: dict, clock: dt.datetime, times: dict) -> dict[str, Any]:
    """Plan, replay and check one triggered entry. Each step reports its own refusal."""
    config = coordinator.config
    card: dict[str, Any] = {}
    try:
        plan = exit_planner.plan(
            entry["symbol"],
            float(entry["price"]),
            dt.datetime.fromisoformat(entry["time"]),
            times,
            "or-low",
            f"{float(config.get('target_r', '2')):g}R",
            entry.get("opening_range"),
        )
        card["plan"] = plan
    except (ValueError, KeyError) as exc:
        card["plan_refused"] = str(exc)[:200]
        return card
    replays = int((config.get("timemachine") or {}).get("replays", 5000))
    try:
        odds = time_machine.run(plan, coordinator.config_path, replays)
        card["odds"] = odds
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        card["odds_unavailable"] = str(exc)[:200]
    book = _book(coordinator)
    if book is None:
        card["check_unavailable"] = "no forward paper book yet (Setup → Paper book)"
    else:
        card["check"] = trade_check.review(plan, book, config, clock, times)
    return card


def tick(
    coordinator: Any,
    now: dt.datetime | None = None,
    bars_for: Callable[[Any, str, dt.datetime], list[dict]] = _bars_for,
    quotes_for: Callable[[list[str]], dict] = price_alerts.kite_quotes,
) -> dict[str, Any]:
    """One pass over today's picks. Never raises for one stock's failure."""
    import autopilot

    clock = (now or dt.datetime.now(intraday.IST)).astimezone(intraday.IST)
    config_path = coordinator.config_path
    times = intraday.session_times(intraday.sessions_manifest(config_path), clock.date())
    summary: dict[str, Any] = {"date": str(clock.date()), "checked_at": clock.isoformat()}
    if times is None:
        return {**summary, "status": "CLOSED", "cards": []}
    picks = autopilot.todays_picks(coordinator.path("reports_dir"), str(clock.date())) or []
    folder = intraday.desk_dir(config_path) / str(clock.date())
    folder.mkdir(exist_ok=True)
    cards, triggers = [], []
    for symbol in picks[:10]:
        path = folder / f"{symbol.split(':')[-1]}.json"
        card = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        card["symbol"] = symbol
        if card.get("entry", {}).get("status") != "TRIGGERED":
            try:
                entry = entry_timer.check(
                    symbol, bars_for(coordinator, symbol, clock), times, clock
                )
            except (ValueError, OSError, KeyError) as exc:
                entry = {"symbol": symbol, "status": "DATA_BLOCK", "message": str(exc)[:200]}
            card["entry"] = entry
            if entry["status"] == "TRIGGERED":
                card.update(work_up(coordinator, entry, clock, times))
                verdict = (card.get("odds") or {}).get("verdict", {}).get("lines", [""])[0]
                check = (card.get("check") or {}).get("verdict", "not checked")
                triggers.append({
                    "id": f"trigger-{symbol}-{clock.date()}", "type": "trigger",
                    "at": clock.isoformat(),
                    "message": f"{entry['message']} Check: {check}. {verdict}".strip(),
                })  # fmt: skip
        intraday.write_json(path, card)
        cards.append(card)
    rang: list[dict] = []
    try:
        if triggers:
            price_alerts.notify(config_path, triggers)
        rang = price_alerts.run_check(config_path, clock, quotes_for)
    except (ValueError, OSError, KeyError) as exc:
        summary["alerts_error"] = str(exc)[:200]
    summary.update(
        status="OPEN" if times["open"] <= clock < times["close"] else "OUTSIDE_HOURS",
        cards=[
            {
                "symbol": card["symbol"],
                "entry": (card.get("entry") or {}).get("status"),
                "message": (card.get("entry") or {}).get("message"),
                "check": (card.get("check") or {}).get("verdict"),
                "odds": ((card.get("odds") or {}).get("verdict") or {}).get("code"),
            }
            for card in cards
        ],
        triggers=len(triggers),
        alerts=len(rang),
    )
    intraday.write_json(intraday.desk_dir(config_path) / "today.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    from decision_pipeline import DailyCoordinator

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--once", action="store_true", help="one pass (the worker loops)")
    parser.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" IST')
    args = parser.parse_args(argv)
    try:
        result = tick(DailyCoordinator(args.config), intraday.now_ist(args.now))
    except (ValueError, OSError, KeyError) as exc:
        print(f"Trade desk refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

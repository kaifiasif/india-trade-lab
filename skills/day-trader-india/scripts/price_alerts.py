#!/usr/bin/env python3
"""Price Alerts: rings when a price, a stop, a target or the NSE clock hits. Once each.

Turns a trade plan into three alerts in one go (the stop, the target and the
square-off time), and also takes above/below levels, a percent move from the
previous close, any time of day and the opening bell. Prices are Kite last-traded
prices (your login, read-only), fetched only for symbols in today's rules. The
NSE clock comes from ``sessions.json``, so holidays and special sessions are right.

| type | rings when | again |
| --- | --- | --- |
| ``above`` / ``target`` | last price at or above ``price`` | after ``reset`` |
| ``below`` / ``stop`` | last price at or below ``price`` | after ``reset`` |
| ``pct_move`` | moved ``pct`` % from the previous close (``direction`` up/down/any) | next day |
| ``time`` | the IST clock passed ``at`` on a trading day | next trading day |
| ``opening_bell`` | NSE is open | next trading day |

A rule with ``date`` is watched on that date only, so yesterday's stop never rings
today. Rang alerts go to ``desk/alerts-log.jsonl`` and, with ``"alerts": {"email":
true}`` in pipeline.json, to your email. The session worker checks them every tick.

An alert is a fact about a price or the clock, never an order. The paper autopilot
handles paper exits; a quote between two checks can pass a level unseen.

    python3 price_alerts.py clock
    python3 price_alerts.py add --from-plan
    python3 price_alerts.py add --symbol INFY --below 1596.20
    python3 price_alerts.py add --symbol INFY --pct 3 --direction down
    python3 price_alerts.py add --at 15:10 --label "close anything still open"
    python3 price_alerts.py add --opening-bell
    python3 price_alerts.py check            # exit 0 when something rang
    python3 price_alerts.py list
    python3 price_alerts.py reset infy-stop-2026-10-29
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
TYPES = ("above", "below", "target", "stop", "pct_move", "time", "opening_bell")
MAX_RULES = 200


def rules_path(config: Path) -> Path:
    return intraday.desk_dir(config) / "alerts.json"


def state_path(config: Path) -> Path:
    return intraday.desk_dir(config) / "alert-state.json"


def load(path: Path, empty: dict) -> dict:
    try:
        return intraday.read_json(path)
    except ValueError:
        return json.loads(json.dumps(empty))


def validate(rule: dict) -> dict:
    """A checked copy of one rule, or ValueError."""
    if rule.get("type") not in TYPES:
        raise ValueError(f"Alert type must be one of {', '.join(TYPES)}")
    if not re.fullmatch(r"[a-z0-9:&.\-]{1,80}", str(rule.get("id", ""))):
        raise ValueError("Alert id must be 1-80 lower-case letters, digits or -.:&")
    clean = {"id": rule["id"], "type": rule["type"], "label": str(rule.get("label", ""))[:120]}
    if rule["type"] in ("above", "below", "target", "stop", "pct_move"):
        clean["symbol"] = intraday.normalise_symbol(str(rule.get("symbol", "")))
    if rule["type"] in ("above", "below", "target", "stop"):
        price = float(rule.get("price", 0))
        if not 0 < price < 10_000_000:
            raise ValueError("A price alert needs a positive price")
        clean["price"] = price
    if rule["type"] == "pct_move":
        pct = float(rule.get("pct", 0))
        if not 0 < pct <= 50:
            raise ValueError("A percent alert needs 0-50%")
        clean["pct"] = pct
        clean["direction"] = rule.get("direction", "any")
        if clean["direction"] not in ("up", "down", "any"):
            raise ValueError("Direction must be up, down or any")
    if rule["type"] == "time":
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(rule.get("at", ""))):
            raise ValueError("A time alert needs at=HH:MM (IST)")
        clean["at"] = rule["at"]
    if rule.get("date"):
        clean["date"] = str(dt.date.fromisoformat(str(rule["date"])))
    return clean


def add(rules: dict, new: list[dict]) -> dict:
    """Rules with ``new`` added or replaced by id."""
    by_id = {rule["id"]: rule for rule in rules.get("rules", [])}
    for rule in new:
        checked = validate(rule)
        by_id[checked["id"]] = checked
    if len(by_id) > MAX_RULES:
        raise ValueError(f"At most {MAX_RULES} alerts; remove old ones first")
    return {"rules": list(by_id.values())}


def from_plan(plan: dict) -> list[dict]:
    """The stop, the target and the square-off time for one plan or recorded trade."""
    plain = plan["symbol"].split(":")[-1].lower()
    day = plan["date"]
    flat = dt.datetime.fromisoformat(plan["flat_by"]).strftime("%H:%M")
    return [
        {"id": f"{plain}-stop-{day}", "type": "stop", "symbol": plan["symbol"],
         "price": plan["stop"], "date": day, "label": "stop"},
        {"id": f"{plain}-target-{day}", "type": "target", "symbol": plan["symbol"],
         "price": plan["target"], "date": day, "label": "target"},
        {"id": f"{plain}-flat-{day}", "type": "time", "at": flat, "date": day,
         "label": f"square off {plan['symbol']} if it is still open"},
    ]  # fmt: skip


def check(
    rules: dict,
    state: dict,
    clock: dt.datetime,
    times: dict | None,
    quotes: dict[str, dict],
) -> tuple[list[dict], dict]:
    """What rang now, and the new state. Pure: quotes are ``{symbol: {last, prev_close}}``."""
    day = str(clock.date())
    rang, state = [], json.loads(json.dumps(state))
    for rule in rules.get("rules", []):
        if rule.get("date") and rule["date"] != day:
            continue
        seen = state.get(rule["id"])
        daily = rule["type"] in ("pct_move", "time", "opening_bell")
        if seen and (not daily or seen["day"] == day):
            continue
        message = None
        if rule["type"] == "opening_bell":
            if times and times["open"] <= clock < times["close"]:
                message = f"NSE is open ({times['open']:%H:%M}-{times['close']:%H:%M} IST)."
        elif rule["type"] == "time":
            hours, minutes = (int(part) for part in rule["at"].split(":"))
            if times and clock >= clock.replace(
                hour=hours, minute=minutes, second=0, microsecond=0
            ):
                message = f"It is {clock:%H:%M} IST (set for {rule['at']}). {rule.get('label', '')}"
        else:
            quote = quotes.get(rule["symbol"])
            if not quote or not quote.get("last"):
                continue
            last = float(quote["last"])
            if rule["type"] in ("above", "target") and last >= rule["price"]:
                message = f"{rule['symbol']} ₹{last:.2f} is at or above ₹{rule['price']:.2f}"
            elif rule["type"] in ("below", "stop") and last <= rule["price"]:
                message = f"{rule['symbol']} ₹{last:.2f} is at or below ₹{rule['price']:.2f}"
            elif rule["type"] == "pct_move" and quote.get("prev_close"):
                move = 100 * (last / float(quote["prev_close"]) - 1)
                direction = rule["direction"]
                hit = abs(move) >= rule["pct"] and (
                    direction == "any" or (move > 0) == (direction == "up")
                )
                if hit:
                    message = f"{rule['symbol']} moved {move:+.2f}% from the previous close"
            if message and rule["type"] in ("stop", "target"):
                message += f" ({rule['type']})."
        if message:
            state[rule["id"]] = {"day": day, "at": clock.isoformat()}
            rang.append({"id": rule["id"], "type": rule["type"], "at": clock.isoformat(),
                         "message": message.strip()})  # fmt: skip
    return rang, state


def kite_quotes(symbols: list[str], client: Any = None) -> dict[str, dict]:
    import market_scan

    if not symbols:
        return {}
    client = client or market_scan.KiteClient()
    data = client.quote(symbols)
    return {
        symbol: {
            "last": (data.get(symbol) or {}).get("last_price"),
            "prev_close": ((data.get(symbol) or {}).get("ohlc") or {}).get("close"),
        }
        for symbol in symbols
    }


def run_check(
    config: Path,
    clock: dt.datetime,
    quotes_for: Callable[[list[str]], dict] = kite_quotes,
    email: bool = True,
) -> list[dict]:
    """Check today's rules, persist what rang, log it and email it when switched on."""
    rules = load(rules_path(config), {"rules": []})
    day = str(clock.date())
    symbols = sorted({
        rule["symbol"] for rule in rules["rules"]
        if "symbol" in rule and rule.get("date") in (None, day)
    })  # fmt: skip
    times = intraday.session_times(intraday.sessions_manifest(config), clock.date())
    quotes: dict[str, dict] = {}
    if symbols and times:
        try:
            quotes = quotes_for(symbols)
        except ValueError as exc:
            # Time and bell alerts still ring; price alerts wait for the next check.
            print(f"Prices unavailable: {exc}", file=sys.stderr)
    rang, state = check(rules, load(state_path(config), {}), clock, times, quotes)
    if not rang:
        return []
    intraday.write_json(state_path(config), state)
    return notify(config, rang, notify_email=email)


def notify(config: Path, items: list[dict], notify_email: bool = True) -> list[dict]:
    """Log rang alerts to desk/alerts-log.jsonl and email them when switched on."""
    with (intraday.desk_dir(config) / "alerts-log.jsonl").open("a", encoding="utf-8") as log:
        for item in items:
            log.write(json.dumps(item) + "\n")
    settings = intraday.load_config(config)
    if notify_email and (settings.get("alerts") or {}).get("email"):
        import premarket

        message = EmailMessage()
        message["Subject"] = "Desk alert: " + "; ".join(item["message"] for item in items)[:150]
        message.set_content(
            "\n".join(f"{item['at'][11:16]}  {item['message']}" for item in items)
            + "\n\nAn alert is information, not an order. Paper trading only."
        )
        result = premarket.smtp_send(message, settings)
        for item in items:
            item["emailed"] = result.get("sent", False)
    return items


def recent(config: Path, limit: int = 50) -> list[dict]:
    """The latest rang alerts, newest first, for the dashboard."""
    path = intraday.desk_dir(config) / "alerts-log.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    items = []
    for line in reversed(lines):
        try:
            items.append(json.loads(line))
        except ValueError:
            continue
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" IST')
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("clock")
    adding = sub.add_parser("add")
    adding.add_argument("--from-plan", action="store_true")
    adding.add_argument("--plan", type=Path)
    adding.add_argument("--symbol")
    for name in ("above", "below", "stop", "target"):
        adding.add_argument(f"--{name}", type=float)
    adding.add_argument("--pct", type=float)
    adding.add_argument("--direction", default="any")
    adding.add_argument("--at")
    adding.add_argument("--opening-bell", action="store_true")
    adding.add_argument("--label", default="")
    adding.add_argument("--date", help="watch on this date only (YYYY-MM-DD)")
    sub.add_parser("check")
    sub.add_parser("list")
    resetting = sub.add_parser("reset")
    resetting.add_argument("id")
    removing = sub.add_parser("remove")
    removing.add_argument("id")
    args = parser.parse_args(argv)
    try:
        clock = intraday.now_ist(args.now)
        if args.command == "clock":
            times = intraday.session_times(intraday.sessions_manifest(args.config), clock.date())
            if times is None:
                print(f"NSE is closed on {clock.date()}.")
            elif clock < times["open"]:
                print(f"NSE opens at {times['open']:%H:%M} IST today.")
            elif clock < times["close"]:
                print(
                    f"NSE is open until {times['close']:%H:%M} IST; square-off {times['flat_by']:%H:%M}."
                )
            else:
                print(f"NSE closed at {times['close']:%H:%M} IST today.")
            return 0
        if args.command == "add":
            new = []
            if args.from_plan:
                new += from_plan(
                    intraday.read_json(args.plan or intraday.desk_dir(args.config) / "plan.json")
                )
            for kind in ("above", "below", "stop", "target"):
                value = getattr(args, kind)
                if value is not None:
                    plain = intraday.normalise_symbol(args.symbol or "").split(":")[-1].lower()
                    new.append({"id": f"{plain}-{kind}-{value:g}", "type": kind, "price": value,
                                "symbol": args.symbol, "label": args.label, "date": args.date})  # fmt: skip
            if args.pct is not None:
                plain = intraday.normalise_symbol(args.symbol or "").split(":")[-1].lower()
                new.append({"id": f"{plain}-pct-{args.pct:g}-{args.direction}", "type": "pct_move",
                            "symbol": args.symbol, "pct": args.pct, "direction": args.direction,
                            "label": args.label, "date": args.date})  # fmt: skip
            if args.at:
                new.append({"id": f"time-{args.at.replace(':', '')}", "type": "time", "at": args.at,
                            "label": args.label, "date": args.date})  # fmt: skip
            if args.opening_bell:
                new.append({"id": "opening-bell", "type": "opening_bell", "label": "opening bell"})
            if not new:
                raise ValueError("Nothing to add; see --help")
            rules = add(load(rules_path(args.config), {"rules": []}), new)
            intraday.write_json(rules_path(args.config), rules)
            for rule in new:
                checked = validate(rule)
                print(f"Added {checked['id']}: {checked['type']} "
                      f"{checked.get('symbol', '')} {checked.get('price', checked.get('at', ''))} "
                      f"{checked.get('date', 'every trading day')}".rstrip())  # fmt: skip
            return 0
        if args.command == "list":
            rules = load(rules_path(args.config), {"rules": []})
            state = load(state_path(args.config), {})
            for rule in rules["rules"]:
                rang = state.get(rule["id"], {}).get("at", "")
                print(f"{rule['id']:<40} {rule['type']:<12} {rule.get('price', rule.get('at', ''))} "
                      f"{'rang ' + rang[:16] if rang else ''}")  # fmt: skip
            return 0
        if args.command in ("reset", "remove"):
            state = load(state_path(args.config), {})
            state.pop(args.id, None)
            intraday.write_json(state_path(args.config), state)
            if args.command == "remove":
                rules = load(rules_path(args.config), {"rules": []})
                rules["rules"] = [rule for rule in rules["rules"] if rule["id"] != args.id]
                intraday.write_json(rules_path(args.config), rules)
            print(f"{args.command.capitalize()} {args.id}.")
            return 0
        rang = run_check(args.config, clock)
    except (ValueError, OSError, KeyError) as exc:
        print(f"Alerts refused: {exc}", file=sys.stderr)
        return 2
    for item in rang:
        print(f"ALERT {item['message']}")
    if not rang:
        print("Nothing rang.")
    return 0 if rang else 1


if __name__ == "__main__":
    sys.exit(main())

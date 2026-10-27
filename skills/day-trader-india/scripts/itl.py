#!/usr/bin/env python3
"""itl: one command for the everyday India Trade Lab tasks.

    itl setup                 create the private project folder and calendar
    itl login                 daily Kite login (2FA) and the two human attestations
    itl report [--email]      collect news, then build (and email) the pre-market report
    itl tournament            re-test every strategy on stored history
    itl status                what is ready, today's picks, the book and the tournament
    itl track [--days 7]      the paper track record, as Markdown you can publish
    itl dashboard             open the local dashboard on 127.0.0.1:8765

Each subcommand calls the same scripts documented in the references, so nothing
here has its own rules. Paper only: no subcommand can place a real order.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sqlite3
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _run(script: str, *args: str) -> int:
    """Run a sibling script with this interpreter; its output goes straight to the terminal."""
    return subprocess.call([sys.executable, str(HERE / script), *args])


def setup(config: Path) -> int:
    if not config.is_file():
        code = _run("decision_pipeline.py", "init", "--config", str(config))
        if code:
            return code
    calendar = config.parent / "sessions.json"
    if not calendar.is_file():
        shutil.copyfile(SKILL / "assets" / "nse-sessions-2026.json", calendar)
    print(
        f"Project folder ready: {config.parent}\n"
        'Tip: alias itl="python3 scripts/itl.py" from the repository folder.\n'
        "Next:\n"
        "  1. itl login                       (needs KITE_API_KEY and KITE_API_SECRET)\n"
        "  2. make_universe.py, then data_sync.py --days 180   (see docs/live-data.md)\n"
        "  3. itl tournament                  (which strategies have earned the right to trade)\n"
        "  4. itl status                      (everything that is still missing, with its fix)"
    )
    return 0


def login(config: Path) -> int:
    code = _run("kite_login.py")
    if code:
        return code
    try:
        universe = json.loads((config.parent / "universe.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("No universe.json yet; attestations will be asked once you choose stocks.")
        return 0
    print(
        "Check NSE's ASM/GSM surveillance lists and today's corporate announcements, "
        "then say where you looked."
    )
    for instrument in universe.get("instruments", [])[:10]:
        code = _run(
            "pretrade.py", "attest", "--config", str(config), "--symbol", instrument["symbol"]
        )
        if code:
            return code
    return 0


def report(config: Path, email: bool) -> int:
    if _run("evidence.py", "collect", "--config", str(config)):
        print("News collection failed; the report will use the headlines already collected.")
    return _run("premarket.py", "--config", str(config), *(["--email"] if email else []))


def _book_summary(path: Path) -> dict | None:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as conn:
            row = conn.execute("SELECT data FROM book WHERE id=1").fetchone()
    except sqlite3.Error:
        return None
    return json.loads(row[0]) if row else None


def closed_trades(book: dict, since: dt.date | None = None) -> list[dict]:
    entries = {event["id"]: event for event in book.get("events", []) if event["side"] == "buy"}
    trades = []
    for event in book.get("events", []):
        if event["side"] != "sell":
            continue
        day = dt.datetime.fromisoformat(event["as_of"]).astimezone(IST).date()
        if since and day < since:
            continue
        entry = entries.get(event.get("entry_event_id"), {})
        trades.append(
            {
                "date": str(day),
                "symbol": event["symbol"],
                "qty": event.get("qty"),
                "entry_inr": entry.get("assumed_fill_inr"),
                "exit_inr": event.get("assumed_fill_inr"),
                "strategy": (entry.get("research_meta") or {}).get("strategy_version", "manual"),
                "net_inr": Decimal(event.get("net_realized_pnl_inr", "0")),
            }
        )
    return trades


def status(config: Path) -> int:
    print("== Setup")
    _run("preflight.py", "--config", str(config))
    from observatory import desk_state

    desk = desk_state(config.parent)
    print("\n== Today's desk")
    if desk["report"]:
        item = desk["report"]
        print(f"{item['session_date']} · {item['mode']} · {item['reason']}")
        for pick in item["picks"]:
            print(
                f"  {pick['symbol']}: {pick['rating']}, {pick['conviction']} conviction, "
                f"{pick.get('strategy') or 'any proven strategy'}"
            )
        if not item["picks"]:
            print("  no picks")
    else:
        print("  no pre-market report yet (itl report)")
    print("\n== Strategy tournament")
    card = desk["scorecard"]
    if card:
        for name, result in card["strategies"].items():
            verdict = "proven" if result["eligible"] else f"not proven: {result['reason']}"
            print(f"  {name}: {verdict}")
    else:
        print("  no scorecard yet (itl tournament)")
    print("\n== Paper book")
    book = _book_summary(config.parent / "paper.sqlite")
    if book:
        today = str(dt.datetime.now(IST).date())
        print(
            f"  cash INR {book['cash']} · open positions {len(book['positions'])} · "
            f"realised today INR {book.get('realized_by_day', {}).get(today, '0')}"
            + (" · PAUSED" if book.get("paused") else "")
        )
    else:
        print("  no forward paper book yet (paper_book.py init, see docs/live-data.md)")
    return 0


def track(config: Path, days: int) -> int:
    book = _book_summary(config.parent / "paper.sqlite")
    if not book:
        print("No forward paper book yet.")
        return 2
    since = dt.datetime.now(IST).date() - dt.timedelta(days=days)
    trades = closed_trades(book, since)
    wins = [trade for trade in trades if trade["net_inr"] > 0]
    net = sum((trade["net_inr"] for trade in trades), Decimal(0))
    print(f"# Paper track record, last {days} days (to {dt.datetime.now(IST).date()})\n")
    print("Virtual money, assumed fills, costs included. Not a forecast or advice.\n")
    print(
        f"- Closed trades: {len(trades)}\n- Wins: {len(wins)}"
        + (f" ({100 * len(wins) / len(trades):.0f}%)" if trades else "")
        + f"\n- Net after costs: INR {net:,.2f}\n"
    )
    if trades:
        print("| Date | Symbol | Strategy | Qty | Entry | Exit | Net INR |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        for trade in reversed(trades):
            print(
                f"| {trade['date']} | {trade['symbol']} | {trade['strategy']} | {trade['qty']} "
                f"| {trade['entry_inr']} | {trade['exit_inr']} | {trade['net_inr']:,.2f} |"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    sub.add_parser("login")
    sub.add_parser("report").add_argument("--email", action="store_true")
    sub.add_parser("tournament")
    sub.add_parser("status")
    sub.add_parser("track").add_argument("--days", type=int, default=7)
    sub.add_parser("dashboard")
    args = parser.parse_args(argv)
    config = args.config
    if args.command == "setup":
        return setup(config)
    if args.command == "login":
        return login(config)
    if args.command == "report":
        return report(config, args.email)
    if args.command == "tournament":
        return _run("tournament.py", "--config", str(config))
    if args.command == "status":
        return status(config)
    if args.command == "track":
        return track(config, max(1, min(args.days, 366)))
    return _run("observatory.py", "--data-dir", str(config.parent))


if __name__ == "__main__":
    sys.exit(main())

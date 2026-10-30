#!/usr/bin/env python3
"""Budget Manager and Risk Manager: size a plan to the paper book and say PASS or BLOCK.

Reads ``desk/plan.json`` (entry, stop, target) and the forward paper book, then:

**Budget.** Finds the most whole shares that fit every limit the paper book
itself enforces, and says which limit decided it:

| limit | the rule |
| --- | --- |
| risk per trade | loss at the stop, with slippage, the entry fee and the exit-fee reserve |
| largest position | entry cost including the fee |
| cash | entry cost, its exit-fee reserve and the reserves of open positions |
| daily loss | today's realised loss, plus open planned losses, plus this one |

The entry it sizes at is the plan's entry, or a fresh price (``--price``, under 15
minutes old) when that is higher: a price that ran up means more risk per share.

**Risk.** Then it checks, in order, everything that would make the paper book
refuse the trade or that the desk's rules forbid: the halt switch, pause, loss
streak and drawdown stops, trades today and open positions, a position already
held or left from a prior day, the book's stock list, the plan's date and the
entry window, reward:risk (``min_reward_risk``, 1.0 by default), and a learned
cooldown on the stock. Any failure is a BLOCK with the reason. Warnings (a stale
price, a target under 2R) do not block.

It writes ``desk/ticket.json``: a proposal only. Nothing is recorded or placed;
the paper autopilot or ``paper_book.py`` records virtual fills under the same rules.

    python3 trade_check.py
    python3 trade_check.py --price 1615.20 --price-time "2026-10-29 09:52" --write
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
FRESH_SECONDS = 15 * 60


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def size(plan: dict, book: dict, config: dict, entry: float, day: str) -> dict[str, Any]:
    """Whole shares that fit every paper-book limit, and which limit decided it. Pure."""
    slip = _d(config.get("slippage_bps", "5")) / 10_000
    fee_bps = _d(config.get("fee_bps", "5")) / 10_000
    fee_flat = _d(config.get("fee_flat_inr", "10"))
    px = _d(entry) * (1 + slip)
    stop = _d(plan["stop"]) * (1 - slip)
    limits = {key: _d(value) for key, value in book["limits"].items()}
    positions = book["positions"]
    open_risk = sum((_d(p["planned_loss_inr"]) for p in positions.values()), Decimal(0))
    reserves = sum((_d(p["exit_fee_reserve_inr"]) for p in positions.values()), Decimal(0))
    realized = _d(book["realized_by_day"].get(day, "0"))
    daily_left = limits["daily_loss"] - max(Decimal(0), -realized) - open_risk
    cash = _d(book["cash"])

    def fee(qty: int) -> Decimal:
        return fee_flat + px * qty * fee_bps

    def checks(qty: int) -> dict[str, bool]:
        loss = (px - stop) * qty + 2 * fee(qty)
        cost = px * qty + fee(qty)
        return {
            "risk per trade": loss <= limits["risk"],
            "largest position": cost <= limits["position_limit"],
            "cash": cost + fee(qty) + reserves <= cash,
            "daily loss": loss <= daily_left,
        }

    per_share = px - stop
    upper = int(limits["position_limit"] / px) if px > 0 else 0
    if per_share > 0:
        upper = min(upper, int(limits["risk"] / per_share))
    qty = max(upper, 0)
    while qty > 0 and not all(checks(qty).values()):
        qty -= 1
    probe = checks(qty + 1)
    decided = next((name for name, ok in probe.items() if not ok), "risk per trade")
    loss = (px - stop) * qty + 2 * fee(qty) if qty else Decimal(0)
    return {
        "qty": qty,
        "decided_by": decided,
        "assumed_entry_inr": float(round(px, 2)),
        "cost_inr": float(round(px * qty + fee(qty), 2)) if qty else 0.0,
        "fee_inr": float(round(fee(qty), 2)) if qty else 0.0,
        "exit_fee_reserve_inr": float(round(fee(qty), 2)) if qty else 0.0,
        "planned_loss_inr": float(round(loss, 2)),
        "daily_loss_left_inr": float(round(daily_left, 2)),
        "limits_inr": {key: float(value) for key, value in limits.items()},
    }


def review(
    plan: dict,
    book: dict,
    config: dict,
    clock: dt.datetime,
    times: dict | None,
    price: float | None = None,
    price_time: dt.datetime | None = None,
    cooldowns: dict[str, str] | None = None,
) -> dict[str, Any]:
    """PASS or BLOCK with every reason, the size, and warnings. Pure."""
    blocks, warnings = [], []
    symbol, day = plan["symbol"], str(clock.date())
    entry = float(plan["entry"])
    if price is not None:
        age = (clock - price_time).total_seconds() if price_time else None
        if age is None or not -5 <= age <= FRESH_SECONDS:
            warnings.append("the price given is not from the last 15 minutes; it was not used")
        elif price > entry:
            entry = price
            warnings.append(f"price ran up to ₹{price:.2f}; sized from there, not the plan")
        if age is not None and age > 120:
            warnings.append("the paper book records only quotes under 2 minutes old")
    if os.environ.get("INDIA_TRADE_LAB_HALT", "0") != "0":
        blocks.append("the halt switch (INDIA_TRADE_LAB_HALT) is on")
    controls = book.get("controls") or {}
    if book.get("paused"):
        blocks.append("new entries are paused in the paper book")
    if book.get("loss_streak", 0) >= controls.get("max_loss_streak", 2):
        blocks.append("the consecutive-loss stop is reached; review before trading again")
    if _d(book.get("closed_trade_drawdown_inr", "0")) >= _d(controls.get("drawdown_stop_inr", "0")):
        blocks.append("the drawdown stop is reached")
    entries = sum(event["side"] == "buy" and event["as_of"][:10] == day for event in book["events"])
    if entries >= controls.get("max_trades_per_day", 3):
        blocks.append(
            f"already {entries} entries today (limit {controls.get('max_trades_per_day')})"
        )
    if len(book["positions"]) >= controls.get("max_open_positions", 2):
        blocks.append(
            f"{len(book['positions'])} positions open (limit {controls.get('max_open_positions')})"
        )
    if symbol in book["positions"]:
        blocks.append(f"{symbol} is already held; close it before re-entering")
    if any(position["day"] != day for position in book["positions"].values()):
        blocks.append("a position from a prior day is still open")
    if symbol not in book["symbols"]:
        blocks.append(f"{symbol} is not on the paper book's stock list")
    if plan["date"] != day:
        blocks.append(f"the plan is for {plan['date']}, not today; make a new plan")
    if times is None:
        blocks.append("NSE is closed today")
    else:
        if clock < times["open"] + dt.timedelta(minutes=15):
            blocks.append("the opening range is still forming; no entries before 09:30")
        if clock >= times["entry_cutoff"]:
            blocks.append(f"past the {times['entry_cutoff']:%H:%M} entry cutoff")
    stop, target = float(plan["stop"]), float(plan["target"])
    if not stop < entry:
        blocks.append("the stop is not below the entry")
    if not target > entry:
        blocks.append("the target is not above the entry; the move already happened")
    if stop < entry < target:
        reward_risk = (target - entry) / (entry - stop)
        minimum = float(config.get("min_reward_risk", 1.0))
        if reward_risk < minimum:
            blocks.append(f"reward:risk {reward_risk:.2f} is under the minimum {minimum:g}")
        elif reward_risk < 2:
            warnings.append(f"reward:risk is {reward_risk:.2f}; the desk's strategies use 2R")
    if cooldowns and symbol in cooldowns:
        blocks.append(f"{symbol} is on a learning cooldown: {cooldowns[symbol]}")
    sized = size(plan, book, config, entry, day) if stop < entry else {"qty": 0}
    if sized["qty"] < 1 and stop < entry:
        blocks.append(f"no whole share fits the {sized['decided_by']} limit")
    return {
        "verdict": "BLOCK" if blocks else "PASS",
        "symbol": symbol,
        "checked_at": clock.isoformat(),
        "blocks": blocks,
        "warnings": warnings,
        "plan": {key: plan.get(key) for key in ("entry", "stop", "target", "target_r", "flat_by")},
        "sized_at_inr": entry,
        **sized,
        "notice": "A proposal only: nothing was recorded or placed. Paper money only.",
    }


def describe(result: dict) -> str:
    lines = [f"{result['verdict']}  {result['symbol']} at ₹{result['sized_at_inr']:.2f}"]
    if result.get("qty"):
        lines.append(
            f"  Size  {result['qty']} shares, ₹{result['cost_inr']:,.2f} "
            f"(decided by the {result['decided_by']} limit)"
        )
        lines.append(
            f"  Loss at the stop  ₹{result['planned_loss_inr']:,.2f} with fees and slippage; "
            f"₹{result['daily_loss_left_inr']:,.2f} of today's loss limit was left"
        )
    lines += [f"  BLOCK: {reason}" for reason in result["blocks"]]
    lines += [f"  note: {reason}" for reason in result["warnings"]]
    lines.append(result["notice"])
    return "\n".join(lines)


def _cooldowns(config_path: Path, config: dict, clock: dt.datetime) -> dict[str, str]:
    try:
        import learning

        folder = intraday.config_folder(config_path)
        store = learning.LearningStore(folder / config.get("learning_db", "learning.sqlite"))
        return store.context([], clock).get("cooldowns", {})
    except (ImportError, AttributeError, TypeError, ValueError, OSError, sqlite3.Error):
        return {}


def main(argv: list[str] | None = None) -> int:
    import decision_pipeline

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--price", type=float, help="a fresh price, to size from if higher")
    parser.add_argument("--price-time", help='"YYYY-MM-DD HH:MM" IST, when that price was seen')
    parser.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" IST')
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    desk = intraday.desk_dir(args.config)
    try:
        config = intraday.load_config(args.config)
        plan = intraday.read_json(args.plan or desk / "plan.json")
        book = decision_pipeline.read_book(
            intraday.config_folder(args.config) / config.get("book", "paper.sqlite")
        )
        clock = intraday.now_ist(args.now)
        times = intraday.session_times(intraday.sessions_manifest(args.config), clock.date())
        seen = intraday.now_ist(args.price_time) if args.price_time else None
        result = review(
            plan, book, config, clock, times, args.price, seen,
            _cooldowns(args.config, config, clock),
        )  # fmt: skip
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        print(f"Trade check refused: {exc}", file=sys.stderr)
        return 2
    if args.write:
        intraday.write_json(desk / "ticket.json", result)
    print(json.dumps(result, indent=2) if args.json else describe(result))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

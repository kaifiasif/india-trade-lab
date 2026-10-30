#!/usr/bin/env python3
"""Desk-wide safety rules for both paper books. Each rule can only stop or close trades.

| Rule | Where it is enforced |
| --- | --- |
| No entries on stale or incomplete data | Quote age (2 minutes) and complete five-minute bars in the coordinator and journal; swing entries check the Kite quote's own timestamp |
| No entries in high-volatility or illiquid conditions | :func:`entry_guard`: India VIX at or above ``max_india_vix`` or the Nifty 50 moved ``max_index_move_pct`` from its previous close blocks new entries; unknown conditions (no reading in ``guard_max_age_seconds``) also block. Spread (20 bps) and traded-value floors stay in the journal and scans |
| No duplicate positions | One position per stock per book (journal), and :func:`held_elsewhere` stops a stock held in the other book |
| Stop and target before entry | The journal refuses a forward entry without both |
| Ambiguous candles | Every simulator assumes the stop first |
| Reward after costs | The journal refuses a forward entry whose reward at the target, after round-trip costs, is below its loss at the stop (1.0); :func:`net_reward_risk` with ``min_net_reward_risk`` (1.5) is checked before that |
| Daily loss limit | The journal: realised loss plus open planned loss may not exceed it |
| Square-off | :func:`square_off` closes every intraday paper position at or after ``flat_by``, whatever the autopilot setting, and closes a position left from an earlier day at the first valid quote |
| Restart recovery | :func:`recover` runs when the worker starts: it verifies both journals' checksums, closes overdue intraday positions, rebuilds swing tracking and reports what it found |

Paper only: nothing here can place an order.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
VIX_KEY = "NSE:INDIA VIX"
NIFTY_KEY = "NSE:NIFTY 50"
DEFAULTS: dict[str, Any] = {
    "market_guard": True,
    "max_india_vix": 22.0,
    "max_index_move_pct": 2.0,
    "guard_max_age_seconds": 180,
    "min_net_reward_risk": 1.5,
    "auto_square_off": True,
}


def settings(config: dict) -> dict[str, Any]:
    return {**DEFAULTS, **(config.get("safety") or {})}


# ---------- market conditions ----------


def read_conditions(quotes: dict[str, dict], clock: dt.datetime, cfg: dict) -> dict[str, Any]:
    """India VIX and the Nifty's move from its previous close, and what they block. Pure."""
    vix = (quotes.get(VIX_KEY) or {}).get("last_price")
    nifty = quotes.get(NIFTY_KEY) or {}
    last, previous = nifty.get("last_price"), (nifty.get("ohlc") or {}).get("close")
    move = round(100 * (last / previous - 1), 2) if last and previous else None
    blocks = []
    if vix is None or move is None:
        blocks.append("India VIX or the Nifty 50 was not available")
    if vix is not None and vix >= float(cfg["max_india_vix"]):
        blocks.append(f"India VIX {vix:.1f} is at or above {float(cfg['max_india_vix']):g}")
    if move is not None and abs(move) >= float(cfg["max_index_move_pct"]):
        blocks.append(f"the Nifty 50 is {move:+.2f}% from its previous close")
    return {"at": clock.isoformat(), "india_vix": vix, "nifty_move_pct": move, "blocks": blocks}


def refresh_conditions(config_path: Path, clock: dt.datetime, quotes_for: Callable) -> dict:
    """Read the market's conditions now and save them for every entry check this tick."""
    cfg = settings(intraday.load_config(config_path))
    reading = read_conditions(quotes_for([VIX_KEY, NIFTY_KEY]), clock, cfg)
    intraday.write_json(intraday.config_folder(config_path) / "market-guard.json", reading)
    return reading


def entry_guard(config_path: Path, clock: dt.datetime) -> str:
    """Why no new entry may be made now because of market conditions; empty means go."""
    cfg = settings(intraday.load_config(config_path))
    if not cfg["market_guard"]:
        return ""
    path = intraday.config_folder(config_path) / "market-guard.json"
    try:
        reading = json.loads(path.read_text(encoding="utf-8"))
        age = (clock - dt.datetime.fromisoformat(reading["at"])).total_seconds()
    except (OSError, ValueError, KeyError):
        return "market conditions (India VIX, Nifty) have not been read yet"
    if not -5 <= age <= int(cfg["guard_max_age_seconds"]):
        return "market conditions are stale; no new entries until they are read again"
    if reading.get("blocks"):
        return "market guard: " + "; ".join(reading["blocks"])
    return ""


# ---------- duplicates across books ----------


def _read(path: Path) -> dict | None:
    import guardrails

    if not path.is_file():
        return None
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
        row = conn.execute("SELECT data FROM book WHERE id=1").fetchone()
    if row is None:
        return None
    book = json.loads(row[0])
    guardrails.verify_state(book)
    return book


def book_paths(config_path: Path) -> dict[str, Path]:
    config = intraday.load_config(config_path)
    folder = intraday.config_folder(config_path)
    swing_book = ((config.get("swing") or {}).get("book")) or "swing.sqlite"
    return {"intraday": folder / config.get("book", "paper.sqlite"), "swing": folder / swing_book}


def held_elsewhere(config_path: Path, symbol: str, entering: str) -> str:
    """Why ``symbol`` may not be entered in the ``entering`` book: the other book holds it."""
    other = "swing" if entering == "intraday" else "intraday"
    try:
        book = _read(book_paths(config_path)[other])
    except (ValueError, OSError, sqlite3.Error):
        return f"the {other} book could not be read, so a duplicate cannot be ruled out"
    if book and symbol in book.get("positions", {}):
        return f"{symbol} is already held in the {other} book"
    return ""


# ---------- reward after costs ----------


def net_reward_risk(
    entry: float,
    stop: float,
    target: float,
    qty: int,
    fee_bps: float,
    fee_flat: float,
    slip_bps: float,
) -> float:
    """Reward at the target over loss at the stop, both after round-trip fees and slippage."""
    if qty < 1 or not stop < entry < target:
        return 0.0

    def fee(price: float) -> float:
        return fee_flat + price * qty * fee_bps / 10_000

    slip = slip_bps / 10_000
    bought = entry * (1 + slip)
    reward = (target * (1 - slip) - bought) * qty - fee(bought) - fee(target)
    loss = (bought - stop * (1 - slip)) * qty + fee(bought) + fee(stop)
    return round(reward / loss, 3) if loss > 0 else 0.0


# ---------- square-off and recovery ----------


def square_off(
    config_path: Path, clock: dt.datetime, quotes_for: Callable[[list[str]], dict]
) -> dict[str, Any]:
    """Close intraday paper positions due for square-off: today's after flat_by, older ones now."""
    import guardrails

    import paper_book

    config = intraday.load_config(config_path)
    cfg = settings(config)
    result: dict[str, Any] = {"closed": [], "waiting": {}}
    if not cfg["auto_square_off"]:
        return {**result, "status": "off"}
    path = book_paths(config_path)["intraday"]
    book = _read(path)
    if not book or not book["positions"]:
        return {**result, "status": "nothing open"}
    times = intraday.session_times(intraday.sessions_manifest(config_path), clock.date())
    if times is None or not times["open"] <= clock < times["close"]:
        due = {s: "waiting for the next session's quotes" for s in book["positions"]}
        return {**result, "waiting": due, "status": "market closed"}
    today = str(clock.date())
    due = {
        symbol: ("square-off" if position["day"] == today else "overdue square-off after a restart")
        for symbol, position in book["positions"].items()
        if position["day"] != today or clock >= times["flat_by"]
    }
    if not due:
        return {**result, "status": "not yet"}
    quotes = quotes_for(list(due))
    fee_bps, fee_flat = (
        Decimal(str(config.get("fee_bps", "5"))),
        Decimal(str(config.get("fee_flat_inr", "10"))),
    )
    for symbol, why in due.items():
        quote = quotes.get(symbol) or {}
        bid = (((quote.get("depth") or {}).get("buy") or [{}])[0]).get("price") or quote.get(
            "last_price"
        )
        if not bid:
            result["waiting"][symbol] = "no quote yet"
            continue
        price = Decimal(str(bid))
        try:
            with sqlite3.connect(path, isolation_level=None, timeout=10) as conn:
                conn.execute("BEGIN IMMEDIATE")
                state = json.loads(conn.execute("SELECT data FROM book WHERE id=1").fetchone()[0])
                guardrails.verify_state(state)
                held = state["positions"].get(symbol)
                if held is None:
                    conn.execute("ROLLBACK")
                    continue
                fee = fee_flat + price * held["qty"] * fee_bps / 10_000
                state = paper_book.fill(
                    state, "sell", f"squareoff:{today}:{symbol}", symbol, str(price),
                    clock.isoformat(), "kite:quote", f"{fee:.2f}", str(config.get("slippage_bps", "5")),
                    now=clock,
                )  # fmt: skip
                guardrails.seal_state(state)
                conn.execute("INSERT OR REPLACE INTO book VALUES (1, ?)", (json.dumps(state),))
                conn.execute("COMMIT")
        except (ValueError, KeyError, sqlite3.Error) as exc:
            result["waiting"][symbol] = str(exc)[:160]
            continue
        result["closed"].append({"symbol": symbol, "price": float(price), "why": why})
    return {**result, "status": "done"}


def recover(
    config_path: Path, clock: dt.datetime, quotes_for: Callable[[list[str]], dict] | None = None
) -> dict[str, Any]:
    """When the worker starts: check both journals, reopen tracking and close what is overdue."""
    report: dict[str, Any] = {"at": clock.isoformat(), "books": {}}
    for kind, path in book_paths(config_path).items():
        try:
            book = _read(path)
        except ValueError as exc:
            report["books"][kind] = {"status": "CHECKSUM_MISMATCH", "detail": str(exc)[:160]}
            continue
        if book is None:
            report["books"][kind] = {"status": "no book"}
            continue
        report["books"][kind] = {
            "status": "ok",
            "open": {
                s: {"qty": p["qty"], "since": p["day"], "stop": p["stop_inr"]}
                for s, p in book["positions"].items()
            },  # fmt: skip
        }
    if (report["books"].get("swing") or {}).get("status") == "ok":
        import swing

        state = swing._state(config_path)
        rebuilt = [
            s for s in report["books"]["swing"]["open"] if s not in state.get("positions", {})
        ]
        report["books"]["swing"]["tracking_rebuilt"] = (
            rebuilt  # manage() rebuilds from the journal.
        )
    if quotes_for is not None and (report["books"].get("intraday") or {}).get("status") == "ok":
        try:
            report["square_off"] = square_off(config_path, clock, quotes_for)
        except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
            report["square_off"] = {"status": "DATA_BLOCK", "detail": str(exc)[:160]}
    intraday.write_json(intraday.config_folder(config_path) / "recovery.json", report)
    return report


def kite_quotes(symbols: list[str]) -> dict[str, dict]:
    import market_scan

    return market_scan.KiteClient().quote(symbols) if symbols else {}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" IST')
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("conditions", "square-off", "recover"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    clock = intraday.now_ist(args.now)
    try:
        if args.command == "conditions":
            result = refresh_conditions(args.config, clock, kite_quotes)
        elif args.command == "square-off":
            result = square_off(args.config, clock, kite_quotes)
        else:
            result = recover(args.config, clock, kite_quotes)
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        print(f"Safety check refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

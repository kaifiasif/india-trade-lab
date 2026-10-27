#!/usr/bin/env python3
"""Check every live-research prerequisite and say exactly what is missing and how to fix it.

The coordinator fails closed: a missing calendar and a stale quote both end as
DATA_BLOCK. That is right for trading and useless for setting up, so this runs each
prerequisite on its own and reports it separately. Read only: it never writes a
journal, places an order, spends a model call or changes configuration.

Exit codes: 0 everything an entry needs is ready, 1 research runs but entries are
blocked, 2 the run itself cannot proceed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import guardrails
import market_router
from history import HistoryStore

import india_research
import paper_book

OK, WARN, BLOCK, FATAL = "OK", "WARN", "BLOCK", "FATAL"
ICON = {OK: "PASS", WARN: "WARN", BLOCK: "BLOCK", FATAL: "FATAL"}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MAX_JSON = 2_000_000


class Checks:
    """Collected findings. BLOCK stops entries; FATAL stops the run."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, name: str, status: str, detail: str, fix: str = "") -> None:
        self.items.append({"check": name, "status": status, "detail": detail, "fix": fix})

    def worst(self) -> str:
        for level in (FATAL, BLOCK, WARN):
            if any(item["status"] == level for item in self.items):
                return level
        return OK


def _read_json(path: Path) -> Any:
    if path.stat().st_size > MAX_JSON:
        raise ValueError("file exceeds its size limit")
    return json.loads(path.read_text(encoding="utf-8"))


def _age(label: str, stamp: dt.datetime, now: dt.datetime, limit: float) -> tuple[str, str]:
    seconds = (now - stamp).total_seconds()
    if seconds < -5:
        return BLOCK, f"{label} is dated in the future ({stamp.isoformat()})"
    if seconds > limit:
        return BLOCK, f"{label} is {int(seconds)}s old; the limit is {int(limit)}s"
    return OK, f"{label} is {int(max(0, seconds))}s old"


def check_config(path: Path, checks: Checks) -> dict | None:
    if not path.is_file():
        checks.add(
            "configuration", FATAL, f"{path} does not exist",
            f"python3 scripts/decision_pipeline.py init --config {path}",
        )  # fmt: skip
        return None
    try:
        from decision_pipeline import DailyCoordinator

        coordinator = DailyCoordinator(path)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        checks.add(
            "configuration", FATAL, f"{path} was refused: {exc}", "Correct the setting it names"
        )
        return None
    checks.add(
        "configuration", OK, f"{path} parsed; provider {coordinator.config['model_provider']}"
    )
    return coordinator


def check_sessions(coordinator, now: dt.datetime, checks: Checks) -> dict | None:
    path = coordinator.path("sessions")
    if not path.is_file():
        checks.add(
            "exchange calendar", FATAL, f"{path} does not exist",
            "cp skills/day-trader-india/assets/nse-sessions-2026.json "
            f"{path}",
        )  # fmt: skip
        return None
    try:
        manifest = _read_json(path)
        route = market_router.route_market("india", now, manifest)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        checks.add(
            "exchange calendar",
            FATAL,
            f"{path} is not a usable calendar: {exc}",
            "Re-copy the bundled calendar",
        )
        return None
    today = str(now.astimezone(IST).date())
    if route["status"] == "DATA_BLOCK":
        checks.add(
            "exchange calendar",
            FATAL,
            f"{today}: {route['reason']}",
            "Add this dated session, or null if the exchange was closed",
        )
        return manifest
    if route["status"] == "CLOSED":
        checks.add(
            "exchange calendar",
            WARN,
            f"{today} is closed or outside 09:15-15:30; exits may still be reviewed",
        )
    else:
        checks.add(
            "exchange calendar",
            OK,
            f"{today} is open until {route.get('close_ist', '')[11:16]} IST",
        )
    try:
        india_research.session(manifest, now.astimezone(IST).date())
    except ValueError as exc:
        checks.add(
            "session boundaries", WARN, str(exc), "Entry cutoff and flat-by must precede the close"
        )
    return manifest


def check_universe(coordinator, now: dt.datetime, checks: Checks) -> list[str]:
    path = coordinator.path("universe")
    if not path.is_file():
        checks.add(
            "instrument universe", BLOCK, f"{path} does not exist",
            "python3 scripts/make_universe.py --equity-list ~/Downloads/EQUITY_L.csv "
            f"--symbols INFY,TCS --output {path}",
        )  # fmt: skip
        return []
    try:
        universe = _read_json(path)
        published = dt.datetime.fromisoformat(universe["as_of"])
        instruments = universe["instruments"]
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        checks.add(
            "instrument universe",
            BLOCK,
            f"{path} is invalid: {exc}",
            "Rebuild it with make_universe.py",
        )
        return []
    days = (now - published).days if published.tzinfo else -1
    if not 0 <= days <= 30:
        checks.add(
            "instrument universe",
            BLOCK,
            f"published {days} days ago; it must be 0-30",
            "Rebuild it with make_universe.py",
        )
    else:
        checks.add(
            "instrument universe", OK, f"{len(instruments)} instruments, published {days} days ago"
        )
    symbols = []
    for item in instruments:
        symbol = item.get("symbol", "?")
        symbols.append(symbol)
        missing = [key for key in ("data_provider", "instrument_id", "isin") if not item.get(key)]
        if missing:
            checks.add(
                f"mapping {symbol}",
                BLOCK,
                "missing " + ", ".join(missing),
                "Rebuild it with make_universe.py",
            )
    if len(instruments) > 3:
        checks.add(
            "instrument universe",
            WARN,
            f"{len(instruments)} instruments; the live feed maps at most 3",
        )
    return symbols


def check_history(coordinator, symbols: list[str], now: dt.datetime, checks: Checks) -> None:
    path = coordinator.path("history_db")
    if not path.is_file():
        checks.add(
            "historical coverage", BLOCK, f"{path} does not exist",
            "python3 scripts/data_sync.py --config <config> --days 180 --max-symbols 3",
        )  # fmt: skip
        return
    store = HistoryStore(path)
    for symbol in symbols or store.symbols():
        try:
            coverage = store.coverage(symbol, now)
        except (ValueError, sqlite3.Error) as exc:
            checks.add(f"history {symbol}", BLOCK, str(exc))
            continue
        have, need = coverage["completed_sessions"], coverage["minimum_sessions"]
        if not coverage["history_ready"]:
            checks.add(
                f"history {symbol}", BLOCK, f"{have}/{need} complete sessions: {coverage['reason']}",
                "python3 scripts/data_sync.py --config <config> --days 180",
            )  # fmt: skip
            continue
        last = dt.date.fromisoformat(coverage["last_session"])
        stale = (now.astimezone(IST).date() - last).days
        status = WARN if stale > 7 else OK
        checks.add(
            f"history {symbol}",
            status,
            f"{have} sessions, latest {last} ({stale} days old)",
            "Re-run data_sync.py weekly" if status == WARN else "",
        )


def check_book(coordinator, checks: Checks) -> dict | None:
    path = coordinator.path("book")
    if not path.is_file():
        checks.add(
            "forward paper book", FATAL, f"{path} does not exist",
            "python3 scripts/paper_book.py --book <path> init --cash-inr 100000 "
            "--symbols NSE:INFY --risk-inr 250 --daily-loss-inr 750 --position-limit-inr 15000",
        )  # fmt: skip
        return None
    try:
        from decision_pipeline import read_book

        book = read_book(path)
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        checks.add(
            "forward paper book", FATAL, str(exc), "Start a separate version-3 paper_manual book"
        )
        return None
    detail = (
        f"{book['mode']}, cash INR {book['cash']}, risk INR {book['limits']['risk']}, "
        f"{len(book['positions'])} open position(s)"
    )
    checks.add("forward paper book", OK, detail)
    if book.get("paused"):
        checks.add(
            "book state",
            BLOCK,
            f"entries paused: {book.get('pause_reason', '')}",
            "Review, then start a fresh practice period",
        )
    if book.get("loss_streak", 0) >= book["controls"]["max_loss_streak"]:
        checks.add(
            "book state",
            BLOCK,
            "consecutive-loss stop reached",
            "Review the strategy before new entries",
        )
    return book


def check_feeds(coordinator, symbols: list[str], now: dt.datetime, checks: Checks) -> None:
    bars = coordinator.path("bars")
    if not bars.is_file():
        checks.add(
            "current candles", BLOCK, f"{bars} does not exist",
            "python3 scripts/data_sync.py --config <config> --current",
        )  # fmt: skip
    else:
        try:
            rows = india_research.bars_from_csv(bars)
            latest = max(row["t"] for row in rows)
            status, detail = _age("latest candle", latest + india_research.BAR, now, 900)
            checks.add(
                "current candles",
                status,
                f"{len(rows)} bars; {detail}",
                "Run data_sync.py --current, or start market_service.py --refresh-india"
                if status != OK
                else "",
            )
        except (ValueError, OSError, KeyError) as exc:
            checks.add("current candles", BLOCK, f"{bars} is invalid: {exc}")
    path = coordinator.path("quotes")
    if not path.is_file():
        checks.add(
            "current quotes", BLOCK, f"{path} does not exist",
            "python3 scripts/quote_data.py --provider kite --symbol NSE:INFY --output <path>",
        )  # fmt: skip
        return
    try:
        quotes = _read_json(path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        checks.add("current quotes", BLOCK, f"{path} is invalid: {exc}")
        return
    for symbol in symbols or list(quotes):
        quote = quotes.get(symbol)
        if not isinstance(quote, dict):
            checks.add(
                f"quote {symbol}",
                BLOCK,
                "no quote for this symbol",
                "Map it in universe.json and refresh the feed",
            )
            continue
        try:
            observed = paper_book.timestamp(quote["as_of"])
            bid = paper_book.number(quote["bid_inr"], True)
            ask = paper_book.number(quote["ask_inr"], True)
        except (ValueError, KeyError, TypeError) as exc:
            checks.add(f"quote {symbol}", BLOCK, f"unusable quote: {exc}")
            continue
        status, detail = _age("quote", observed, now, 120)
        extra = []
        if quote.get("timestamp_kind", "exchange") != "exchange":
            status, extra = (
                BLOCK,
                ["no exchange bid/ask timestamp (last-trade time cannot replace it)"],
            )
        if bid > ask:
            status, extra = BLOCK, [*extra, "crossed bid/ask"]
        if "SYNTHETIC" in str(quote.get("source", "")).upper():
            status, extra = BLOCK, [*extra, "synthetic source cannot support a forward call"]
        spread = (ask - bid) / ((ask + bid) / 2) * 10000
        if spread > 20:
            status, extra = BLOCK, [*extra, f"spread {spread:.1f} bps exceeds the 20 bps ceiling"]
        checks.add(
            f"quote {symbol}",
            status,
            "; ".join([detail, *extra]),
            "Refresh quotes during market hours" if status != OK else "",
        )


def check_evidence(coordinator, symbols: list[str], now: dt.datetime, checks: Checks) -> None:
    for name, label in (
        ("pretrade_evidence", "pre-trade evidence"),
        ("research_evidence", "research evidence"),
    ):
        path = coordinator.path(name)
        if not path.is_file():
            fix = (
                "python3 scripts/evidence.py collect --config <config>"
                if name == "research_evidence"
                else "python3 scripts/pretrade.py --config <config> --symbol NSE:INFY"
            )
            checks.add(label, BLOCK, f"{path} does not exist", fix)
            continue
        try:
            payload = _read_json(path)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            checks.add(label, BLOCK, f"{path} is invalid: {exc}")
            continue
        for symbol in symbols or list(payload):
            item = payload.get(symbol)
            if not item:
                checks.add(f"{label} {symbol}", BLOCK, "nothing recorded for this symbol")
                continue
            if name == "research_evidence":
                checks.add(f"{label} {symbol}", OK, f"{len(item)} dated item(s)")
                continue
            missing = [
                check for check in guardrails.REQUIRED_CHECKS
                if (item.get("checks") or {}).get(check) is not True
            ]  # fmt: skip
            if missing:
                checks.add(
                    f"{label} {symbol}",
                    BLOCK,
                    "unconfirmed: " + ", ".join(missing),
                    "Re-run pretrade.py and confirm each check",
                )
                continue
            try:
                status, detail = _age(
                    "evidence check", guardrails.evidence_time(item["checked_at"]), now, 120
                )
            except (ValueError, KeyError):
                checks.add(f"{label} {symbol}", BLOCK, "checked_at is missing or unreadable")
                continue
            checks.add(
                f"{label} {symbol}",
                status,
                detail,
                "Re-confirm within 120 seconds of the quote" if status != OK else "",
            )


def check_models(coordinator, checks: Checks) -> None:
    provider = coordinator.config["model_provider"]
    if provider == "disabled":
        checks.add(
            "research models", BLOCK, "model_provider is 'disabled', so every review is DATA_BLOCK",
            "Set model_provider (openai, anthropic, gemini or local) and its key, or accept exits-only research",
        )  # fmt: skip
        return
    env = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }.get(provider)
    if env and not os.environ.get(env):
        checks.add(
            "research models",
            BLOCK,
            f"{env} is not set in this terminal",
            f"export {env}=... (keep it out of Git)",
        )
    else:
        where = (
            coordinator.config["local_base_url"] if provider == "local" else "the official endpoint"
        )
        checks.add("research models", OK, f"{provider} via {where}")
    debate = coordinator.config["debate"]
    if debate["enabled"]:
        import debate as debate_module

        calls = debate_module.planned_calls(debate["research_rounds"], debate["risk_rounds"])
        budget = coordinator.config["max_model_calls_per_day"]
        per_candidate = (
            calls + len(coordinator.config["required_roles"])
            if coordinator.config.get("required_roles")
            else calls + 6
        )
        checks.add(
            "model budget", OK if per_candidate <= budget else WARN,
            f"about {per_candidate} calls per candidate against a daily budget of {budget}",
            "Raise max_model_calls_per_day or lower the debate rounds" if per_candidate > budget else "",
        )  # fmt: skip


def check_credentials(checks: Checks) -> None:
    present = [name for name in ("KITE_API_KEY", "KITE_ACCESS_TOKEN") if os.environ.get(name)]
    if len(present) == 2:
        checks.add(
            "broker credentials",
            OK,
            "KITE_API_KEY and KITE_ACCESS_TOKEN are set (values not shown)",
        )
    else:
        checks.add(
            "broker credentials", WARN,
            "not set in this terminal; only the live collectors need them",
            "python3 scripts/kite_login.py && source ~/.india-trade-lab.env",
        )  # fmt: skip


def run(config_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    checks = Checks()
    clock = now or dt.datetime.now(IST)
    coordinator = check_config(config_path, checks)
    if coordinator is not None:
        check_sessions(coordinator, clock, checks)
        symbols = check_universe(coordinator, clock, checks)
        check_history(coordinator, symbols, clock, checks)
        check_book(coordinator, checks)
        check_feeds(coordinator, symbols, clock, checks)
        check_evidence(coordinator, symbols, clock, checks)
        check_models(coordinator, checks)
    check_credentials(checks)
    worst = checks.worst()
    summary = {
        OK: "Ready: every prerequisite for a reviewed entry proposal is in place.",
        WARN: "Ready with warnings; read them before relying on a proposal.",
        BLOCK: "Research and exit reviews can run; entry proposals are blocked.",
        FATAL: "The coordinator cannot run until the fatal items are fixed.",
    }[worst]
    return {
        "as_of": clock.isoformat(),
        "config": str(config_path),
        "status": worst,
        "summary": summary,
        "checks": checks.items,
        "notice": "Preflight checks inputs only. Passing says nothing about whether a "
        "strategy is profitable, and never authorises a real order.",
    }


def render(result: dict) -> str:
    lines = [f"India Trade Lab preflight · {result['as_of']}", ""]
    width = max((len(item["check"]) for item in result["checks"]), default=10)
    for item in result["checks"]:
        lines.append(f"  [{ICON[item['status']]:5s}] {item['check']:<{width}}  {item['detail']}")
        if item["fix"] and item["status"] != OK:
            lines.append(f"          {' ' * width}  fix: {item['fix']}")
    lines += ["", result["summary"], "", result["notice"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)
    result = run(args.config)
    print(json.dumps(result, indent=2) if args.json else render(result))
    return {OK: 0, WARN: 0, BLOCK: 1, FATAL: 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())

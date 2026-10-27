#!/usr/bin/env python3
"""Paper autopilot: record the agents' approved calls in the virtual book, all session.

The coordinator already does the deciding. Each tick it reviews every candidate
with the evidence roles and the bull/bear and risk debate, freezes a ticket, and
proposes protective exits (stop, target, square-off) for open positions. Until
now a person had to copy an approved ticket into the journal. With the autopilot
on, the market service records those calls itself:

- **Exits** (``SELL_PAPER_PROPOSAL``) are recorded first, whenever proposed.
- **Entries** (``BUY_PAPER_PROPOSAL``, the one selected per snapshot) are recorded
  only when the stock is one of today's pre-market judge picks (unless
  ``require_premarket_pick`` is false), the book has not changed since the ticket
  was frozen, and the pre-trade evidence still matches the ticket's digest.

Every journal guard still applies at the moment of recording: quote age, entry
cutoff, per-trade risk, daily loss, trade and position caps, loss streak,
drawdown stop, pause and ``INDIA_TRADE_LAB_HALT``. A refused recording is logged
with its reason and retried on a later tick only through a fresh decision.

Virtual money only. This module has no broker client and cannot place an order.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

import agent_workflow
import guardrails

import paper_book

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def todays_picks(reports_dir: Path, session_date: str) -> list[str] | None:
    """The judge's watchlist for today, or None when no pre-market report was written."""
    path = reports_dir / f"premarket-{session_date}.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if report.get("session_date") != session_date or not isinstance(report.get("watching"), list):
        return None
    return [str(symbol) for symbol in report["watching"]]


def _write(conn: sqlite3.Connection, state: dict) -> None:
    guardrails.seal_state(state)
    conn.execute("INSERT OR REPLACE INTO book VALUES (1, ?)", (json.dumps(state),))


def apply(coordinator: Any, report: dict, now: dt.datetime | None = None) -> dict[str, Any]:
    """Record approved paper exits and the selected entry from one coordinator report."""
    settings = getattr(coordinator, "config", {}).get("autopilot") or {}
    enabled = settings.get("enabled") is True
    outcome: dict[str, Any] = {"enabled": enabled, "recorded": [], "skipped": []}
    if not enabled:
        return outcome
    if report.get("cached") or report.get("status") == "ARCHIVED_RESULT":
        outcome["skipped"].append({"reason": "archived result; nothing current to record"})
        return outcome
    clock = (now or dt.datetime.now(IST)).astimezone(IST)
    session_date = str(clock.date())
    picks = todays_picks(coordinator.path("reports_dir"), session_date)
    calls = sorted(
        report.get("calls", []),
        key=lambda call: call.get("decision") != "SELL_PAPER_PROPOSAL",
    )
    book_path = coordinator.path("book")
    slippage = coordinator.config["slippage_bps"]
    pretrade = {}
    try:
        pretrade = json.loads(coordinator.path("pretrade_evidence").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pretrade = {}
    for call in calls:
        decision, symbol = call.get("decision"), call.get("symbol")
        ticket = call.get("proposal") or {}
        if decision == "BUY_PAPER_PROPOSAL" and not call.get("selected"):
            continue
        if decision not in ("BUY_PAPER_PROPOSAL", "SELL_PAPER_PROPOSAL"):
            continue
        if decision == "BUY_PAPER_PROPOSAL" and settings.get("require_premarket_pick", True):
            if picks is None:
                outcome["skipped"].append(
                    {"symbol": symbol, "reason": "no pre-market report today; entries wait"}
                )
                continue
            if symbol not in picks:
                outcome["skipped"].append(
                    {"symbol": symbol, "reason": "not one of today's pre-market judge picks"}
                )
                continue
        try:
            with sqlite3.connect(book_path, isolation_level=None, timeout=10) as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT data FROM book WHERE id=1").fetchone()
                if row is None:
                    raise ValueError("No paper book")
                state = json.loads(row[0])
                guardrails.verify_state(state)
                if state.get("mode") != "paper_manual":
                    raise ValueError("Autopilot records only into the forward paper book")
                if decision == "SELL_PAPER_PROPOSAL":
                    held = state["positions"].get(symbol)
                    if not held or held["qty"] != ticket["qty"]:
                        raise ValueError("Position changed since the exit was proposed")
                    state = paper_book.fill(
                        state,
                        "sell",
                        f"auto:{report['run_id']}:{symbol}:X",
                        symbol,
                        ticket["price_inr"],
                        ticket["quote_as_of"],
                        ticket["quote_source"],
                        ticket["fee_inr"],
                        slippage,
                        now=clock,
                    )
                else:
                    if state["state_sha256"] != ticket["book_state_sha256"]:
                        raise ValueError("Book changed since the ticket was frozen")
                    evidence = pretrade.get(symbol)
                    if evidence is None or (
                        agent_workflow.proposal_digest(evidence) != ticket["pretrade_sha256"]
                    ):
                        raise ValueError("Pre-trade evidence no longer matches the ticket")
                    state = paper_book.fill(
                        state,
                        "buy",
                        ticket["event_id"],
                        symbol,
                        ticket["price_inr"],
                        ticket["quote_as_of"],
                        ticket["quote_source"],
                        ticket["fee_inr"],
                        ticket["slippage_bps"],
                        ticket["qty"],
                        ticket["stop_inr"],
                        ticket["exit_fee_reserve_inr"],
                        now=clock,
                        evidence=evidence,
                        target=ticket["target_inr"],
                        research_meta={
                            "strategy_version": ticket["strategy_version"],
                            "patterns": list(ticket.get("patterns", []))[:10],
                            "run_id": report["run_id"],
                            "proposal_sha256": agent_workflow.proposal_digest(ticket),
                            "execution_kind": "paper_autopilot",
                        },
                    )
                _write(conn, state)
                conn.commit()
            entry = {
                "symbol": symbol,
                "side": "sell" if decision == "SELL_PAPER_PROPOSAL" else "buy",
                "qty": ticket["qty"],
                "price_inr": ticket["price_inr"],
                "reason": ticket.get("reason") or "agent-approved entry",
            }
            if decision == "BUY_PAPER_PROPOSAL":
                entry.update(stop_inr=ticket["stop_inr"], target_inr=ticket["target_inr"])
            outcome["recorded"].append(entry)
        except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            outcome["skipped"].append(
                {
                    "symbol": symbol,
                    "reason": str(exc)[:200] if isinstance(exc, ValueError) else "invalid ticket",
                }
            )
    coordinator.store.event(
        report["run_id"],
        {"kind": "paper_autopilot", "at": clock.isoformat(), **outcome},
    )
    return outcome

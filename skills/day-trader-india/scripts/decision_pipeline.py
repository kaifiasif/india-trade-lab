#!/usr/bin/env python3
"""Persistent daily paper-research coordinator. Produces calls, never exchange orders."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import threading
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import agent_runtime
import agent_workflow
import guardrails
import model_providers
import paper_analytics
import research_lab
from history import HistoryStore
from watchlist import build_watchlist

import engine
import india_research
import paper_book

OPTIONAL_CONFIG = {
    "review_workflow": "intraday",
    "quick_model": "",
    "deep_model": "",
    "model_routes": {},
    "model_timeout_seconds": 20,
    "max_output_tokens": 1200,
    "reasoning_effort": None,
    "screening_mode": "liquidity",
    "daily_bars": "daily-bars.csv",
    "benchmark_symbol": "NSE:NIFTY50",
    "benchmark_observations": "benchmark-quotes.json",
}

DEFAULT_CONFIG = {
    **OPTIONAL_CONFIG,
    "version": 1,
    "mode": "paper_research",
    "daily_profit_goal_inr": "80000.00",
    "model_provider": "disabled",
    "model": "",
    "max_candidates": 3,
    "max_model_calls_per_day": 60,
    "poll_seconds": 60,
    "fee_bps": "5",
    "fee_flat_inr": "10",
    "slippage_bps": "5",
    "target_r": "2",
    "min_turnover_inr": 20000000,
    "history_db": "history.sqlite",
    "universe": "universe.json",
    "book": "paper.sqlite",
    "sessions": "sessions.json",
    "bars": "current-bars.csv",
    "quotes": "quotes.json",
    "pretrade_evidence": "pretrade-evidence.json",
    "research_evidence": "research-evidence.json",
    "decision_db": "decisions.sqlite",
}


def read_json(path: Path, maximum: int = 2_000_000) -> Any:
    if path.stat().st_size > maximum:
        raise ValueError("Input JSON exceeds its size limit")
    return json.loads(path.read_text(encoding="utf-8"))


def read_book(path: Path) -> dict:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
        row = conn.execute("SELECT data FROM book WHERE id=1").fetchone()
    if row is None:
        raise ValueError("No paper book")
    book = json.loads(row[0])
    guardrails.verify_state(book)
    if book.get("mode") != "paper_manual":
        raise ValueError(
            "Forward research requires a separate forward paper book, never replay results"
        )
    guardrails.enforce_forward_policy(book)
    return book


def goal_report(book: dict | None, goal: str, now: dt.datetime) -> dict:
    """The income goal is reporting metadata and is never used in trade sizing."""
    target = paper_book.number(goal, True)
    actual = (
        Decimal(book.get("realized_by_day", {}).get(str(now.astimezone(engine.IST).date()), "0"))
        if book
        else Decimal(0)
    )
    return {
        "daily_target_inr": str(target),
        "realized_today_inr": str(actual),
        "shortfall_inr": str(max(Decimal(0), target - actual)),
        "guaranteed": False,
        "affects_sizing": False,
        "basis": "realized paper P&L after recorded charges",
    }


class DecisionStore:
    """Append audit events and calls with a durable process lease and input idempotency."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, "
                "started_at TEXT, completed_at TEXT, report TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, run_id TEXT, data TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS model_budget (day TEXT PRIMARY KEY, calls INTEGER)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS lease (id INTEGER PRIMARY KEY CHECK(id=1), "
                "owner TEXT, until REAL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS handoffs (run_id TEXT, role TEXT, data TEXT, PRIMARY KEY(run_id,role))"
            )

    def save_handoff(self, run_id: str, report: dict) -> None:
        with sqlite3.connect(self.path) as conn:
            existing = conn.execute(
                "SELECT data FROM handoffs WHERE run_id=? AND role=?",
                (run_id + ":" + report["symbol"], report["role"]),
            ).fetchone()
            if existing and json.loads(existing[0]) != report:
                raise ValueError("Checkpoint conflicts with the persisted handoff")
            conn.execute(
                "INSERT OR IGNORE INTO handoffs VALUES (?,?,?)",
                (run_id + ":" + report["symbol"], report["role"], json.dumps(report)),
            )

    def handoffs(self, run_id: str, symbol: str) -> list[dict]:
        with sqlite3.connect(self.path) as conn:
            return [
                json.loads(row[0])
                for row in conn.execute(
                    "SELECT data FROM handoffs WHERE run_id=? ORDER BY rowid",
                    (run_id + ":" + symbol,),
                )
            ]

    def acquire(self, owner: str) -> bool:
        now = dt.datetime.now(dt.timezone.utc).timestamp()
        with sqlite3.connect(self.path, isolation_level=None) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT owner,until FROM lease WHERE id=1").fetchone()
            if row and row[0] != owner and row[1] > now:
                conn.rollback()
                return False
            conn.execute("INSERT OR REPLACE INTO lease VALUES (1,?,?)", (owner, now + 600))
            conn.commit()
        return True

    def release(self, owner: str) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM lease WHERE owner=?", (owner,))

    def event(self, run_id: str, payload: dict) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO events (run_id,data) VALUES (?,?)", (run_id, json.dumps(payload))
            )

    def reserve_model_calls(self, day: str, count: int, ceiling: int) -> bool:
        with sqlite3.connect(self.path, isolation_level=None) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT calls FROM model_budget WHERE day=?", (day,)).fetchone()
            used = row[0] if row else 0
            if used + count > ceiling:
                conn.rollback()
                return False
            conn.execute("INSERT OR REPLACE INTO model_budget VALUES (?,?)", (day, used + count))
            conn.commit()
        return True

    def latest(self) -> dict | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT report FROM runs WHERE report IS NOT NULL ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row[0]) if row else None


class DailyCoordinator:
    """Build a shortlist, freeze tickets, validate accounting and run research reviewers."""

    def __init__(
        self, config_path: Path, reviewer: agent_runtime.ResearchReviewer | None = None, now=None
    ) -> None:
        self.config_path = config_path.resolve()
        self.config = {**OPTIONAL_CONFIG, **read_json(config_path)}
        cfg = self.config
        if cfg.get("version") != 1 or cfg.get("mode") != "paper_research":
            raise ValueError("Only version-1 paper_research configuration is supported")
        for key in DEFAULT_CONFIG:
            if key not in cfg:
                raise ValueError(f"Missing pipeline setting: {key}")
        if type(cfg["max_candidates"]) is not int or not 1 <= cfg["max_candidates"] <= 3:
            raise ValueError("Model review budget permits 1–3 candidates per run")
        if (
            type(cfg["max_model_calls_per_day"]) is not int
            or not 0 <= cfg["max_model_calls_per_day"] <= 120
        ):
            raise ValueError("Model call budget must be between zero and 120 per IST day")
        if type(cfg["poll_seconds"]) is not int or not 30 <= cfg["poll_seconds"] <= 3600:
            raise ValueError("Poll interval must be 30–3600 seconds")
        for key in ("daily_profit_goal_inr", "fee_bps", "fee_flat_inr", "slippage_bps", "target_r"):
            paper_book.number(cfg[key], key in ("daily_profit_goal_inr", "target_r"))
        if Decimal(cfg["target_r"]) < 1:
            raise ValueError("Target R must be at least one")
        self.now = now or (lambda: dt.datetime.now(engine.IST))
        self.store = DecisionStore(self.path("decision_db"))
        self.owner = uuid.uuid4().hex
        if cfg["review_workflow"] not in ("intraday", "intraday_debate") or cfg[
            "screening_mode"
        ] not in ("liquidity", "relative_strength"):
            raise ValueError("Unsupported research workflow or screening mode")
        if reviewer is not None:
            self.reviewer = reviewer
        else:
            self.reviewer = model_providers.configured_reviewer(cfg)

    def path(self, name: str) -> Path:
        value = self.config[name]
        if not isinstance(value, str) or not value or "://" in value:
            raise ValueError("Input paths must be local files")
        return (self.config_path.parent / value).resolve()

    @staticmethod
    def _file_digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(65536):
                digest.update(chunk)
        return digest.hexdigest()

    def _fingerprint(self, allow_entries: bool = True) -> str:
        files = {
            name: self._file_digest(self.path(name))
            for name in (
                "universe",
                "sessions",
                "bars",
                "quotes",
                "pretrade_evidence",
                "research_evidence",
                "daily_bars",
                "benchmark_observations",
            )
            if self.path(name).is_file()
        }
        # Include the book and history contents; SQLite timestamps alone are not a version.
        for name in ("book", "history_db"):
            if self.path(name).is_file():
                files[name] = self._file_digest(self.path(name))
        payload = {
            "inputs": files,
            "config": self.config,
            "date": str(self.now().astimezone(engine.IST).date()),
            "allow_entries": allow_entries,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def run_once(self, allow_entries: bool = True, resume: bool = False) -> dict:
        """A run is idempotent for unchanged evidence. No missing input is assumed clear."""
        if not self.store.acquire(self.owner):
            raise ValueError("Another coordinator owns the research lease")
        run_id = uuid.uuid4().hex
        started = self.now()
        try:
            if started.tzinfo is None:
                raise ValueError("Coordinator clock must be timezone-aware")
            started = started.astimezone(engine.IST)
            fingerprint = self._fingerprint(allow_entries)
            with sqlite3.connect(self.store.path) as conn:
                row = conn.execute(
                    "SELECT id,started_at,report FROM runs WHERE fingerprint=?", (fingerprint,)
                ).fetchone()
                if row:
                    if row[2] is None and not resume:
                        raise ValueError(
                            "An interrupted run exists for these inputs; refresh evidence"
                        )
                    if row[2] is None:
                        run_id, started = row[0], paper_book.timestamp(row[1])
                        if (self.now() - started).total_seconds() > 120:
                            raise ValueError("Interrupted research is stale; refresh observations")
                    else:
                        archived = json.loads(row[2])
                        archived["cached"] = True
                        archived["status"] = "ARCHIVED_RESULT"
                        for call in archived["calls"]:
                            call["original_decision"] = call["decision"]
                            call["decision"] = "DATA_BLOCK"
                            call["reasons"] = [
                                "Unchanged archived evidence; refresh before a current call"
                            ]
                        return archived
                else:
                    conn.execute(
                        "INSERT INTO runs VALUES (?,?,?,?,?)",
                        (run_id, fingerprint, started.isoformat(), None, None),
                    )
            self.review_cutoff = started
            self.screen_context = {}
            report = {
                "run_id": run_id,
                "as_of": started.isoformat(),
                "mode": "paper_research",
                "status": "DATA_BLOCK",
                "calls": [],
                "blockers": [],
                "cached": False,
                "real_orders_allowed": False,
                "paper_recorded": False,
                "provider": self.reviewer.name,
            }
            book = None
            try:
                book = read_book(self.path("book"))
                history = HistoryStore(self.path("history_db"))
                sessions = read_json(self.path("sessions"))
                quotes = read_json(self.path("quotes"))
                # Existing-position exit proposals do not depend on entry-only research inputs.
                for symbol in book["positions"]:
                    report["calls"].append(
                        self.evaluate(symbol, book, history, sessions, [], quotes, {}, {}, run_id)
                    )
                try:
                    if not allow_entries:
                        raise ValueError("Entry research paused by market schedule or halt file")
                    shortlist = build_watchlist(
                        history,
                        read_json(self.path("universe")),
                        started,
                        top=self.config["max_candidates"],
                        min_turnover_inr=self.config["min_turnover_inr"],
                    )
                    if self.config["screening_mode"] == "relative_strength":
                        shortlist = research_lab.screen(
                            research_lab.load_daily(self.path("daily_bars"), started),
                            read_json(self.path("universe")),
                            self.config["benchmark_symbol"],
                            started,
                            self.config["max_candidates"],
                            min_turnover=self.config["min_turnover_inr"],
                        )
                    report["shortlist"] = shortlist
                    self.screen_context = {item["symbol"]: item for item in shortlist["candidates"]}
                    bars = india_research.bars_from_csv(self.path("bars"))
                    pretrade = read_json(self.path("pretrade_evidence"))
                    evidence = read_json(self.path("research_evidence"))
                    for candidate in shortlist["candidates"]:
                        if candidate["symbol"] not in book["positions"]:
                            report["calls"].append(
                                self.evaluate(
                                    candidate["symbol"],
                                    book,
                                    history,
                                    sessions,
                                    bars,
                                    quotes,
                                    pretrade,
                                    evidence,
                                    run_id,
                                )
                            )
                except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
                    report["blockers"].append(
                        "Entry research inputs are incomplete; existing exit reviews retained"
                    )
                # One selected entry per snapshot: candidates do not reserve cash independently.
                selected = False
                for call in report["calls"]:
                    if call["decision"] == "BUY_PAPER_PROPOSAL":
                        if selected:
                            call.update(
                                decision="WAIT_ALLOCATION",
                                reasons=[
                                    "Another ranked entry was selected for this portfolio snapshot"
                                ],
                            )
                        else:
                            selected = True
                            call["selected"] = True
                decisions = {call["decision"] for call in report["calls"]}
                report["status"] = (
                    "RESEARCH_PROPOSALS"
                    if decisions & {"BUY_PAPER_PROPOSAL", "SELL_PAPER_PROPOSAL"}
                    else "DATA_BLOCK"
                    if "DATA_BLOCK" in decisions or report["blockers"]
                    else "NO_TRADE"
                )
                if not report["calls"]:
                    report["blockers"].append("No instruments passed the research shortlist")
            except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, InvalidOperation):
                report["blockers"].append(
                    "Required forward book, sourced universe, history, current bars, "
                    "quotes or evidence is missing or invalid"
                )
            report["goal"] = goal_report(book, self.config["daily_profit_goal_inr"], started)
            report["workflow"] = self.config["review_workflow"]
            report["required_roles"] = list(
                agent_workflow.WORKFLOWS[self.config["review_workflow"]]
            )
            if book:
                try:
                    benchmark = (
                        read_json(self.path("benchmark_observations"))
                        if self.path("benchmark_observations").is_file()
                        else None
                    )
                    report["performance"] = paper_analytics.performance(
                        book,
                        read_json(self.path("quotes")),
                        self.now(),
                        benchmark,
                        fee_bps=self.config["fee_bps"],
                        fee_flat=self.config["fee_flat_inr"],
                        slippage_bps=self.config["slippage_bps"],
                    )
                except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
                    report["performance"] = {"status": "DATA_REQUIRED"}
            report["completed_at"] = self.now().isoformat()
            self.store.event(
                run_id,
                {
                    "kind": "final_calls",
                    "at": report["completed_at"],
                    "status": report["status"],
                    "blockers": report["blockers"],
                },
            )
            with sqlite3.connect(self.store.path) as conn:
                conn.execute(
                    "UPDATE runs SET completed_at=?,report=? WHERE id=?",
                    (report["completed_at"], json.dumps(report), run_id),
                )
            return report
        finally:
            self.store.release(self.owner)

    def evaluate(
        self,
        symbol: str,
        book: dict,
        history: HistoryStore,
        manifest: dict,
        bars: list,
        quotes: dict,
        pretrade: dict,
        evidence: dict,
        run_id: str,
    ) -> dict:
        now = self.now().astimezone(engine.IST)
        result = {
            "symbol": symbol,
            "decision": "DATA_BLOCK",
            "reasons": [],
            "proposal": None,
            "paper_recorded": False,
            "real_orders_allowed": False,
        }
        try:
            q = quotes[symbol]
            if q.get("timestamp_kind", "exchange") != "exchange":
                raise ValueError(
                    "Original bid/ask timestamp is unavailable; last-trade time cannot replace it"
                )
            observed = paper_book.timestamp(q["as_of"])
            quote = engine.Quote(
                symbol,
                observed,
                paper_book.number(q["bid_inr"], True),
                paper_book.number(q["ask_inr"], True),
                q["source"],
            )
            settings = engine.EngineConfig(
                (symbol,),
                Decimal(self.config["fee_bps"]),
                Decimal(self.config["fee_flat_inr"]),
                Decimal(self.config["slippage_bps"]),
            )
            if not -5 <= (now - observed).total_seconds() <= settings.max_quote_age_seconds:
                raise ValueError("Current quote is stale or future dated")
            if quote.bid > quote.ask or quote.spread_bps > settings.max_spread_bps:
                raise ValueError("Current spread is invalid or too wide")
            if "SYNTHETIC" in quote.source.upper():
                raise ValueError("Synthetic quotes cannot support forward calls")
            session = india_research.session(manifest, now.date())
            held = book["positions"].get(symbol)
            if held:
                reason = (
                    "stop"
                    if quote.bid <= Decimal(held["stop_inr"])
                    else "target"
                    if held.get("target_inr") and quote.bid >= Decimal(held["target_inr"])
                    else "square_off"
                    if now >= session["flat_by"]
                    else None
                )
                if reason:
                    proposal = {
                        "symbol": symbol,
                        "side": "sell",
                        "qty": held["qty"],
                        "price_inr": str(quote.bid),
                        "quote_as_of": observed.isoformat(),
                        "quote_source": quote.source,
                        "reason": reason,
                        "fee_inr": str(settings.fee(quote.bid, held["qty"])),
                        "book_state_sha256": book["state_sha256"],
                    }
                    paper_book.fill(
                        book,
                        "sell",
                        f"research:{run_id}:{symbol}:X",
                        symbol,
                        quote.bid,
                        observed.isoformat(),
                        quote.source,
                        settings.fee(quote.bid, held["qty"]),
                        settings.slippage_bps,
                        now=now,
                    )
                    result.update(
                        decision="SELL_PAPER_PROPOSAL",
                        proposal=proposal,
                        reasons=["Protective paper exit proposed: " + reason],
                    )
                else:
                    result.update(
                        decision="HOLD_PAPER",
                        reasons=[
                            "No stop or time exit observed; this coordinator does not execute exits"
                        ],
                    )
                return result
            coverage = history.coverage(symbol, now)
            if not coverage["history_ready"]:
                raise ValueError("Insufficient historical coverage")
            rows, session = india_research.checked_session(
                [row for row in bars if row["symbol"] == symbol], manifest, now.date(), now
            )
            signal = india_research.first_signal(rows, session)
            if signal is None or signal["confirmed_at"] != (rows[-1]["t"] + engine.BAR).isoformat():
                result.update(
                    decision="WAIT", reasons=["No new completed-bar breakout on the latest candle"]
                )
                return result
            strategy = engine.OpeningRangeBreakout(
                Decimal(book["limits"]["risk"]),
                Decimal(book["limits"]["position_limit"]),
                Decimal(self.config["target_r"]),
            )
            stop = Decimal(str(signal["range_low"]))
            qty = strategy.size(quote.ask, stop, settings)
            if qty <= 0:
                raise ValueError("No whole-share quantity fits planned risk and cost limits")
            assumed = quote.ask * (1 + settings.slippage_bps / engine.BPS)
            target = (assumed + (assumed - stop) * strategy.target_r).quantize(engine.CENT)
            proposal = {
                "symbol": symbol,
                "side": "buy",
                "event_id": f"research:{run_id}:{symbol}",
                "qty": qty,
                "price_inr": str(quote.ask),
                "stop_inr": str(stop),
                "target_inr": str(target),
                "quote_as_of": observed.isoformat(),
                "quote_source": quote.source,
                "fee_inr": str(settings.fee(quote.ask, qty)),
                "exit_fee_reserve_inr": str(settings.fee(stop, qty)),
                "slippage_bps": str(settings.slippage_bps),
                "book_state_sha256": book["state_sha256"],
                "pretrade_sha256": agent_workflow.proposal_digest(pretrade[symbol]),
                "quote_bid_inr": str(quote.bid),
                "strategy_version": "intraday-orb-v1",
                "patterns": ["OPENING_RANGE_BREAKOUT"]
                + self.screen_context.get(symbol, {}).get("features", {}).get("patterns", []),
            }
            # Validate the exact proposed transition on a pure copy; never persist a fill here.
            paper_book.fill(
                book,
                "buy",
                proposal["event_id"],
                symbol,
                quote.ask,
                observed.isoformat(),
                quote.source,
                settings.fee(quote.ask, qty),
                settings.slippage_bps,
                qty,
                stop,
                settings.fee(stop, qty),
                now=now,
                evidence=pretrade[symbol],
                target=target,
            )
            supplied = evidence[symbol]
            if not isinstance(supplied, list) or not supplied or len(supplied) > 50:
                raise ValueError("Dated research evidence is required")
            ids = set()
            for item in supplied:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("id"), str)
                    or item["id"] in ids
                    or not item.get("source")
                    or not item.get("facts")
                ):
                    raise ValueError(
                        "Research evidence must have unique IDs, sources and factual extracts"
                    )
                ids.add(item["id"])
                if guardrails.evidence_time(item["observed_at"]) > now:
                    raise ValueError("Research evidence is from the future")
                if (
                    item.get("published_at")
                    and guardrails.evidence_time(item["published_at"]) > now
                ):
                    raise ValueError("Research publication is from the future")
            context = {
                "run_id": run_id,
                "symbol": symbol,
                "as_of": self.review_cutoff.isoformat(),
                "workflow": self.config["review_workflow"],
                "proposal": proposal,
                "proposal_sha256": agent_workflow.proposal_digest(proposal),
                "history": coverage,
                "daily_screen": self.screen_context.get(symbol),
                "evidence": supplied,
                "resolved_paper_outcomes": paper_analytics.closed_outcomes(book, now)[-20:],
                "book": {
                    key: book[key]
                    for key in (
                        "cash",
                        "limits",
                        "controls",
                        "positions",
                        "loss_streak",
                        "closed_trade_drawdown_inr",
                    )
                },
            }
            if getattr(self.reviewer, "uses_network", False):
                if not self.store.reserve_model_calls(
                    str(now.date()),
                    len(agent_workflow.WORKFLOWS[self.config["review_workflow"]]),
                    self.config["max_model_calls_per_day"],
                ):
                    raise ValueError(
                        "Daily model-call budget exhausted; no automatic retry or limit increase"
                    )
            reviewed = agent_runtime.run_reviews(
                context,
                self.reviewer,
                emit=lambda event: self.store.event(run_id, event),
                now=self.now,
                resume_reports=self.store.handoffs(run_id, symbol),
                checkpoint=lambda handoff: self.store.save_handoff(run_id, handoff),
            )
            result.update(proposal=proposal, agent_review=reviewed)
            if reviewed["review"]["status"] != "REVIEW_COMPLETE":
                result["reasons"] = reviewed["review"]["blockers"]
                return result
            if read_book(self.path("book"))["state_sha256"] != book["state_sha256"]:
                raise ValueError("Book changed during review; the ticket must be rebuilt")
            if (self.now() - observed).total_seconds() > 120:
                raise ValueError("Quote expired during review; refresh the full decision")
            result.update(
                decision="BUY_PAPER_PROPOSAL",
                reasons=["Frozen ticket passed accounting and fresh research review"],
            )
            return result
        except (ValueError, TypeError, KeyError, InvalidOperation, OSError, sqlite3.Error) as exc:
            # Domain rejections are our own messages; supplied/provider text is never used here.
            result["reasons"] = [
                str(exc) if isinstance(exc, ValueError) else "Required evidence is unavailable"
            ]
            return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
    for name in ("run", "watch"):
        child = sub.add_parser(name)
        child.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
        child.add_argument(
            "--resume",
            action="store_true",
            help="Resume only unchanged, still-fresh interrupted reviews",
        )
    args = parser.parse_args()
    try:
        if args.command == "init":
            args.config.parent.mkdir(parents=True, exist_ok=True)
            with args.config.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(DEFAULT_CONFIG, indent=2) + "\n")
            print(
                "Created private paper-research configuration; populate sourced inputs before running"
            )
            return 0
        coordinator = DailyCoordinator(args.config)
        while True:
            print(json.dumps(coordinator.run_once(resume=args.resume), indent=2), flush=True)
            if args.command != "watch":
                break
            threading.Event().wait(coordinator.config["poll_seconds"])
        return 0
    except KeyboardInterrupt:
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, InvalidOperation):
        print(
            "REFUSED: coordinator configuration or inputs are invalid. No orders or fills were sent."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

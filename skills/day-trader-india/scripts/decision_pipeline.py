#!/usr/bin/env python3
"""Persistent daily paper-research coordinator. Produces calls, never exchange orders."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import agent_runtime
import agent_workflow
import debate
import guardrails
import model_providers
import paper_analytics
import report_html
import research_lab
import technical
from history import HistoryStore
from memory import DecisionMemory
from watchlist import build_watchlist

import engine
import india_research
import model_router
import paper_book
import strategies

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
    # Bull/bear and risk debates with research- and portfolio-manager ratings.
    "debate": {"enabled": True, "research_rounds": 1, "risk_rounds": 1},
    # Rated calls are settled on later stored prices and become point-in-time lessons.
    "memory": {"enabled": True, "horizon_sessions": 1, "reflect": False},
    "memory_db": "memory.sqlite",
    "reports_dir": "reports",
    "local_base_url": "http://127.0.0.1:11434/v1",
    "local_timeout_seconds": 60,
    # Reference data (sector, market-cap tier, F&O lot size) and the pre-market report.
    "reference_db": "reference.sqlite",
    "min_scored_headlines": 3,
    # Email over SMTP; the password lives in the owner-only secret store.
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "email_from": "",
    "email_to": "",
    # Pre-market selection: hard filters first, then six specialist agents and a judge.
    "selection": {
        "agents": True,
        "pool": 10,
        "min_specialists": 4,
        "finalists": 3,
        "min_market_cap_tier": "large",
        "max_reference_age_days": 7,
    },
    # Market-wide RSS feeds matched to stocks by name; ET Markets by default.
    "market_feeds": ["https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"],
    # Paper autopilot: record agent-approved entries and protective exits in the virtual
    # book each tick. Off by default; entries need a pre-market judge pick unless relaxed.
    "autopilot": {"enabled": False, "require_premarket_pick": True},
    # Strategy library. Entries use only strategies the tournament proved after doubled
    # costs (strategy-scorecard.json); with none proven the desk sits out. Managed exits
    # move the stop to breakeven, trail it, and time out trades that go nowhere.
    "strategy": {
        "require_proven": True,
        "enabled": list(strategies.STRATEGIES),
        "max_scorecard_age_days": 7,
        "managed_exits": True,
        "filters": True,
    },
    # Learning from mistakes: each evening every agent's calls are graded against what
    # the stock then did and against paper trades. Lessons and stock notes go back into
    # the next prompts; repeated losers cool down. All of it can only narrow choices.
    "learning": {
        "enabled": True,
        "lessons_in_prompts": True,
        "stock_notes": True,
        "cooldown": True,
        "weight_specialists": True,
        "min_graded": 20,
    },
    # Market scan: the desk finds its own stocks among all F&O names, ranked on signals
    # that lead the open (positioning, pre-open strength, upcoming events), and checks
    # volume and VWAP after the first fifteen minutes before any entry.
    "scan": {
        "enabled": False,
        "shortlist": 25,
        "max_gap_up_pct": 3.0,
        "max_gap_down_pct": 1.5,
        "event_window_days": 5,
        "min_rvol": 1.5,
        "require_confirmation": True,
    },
    # Smart routing: simple jobs to free tiers, hard ones to the strongest tier allowed,
    # with quotas you enter, a same-day cache and escalation on bad answers.
    "routing": {
        "enabled": False,
        "tiers": [],
        "simple": [],
        "complex": [],
        "escalate": True,
        "cache": True,
        "store_prompts": True,
        "max_escalations_per_day": 10,
    },
}
NESTED_DEFAULTS = (
    "debate", "memory", "selection", "autopilot", "strategy", "learning", "routing", "scan",
)  # fmt: skip

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
        for key in NESTED_DEFAULTS:
            if not isinstance(cfg[key], dict) or set(cfg[key]) - set(OPTIONAL_CONFIG[key]):
                raise ValueError(f"Unknown {key} setting")
            cfg[key] = {**OPTIONAL_CONFIG[key], **cfg[key]}
        if (
            type(cfg["debate"]["enabled"]) is not bool
            or any(
                type(cfg["debate"][key]) is not int or not 1 <= cfg["debate"][key] <= 3
                for key in ("research_rounds", "risk_rounds")
            )
            or type(cfg["memory"]["enabled"]) is not bool
            or type(cfg["memory"]["reflect"]) is not bool
            or type(cfg["memory"]["horizon_sessions"]) is not int
            or not 1 <= cfg["memory"]["horizon_sessions"] <= 20
        ):
            raise ValueError("Debate rounds must be 1-3 and the memory window 1-20 sessions")
        chooser = cfg["selection"]
        if (
            type(chooser["agents"]) is not bool
            or type(chooser["pool"]) is not int
            or not 1 <= chooser["pool"] <= 15
            or type(chooser["min_specialists"]) is not int
            or not 1 <= chooser["min_specialists"] <= 6
            or type(chooser["finalists"]) is not int
            or not 1 <= chooser["finalists"] <= 5
            or chooser["min_market_cap_tier"] not in ("large", "mid", "small")
            or type(chooser["max_reference_age_days"]) is not int
            or not 1 <= chooser["max_reference_age_days"] <= 31
        ):
            raise ValueError(
                "Selection needs a pool of 1-15, a quorum of 1-6 specialists, a market-cap "
                "tier of large/mid/small and a reference age of 1-31 days"
            )
        plan = cfg["strategy"]
        if (
            type(plan["require_proven"]) is not bool
            or type(plan["managed_exits"]) is not bool
            or type(plan["filters"]) is not bool
            or not isinstance(plan["enabled"], list)
            or not plan["enabled"]
            or set(plan["enabled"]) - set(strategies.STRATEGIES)
            or type(plan["max_scorecard_age_days"]) is not int
            or not 1 <= plan["max_scorecard_age_days"] <= 31
        ):
            raise ValueError(
                "strategy.enabled must list known strategies ("
                + ", ".join(strategies.STRATEGIES)
                + ") and the scorecard age must be 1-31 days"
            )
        if any(type(value) is not bool for value in cfg["autopilot"].values()):
            raise ValueError("Autopilot settings must be true or false")
        scan = cfg["scan"]
        if (
            type(scan["enabled"]) is not bool
            or type(scan["require_confirmation"]) is not bool
            or type(scan["shortlist"]) is not int
            or not 10 <= scan["shortlist"] <= 50
            or type(scan["event_window_days"]) is not int
            or not 1 <= scan["event_window_days"] <= 10
            or any(
                not isinstance(scan[key], (int, float)) or not 0 < scan[key] <= 10
                for key in ("max_gap_up_pct", "max_gap_down_pct", "min_rvol")
            )
        ):
            raise ValueError(
                "scan needs true/false switches, a shortlist of 10-50, an event window of "
                "1-10 days and gap/volume limits between 0 and 10"
            )
        learn = cfg["learning"]
        if any(type(learn[key]) is not bool for key in learn if key != "min_graded") or (
            type(learn["min_graded"]) is not int or not 5 <= learn["min_graded"] <= 500
        ):
            raise ValueError("learning switches must be true/false and min_graded 5-500")
        model_router.validate_routing(
            cfg["routing"], model_providers.PROVIDERS, model_providers.MODEL_PATTERNS
        )
        if cfg["smtp_host"] and not re.fullmatch(
            r"(?=.{1,253}$)([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}", str(cfg["smtp_host"])
        ):
            raise ValueError("smtp_host must be a mail server name such as smtp.gmail.com")
        if cfg["smtp_port"] not in (25, 465, 587, 2525):
            raise ValueError("smtp_port must be 25, 465, 587 or 2525")
        if not isinstance(cfg["market_feeds"], list) or len(cfg["market_feeds"]) > 5:
            raise ValueError("market_feeds must be a list of at most five feed URLs")
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
        self.memory = DecisionMemory(self.path("memory_db")) if cfg["memory"]["enabled"] else None
        self.owner = uuid.uuid4().hex
        if cfg["review_workflow"] not in ("intraday", "intraday_debate") or cfg[
            "screening_mode"
        ] not in ("liquidity", "relative_strength"):
            raise ValueError("Unsupported research workflow or screening mode")
        if reviewer is not None:
            self.reviewer = reviewer
        else:
            self.reviewer = model_providers.configured_reviewer(cfg, self.config_path.parent)

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
            if self.memory:
                report["memory"] = self.settle_memory(started)
            try:
                book = read_book(self.path("book"))
                history = HistoryStore(self.path("history_db"))
                sessions = read_json(self.path("sessions"))
                quotes = read_json(self.path("quotes"))
                # Existing-position exit proposals do not depend on entry-only research inputs.
                # Current bars, when readable, let managed exits trail the stop.
                try:
                    exit_bars = india_research.bars_from_csv(self.path("bars"))
                except (ValueError, OSError, KeyError):
                    exit_bars = []
                for symbol in book["positions"]:
                    report["calls"].append(
                        self.evaluate(
                            symbol, book, history, sessions, exit_bars, quotes, {}, {}, run_id
                        )
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
                    symbols = [
                        candidate["symbol"]
                        for candidate in shortlist["candidates"]
                        if candidate["symbol"] not in book["positions"]
                    ]
                    # Every review is bound to this run's 120-second observation window.
                    # Reviewing candidates one after another would expire all but the first,
                    # so review them concurrently and keep the shortlist's ranking order.
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=max(1, len(symbols))
                    ) as pool:
                        futures = [
                            pool.submit(
                                self.evaluate,
                                symbol,
                                book,
                                history,
                                sessions,
                                bars,
                                quotes,
                                pretrade,
                                evidence,
                                run_id,
                            )
                            for symbol in symbols
                        ]
                        report["calls"].extend(future.result() for future in futures)
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
            try:
                page = self.path("reports_dir") / f"{run_id}.html"
                report_html.write(report, page)
                report["report_html"] = str(page)
            except (OSError, ValueError, KeyError, TypeError):
                report["report_html"] = None
            with sqlite3.connect(self.store.path) as conn:
                conn.execute(
                    "UPDATE runs SET completed_at=?,report=? WHERE id=?",
                    (report["completed_at"], json.dumps(report), run_id),
                )
            return report
        finally:
            self.store.release(self.owner)

    def playbook(self, symbol: str, now: dt.datetime) -> dict:
        """Strategies this symbol may trade today: proven ones, narrowed by the judge."""
        return strategies.allowed_for(
            self.config_path.parent,
            self.config["strategy"],
            symbol,
            str(now.astimezone(engine.IST).date()),
            self.path("reports_dir"),
        )

    def managed_exit(
        self, symbol: str, held: dict, book: dict, bars: list, now: dt.datetime
    ) -> dict:
        """Breakeven, trailing and time stops from the bars completed since entry."""
        initial = float(held["stop_inr"])
        if not self.config["strategy"]["managed_exits"]:
            return {"stop": initial, "rule": "initial", "time_stop": False}
        entry_event = next(
            (event for event in book["events"] if event["id"] == held["entry_event_id"]), None
        )
        if entry_event is None:
            return {"stop": initial, "rule": "initial", "time_stop": False}
        entered = paper_book.timestamp(entry_event["as_of"])
        since = [
            row
            for row in bars
            if row["symbol"] == symbol and row["t"] >= entered and row["t"] + engine.BAR <= now
        ]
        per_share = (float(held["entry_fee_inr"]) + float(held["exit_fee_reserve_inr"])) / held[
            "qty"
        ]
        return strategies.managed_stop(float(held["entry_inr"]), initial, per_share, since)

    def benchmark(self) -> dict | None:
        path = self.path("benchmark_observations")
        return read_json(path) if path.is_file() else None

    def settle_memory(self, as_of: dt.datetime) -> dict:
        """Settle closed holding windows; a failure is reported and never blocks the run."""
        reflect = None
        if self.config["memory"]["reflect"] and getattr(self.reviewer, "uses_network", False):

            def reflect(outcome: dict) -> str:
                if not self.store.reserve_model_calls(
                    str(as_of.date()), 1, self.config["max_model_calls_per_day"]
                ):
                    raise ValueError("Model budget exhausted")
                return debate.reflect(self.reviewer, outcome)

        try:
            result = self.memory.settle(
                HistoryStore(self.path("history_db")), as_of, self.benchmark(), reflect
            )
            result["scorecard"] = self.memory.scorecard()
            return result
        except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
            return {"status": "DATA_REQUIRED", "reason": "Memory settlement unavailable"}

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
                managed = self.managed_exit(symbol, held, book, bars, now)
                stop_level = max(Decimal(held["stop_inr"]), Decimal(str(managed["stop"])))
                reason = (
                    ("stop" if managed["rule"] == "initial" else managed["rule"] + "_stop")
                    if quote.bid <= stop_level
                    else "target"
                    if held.get("target_inr") and quote.bid >= Decimal(held["target_inr"])
                    else "square_off"
                    if now >= session["flat_by"]
                    else "time_stop"
                    if managed["time_stop"]
                    else None
                )
                result["managed_exit"] = {
                    key: (str(value) if isinstance(value, Decimal) else value)
                    for key, value in managed.items()
                }
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
                            f"Holding: protective stop INR {stop_level} ({managed['rule']}), "
                            "no target, square-off or time stop reached"
                        ],
                    )
                return result
            coverage = history.coverage(symbol, now)
            if not coverage["history_ready"]:
                raise ValueError("Insufficient historical coverage")
            rows, session = india_research.checked_session(
                [row for row in bars if row["symbol"] == symbol], manifest, now.date(), now
            )
            playbook = self.playbook(symbol, now)
            if not playbook["allowed"]:
                result.update(decision="WAIT", reasons=["No proven strategy: " + playbook["basis"]])
                return result
            try:
                snapshot = technical.snapshot(technical.daily_bars(history, symbol, now))
            except (ValueError, KeyError, TypeError, sqlite3.Error):
                snapshot = None
            signal = strategies.latest_signal(
                rows,
                session,
                playbook["allowed"],
                snapshot if self.config["strategy"]["filters"] else None,
            )
            if signal is None or "blocked" in signal:
                result.update(
                    decision="WAIT",
                    reasons=(signal or {}).get("blocked")
                    or ["No allowed setup on the latest completed bar"],
                    playbook=playbook,
                )
                return result
            strategy = engine.OpeningRangeBreakout(
                Decimal(book["limits"]["risk"]),
                Decimal(book["limits"]["position_limit"]),
                Decimal(self.config["target_r"]),
            )
            stop = Decimal(str(signal["stop"]))
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
                "strategy_version": signal["version"],
                "setup": signal["reason"],
                "patterns": (
                    [signal["version"].upper().replace("-", "_")]
                    + self.screen_context.get(symbol, {}).get("features", {}).get("patterns", [])
                )[:10],
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
            if snapshot is not None and "technical-snapshot" not in ids:
                supplied = [*supplied, technical.evidence_item(symbol, snapshot)]
            context = {
                "technical": snapshot,
                "past_lessons": self.memory.lessons(symbol, now) if self.memory else [],
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
            settings_debate = self.config["debate"]
            planned = len(agent_workflow.WORKFLOWS[self.config["review_workflow"]])
            if settings_debate["enabled"]:
                planned += debate.planned_calls(
                    settings_debate["research_rounds"], settings_debate["risk_rounds"]
                )
            if getattr(self.reviewer, "uses_network", False):
                if not self.store.reserve_model_calls(
                    str(now.date()),
                    planned,
                    self.config["max_model_calls_per_day"],
                ):
                    raise ValueError(
                        "Daily model-call budget exhausted; no automatic retry or limit increase"
                    )
            # Evidence reviews and the debate share the 120-second window, so run together.
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                review_job = pool.submit(
                    agent_runtime.run_reviews,
                    context,
                    self.reviewer,
                    emit=lambda event: self.store.event(run_id, event),
                    now=self.now,
                    resume_reports=self.store.handoffs(run_id, symbol),
                    checkpoint=lambda handoff: self.store.save_handoff(run_id, handoff),
                )
                debate_job = (
                    pool.submit(
                        debate.run_debate,
                        context,
                        self.reviewer,
                        settings_debate["research_rounds"],
                        settings_debate["risk_rounds"],
                        emit=lambda event: self.store.event(run_id, event),
                        now=self.now,
                    )
                    if settings_debate["enabled"]
                    else None
                )
                reviewed = review_job.result()
                debated = debate_job.result() if debate_job else None
            result.update(proposal=proposal, agent_review=reviewed, debate=debated)
            if debated and debated["rating"] != debate.REVIEW:
                result.update(rating=debated["rating"], conviction=debated["conviction"])
                if self.memory:
                    # Every rated call is scored later, including ones a veto stopped.
                    self.memory.record(
                        run_id,
                        symbol,
                        observed,
                        debated["rating"],
                        float(quote.ask),
                        self.config["memory"]["horizon_sessions"],
                        debated["conviction"],
                        context["proposal_sha256"],
                        (debated.get("decision") or {}).get("thesis", ""),
                    )
            if reviewed["review"]["status"] != "REVIEW_COMPLETE":
                result["reasons"] = reviewed["review"]["blockers"]
                return result
            if debated:
                outcome, reasons = debate.verdict(debated)
                if outcome != "PROCEED":
                    result.update(decision=outcome, reasons=reasons)
                    return result
            if read_book(self.path("book"))["state_sha256"] != book["state_sha256"]:
                raise ValueError("Book changed during review; the ticket must be rebuilt")
            if (self.now() - observed).total_seconds() > 120:
                raise ValueError("Quote expired during review; refresh the full decision")
            reasons = ["Frozen ticket passed accounting and fresh research review"]
            if debated:
                reasons.append(
                    f"Portfolio manager rated {debated['rating']} with "
                    f"{debated['conviction']} conviction"
                )
            result.update(decision="BUY_PAPER_PROPOSAL", reasons=reasons)
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
            # New projects let the desk scan for its own stocks every morning.
            config = {**DEFAULT_CONFIG, "scan": {**DEFAULT_CONFIG["scan"], "enabled": True}}
            with args.config.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(config, indent=2) + "\n")
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

#!/usr/bin/env python3
"""Local paper-engine dashboard and event API. No broker orders or external requests."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import sqlite3
import threading
import uuid
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from history import HistoryStore
from watchlist import build_watchlist

import engine
import india_research
import paper_book
import setup_api

ASSETS = Path(__file__).resolve().parents[1] / "assets"
WEB = ASSETS / "observatory"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".json": "application/json",
    ".ico": "image/x-icon",
}
STAGES = (
    ("data", "Data sentinel", "Validated observations", ("quote", "quote_rejected")),
    (
        "strategy",
        "Setup scout",
        "Completed-bar strategy",
        ("decision", "strategy_wait", "strategy_blocked"),
    ),
    ("risk", "Risk guardian", "Deterministic veto", ("risk_passed", "entry_blocked")),
    ("execution", "Paper executor", "Assumed virtual fills", ("order",)),
    ("journal", "Journal keeper", "Persisted accounting", ("order",)),
)


def research_state(directory: Path) -> dict:
    """Read worker records without starting models, collectors or changing journal state."""
    result: dict[str, Any] = {"report": None, "events": [], "crypto": [], "service": None}
    now = dt.datetime.now(dt.timezone.utc)
    for filename, kind in (
        ("decisions.sqlite", "report"),
        ("crypto.sqlite", "crypto"),
        ("service.sqlite", "service"),
    ):
        path = directory / filename
        if not path.is_file():
            continue
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as conn:
                conn.execute("BEGIN")
                if kind == "report":
                    row = conn.execute(
                        "SELECT id,report FROM runs ORDER BY started_at DESC LIMIT 1"
                    ).fetchone()
                    if row:
                        result["report"] = (
                            json.loads(row[1])
                            if row[1]
                            else {"run_id": row[0], "status": "IN_PROGRESS", "calls": []}
                        )
                        result["events"] = [
                            json.loads(value[0])
                            for value in conn.execute(
                                "SELECT data FROM events WHERE run_id=? ORDER BY seq", (row[0],)
                            )
                        ]
                        report = result["report"]
                        report["archived"] = (
                            not report.get("as_of")
                            or (now - paper_book.timestamp(report["as_of"])).total_seconds() > 120
                        )
                        report["display_notice"] = (
                            "Recorded research; every proposal requires fresh validation before a manual paper fill"
                        )
                elif kind == "crypto":
                    for row in conn.execute(
                        "SELECT data FROM snapshots WHERE id IN "
                        "(SELECT MAX(id) FROM snapshots GROUP BY symbol) ORDER BY symbol"
                    ):
                        snapshot = json.loads(row[0])
                        snapshot.pop("candles", None)
                        snapshot["stale"] = (
                            now - paper_book.timestamp(snapshot["received_at"])
                        ).total_seconds() > 1800
                        result["crypto"].append(snapshot)
                else:
                    row = conn.execute("SELECT data FROM state WHERE id=1").fetchone()
                    if row:
                        result["service"] = json.loads(row[0])
                        result["service"]["stale"] = (
                            now - paper_book.timestamp(result["service"]["as_of"])
                        ).total_seconds() > 180
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            result[kind] = [] if kind == "crypto" else None
    return result


def trade_desk_state(directory: Path) -> dict[str, Any] | None:
    """The desk agent's cards for today's picks and the latest alerts, read only."""
    folder = directory / "desk"
    try:
        summary = json.loads((folder / "today.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cards = []
    day_folder = folder / str(summary.get("date", ""))
    for item in summary.get("cards") or []:
        symbol = str(item.get("symbol", ""))
        path = day_folder / f"{symbol.split(':')[-1]}.json"
        try:
            if path.stat().st_size > 2_000_000:
                continue
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entry, plan = card.get("entry") or {}, card.get("plan") or {}
        odds, check = card.get("odds") or {}, card.get("check") or {}
        mc = odds.get("mc") or {}
        cards.append(
            {
                "symbol": symbol,
                "entry": {key: entry.get(key) for key in ("status", "message", "time", "price")},
                "plan": {
                    key: plan.get(key)
                    for key in ("entry", "stop", "target", "risk_per_share", "reward_risk")
                }
                if plan
                else None,
                "plan_refused": card.get("plan_refused"),
                "odds": {
                    **{
                        key: mc.get(key)
                        for key in (
                            "target_first_pct", "stop_first_pct", "neither_pct", "green_pct",
                            "average_r", "replays", "sessions", "seed", "fan",
                        )
                    },
                    "after_costs": odds.get("average_r_after_costs"),
                    "code": (odds.get("verdict") or {}).get("code"),
                    "verdict": ((odds.get("verdict") or {}).get("lines") or [""])[0],
                    "history": odds.get("history"),
                }
                if mc
                else None,
                "odds_unavailable": card.get("odds_unavailable"),
                "check": {
                    key: check.get(key)
                    for key in (
                        "verdict", "qty", "cost_inr", "planned_loss_inr", "decided_by", "blocks",
                    )
                }
                if check
                else None,
                "check_unavailable": card.get("check_unavailable"),
            }
        )  # fmt: skip
    alerts = []
    try:
        lines = (folder / "alerts-log.jsonl").read_text(encoding="utf-8").splitlines()[-8:]
        for line in reversed(lines):
            item = json.loads(line)
            alerts.append({key: item.get(key) for key in ("at", "type", "message")})
    except (OSError, ValueError):
        alerts = []
    return {
        "date": summary.get("date"),
        "checked_at": summary.get("checked_at"),
        "status": summary.get("status"),
        "cards": cards,
        "alerts": alerts,
    }


def desk_state(directory: Path) -> dict[str, Any]:
    """Today's desk: the latest pre-market selection and the strategy scorecard, read only."""
    result: dict[str, Any] = {"report": None, "scorecard": None}
    reports = directory / "reports"
    try:
        config = json.loads((directory / "pipeline.json").read_text(encoding="utf-8"))
        folder = config.get("reports_dir")
        if isinstance(folder, str) and folder and "://" not in folder:
            reports = (directory / folder).resolve()
    except (OSError, ValueError, AttributeError):
        pass
    try:
        latest = max(reports.glob("premarket-*.json"), key=lambda item: item.name, default=None)
        if latest is not None and latest.stat().st_size <= 5_000_000:
            report = json.loads(latest.read_text(encoding="utf-8"))
            selection = report.get("selection") or {}
            judge = selection.get("judge") or {}
            finalists = selection.get("finalists") or {}
            result["report"] = {
                "session_date": report.get("session_date"),
                "as_of": report.get("as_of"),
                "mode": selection.get("mode"),
                "reason": selection.get("reason"),
                "summary": judge.get("summary"),
                "watching": report.get("watching") or [],
                "picks": [
                    {
                        key: pick.get(key)
                        for key in ("symbol", "rating", "conviction", "strategy", "reason")
                    }
                    | {
                        "risk": (
                            (finalists.get(pick.get("symbol")) or {}).get("risk-scout") or {}
                        ).get("risk_level")
                    }
                    for pick in judge.get("picks") or []
                ],
                "dropped": [
                    {"symbol": item.get("symbol"), "why": item.get("dropped")}
                    for item in judge.get("dropped") or []
                ],
                "specialists": {
                    role: view.get("status")
                    for role, view in (selection.get("specialists") or {}).items()
                },
                "strategies": list((selection.get("strategies") or {}).keys()),
                "assessed": len(report.get("candidates") or []),
                "pool": len(selection.get("pool") or []),
                "scan": report.get("scan"),
                "ranked": [
                    {
                        "symbol": item.get("symbol"),
                        "score": (item.get("score") or {}).get("total"),
                        "eligible": item.get("eligible"),
                        "watch": item.get("symbol") in (report.get("watching") or []),
                        "buildup": ((item.get("signals") or {}).get("positioning") or {}).get(
                            "buildup"
                        ),
                        "delivery_pct": ((item.get("signals") or {}).get("positioning") or {}).get(
                            "delivery_pct"
                        ),
                        "gap_pct": ((item.get("signals") or {}).get("opening") or {}).get(
                            "gap_pct"
                        ),
                        "rs_pct": ((item.get("signals") or {}).get("opening") or {}).get(
                            "rs_vs_nifty_pct"
                        ),
                        "events": (item.get("signals") or {}).get("events") or [],
                        "setups": (item.get("signals") or {}).get("setups") or [],
                        "insiders": (item.get("signals") or {}).get("insiders"),
                        "results": (item.get("signals") or {}).get("results"),
                    }
                    for item in (report.get("candidates") or [])[:12]
                    if item.get("signals")
                ],
            }
            try:
                checked = json.loads(
                    (directory / f"confirm-{report.get('session_date')}.json").read_text("utf-8")
                )
                result["report"]["confirmation"] = checked.get("picks")
            except (OSError, ValueError):
                result["report"]["confirmation"] = None
    except (OSError, ValueError, TypeError, AttributeError):
        result["report"] = None
    result["trade_desk"] = trade_desk_state(directory)
    try:
        import swing

        result["swing"] = (
            swing.status(directory / "pipeline.json")
            if (directory / "pipeline.json").is_file()
            else None
        )
    except (ValueError, OSError, KeyError, TypeError):
        result["swing"] = None
    try:
        card = json.loads((directory / "strategy-scorecard.json").read_text(encoding="utf-8"))
        result["scorecard"] = {
            "as_of": card.get("as_of"),
            "sessions": card.get("sessions"),
            "strategies": {
                name: {
                    "eligible": bool(item.get("eligible")),
                    "reason": (item.get("reasons") or [""])[0],
                    "doubled_costs": {
                        key: (item.get("doubled_costs") or {}).get(key)
                        for key in ("trades", "net_inr", "profit_factor")
                    },
                }
                for name, item in (card.get("strategies") or {}).items()
            },
        }
    except (OSError, ValueError, TypeError, AttributeError):
        result["scorecard"] = None
    return result


def read_run(path: Path) -> tuple[dict, dict | None, list[dict]]:
    """Read a consistent view without taking ownership of the engine's write version."""
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
        conn.execute("BEGIN")
        book = json.loads(conn.execute("SELECT data FROM book WHERE id=1").fetchone()[0])
        row = conn.execute("SELECT data FROM engine_state WHERE id=1").fetchone()
        events = [
            json.loads(row[0]) for row in conn.execute("SELECT data FROM engine_log ORDER BY seq")
        ]
    paper_book.verify_state(book)
    return book, json.loads(row[0]) if row else None, events


def project_state(path: Path, status: str = "interrupted") -> dict[str, Any]:
    """Project recorded events into UI summaries. No agent activity is invented."""
    book, snapshot, events = read_run(path)
    orders = [event for event in events if event["kind"] == "order"]
    quotes = [event for event in events if event["kind"] == "quote"]
    decisions = [event for event in events if event["kind"] == "decision"]
    for seq, event in enumerate(events, 1):
        event["seq"] = seq
    agents = []
    for key, name, role, kinds in STAGES:
        observed = [event for event in events if event["kind"] in kinds]
        last = observed[-1] if observed else {}
        blocked = last.get("kind") in ("quote_rejected", "entry_blocked", "strategy_blocked") or (
            last.get("kind") == "order" and last.get("status") == "rejected"
        )
        agents.append(
            {
                "id": key,
                "name": name,
                "role": role,
                "count": len(observed),
                "status": "blocked" if blocked else "recorded" if observed else "idle",
                "latest": last,
                "implementation": "Deterministic Python stage",
            }
        )
    agents.extend(
        {
            "id": key,
            "name": name,
            "role": role,
            "count": 0,
            "status": "idle",
            "latest": {},
            "implementation": "Portable skill; not invoked by this replay",
        }
        for key, name, role in (
            ("news", "News analyst", "Exchange announcements"),
            ("fundamentals", "Company analyst", "Financial disclosures"),
            ("reviewer", "Independent reviewer", "Research handoff review"),
        )
    )
    calls = []
    for order in orders:
        plan = next(
            (
                event
                for event in reversed(decisions)
                if event["seq"] < order["seq"]
                and event["symbol"] == order["symbol"]
                and event["side"] == order["side"]
            ),
            {},
        )
        calls.append({**plan, **order, "stop": plan.get("stop"), "target": plan.get("target")})
    realized = sum((Decimal(value) for value in book["realized_by_day"].values()), Decimal(0))
    marks = {event["symbol"]: Decimal(event["bid"]) for event in quotes}
    market_value = sum(
        (
            marks.get(symbol, Decimal(position["entry_inr"])) * position["qty"]
            for symbol, position in book["positions"].items()
        ),
        Decimal(0),
    )
    start = next((event for event in events if event["kind"] == "run_started"), {})
    return {
        "run_id": path.stem,
        "status": status,
        "mode": "synthetic_replay",
        "source": "Bundled synthetic candles · historical replay · no exchange connection",
        "scenario": start.get("scenario", "imported"),
        "clock": snapshot.get("clock") if snapshot else None,
        "phase": events[-1].get("phase", "PRE_OPEN") if events else "PRE_OPEN",
        "halt_reason": snapshot.get("halt_reason") if snapshot else None,
        "metrics": {
            "cash_inr": book["cash"],
            "realized_inr": str(realized),
            "equity_inr": str(Decimal(book["cash"]) + market_value),
            "initial_cash_inr": book["initial_cash"],
            "open_positions": len(book["positions"]),
            "fills": len(book["events"]),
            "quotes": len(quotes),
            "proposals": sum(event.get("side") == "buy" for event in decisions),
            "blocked": sum(
                event["kind"] in ("entry_blocked", "quote_rejected", "strategy_blocked")
                or (event["kind"] == "order" and event["status"] == "rejected")
                for event in events
            ),
        },
        "agents": agents,
        "calls": calls,
        "events": events[-300:],
        "positions": book["positions"],
        "limits": book["limits"],
        "controls": book["controls"],
        "prices": [{"at": event["at"], "price": event["bid"]} for event in quotes],
        "config_sha256": snapshot.get("run_sha256") if snapshot else None,
        "notice": "Virtual fills include configured costs. No live exchange or LLM agents connected.",
    }


class Observatory:
    """Own one replay worker; persist every processed candle with its journal and events."""

    def __init__(self, directory: Path, interval: float = 0.18) -> None:
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.interval = interval
        self.history = HistoryStore(self.directory / "history.sqlite")
        self.lock = threading.RLock()
        self.worker: threading.Thread | None = None
        self.paused = threading.Event()
        self.halted = threading.Event()
        self.status = "idle"
        self.error: str | None = None
        self.token = secrets.token_urlsafe(32)
        self.setup = setup_api.SetupApi(self.directory)
        self.selection_key: tuple | None = None
        self.selection: dict = {}
        files = sorted(self.directory.glob("run-*.sqlite"), key=lambda item: item.stat().st_mtime)
        self.current = files[-1] if files else None
        if self.current:
            self.status = "interrupted"

    def watchlist(self) -> dict:
        """Build a research shortlist when private master/history inputs change."""
        source = self.directory / "universe.json"
        if not source.exists():
            return {
                "candidates": [],
                "blocked": [],
                "mode": "data_required",
                "as_of": None,
                "reason": "Add a sourced universe.json and complete broker history to build a daily shortlist",
            }
        now = dt.datetime.now(engine.IST)
        key = (source.stat().st_mtime_ns, self.history.path.stat().st_mtime_ns, str(now.date()))
        if key != self.selection_key:
            try:
                result = build_watchlist(self.history, json.loads(source.read_text()), now)
                with sqlite3.connect(self.directory / "selection.sqlite") as conn:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS selections "
                        "(id INTEGER PRIMARY KEY, data TEXT NOT NULL)"
                    )
                    conn.execute("INSERT INTO selections (data) VALUES (?)", (json.dumps(result),))
                self.selection = result
            except (ValueError, KeyError, TypeError, sqlite3.Error, OSError):
                self.selection = {
                    "candidates": [],
                    "blocked": [],
                    "mode": "data_required",
                    "as_of": now.isoformat(),
                    "reason": "Instrument or historical inputs failed validation",
                }
            self.selection_key = key
        return self.selection

    def histories(self) -> list[dict]:
        return [
            self.history.coverage(symbol, dt.datetime.now(dt.timezone.utc))
            for symbol in sorted(set(self.history.symbols()) | {"NSE:DEMO"})
        ]

    def state(self) -> dict[str, Any]:
        with self.lock:
            if self.current is None:
                return {
                    "status": "idle",
                    "mode": "synthetic_replay",
                    "run_id": None,
                    "histories": self.histories(),
                    "watchlist": self.watchlist(),
                    "events": [],
                    "history": self.history.coverage("NSE:DEMO", dt.datetime.now(dt.timezone.utc)),
                    "calls": [],
                    "agents": [],
                    "prices": [],
                    "positions": {},
                    "research": research_state(self.directory),
                    "desk": desk_state(self.directory),
                }
            result = project_state(self.current, self.status)
            result["watchlist"] = self.watchlist()
            result["histories"] = self.histories()
            result["history"] = self.history.coverage("NSE:DEMO", dt.datetime.now(dt.timezone.utc))
            result["error"] = self.error
            result["research"] = research_state(self.directory)
            result["desk"] = desk_state(self.directory)
            return result

    def start(self, scenario: str) -> str:
        """Start an isolated synthetic scenario; never overwrite or reset an existing book."""
        if scenario not in ("baseline", "data-gap", "risk-block"):
            raise ValueError("Unknown replay scenario")
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError("A replay is already active")
            path = self.directory / f"run-{uuid.uuid4().hex}.sqlite"
            manifest = json.loads((ASSETS / "synthetic-sessions.json").read_text())
            date = dt.date(2026, 10, 19)
            session = india_research.session(manifest, date)
            config = engine.EngineConfig(
                ("NSE:DEMO",), Decimal(5), Decimal(10), Decimal(5), heartbeat_timeout_seconds=600
            )
            book = paper_book.create("100000", "NSE:DEMO", "250", "750", "15000", replay=True)
            store = engine.EngineStore(path)
            store.create(book)
            strategy = engine.OpeningRangeBreakout(
                Decimal(250), Decimal(50000 if scenario == "risk-block" else 15000), Decimal(2)
            )
            if scenario == "risk-block":
                strategy.risk = Decimal(5000)
            runner = engine.Engine(
                config,
                session,
                engine.PaperBroker(book, Decimal(5)),
                strategy,
                notifier=lambda *_: None,
            )
            runner._record("run_started", scenario=scenario, source="SYNTHETIC_TEST_ONLY")
            store.save(runner)
            bars = india_research.bars_from_csv(str(ASSETS / "synthetic-bars.csv"))
            quotes = engine.bar_quotes(bars, "NSE:DEMO", date, Decimal(4))
            if scenario == "data-gap":
                quotes = [q for index, q in enumerate(quotes) if index not in (1, 2)]
            self.history.ingest(
                ASSETS / "synthetic-bars.csv",
                ASSETS / "synthetic-sessions.json",
                "NSE:DEMO",
                "synthetic",
                session["close"],
            )
            self.current, self.status, self.error = path, "running", None
            self.paused.clear()
            self.halted.clear()
            self.worker = threading.Thread(
                target=self._run, args=(runner, store, quotes), daemon=True
            )
            self.worker.start()
            return path.stem

    def _run(self, runner: engine.Engine, store: engine.EngineStore, quotes: list) -> None:
        try:
            for quote in quotes:
                while self.paused.is_set() and not self.halted.is_set():
                    self.halted.wait(0.1)
                if self.halted.is_set():
                    runner.halt("Dashboard entry halt; protective paper exits remain enabled")
                runner.on_quote(quote, quote.as_of)
                runner.tick(quote.as_of)
                store.save(runner)
                threading.Event().wait(self.interval)
            runner.tick(runner.session["close"])
            store.save(runner)
            with self.lock:
                self.status = "halted" if runner.halt_reason else "completed"
        except (ValueError, KeyError, sqlite3.Error, OSError, ArithmeticError):
            with self.lock:
                self.status = "error"
                self.error = "Replay stopped. Inspect the journal before starting another run."

    def control(self, action: str) -> None:
        with self.lock:
            if not self.worker or not self.worker.is_alive():
                raise ValueError("No active replay")
            if action == "pause":
                self.paused.set()
                self.status = "paused"
            elif action == "resume":
                self.paused.clear()
                self.status = "running"
            elif action == "halt":
                self.halted.set()
                self.paused.clear()
                self.status = "halting"
            else:
                raise ValueError("Unknown control")


def make_handler(app: Observatory) -> type[BaseHTTPRequestHandler]:
    """Serve fixed assets and same-origin, token-protected replay controls on loopback."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:
            pass

        def send_bytes(
            self, status: int, body: bytes, content_type: str, extra: dict | None = None
        ) -> None:
            self.send_response(status)
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; "
                "script-src 'self'; img-src 'self' data:; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; "
                "object-src 'none'",
            )
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header(
                "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
            )
            self.end_headers()
            self.wfile.write(body)

        def json_response(self, status: int, payload: dict, extra: dict | None = None) -> None:
            self.send_bytes(status, json.dumps(payload).encode(), "application/json", extra)

        def trusted_host(self) -> bool:
            return self.headers.get("Host") in (
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            )

        def do_GET(self) -> None:
            if not self.trusted_host():
                self.json_response(403, {"error": "Loopback host required"})
                return
            parts = urlsplit(self.path)
            route = parts.path
            if route == "/api/health":
                self.json_response(200, app.setup.health())
                return
            if route.startswith("/api/setup/"):
                try:
                    self.json_response(200, app.setup.handle_get(route, parse_qs(parts.query)))
                except setup_api.ApiError as error:
                    self.json_response(error.status, error.payload())
                except (OSError, ValueError, sqlite3.Error):
                    self.json_response(503, {"error": "storage_unavailable"})
                return
            if route == "/api/state":
                try:
                    self.json_response(200, app.state())
                except (ValueError, sqlite3.Error, OSError, KeyError):
                    self.json_response(503, {"error": "Journal unavailable; controls are blocked"})
                return
            if route == "/api/session":
                self.json_response(200, {"token": app.token, "paper_only": True})
                return
            # The built single-page app: any file under the web folder, never a dotfile,
            # Markdown or anything outside it. Unknown paths fall back to index.html.
            relative = "index.html" if route in ("/", "/index.html") else route.lstrip("/")
            path = (WEB / relative).resolve()
            if (
                not path.is_relative_to(WEB.resolve())
                or path.suffix not in STATIC_TYPES
                or any(part.startswith(".") for part in path.relative_to(WEB.resolve()).parts)
            ):
                self.json_response(404, {"error": "Not found"})
                return
            if not path.is_file():
                if "." in Path(relative).name:
                    self.json_response(404, {"error": "Not found"})
                    return
                path = WEB / "index.html"
            self.send_bytes(200, path.read_bytes(), STATIC_TYPES[path.suffix])

        def do_POST(self) -> None:
            origin = self.headers.get("Origin")
            expected = {
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}",
            }
            if (
                not self.trusted_host()
                or (origin is not None and origin not in expected)
                or not secrets.compare_digest(self.headers.get("X-Session-Token", ""), app.token)
            ):
                self.json_response(403, {"error": "Same-origin session required"})
                return
            route = urlsplit(self.path).path
            if route.startswith("/api/setup/"):
                self.setup_post(route.rsplit("/", 1)[1])
                return
            if app.setup.limiter.check("replay-control", 30):
                self.json_response(429, {"error": "rate_limited"}, {"Retry-After": "60"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024 or self.headers.get("Content-Type") != "application/json":
                    raise ValueError("Expected a small JSON request")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object")
                if route == "/api/replay":
                    app.start(payload.get("scenario", "baseline"))
                elif route == "/api/control":
                    app.control(payload.get("action", ""))
                else:
                    self.json_response(404, {"error": "Not found"})
                    return
                self.json_response(200, app.state())
            except (ValueError, TypeError):
                self.json_response(409, {"error": "Invalid request or replay already active"})
            except (OSError, sqlite3.Error):
                self.json_response(503, {"error": "Storage unavailable; replay not started"})

        def setup_post(self, action: str) -> None:
            limit = setup_api.body_limit(action)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if self.headers.get("Content-Type") != "application/json":
                self.json_response(415, {"error": "json_required"})
                return
            if not 0 <= length <= limit:
                self.json_response(413, {"error": "too_large"})
                return
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError
            except ValueError:
                self.json_response(400, {"error": "malformed_json"})
                return
            try:
                body, headers = app.setup.handle_post(action, payload)
                self.json_response(200, body, headers)
            except setup_api.ApiError as error:
                retry = error.extra.get("retry_after")
                self.json_response(
                    error.status, error.payload(), {"Retry-After": str(retry)} if retry else None
                )
            except (OSError, sqlite3.Error):
                self.json_response(503, {"error": "storage_unavailable"})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/observatory"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--export-preview", type=Path, help="Export the latest synthetic state as JSON"
    )
    args = parser.parse_args()
    app = Observatory(args.data_dir)
    if args.export_preview:
        if app.current is None:
            parser.error("Run a synthetic replay before exporting a preview")
        args.export_preview.write_text(json.dumps(app.state(), indent=2) + "\n")
        return 0
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app))
    print(f"Paper observatory: http://127.0.0.1:{args.port} (local access only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

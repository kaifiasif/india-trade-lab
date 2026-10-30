"""Setup actions for the dashboard: everything a user would type, done on screen.

Served by the observatory on loopback (reached remotely only through an SSH
tunnel), behind its Host, Origin and per-process session-token checks. Each
POST action does one thing and returns JSON; long work runs as a background job.
Secrets are written to the owner-only store and never returned; settings are
validated before they replace pipeline.json; every change is recorded in an
audit log that names the keys changed and never their values. Paper only:
nothing here can place an order.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import job_runner
import kite_login
import make_universe
import secret_store
import settings_store

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SKILL = Path(__file__).resolve().parents[1]
MAX_BODY = {"upload_equity_list": 3_000_000, "save_settings": 64_000}
DEFAULT_BODY = 16_000


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra

    def payload(self) -> dict:
        return {"error": self.code, "message": self.message, **self.extra}


def body_limit(action: str) -> int:
    return MAX_BODY.get(action, DEFAULT_BODY)


# Requests allowed per action per minute. Logins and email are tight because each
# one reaches a third party; everything else is generous for a single owner.
RATE_PER_MINUTE = {
    "kite_exchange": 5,
    "kite_login_url": 10,
    "send_test_email": 3,
    "upload_equity_list": 5,
    "build_universe": 5,
    "save_secret": 20,
    "run_job": 10,
    "check_openrouter": 6,
}
DEFAULT_RATE = 30


class RateLimiter:
    """A sliding one-minute window per key. In memory: the server is one process."""

    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self.hits: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def check(self, key: str, per_minute: int) -> float:
        """Record a hit and return 0, or return the seconds to wait if over the limit."""
        now = self.clock()
        with self.lock:
            recent = [moment for moment in self.hits.get(key, []) if now - moment < 60]
            if len(recent) >= per_minute:
                self.hits[key] = recent
                return max(1.0, 60 - (now - recent[0]))
            recent.append(now)
            self.hits[key] = recent
            return 0.0


class SetupApi:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = self.data_dir / "pipeline.json"
        self.audit_path = self.data_dir / "setup-audit.jsonl"
        self.jobs = job_runner.JobRunner(self.data_dir, self.config)
        self.lock = threading.Lock()
        self.limiter = RateLimiter()
        self.metrics: dict[str, dict[str, float]] = {}
        self.used_request_tokens: set[str] = set()

    # ---------- bookkeeping ----------

    def audit(
        self, action: str, outcome: str, keys: list[str] | None = None, code: str = ""
    ) -> None:
        entry = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "id": uuid.uuid4().hex[:12],
            "action": action,
            "keys_changed": keys or [],
            "outcome": outcome,
            "error": code or None,
        }
        with self.lock, self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def measure(self, action: str, started: float, ok: bool) -> None:
        item = self.metrics.setdefault(action, {"count": 0, "errors": 0, "ms_total": 0.0})
        item["count"] += 1
        item["errors"] += 0 if ok else 1
        item["ms_total"] += (time.monotonic() - started) * 1000

    # ---------- reads ----------

    def health(self) -> dict:
        writable = True
        try:
            probe = self.data_dir / ".health"
            probe.write_text("ok")
            probe.unlink()
        except OSError:
            writable = False
        return {
            "ok": writable,
            "storage_writable": writable,
            "paper_only": True,
            "actions": {
                key: {**value, "ms_avg": round(value["ms_total"] / max(1, value["count"]), 1)}
                for key, value in self.metrics.items()
            },
            "running_jobs": sorted(self.jobs.running),
        }

    def _profile(self) -> dict:
        try:
            return json.loads((self.data_dir / "profile.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _universe(self) -> dict:
        try:
            data = json.loads((self.data_dir / "universe.json").read_text(encoding="utf-8"))
            as_of = dt.datetime.fromisoformat(data["as_of"])
            return {
                "exists": True,
                "as_of": data["as_of"],
                "age_days": (dt.datetime.now(IST) - as_of).days,
                "symbols": [item["symbol"] for item in data.get("instruments", [])],
                "names": {item["symbol"]: item.get("name", "") for item in data["instruments"]},
            }
        except (OSError, ValueError, KeyError, TypeError):
            return {"exists": False, "symbols": []}

    def _history(self, symbols: list[str]) -> dict:
        path = self.data_dir / "history.sqlite"
        if not path.is_file():
            return {"exists": False, "symbols": {}}
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as conn:
                rows = conn.execute(
                    "SELECT symbol, COUNT(*), MAX(date) FROM sessions "
                    "WHERE kind='broker_export' GROUP BY symbol"
                ).fetchall()
        except sqlite3.Error:
            return {"exists": True, "symbols": {}}
        counts = {row[0]: {"sessions": row[1], "last": row[2]} for row in rows}
        return {
            "exists": True,
            "symbols": {
                symbol: counts.get(symbol, {"sessions": 0, "last": None}) for symbol in symbols
            }
            or counts,
        }

    def _token_today(self) -> dict:
        path = secret_store.config_dir() / secret_store.TOKENS_FILE
        if not secret_store.get("KITE_ACCESS_TOKEN") or not path.is_file():
            return {"set": False, "saved_at": None, "today": False}
        saved = dt.datetime.fromtimestamp(path.stat().st_mtime, IST)
        now = dt.datetime.now(IST)
        # Kite tokens expire around 06:00 IST the next morning.
        cutoff = now.replace(hour=6, minute=0, second=0, microsecond=0)
        fresh = saved >= (cutoff if now >= cutoff else cutoff - dt.timedelta(days=1))
        return {"set": True, "saved_at": saved.isoformat(), "today": fresh}

    def status(self) -> dict:
        secrets = secret_store.status()
        config_exists = self.config.is_file()
        settings: dict[str, Any] = {}
        if config_exists:
            try:
                settings = settings_store.editable_view(self.config)["settings"]
            except (OSError, ValueError):
                settings = {}
        universe = self._universe()
        history = self._history(universe["symbols"])
        provider = settings.get("model_provider", "disabled")
        provider_key = {
            "gemini": "GEMINI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }.get(provider)
        routing = settings.get("routing") or {}
        if routing.get("enabled"):
            needed = {
                {
                    "gemini": "GEMINI_API_KEY",
                    "anthropic": "ANTHROPIC_API_KEY",
                    "openai": "OPENAI_API_KEY",
                    "openrouter": "OPENROUTER_API_KEY",
                }.get(tier.get("provider"))  # fmt: skip
                for tier in routing.get("tiers", [])
            } - {None}
            model_ready = all(secrets[key]["set"] for key in needed)
        else:
            model_ready = provider in ("disabled", "local") or bool(
                provider_key and secrets[provider_key]["set"]
            )
        scanning = bool((settings.get("scan") or {}).get("enabled"))
        if scanning:
            # The desk picks its own stocks each morning; the list only seeds strategy history.
            stocks_ready = (self.data_dir / "EQUITY_L.csv").is_file() and universe["exists"]
            stocks_detail = "Upload NSE's stock list and pick 1-10 stocks to seed strategy testing; the daily scan picks the rest"
        else:
            stocks_ready = universe["exists"] and universe.get("age_days", 99) <= 30
            stocks_detail = "NSE stock list plus today's Kite instrument list"
        today = str(dt.datetime.now(IST).date())
        try:
            attested = json.loads(
                (self.data_dir / "attestations.json").read_text(encoding="utf-8")
            ).get(today, {})
        except (OSError, ValueError):
            attested = {}
        try:
            card = json.loads((self.data_dir / "strategy-scorecard.json").read_text("utf-8"))
            tournament = {
                "ran": True,
                "as_of": card.get("as_of"),
                "eligible": card.get("eligible", []),
            }
        except (OSError, ValueError):
            tournament = {"ran": False, "eligible": []}
        equity = self.data_dir / "EQUITY_L.csv"
        kite = {
            "api_key": secrets["KITE_API_KEY"]["set"],
            "api_secret": secrets["KITE_API_SECRET"]["set"],
            "token": self._token_today(),
        }
        email = {
            "server": bool(settings.get("smtp_host")) and bool(settings.get("smtp_user")),
            "password": secrets["SMTP_PASSWORD"]["set"],
            "recipients": bool(settings.get("email_to")),
        }
        enough = bool(history["symbols"]) and all(
            item.get("sessions", 0) >= 50 for item in history["symbols"].values()
        )
        steps = [
            ("project", "Create the private project", config_exists, "pipeline.json and the NSE calendar"),
            ("profile", "Your details", bool(self._profile().get("name")) and bool(settings.get("email_to")), "Name and where the morning report goes"),
            ("kite_keys", "Kite Connect keys", kite["api_key"] and kite["api_secret"], "From developers.kite.trade (₹500/month Connect plan)"),
            ("kite_login", "Today's Kite login", kite["token"]["today"], "2FA login; tokens expire every morning"),
            ("email", "Email delivery", email["server"] and email["password"], "Mail server, sender and app password"),
            ("model", "Research model", model_ready, "Optional: the judge and agents need one"),
            ("stocks", "Choose stocks", stocks_ready, stocks_detail),
            ("history", "Load history", enough, "At least 50 complete sessions per stock"),
            ("tournament", "Run the tournament", tournament["ran"], "Decides which strategies may trade"),
            ("book", "Create the paper book", (self.data_dir / "paper.sqlite").is_file(), "Virtual cash and loss limits"),
            ("attest", "Today's checks", bool(universe["symbols"]) and all(s in attested for s in universe["symbols"]), "NSE surveillance lists and announcements, by you"),
        ]  # fmt: skip
        return {
            "paper_only": True,
            "profile": self._profile(),
            "config_exists": config_exists,
            "settings": settings,
            "secrets": {key: {k: v for k, v in item.items()} for key, item in secrets.items()},
            "kite": kite,
            "email": email,
            "model": {
                "provider": provider,
                "key_set": bool(provider_key and secrets[provider_key]["set"]),
            },
            "universe": universe,
            "equity_list": {
                "uploaded": equity.is_file(),
                "uploaded_at": dt.datetime.fromtimestamp(equity.stat().st_mtime, IST).isoformat()
                if equity.is_file()
                else None,
            },
            "history": history,
            "tournament": tournament,
            "attested_today": attested,
            "book": (self.data_dir / "paper.sqlite").is_file(),
            "swing_book": (self.data_dir / "swing.sqlite").is_file(),
            "jobs": self.jobs.recent(),
            "job_kinds": {kind: spec["label"] for kind, spec in job_runner.KINDS.items()},
            "steps": [
                {"id": key, "label": label, "done": bool(done), "detail": detail}
                for key, label, done, detail in steps
            ],
        }

    def handle_get(self, route: str, query: dict[str, list[str]]) -> dict:
        if route == "/api/setup/status":
            return self.status()
        if route == "/api/setup/settings":
            self._require_project()
            return settings_store.editable_view(self.config)
        if route == "/api/setup/jobs":
            return {"jobs": self.jobs.recent()}
        if route == "/api/setup/learning":
            return self.learning()
        if route.startswith("/api/setup/jobs/"):
            offset = int((query.get("offset") or ["0"])[0] or 0)
            try:
                return self.jobs.get(route.rsplit("/", 1)[1], offset)
            except KeyError:
                raise ApiError(404, "not_found", "No such job") from None
        raise ApiError(404, "not_found", "Not found")

    def learning(self) -> dict:
        """Track records, lessons, stock notes, fine-tune readiness and today's model use."""
        import learning
        import model_router

        now = dt.datetime.now(IST)
        path = self.data_dir / "learning.sqlite"
        routing: dict = {}
        if self.config.is_file():
            try:
                current = settings_store.editable_view(self.config)["settings"]
                routing = current.get("routing") or {}
                if not routing.get("enabled") and current.get("model_provider") == "openrouter":
                    import model_providers

                    routing = model_providers.openrouter_routing(current)
            except (OSError, ValueError):
                routing = {}
        summary = (
            learning.LearningStore(path).summary(now)
            if path.is_file()
            else {
                "sessions_graded": 0,
                "totals": {},
                "track_records": {},
                "lessons": [],
                "stock_notes": [],
                "finetune": [],
            }  # fmt: skip
        )
        return {
            **summary,
            "routing": {
                "enabled": bool(routing.get("enabled")),
                "usage": model_router.usage_today(path, routing, now) if path.is_file() else [],
            },
        }

    # ---------- writes ----------

    def _require_project(self) -> None:
        if not self.config.is_file():
            raise ApiError(409, "project_required", "Create the project first")

    def handle_post(self, action: str, payload: dict) -> tuple[dict, dict]:
        """Return (body, extra headers)."""
        started = time.monotonic()
        handler = getattr(self, "do_" + action, None)
        if handler is None or not action.replace("_", "").isalpha():
            raise ApiError(400, "unknown_action", "Unknown setup action")
        wait = self.limiter.check(action, RATE_PER_MINUTE.get(action, DEFAULT_RATE))
        if wait:
            self.audit(action, "refused", code="rate_limited")
            raise ApiError(
                429, "rate_limited", "Too many attempts; wait a minute", retry_after=int(wait)
            )
        try:
            result = handler(payload)
            self.measure(action, started, True)
        except ApiError as error:
            self.measure(action, started, False)
            self.audit(action, "refused", code=error.code)
            raise
        body, headers, keys = result if isinstance(result, tuple) else (result, {}, [])
        self.audit(action, "ok", keys)
        return body, headers

    def do_init_project(self, payload: dict, **_: Any):
        from decision_pipeline import DEFAULT_CONFIG

        created = []
        if not self.config.is_file():
            # Projects made from the dashboard let the desk scan for its own stocks.
            config = {**DEFAULT_CONFIG, "scan": {**DEFAULT_CONFIG["scan"], "enabled": True}}
            self.config.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
            created.append("pipeline.json")
        calendar = self.data_dir / "sessions.json"
        if not calendar.is_file():
            shutil.copyfile(SKILL / "assets" / "nse-sessions-2026.json", calendar)
            created.append("sessions.json")
        return {"created": created}, {}, created

    def do_save_profile(self, payload: dict, **_: Any):
        self._require_project()
        name = str(payload.get("name", "")).strip()[:80]
        email_to = payload.get("email_to")
        email_from = str(payload.get("email_from", "")).strip()[:200]
        recipients = [email_to] if isinstance(email_to, str) else email_to
        if not name:
            raise ApiError(
                422, "invalid", "Check the highlighted fields", errors={"name": "Enter your name"}
            )
        if (
            not isinstance(recipients, list)
            or not recipients
            or len(recipients) > 5
            or any(
                not isinstance(item, str) or "@" not in item or len(item) > 200
                for item in recipients
            )
        ):
            raise ApiError(
                422,
                "invalid",
                "Check the highlighted fields",
                errors={"email_to": "Enter at least one email address"},
            )
        if email_from and "@" not in email_from:
            raise ApiError(
                422,
                "invalid",
                "Check the highlighted fields",
                errors={"email_from": "Enter an email address"},
            )
        (self.data_dir / "profile.json").write_text(json.dumps({"name": name}), encoding="utf-8")
        view = settings_store.editable_view(self.config)
        settings_store.save(
            self.config,
            {"email_to": [item.strip() for item in recipients], "email_from": email_from},
            view["version"],
        )
        return {"ok": True}, {}, ["name", "email_to", "email_from"]

    def do_save_secret(self, payload: dict, **_: Any):
        key, value = payload.get("key"), payload.get("value", "")
        if key not in secret_store.SECRET_KEYS or not isinstance(value, str):
            raise ApiError(422, "invalid", "Unknown key or value")
        try:
            described = secret_store.set_secret(key, value)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from None
        return described, {}, [key]

    def do_kite_login_url(self, payload: dict, **_: Any):
        api_key = secret_store.get("KITE_API_KEY")
        if not api_key:
            raise ApiError(409, "kite_keys_required", "Save the Kite API key first")
        return {"url": kite_login.login_url(api_key)}, {}, []

    def do_kite_exchange(self, payload: dict, **_: Any):
        api_key, api_secret = secret_store.get("KITE_API_KEY"), secret_store.get("KITE_API_SECRET")
        if not api_key or not api_secret:
            raise ApiError(409, "kite_keys_required", "Save the Kite API key and secret first")
        pasted = str(payload.get("redirect_url") or payload.get("request_token") or "")
        try:
            request_token = kite_login.request_token_from(pasted)
        except ValueError:
            raise ApiError(
                422, "invalid", "Paste the full address Zerodha sent you back to"
            ) from None
        if request_token in self.used_request_tokens:
            raise ApiError(409, "token_used", "That login was already used; log in again")
        self.used_request_tokens.add(request_token)
        try:
            token = kite_login.exchange(api_key, request_token, api_secret)
        except ValueError:
            raise ApiError(
                502,
                "kite_exchange_failed",
                "Kite refused the login. Tokens expire in minutes; log in again.",
            ) from None
        secret_store.set_secret("KITE_ACCESS_TOKEN", token)
        return {"ok": True, "token": self._token_today()}, {}, ["KITE_ACCESS_TOKEN"]

    def do_send_test_email(self, payload: dict, **_: Any):
        self._require_project()
        import premarket

        config = {**settings_store.editable_view(self.config)["settings"]}
        report = {
            "session_date": str(dt.datetime.now(IST).date()),
            "watching": [],
            "notice": "Test message from India Trade Lab setup. Paper only.",
        }
        page = "<p>India Trade Lab test message. If you can read this, the morning report will reach you.</p>"
        result = premarket.send_email(report, page, config)
        if not result.get("sent"):
            raise ApiError(502, "email_failed", result.get("reason", "Email could not be sent"))
        return result, {}, []

    def do_check_openrouter(self, payload: dict, **_: Any):
        """Free requests left today and spend, as OpenRouter reports them. Never the key."""
        import openrouter

        key = secret_store.get("OPENROUTER_API_KEY")
        if not key:
            raise ApiError(409, "key_required", "Save your OpenRouter API key first")
        try:
            status = openrouter.key_status(key)
        except ValueError:
            raise ApiError(
                502, "openrouter_unreachable", "OpenRouter did not answer; check the key"
            ) from None
        try:
            models = openrouter.catalogue(self.data_dir)
            options = {
                **openrouter.DEFAULTS,
                **(settings_store.editable_view(self.config)["settings"].get("openrouter") or {}),
            }
            usable = [m for m in models if openrouter.usable(m, options)]
            status["models"] = {
                "free": sum(openrouter.is_free(m) for m in usable),
                "paid_within_caps": sum(openrouter.within_caps(m, options) for m in usable),
            }
        except (ValueError, OSError):
            status["models"] = None
        return status, {}, []

    def do_save_settings(self, payload: dict, **_: Any):
        self._require_project()
        version, changes = payload.get("version"), payload.get("changes")
        if not isinstance(version, str):
            raise ApiError(428, "version_required", "Reload the settings before saving")
        try:
            view = settings_store.save(self.config, changes, version)
        except KeyError as error:
            raise ApiError(
                422, "invalid", f"These settings cannot be changed here: {error}"
            ) from None
        except PermissionError as error:
            raise ApiError(409, "version_conflict", str(error)) from None
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from None
        return view, {}, sorted(changes)

    def do_upload_equity_list(self, payload: dict, **_: Any):
        text = payload.get("csv_text")
        if not isinstance(text, str) or not text.strip():
            raise ApiError(422, "invalid", "Choose NSE's EQUITY_L.csv")
        header = text.lstrip("\ufeff").split("\n", 1)[0].upper()
        if (
            not header.startswith("SYMBOL,")
            or "ISIN NUMBER" not in header
            or "\x00" in text
            or any(ord(char) < 32 and char not in "\r\n\t" for char in text)
            or text.count("\n") > 20_000
        ):
            raise ApiError(
                422, "invalid", "That is not NSE's EQUITY_L.csv (SYMBOL, SERIES, ISIN NUMBER)"
            )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
            tmp.write(text)
        try:
            rows = make_universe.parse_equity_list(Path(tmp.name))
        except (ValueError, KeyError, UnicodeError):
            raise ApiError(
                422, "invalid", "That is not NSE's EQUITY_L.csv (SYMBOL, SERIES, ISIN NUMBER)"
            ) from None
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        (self.data_dir / "EQUITY_L.csv").write_text(text, encoding="utf-8")
        eq = sorted(symbol for symbol, row in rows.items() if row.get("SERIES") == "EQ")
        return {"rows": len(rows), "eq_symbols": len(eq)}, {}, ["EQUITY_L.csv"]

    def do_search_symbols(self, payload: dict, **_: Any):
        query = str(payload.get("query", "")).strip().upper()[:40]
        path = self.data_dir / "EQUITY_L.csv"
        if not path.is_file():
            raise ApiError(409, "equity_list_required", "Upload NSE's EQUITY_L.csv first")
        rows = make_universe.parse_equity_list(path)
        matches = [
            {"symbol": symbol, "name": row.get("NAME OF COMPANY", "")}
            for symbol, row in sorted(rows.items())
            if row.get("SERIES") == "EQ"
            and (not query or query in symbol or query in row.get("NAME OF COMPANY", "").upper())
        ]
        return {"matches": matches[:25]}, {}, []

    def do_build_universe(self, payload: dict, **_: Any):
        symbols = payload.get("symbols")
        if not isinstance(symbols, list):
            raise ApiError(422, "invalid", "Choose one to ten stocks")
        path = self.data_dir / "EQUITY_L.csv"
        if not path.is_file():
            raise ApiError(409, "equity_list_required", "Upload NSE's EQUITY_L.csv first")
        if not self._token_today()["today"]:
            raise ApiError(409, "kite_token_required", "Do today's Kite login first")
        try:
            dump = make_universe.fetch_kite_dump(secret_store.environment())
            universe = make_universe.build_universe(
                [str(item).strip().upper() for item in symbols],
                make_universe.parse_equity_list(path),
                make_universe.parse_kite_dump(dump),
                dt.datetime.now(IST),
            )
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from None
        (self.data_dir / "universe.json").write_text(json.dumps(universe, indent=2) + "\n", "utf-8")
        return universe, {}, ["universe.json"]

    def do_attest(self, payload: dict, **_: Any):
        import pretrade

        symbol = str(payload.get("symbol", ""))
        if symbol not in self._universe()["symbols"]:
            raise ApiError(422, "invalid", "Choose a stock from your list")
        answers = {
            "surveillance_clear": str(payload.get("surveillance_source", ""))[:400],
            "no_material_event": str(payload.get("event_source", ""))[:400],
        }
        now = dt.datetime.now(IST)
        try:
            recorded = pretrade.attest(
                self.data_dir / "attestations.json", symbol, str(now.date()), answers, now
            )
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from None
        return recorded, {}, [symbol]

    def do_create_book(self, payload: dict, **_: Any):
        import paper_book

        path = self.data_dir / "paper.sqlite"
        if path.is_file():
            raise ApiError(
                409, "book_exists", "A paper book already exists; it is never overwritten"
            )
        symbols = self._universe()["symbols"]
        if not symbols:
            raise ApiError(409, "stocks_required", "Choose your stocks first")
        try:
            book = paper_book.create(
                str(payload.get("cash_inr", "100000")),
                ",".join(symbols),
                str(payload.get("risk_inr", "250")),
                str(payload.get("daily_loss_inr", "750")),
                str(payload.get("position_limit_inr", "15000")),
            )
        except (ValueError, ArithmeticError) as error:
            raise ApiError(422, "invalid", str(error)) from None
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS book (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)"
            )
            conn.execute("INSERT INTO book VALUES (1, ?)", (json.dumps(book),))
        return {"ok": True, "cash": book["cash"], "symbols": symbols}, {}, ["paper.sqlite"]

    def do_create_swing_book(self, payload: dict, **_: Any):
        import swing

        self._require_project()
        try:
            book = swing.create_book(
                self.config,
                str(payload.get("cash_inr", "100000")),
                str(payload.get("risk_inr", "500")),
                str(payload.get("daily_loss_inr", "1500")),
                str(payload.get("position_limit_inr", "25000")),
            )
        except (ValueError, ArithmeticError) as error:
            code = 409 if "already exists" in str(error) else 422
            raise ApiError(code, "invalid", str(error)) from None
        return {"ok": True, "cash": book["cash"]}, {}, [swing.settings(self.config)["book"]]

    def do_run_job(self, payload: dict, **_: Any):
        kind = payload.get("kind")
        if kind not in job_runner.KINDS:
            raise ApiError(422, "invalid", "Unknown job")
        self._require_project()
        try:
            job = self.jobs.start(kind)
        except OSError:
            raise ApiError(503, "storage_unavailable", "Could not start the job") from None
        return job, {}, [kind]

"""Smart model routing: simple jobs go to free tiers, hard ones to the strongest tier you allow.

Each research role is either *simple* (specialists, sub-agents, debaters) or
*complex* (the selection judge, managers, the reflector). The configuration
lists the tiers to try for each class, in order. For every call the router:

1. answers from a same-day cache when the exact same prompt was already
   answered (a rerun of the morning report costs no tokens);
2. skips a tier whose daily or per-minute quota (as you entered it) is used up,
   which recently returned HTTP 429, whose key is missing, or which keeps
   returning invalid answers for this role (it learns from its own mistakes);
3. calls the first remaining tier, and if the answer fails validation or the
   provider refuses, escalates to the next tier within a daily escalation cap;
4. logs every attempt (role, tier, model, outcome, tokens, latency) so the
   dashboard can show usage against your free limits.

No model ever chooses the route: routing is plain code, so it costs nothing.
Prompts and answers are stored only when ``store_prompts`` is on, contain market
data only (never keys), and are kept for 180 days for learning and fine-tuning.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent_runtime import MODEL_ROLES, REPORT_SCHEMA, RateLimited, review_prompt

IST = ZoneInfo("Asia/Kolkata")
SIMPLE_REVIEW_ROLES = {"india-data", "india-news", "india-screener", "india-sentiment"}
TIER_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,23}")
DEFAULT_ROUTING: dict[str, Any] = {
    "enabled": False,
    "tiers": [],
    "simple": [],
    "complex": [],
    "escalate": True,
    "cache": True,
    "store_prompts": True,
    "max_escalations_per_day": 10,
}
KEEP_DAYS = 180


def is_auto(tier: dict) -> bool:
    return tier.get("provider") == "openrouter" and str(tier.get("model", "")).startswith("auto:")


def role_class(role: str) -> str:
    if role in SIMPLE_REVIEW_ROLES or MODEL_ROLES.get(role) == "quick":
        return "simple"
    return "complex"


def validate_routing(routing: dict, providers: tuple[str, ...], patterns: dict[str, str]) -> None:
    """Refuse anything ambiguous; a wrong route should fail at startup, not at 08:40."""
    if not isinstance(routing, dict) or set(routing) - set(DEFAULT_ROUTING):
        raise ValueError("routing has unknown keys")
    for flag in ("enabled", "escalate", "cache", "store_prompts"):
        if type(routing.get(flag)) is not bool:
            raise ValueError(f"routing.{flag} must be true or false")
    cap = routing.get("max_escalations_per_day")
    if type(cap) is not int or not 0 <= cap <= 100:
        raise ValueError("routing.max_escalations_per_day must be 0-100")
    tiers = routing.get("tiers")
    if not isinstance(tiers, list) or len(tiers) > 6:
        raise ValueError("routing.tiers must be a list of at most six tiers")
    names = set()
    for tier in tiers:
        allowed = {
            "name", "provider", "model", "requests_per_day", "requests_per_minute",
            "tokens_per_day", "reset_timezone", "max_input_tokens",
        }  # fmt: skip
        if not isinstance(tier, dict) or set(tier) - allowed:
            raise ValueError("Each routing tier allows only known fields")
        name = tier.get("name")
        if not isinstance(name, str) or not TIER_NAME.fullmatch(name) or name in names:
            raise ValueError("Each routing tier needs a unique short name (a-z, 0-9, -)")
        names.add(name)
        provider, model = tier.get("provider"), tier.get("model")
        if provider not in providers:
            raise ValueError(f"routing tier '{name}': provider must be one of {providers}")
        if (
            provider == "openrouter"
            and model.startswith("auto:")
            and model not in ("auto:free", "auto:paid")
        ):
            raise ValueError(f"routing tier '{name}': use auto:free, auto:paid or a model ID")
        if not isinstance(model, str) or not re.fullmatch(patterns[provider], model):
            raise ValueError(f"routing tier '{name}': enter the exact model ID")
        for field, top in (
            ("requests_per_day", 1_000_000),
            ("requests_per_minute", 10_000),
            ("tokens_per_day", 1_000_000_000),
            ("max_input_tokens", 10_000_000),
        ):
            value = tier.get(field, 0)
            if type(value) is not int or not 0 <= value <= top:
                raise ValueError(f"routing tier '{name}': {field} must be 0 (no cap) to {top}")
        try:
            ZoneInfo(tier.get("reset_timezone", "UTC"))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError(f"routing tier '{name}': unknown reset_timezone") from None
    for kind in ("simple", "complex"):
        order = routing.get(kind)
        if not isinstance(order, list) or any(item not in names for item in order):
            raise ValueError(f"routing.{kind} must list tier names in the order to try")
        if len(set(order)) != len(order):
            raise ValueError(f"routing.{kind} names a tier twice")
    if routing["enabled"] and (not routing["simple"] or not routing["complex"]):
        raise ValueError("Enabled routing needs at least one tier for simple and complex jobs")


class ModelRouter:
    """A reviewer that spreads calls across tiers. Same interface as the single reviewers."""

    name = "smart_router"
    uses_network = True
    accepts_validate = True

    def __init__(
        self,
        config: dict,
        db_path: Path,
        build_client: Callable[[dict], Any],
        clock: Callable[[], dt.datetime] | None = None,
        auto_models: Callable[[dict, str, str], list[str]] | None = None,
    ) -> None:
        self.routing = {**DEFAULT_ROUTING, **config.get("routing", {})}
        self.tiers = {tier["name"]: tier for tier in self.routing["tiers"]}
        self.build_client = build_client
        self.auto_models = auto_models
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self.db_path = db_path
        self.lock = threading.Lock()
        self.clients: dict[tuple[str, str], Any] = {}
        self.missing: set[str] = set()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, at TEXT NOT NULL, "
                "session TEXT, role TEXT NOT NULL, tier TEXT NOT NULL, provider TEXT, model TEXT, "
                "attempt INTEGER NOT NULL, outcome TEXT NOT NULL, input_tokens INTEGER, "
                "output_tokens INTEGER, latency_ms INTEGER, prompt_sha TEXT, "
                "system TEXT, user TEXT, response TEXT)"
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(calls)")}
            if "cost_usd" not in columns:
                conn.execute("ALTER TABLE calls ADD COLUMN cost_usd REAL")
            conn.execute("CREATE INDEX IF NOT EXISTS calls_tier_at ON calls(tier, at)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, day TEXT NOT NULL, "
                "response TEXT NOT NULL)"
            )

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ---------- quota bookkeeping ----------

    def _day_start(self, tier: dict, now: dt.datetime) -> str:
        zone = ZoneInfo(tier.get("reset_timezone", "UTC"))
        local = now.astimezone(zone)
        return (
            local.replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(dt.timezone.utc)
            .isoformat()
        )

    def _usable(self, conn: sqlite3.Connection, name: str, role: str, now: dt.datetime) -> str:
        """Return '' if the tier can take a call now, else the reason it is skipped."""
        tier = self.tiers[name]
        if name in self.missing:
            return "no API key saved for this provider"
        start = self._day_start(tier, now)
        used, tokens = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)),0) "
            "FROM calls WHERE tier=? AND at>=? AND outcome!='cached'",
            (name, start),
        ).fetchone()
        if tier.get("requests_per_day") and used >= tier["requests_per_day"]:
            return "daily request limit reached"
        if tier.get("tokens_per_day") and tokens >= tier["tokens_per_day"]:
            return "daily token limit reached"
        minute = (now - dt.timedelta(seconds=60)).isoformat()
        if tier.get("requests_per_minute"):
            recent = conn.execute(
                "SELECT COUNT(*) FROM calls WHERE tier=? AND at>=? AND outcome!='cached'",
                (name, minute),
            ).fetchone()[0]
            if recent >= tier["requests_per_minute"]:
                return "per-minute limit reached"
        if is_auto(tier):
            return ""  # Auto tiers judge each model separately; see openrouter.choose.
        limited = conn.execute(
            "SELECT at FROM calls WHERE tier=? AND at>=? AND outcome='rate_limited' "
            "ORDER BY at DESC",
            (name, start),
        ).fetchall()
        if len(limited) >= 3:
            return "provider refused for quota three times today"
        if limited and limited[0][0] >= minute:
            return "provider refused for quota in the last minute"
        last = [
            row[0]
            for row in conn.execute(
                "SELECT outcome FROM calls WHERE tier=? AND role=? AND at>=? "
                "AND outcome IN ('ok','invalid') ORDER BY id DESC LIMIT 5",
                (name, role, start),
            )
        ]
        if last.count("invalid") >= 3:
            return "kept giving invalid answers for this role today"
        return ""

    def _escalations_left(self, conn: sqlite3.Connection, now: dt.datetime) -> bool:
        start = now.astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
        used = conn.execute(
            "SELECT COUNT(*) FROM calls WHERE attempt>1 AND at>=? AND outcome!='cached'",
            (start.astimezone(dt.timezone.utc).isoformat(),),
        ).fetchone()[0]
        return used < self.routing["max_escalations_per_day"]

    def _client(self, name: str, model: str):
        if (name, model) not in self.clients:
            tier = self.tiers[name]
            try:
                self.clients[(name, model)] = self.build_client({**tier, "model": model})
            except ValueError:
                self.missing.add(name)
                return None
        return self.clients[(name, model)]

    def _models(self, tier: dict, role: str, session: str) -> list[str]:
        if not is_auto(tier):
            return [tier["model"]]
        if self.auto_models is None:
            return []
        try:
            return self.auto_models(tier, role, session)
        except ValueError:
            return []

    # ---------- the call ----------

    def plan(self, role: str) -> list[str]:
        return list(self.routing[role_class(role)])

    def argue(
        self,
        role: str,
        system: str,
        user: str,
        schema: dict,
        validate: Callable[[dict], Any] | None = None,
    ) -> dict:
        if role not in MODEL_ROLES and role not in SIMPLE_REVIEW_ROLES:
            raise ValueError("Unknown model role")
        return self._route(role, system, user, schema, role.replace("-", "_"), validate)

    def review(self, role: str, context: dict, reports: list[dict]) -> dict:
        system, user = review_prompt(role, context, reports)
        return self._route(role, system, user, REPORT_SCHEMA, "research_handoff", None)

    def _route(
        self,
        role: str,
        system: str,
        user: str,
        schema: dict,
        name: str,
        validate: Callable[[dict], Any] | None,
    ) -> dict:
        key = hashlib.sha256(
            json.dumps([role, system, user, schema], sort_keys=True).encode()
        ).hexdigest()
        now = self.clock()
        today = str(now.astimezone(IST).date())
        session = _session_of(user) or today
        if self.routing["cache"]:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT response FROM cache WHERE key=? AND day=?", (key, today)
                ).fetchone()
            if row:
                cached = json.loads(row[0])
                if validate is None or _passes(validate, cached):
                    self._log(role, "cache", cached, 1, "cached", key, session, 0, None)
                    return {**cached, "routed": {"tier": "cache", "attempts": []}}
        attempts: list[dict] = []
        estimate = (len(system) + len(user)) // 4
        tried = 0  # Real calls made so far; a second real call is an escalation.
        for tier_name in self.plan(role):
            with self.lock, self._connect() as conn:
                reason = self._usable(conn, tier_name, role, now)
                if not reason and self.tiers[tier_name].get("max_input_tokens"):
                    if estimate > self.tiers[tier_name]["max_input_tokens"]:
                        reason = "prompt is larger than this tier accepts"
                if (
                    not reason
                    and tried
                    and not (self.routing["escalate"] and self._escalations_left(conn, now))
                ):
                    reason = "escalation is off or today's escalation cap is used"
            if reason:
                attempts.append({"tier": tier_name, "skipped": reason})
                continue
            tier = self.tiers[tier_name]
            models = self._models(tier, role, session)
            if not models:
                attempts.append(
                    {
                        "tier": tier_name,
                        "skipped": "no model available (none usable, or today's dollar cap is reached)",
                    }
                )
                continue
            tried += 1
            for model in models:
                client = self._client(tier_name, model)
                if client is None:
                    attempts.append({"tier": tier_name, "skipped": "no API key saved"})
                    break
                started = time.monotonic()
                try:
                    raw = client.structured(system, user, schema, name)
                    if validate is not None:
                        validate(raw)
                except RateLimited:
                    self._log(role, tier_name, None, tried, "rate_limited", key, session,
                              _ms(started), tier, model=model)  # fmt: skip
                    attempts.append({"tier": tier_name, "model": model, "outcome": "rate_limited"})
                    continue
                except (ValueError, OSError, KeyError, TypeError, AttributeError):
                    self._log(role, tier_name, None, tried, "invalid", key, session,
                              _ms(started), tier, model=model)  # fmt: skip
                    attempts.append({"tier": tier_name, "model": model, "outcome": "invalid"})
                    continue
                self._log(role, tier_name, raw, tried, "ok", key, session, _ms(started),
                          tier, system, user, model=model)  # fmt: skip
                if self.routing["cache"]:
                    stored = {k: v for k, v in raw.items() if k != "routed"}
                    with self._connect() as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                            (key, today, json.dumps(stored, default=str)),
                        )
                attempts.append({"tier": tier_name, "model": model, "outcome": "ok"})
                return {**raw, "routed": {"tier": tier_name, "model": model, "attempts": attempts}}
        raise ValueError(
            "No model tier could answer: "
            + "; ".join(
                f"{item['tier']}: {item.get('skipped') or item.get('outcome')}" for item in attempts
            )[:300]  # fmt: skip
        )

    def _log(
        self,
        role: str,
        tier_name: str,
        raw: dict | None,
        attempt: int,
        outcome: str,
        key: str,
        session: str,
        latency: int,
        tier: dict | None,
        system: str | None = None,
        user: str | None = None,
        model: str | None = None,
    ) -> None:
        usage = (raw or {}).get("usage") or {}
        keep = self.routing["store_prompts"] and outcome == "ok"
        response = None
        if keep and raw is not None:
            response = json.dumps(
                {k: v for k, v in raw.items() if k not in ("usage", "response_id", "routed")},
                default=str,
            )
        now = self.clock()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO calls (at, session, role, tier, provider, model, attempt, outcome, "
                "input_tokens, output_tokens, latency_ms, prompt_sha, system, user, response, "
                "cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    now.isoformat(),
                    session,
                    role,
                    tier_name,
                    (tier or {}).get("provider"),
                    model or (tier or {}).get("model"),
                    attempt,
                    outcome,
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                    latency,
                    key,
                    system if keep else None,
                    user if keep else None,
                    response,
                    usage.get("cost_usd"),
                ),
            )
            if now.minute == 0:  # Light, occasional housekeeping.
                cutoff = (now - dt.timedelta(days=KEEP_DAYS)).isoformat()
                conn.execute("DELETE FROM calls WHERE at<?", (cutoff,))
                conn.execute("DELETE FROM cache WHERE day<?", (str(now.date()),))

    # ---------- reporting ----------

    def usage_today(self) -> list[dict]:
        return usage_today(self.db_path, self.routing, self.clock())


def usage_today(db_path: Path, routing: dict, now: dt.datetime | None = None) -> list[dict]:
    """Per tier: today's calls and tokens against the limits you entered."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if not db_path.is_file():
        return []
    rows = []
    with contextlib.closing(sqlite3.connect(db_path, timeout=10)) as conn:
        try:
            conn.execute("SELECT 1 FROM calls LIMIT 1")
        except sqlite3.OperationalError:
            return []
        for tier in routing.get("tiers", []):
            zone = ZoneInfo(tier.get("reset_timezone", "UTC"))
            start = (
                now.astimezone(zone)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .astimezone(dt.timezone.utc)
                .isoformat()
            )
            counts = dict(
                conn.execute(
                    "SELECT outcome, COUNT(*) FROM calls WHERE tier=? AND at>=? GROUP BY outcome",
                    (tier["name"], start),
                ).fetchall()
            )
            tokens = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)),0) "
                "FROM calls WHERE tier=? AND at>=?",
                (tier["name"], start),
            ).fetchone()[0]
            requests = sum(value for key, value in counts.items() if key != "cached")
            models = dict(
                conn.execute(
                    "SELECT model, COUNT(*) FROM calls WHERE tier=? AND at>=? AND outcome='ok' "
                    "GROUP BY model ORDER BY COUNT(*) DESC LIMIT 6",
                    (tier["name"], start),
                ).fetchall()
            )
            try:
                cost = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM calls WHERE tier=? AND at>=?",
                    (tier["name"], start),
                ).fetchone()[0]
            except sqlite3.OperationalError:
                cost = 0.0  # Logged before costs were recorded.
            rows.append(
                {
                    "tier": tier["name"],
                    "provider": tier["provider"],
                    "model": tier["model"],
                    "requests": requests,
                    "requests_per_day": tier.get("requests_per_day", 0),
                    "tokens": tokens,
                    "tokens_per_day": tier.get("tokens_per_day", 0),
                    "outcomes": counts,
                    "models": models,
                    "cost_usd": round(float(cost or 0), 4),
                }
            )
        start_ist = (
            (now.astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0))
            .astimezone(dt.timezone.utc)
            .isoformat()
        )
        cached = conn.execute(
            "SELECT COUNT(*) FROM calls WHERE tier='cache' AND at>=?", (start_ist,)
        ).fetchone()[0]
    if cached:
        rows.append({"tier": "cache", "provider": "", "model": "same-day answers",
                     "requests": cached, "requests_per_day": 0, "tokens": 0,
                     "tokens_per_day": 0, "outcomes": {"cached": cached}})  # fmt: skip
    return rows


def _session_of(user: str) -> str | None:
    match = re.search(r'"session_date":\s*"(\d{4}-\d{2}-\d{2})"', user)
    return match.group(1) if match else None


def _passes(validate: Callable[[dict], Any], raw: dict) -> bool:
    try:
        validate(raw)
        return True
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def _ms(started: float) -> int:
    return int(1000 * (time.monotonic() - started))

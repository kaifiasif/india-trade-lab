"""OpenRouter: one key, and the desk chooses the models itself.

You paste one OpenRouter API key. Each morning the desk reads OpenRouter's model
list (cached for the day), keeps text models that support strict JSON-schema
output, and ranks them for two kinds of work:

``auto:free``
    Models whose prompt, completion and request prices are all zero, for the
    simple jobs (specialists, sub-agents, debaters).
``auto:paid``
    Paid models under your price caps, for the judge, and only while today's
    spend is below your daily dollar cap.

A model's rank starts from a short prior (well-known instruction-following
families, larger context) and is then adjusted by what the desk has measured
itself: how often each model's answers passed validation, and how often its
calls were graded right. A model that keeps failing a role today is skipped.
Simple jobs alternate between the two best free models, which spreads
OpenRouter's per-model free limits and gives the desk a fair comparison.

Model choice is plain code, so it costs no tokens. Nothing here can place an
order. The key stays in the owner-only secret store and is sent only to
openrouter.ai.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_runtime import raise_if_rate_limited, token_usage

from broker_data import NoRedirect

API = "https://openrouter.ai/api/v1"
MODEL_ID = re.compile(r"[A-Za-z0-9_.:/-]{1,120}")
AUTO = ("auto:free", "auto:paid")
DEFAULTS: dict[str, Any] = {
    "max_input_usd_per_mtok": 1.0,
    "max_output_usd_per_mtok": 4.0,
    "max_usd_per_day": 0.5,
    "max_usd_per_month": 10.0,
    "min_context": 16000,
}
# A light starting order only. Measured validity and accuracy quickly outweigh it.
FAMILY_PRIOR = (
    ("anthropic/claude", 3.5),
    ("openai/gpt-5", 3.5),
    ("google/gemini-2.5-pro", 3.5),
    ("openai/gpt-4.1", 3.0),
    ("google/gemini", 3.0),
    ("deepseek/", 3.0),
    ("qwen/qwen3", 2.5),
    ("moonshotai/", 2.5),
    ("z-ai/glm", 2.5),
    ("meta-llama/llama-4", 2.0),
    ("meta-llama/llama-3.3-70b", 2.0),
    ("mistralai/", 1.5),
    ("openai/gpt-oss", 2.0),
    ("nvidia/", 1.5),
)
MAX_BYTES = 8_000_000


def _get_json(url: str, key: str = "", timeout: int = 20, opener: Any = None) -> Any:
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with (opener or urllib.request.build_opener(NoRedirect)).open(
            request, timeout=timeout
        ) as response:
            raw = response.read(MAX_BYTES + 1)
    except (OSError, urllib.error.URLError):
        raise ValueError("OpenRouter could not be reached") from None
    if len(raw) > MAX_BYTES:
        raise ValueError("OpenRouter response too large")
    return json.loads(raw)


class OpenRouterClient:
    """Strict JSON-schema chat completions through OpenRouter, one model per client."""

    uses_network = True

    def __init__(
        self, model: str, timeout: int = 30, max_output_tokens: int = 1200, opener: Any = None
    ) -> None:
        if not MODEL_ID.fullmatch(model) or model in AUTO:
            raise ValueError("Use an explicit OpenRouter model ID, e.g. deepseek/deepseek-chat")
        self.key = os.environ.get("OPENROUTER_API_KEY", "")
        if not self.key:
            raise ValueError("Save your OpenRouter API key in Setup first")
        self.model, self.timeout, self.max_output_tokens = model, timeout, max_output_tokens
        self.opener = opener or urllib.request.build_opener(NoRedirect)
        self.name = "openrouter"

    def structured(self, system: str, user: str, schema: dict, name: str) -> dict:
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": self.max_output_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": name, "strict": True, "schema": schema},
                },
                # Only endpoints that honour the schema may serve the request.
                "provider": {"require_parameters": True},
            },
            allow_nan=False,
        ).encode()
        if len(body) > 180_000:
            raise ValueError("Research request exceeds context byte budget")
        request = urllib.request.Request(
            f"{API}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "X-Title": "India Trade Lab",
            },
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("Oversized model response")
            result = json.loads(raw)
            choices = result.get("choices")
            if (
                not isinstance(choices, list)
                or len(choices) != 1
                or choices[0].get("finish_reason") not in ("stop", "STOP")
            ):
                raise ValueError("Incomplete or ambiguous model response")
            handoff = json.loads(choices[0]["message"]["content"])
            if not isinstance(handoff, dict):
                raise ValueError("Invalid structured handoff")
            usage = result.get("usage") or {}
            return {
                **handoff,
                "provider": "openrouter",
                "model": result.get("model") or self.model,
                "response_id": result.get("id"),
                "usage": {
                    **token_usage(
                        {
                            "input_tokens": usage.get("prompt_tokens"),
                            "output_tokens": usage.get("completion_tokens"),
                        }
                    ),
                    "cost_usd": float(usage.get("cost") or 0.0),
                },
            }
        except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
            raise_if_rate_limited(exc)
            raise ValueError("OpenRouter request failed") from None


# ---------- the model list ----------


def catalogue(folder: Path, fetch: Callable[[], Any] | None = None) -> list[dict]:
    """OpenRouter's model list, fetched at most once a day and cached beside pipeline.json."""
    path = folder / "openrouter-models.json"
    today = str(dt.datetime.now(dt.timezone.utc).date())
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("day") == today:
            return cached["models"]
    except (OSError, ValueError, KeyError):
        cached = None
    try:
        payload = (fetch or (lambda: _get_json(f"{API}/models")))()
        models = payload["data"]
        if not isinstance(models, list) or not models:
            raise ValueError("empty model list")
    except (ValueError, KeyError, TypeError):
        if cached:
            return cached["models"]  # Yesterday's list beats no list.
        raise ValueError("OpenRouter's model list is unavailable") from None
    path.write_text(json.dumps({"day": today, "models": models}), encoding="utf-8")
    return models


def _price(model: dict, key: str) -> float:
    try:
        return float((model.get("pricing") or {}).get(key) or 0)
    except (TypeError, ValueError):
        return math.inf


def usable(model: dict, options: dict) -> bool:
    arch = model.get("architecture") or {}
    params = model.get("supported_parameters") or []
    expires = model.get("expiration_date")
    return (
        isinstance(model.get("id"), str)
        and MODEL_ID.fullmatch(model["id"]) is not None
        and "text" in (arch.get("input_modalities") or ["text"])
        and "text" in (arch.get("output_modalities") or ["text"])
        and ("structured_outputs" in params or "response_format" in params)
        and (model.get("context_length") or 0) >= options["min_context"]
        and not (expires and str(expires) <= str(dt.date.today()))
    )


def is_free(model: dict) -> bool:
    return all(_price(model, key) == 0 for key in ("prompt", "completion", "request"))


def within_caps(model: dict, options: dict) -> bool:
    return (
        not is_free(model)
        and _price(model, "request") == 0
        and _price(model, "prompt") * 1e6 <= options["max_input_usd_per_mtok"]
        and _price(model, "completion") * 1e6 <= options["max_output_usd_per_mtok"]
    )


def prior(model: dict) -> float:
    model_id = model["id"].lower()
    family = next((points for prefix, points in FAMILY_PRIOR if model_id.startswith(prefix)), 1.0)
    context = min(1.0, (model.get("context_length") or 0) / 128_000)
    return family + context


# ---------- what the desk measured ----------


@contextlib.contextmanager
def _db(path: Path):
    conn = sqlite3.connect(path, timeout=10)
    try:
        yield conn
    finally:
        conn.close()


def measured(db_path: Path, role_kind: str, roles: list[str], days: int = 14) -> dict[str, dict]:
    """Per model: share of valid answers, and graded accuracy, for this kind of job."""
    if not db_path.is_file():
        return {}
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    marks = ",".join("?" for _ in roles)
    stats: dict[str, dict] = {}
    with _db(db_path) as conn:
        try:
            for model, outcome, count in conn.execute(
                f"SELECT model, outcome, COUNT(*) FROM calls WHERE provider='openrouter' "
                f"AND at>=? AND role IN ({marks}) AND outcome IN ('ok','invalid','rate_limited') "
                "GROUP BY model, outcome",
                (since, *roles),
            ):
                stats.setdefault(model, {}).setdefault(outcome, 0)
                stats[model][outcome] += count
        except sqlite3.OperationalError:
            return {}
        try:
            for model, verdict, count in conn.execute(
                f"SELECT v.model, g.verdict, COUNT(*) FROM views v JOIN grades g "
                "ON g.session=v.session AND g.role=v.role AND g.symbol=v.symbol "
                f"WHERE v.model IS NOT NULL AND v.role IN ({marks}) AND g.verdict!='flat' "
                "GROUP BY v.model, g.verdict",
                tuple(roles),
            ):
                stats.setdefault(model, {}).setdefault("graded_" + verdict, 0)
                stats[model]["graded_" + verdict] += count
        except sqlite3.OperationalError:
            pass
    return stats


def failing_today(db_path: Path, role: str) -> set[str]:
    """Models with three invalid answers in their last five for this role today."""
    if not db_path.is_file():
        return set()
    start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
    bad = set()
    with _db(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT model, outcome FROM calls WHERE provider='openrouter' AND role=? "
                "AND at>=? AND outcome IN ('ok','invalid') ORDER BY id DESC",
                (role, start),
            ).fetchall()
        except sqlite3.OperationalError:
            return set()
    recent: dict[str, list[str]] = {}
    for model, outcome in rows:
        if len(recent.setdefault(model, [])) < 5:
            recent[model].append(outcome)
    for model, outcomes in recent.items():
        if outcomes.count("invalid") >= 3:
            bad.add(model)
    return bad


def spent_today(db_path: Path) -> float:
    start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
    return spent_since(db_path, start)


def spent_this_month(db_path: Path, now: dt.datetime | None = None) -> float:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    return spent_since(
        db_path, now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    )


def ledger(db_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    """AI spend for the dashboard: today, this month, and per role this month. Never prompts."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    roles: dict[str, dict] = {}
    if db_path.is_file():
        with _db(db_path) as conn:
            try:
                rows = conn.execute(
                    "SELECT role, COUNT(*), COALESCE(SUM(cost_usd), 0), COALESCE(SUM(input_tokens), 0), "
                    "COALESCE(SUM(output_tokens), 0) FROM calls WHERE at>=? GROUP BY role",
                    (month,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        roles = {role: {"calls": calls, "usd": round(cost, 4), "input_tokens": inp, "output_tokens": out}
                 for role, calls, cost, inp, out in rows}  # fmt: skip
    return {
        "today_usd": round(spent_today(db_path), 4),
        "month_usd": round(sum(item["usd"] for item in roles.values()), 4),
        "by_role": roles,
    }


def spent_since(db_path: Path, start: str) -> float:
    if not db_path.is_file():
        return 0.0
    with _db(db_path) as conn:
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM calls WHERE provider='openrouter' "
                "AND at>=?",
                (start,),
            ).fetchone()
        except sqlite3.OperationalError:
            return 0.0
    return float(row[0] or 0.0)


def score(model: dict, stats: dict[str, dict]) -> float:
    seen = stats.get(model["id"], {})
    value = prior(model)
    answered = seen.get("ok", 0) + seen.get("invalid", 0)
    if answered >= 5:
        value += 5 * (seen.get("ok", 0) / answered - 0.8)  # Valid JSON is the first test.
    graded = sum(seen.get(f"graded_{verdict}", 0) for verdict in ("right", "wrong", "missed"))
    if graded >= 10:
        value += 4 * (seen.get("graded_right", 0) / graded - 0.5)  # Then being right.
    if seen.get("rate_limited", 0) >= 3:
        value -= 1  # Busy free models are tried later, not dropped.
    return value


def choose(
    models: list[dict],
    choice: str,
    role: str,
    session: str,
    db_path: Path,
    options: dict | None = None,
    roles: list[str] | None = None,
    limit: int = 3,
) -> list[str]:
    """Model IDs to try, best first, for one call. Plain code; no tokens spent."""
    options = {**DEFAULTS, **(options or {})}
    candidates = [model for model in models if usable(model, options)]
    if choice == "auto:free":
        pool = [model for model in candidates if is_free(model)]
    elif choice == "auto:paid":
        if spent_today(db_path) >= options["max_usd_per_day"]:
            return []  # Today's dollar cap is reached: paid models wait until tomorrow.
        if spent_this_month(db_path) >= options["max_usd_per_month"]:
            return []  # This month's cap is reached: free models only until the 1st.
        pool = [model for model in candidates if within_caps(model, options)]
    else:
        raise ValueError("Use auto:free or auto:paid")
    stats = measured(db_path, choice, roles or [role])
    skip = failing_today(db_path, role)
    ranked = sorted(
        (model for model in pool if model["id"] not in skip),
        key=lambda model: (score(model, stats), model["id"]),
        reverse=True,
    )
    order = [model["id"] for model in ranked[:limit]]
    if choice == "auto:free" and len(order) >= 2:
        # Alternate the two best by role and day: spreads per-model free limits and
        # gives both a fair, comparable record.
        flip = int(hashlib.sha256(f"{role}|{session}".encode()).hexdigest(), 16) % 2
        if flip:
            order[0], order[1] = order[1], order[0]
    return order


def key_status(key: str, opener: Any = None) -> dict[str, Any]:
    """What OpenRouter reports for the key: free requests left today and spend. Never the key."""
    data = (_get_json(f"{API}/key", key, opener=opener) or {}).get("data") or {}
    free = data.get("free_model_daily_requests") or {}
    return {
        "is_free_tier": data.get("is_free_tier"),
        "free_requests_today": {k: free.get(k) for k in ("used", "limit", "remaining")},
        "usage_today_usd": data.get("usage_daily"),
        "limit_remaining_usd": data.get("limit_remaining"),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

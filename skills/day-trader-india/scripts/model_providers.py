"""Explicit research-model routing. Fixed official hosts (or loopback), no tools or fallback."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from agent_runtime import (
    MODEL_ROLES,
    REPORT_SCHEMA,
    ROLE_PURPOSES,
    OfflineReviewer,
    OpenAIReviewer,
    raise_if_rate_limited,
    review_prompt,
    token_usage,
)

from broker_data import NoRedirect

PROVIDERS = ("openai", "anthropic", "gemini", "local")
CLOUD_MODEL = r"[A-Za-z0-9_.-]{1,100}"
OPENAI_MODEL = r"[A-Za-z0-9_.:-]{1,100}"
LOCAL_MODEL = r"[A-Za-z0-9_.:/-]{1,100}"


def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    raw = json.dumps(payload, allow_nan=False).encode()
    if len(raw) > 180_000:
        raise ValueError("Research request exceeds context byte budget")
    request = urllib.request.Request(
        url, data=raw, headers={**headers, "Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
        body = response.read(1_000_001)
    if len(body) > 1_000_000:
        raise ValueError("Oversized model response")
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError("Invalid provider response")
    return result


def _single_object(texts: list[str], response_id: object) -> dict:
    if len(texts) != 1 or not isinstance(response_id, str) or not response_id:
        raise ValueError("No unambiguous provider receipt")
    handoff = json.loads(texts[0])
    if not isinstance(handoff, dict):
        raise ValueError("Invalid structured handoff")
    return handoff


class StructuredReviewer:
    """Anthropic Messages or Gemini generateContent with a strict JSON schema."""

    uses_network = True

    def __init__(
        self, provider: str, model: str, timeout: int = 20, max_output_tokens: int = 1200
    ) -> None:
        if provider not in ("anthropic", "gemini") or not re.fullmatch(CLOUD_MODEL, model):
            raise ValueError("Use an explicit supported provider and model identifier")
        if (
            not 1 <= timeout <= 30
            or type(max_output_tokens) is not int
            or not 400 <= max_output_tokens <= 8000
        ):
            raise ValueError("Invalid model timeout/output bound")
        self.provider, self.model = provider, model
        self.timeout, self.max_output_tokens = timeout, max_output_tokens
        self.name = provider + "_structured"
        self.key = os.environ.get(
            "ANTHROPIC_API_KEY" if provider == "anthropic" else "GEMINI_API_KEY"
        )
        if not self.key:
            raise ValueError("Configure the selected provider API key privately")

    def review(self, role: str, context: dict, reports: list[dict]) -> dict:
        system, user = review_prompt(role, context, reports)
        return self.structured(system, user, REPORT_SCHEMA, "research_handoff")

    def structured(self, system: str, user: str, schema: dict, name: str) -> dict:
        try:
            if self.provider == "anthropic":
                result = _post_json(
                    "https://api.anthropic.com/v1/messages",
                    {
                        "model": self.model,
                        "max_tokens": self.max_output_tokens,
                        "system": system,
                        "messages": [{"role": "user", "content": user}],
                        "output_config": {"format": {"type": "json_schema", "schema": schema}},
                    },
                    {"x-api-key": self.key, "anthropic-version": "2023-06-01"},
                    self.timeout,
                )
                if result.get("stop_reason") != "end_turn" or not isinstance(
                    result.get("content"), list
                ):
                    raise ValueError("Incomplete provider response")
                texts = [
                    part["text"]
                    for part in result["content"]
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                usage, response_id = token_usage(result.get("usage")), result.get("id")
            else:
                result = _post_json(
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    + self.model
                    + ":generateContent",
                    {
                        "systemInstruction": {"parts": [{"text": system}]},
                        "contents": [{"role": "user", "parts": [{"text": user}]}],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "responseJsonSchema": schema,
                            "maxOutputTokens": self.max_output_tokens,
                        },
                    },
                    {"x-goog-api-key": self.key},
                    self.timeout,
                )
                candidates = result.get("candidates")
                if (
                    not isinstance(candidates, list)
                    or len(candidates) != 1
                    or candidates[0].get("finishReason") != "STOP"
                ):
                    raise ValueError("Incomplete or ambiguous provider response")
                texts = [
                    part["text"]
                    for part in candidates[0]["content"]["parts"]
                    if "text" in part and not part.get("thought")
                ]
                counters = result.get("usageMetadata", {})
                usage = token_usage(
                    {
                        "input_tokens": counters.get("promptTokenCount"),
                        "output_tokens": (
                            counters.get("candidatesTokenCount", 0)
                            + counters.get("thoughtsTokenCount", 0)
                        ),
                    }
                )
                response_id = result.get("responseId")
            handoff = _single_object(texts, response_id)
            return {
                **handoff,
                "provider": self.provider,
                "model": self.model,
                "response_id": response_id,
                "usage": usage,
            }
        except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
            raise_if_rate_limited(exc)
            raise ValueError(
                "Research provider failed; no retry, host switch or fallback"
            ) from None


def loopback_base_url(value: str) -> str:
    """Accept only http(s) on this computer, so a local model never becomes a remote one."""
    parts = urllib.parse.urlsplit(value)
    host = parts.hostname or ""
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if parts.scheme not in ("http", "https") or not loopback or parts.query or parts.fragment:
        raise ValueError(
            "Local model URL must point at this computer, e.g. http://127.0.0.1:11434/v1"
        )
    return value.rstrip("/")


class LocalReviewer:
    """OpenAI-compatible chat completions on loopback (Ollama, LM Studio, llama.cpp, vLLM)."""

    uses_network = True

    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:11434/v1",
        timeout: int = 60,
        max_output_tokens: int = 1200,
    ) -> None:
        if not re.fullmatch(LOCAL_MODEL, model):
            raise ValueError("Use an explicit local model identifier, e.g. qwen3:14b")
        if not 1 <= timeout <= 120 or not 400 <= max_output_tokens <= 8000:
            raise ValueError("Invalid local model timeout/output bound")
        self.model, self.base_url = model, loopback_base_url(base_url)
        self.timeout, self.max_output_tokens = timeout, max_output_tokens
        self.name = "local_openai_compatible"
        self.key = os.environ.get("LOCAL_LLM_API_KEY", "")

    def review(self, role: str, context: dict, reports: list[dict]) -> dict:
        system, user = review_prompt(role, context, reports)
        return self.structured(system, user, REPORT_SCHEMA, "research_handoff")

    def structured(self, system: str, user: str, schema: dict, name: str) -> dict:
        headers = {"Authorization": "Bearer " + self.key} if self.key else {}
        try:
            result = _post_json(
                self.base_url + "/chat/completions",
                {
                    "model": self.model,
                    "stream": False,
                    "max_tokens": self.max_output_tokens,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": name, "strict": True, "schema": schema},
                    },
                },
                headers,
                self.timeout,
            )
            choices = result.get("choices")
            if (
                not isinstance(choices, list)
                or len(choices) != 1
                or choices[0].get("finish_reason") != "stop"
            ):
                raise ValueError("Incomplete or ambiguous local response")
            handoff = _single_object([choices[0]["message"]["content"]], result.get("id"))
            return {
                **handoff,
                "provider": "local",
                "model": self.model,
                "response_id": result["id"],
                "usage": token_usage(
                    {
                        "input_tokens": (result.get("usage") or {}).get("prompt_tokens"),
                        "output_tokens": (result.get("usage") or {}).get("completion_tokens"),
                    }
                ),
            }
        except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
            raise_if_rate_limited(exc)
            raise ValueError("Local model failed; no retry or fallback") from None


class RoutedReviewer:
    """Quick/deep defaults plus per-role overrides. All responses still face the same veto gates."""

    name = "routed_research_models"
    uses_network = True
    accepts_validate = True
    QUICK_ROLES = {"india-data", "india-news", "india-screener", "india-sentiment"} | {
        role for role, tier in MODEL_ROLES.items() if tier == "quick"
    }

    def __init__(self, config: dict) -> None:
        self.routes = {}
        provider = config["model_provider"]
        overrides = config.get("model_routes", {})
        known = set(ROLE_PURPOSES) | set(MODEL_ROLES)
        if not isinstance(overrides, dict) or set(overrides) - known:
            raise ValueError("Unknown model routing role")
        for role in sorted(known):
            default = (
                config.get("quick_model" if role in self.QUICK_ROLES else "deep_model")
                or config["model"]
            )
            route = overrides.get(role, {"provider": provider, "model": default})
            if not isinstance(route, dict) or set(route) != {"provider", "model"}:
                raise ValueError("Each role route needs provider and model only")
            if not route["model"]:
                tier = "quick_model" if role in self.QUICK_ROLES else "deep_model"
                raise ValueError(
                    f'No model named for role \'{role}\': set "{tier}" or "model" in '
                    f"pipeline.json for provider '{route['provider']}'"
                )
            pattern = {"openai": OPENAI_MODEL, "local": LOCAL_MODEL}.get(
                route["provider"], CLOUD_MODEL
            )
            if (
                route["provider"] not in PROVIDERS
                or not isinstance(route["model"], str)
                or not re.fullmatch(pattern, route["model"])
            ):
                raise ValueError("Unsupported role provider or model identifier")
            self.routes[role] = dict(route)
        if any(route["provider"] == "local" for route in self.routes.values()):
            loopback_base_url(config.get("local_base_url", "http://127.0.0.1:11434/v1"))
        self.config = dict(config)

    def client(self, role: str):
        return client_for(self.routes[role], self.config)

    def review(self, role: str, context: dict, reports: list[dict]) -> dict:
        return self.client(role).review(role, context, reports)

    def argue(self, role: str, system: str, user: str, schema: dict, validate=None) -> dict:
        if role not in MODEL_ROLES:
            raise ValueError("Unknown model role")
        raw = self.client(role).structured(system, user, schema, role.replace("-", "_"))
        if validate is not None:
            validate(raw)
        return raw


def client_for(route: dict, config: dict):
    """One provider client for a {provider, model} route. Raises ValueError without a key."""
    if route["provider"] == "openai":
        return OpenAIReviewer(
            route["model"],
            timeout=config.get("model_timeout_seconds", 20),
            effort=config.get("reasoning_effort"),
            max_output_tokens=config.get("max_output_tokens", 1200),
        )
    if route["provider"] == "local":
        return LocalReviewer(
            route["model"],
            config.get("local_base_url", "http://127.0.0.1:11434/v1"),
            config.get("local_timeout_seconds", 60),
            config.get("max_output_tokens", 1200),
        )
    return StructuredReviewer(
        route["provider"],
        route["model"],
        config.get("model_timeout_seconds", 20),
        config.get("max_output_tokens", 1200),
    )


MODEL_PATTERNS = {
    "openai": OPENAI_MODEL,
    "anthropic": CLOUD_MODEL,
    "gemini": CLOUD_MODEL,
    "local": LOCAL_MODEL,
}


def configured_reviewer(config: dict, state_dir: Path | None = None):
    routing = config.get("routing") or {}
    if routing.get("enabled"):
        import model_router

        model_router.validate_routing(routing, PROVIDERS, MODEL_PATTERNS)
        if any(tier["provider"] == "local" for tier in routing["tiers"]):
            loopback_base_url(config.get("local_base_url", "http://127.0.0.1:11434/v1"))
        folder = state_dir or Path.cwd()
        return model_router.ModelRouter(
            config, folder / "learning.sqlite", lambda tier: client_for(tier, config)
        )
    if config["model_provider"] == "disabled":
        return OfflineReviewer()
    if config["model_provider"] not in PROVIDERS:
        raise ValueError("Supported research providers: disabled, openai, anthropic, gemini, local")
    return RoutedReviewer(config)

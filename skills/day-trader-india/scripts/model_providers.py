"""Explicit research-model routing. Fixed official hosts, no tools or provider fallback."""

from __future__ import annotations

import json
import os
import re
import urllib.request

from agent_runtime import (
    REPORT_SCHEMA,
    ROLE_PURPOSES,
    OfflineReviewer,
    OpenAIReviewer,
    review_prompt,
    token_usage,
)

from broker_data import NoRedirect


class StructuredReviewer:
    uses_network = True

    def __init__(
        self, provider: str, model: str, timeout: int = 20, max_output_tokens: int = 1200
    ) -> None:
        if provider not in ("anthropic", "gemini") or not re.fullmatch(
            r"[A-Za-z0-9_.-]{1,100}", model
        ):
            raise ValueError("Use an explicit supported provider and model identifier")
        if (
            not 1 <= timeout <= 30
            or type(max_output_tokens) is not int
            or not 400 <= max_output_tokens <= 8000
        ):
            raise ValueError("Invalid model timeout/output bound")
        self.provider, self.model, self.timeout, self.max_output_tokens = (
            provider,
            model,
            timeout,
            max_output_tokens,
        )
        self.name = provider + "_structured"
        self.key = os.environ.get(
            "ANTHROPIC_API_KEY" if provider == "anthropic" else "GEMINI_API_KEY"
        )
        if not self.key:
            raise ValueError("Configure the selected provider API key privately")

    def review(self, role: str, context: dict, reports: list[dict]) -> dict:
        system, user = review_prompt(role, context, reports)
        if self.provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            payload = {
                "model": self.model,
                "max_tokens": self.max_output_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "output_config": {"format": {"type": "json_schema", "schema": REPORT_SCHEMA}},
            }
            headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
        else:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                + self.model
                + ":generateContent"
            )
            payload = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": REPORT_SCHEMA,
                    "maxOutputTokens": self.max_output_tokens,
                },
            }
            headers = {"x-goog-api-key": self.key}
        raw = json.dumps(payload, allow_nan=False).encode()
        if len(raw) > 180_000:
            raise ValueError("Research request exceeds context byte budget")
        try:
            request = urllib.request.Request(
                url,
                data=raw,
                headers={**headers, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.build_opener(NoRedirect).open(
                request, timeout=self.timeout
            ) as response:
                body = response.read(1_000_001)
            if len(body) > 1_000_000:
                raise ValueError("Oversized model response")
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError("Invalid provider response")
            if self.provider == "anthropic":
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
            if len(texts) != 1 or not isinstance(response_id, str) or not response_id:
                raise ValueError("No unambiguous provider receipt")
            handoff = json.loads(texts[0])
            if not isinstance(handoff, dict):
                raise ValueError("Invalid structured handoff")
            return {
                **handoff,
                "provider": self.provider,
                "model": self.model,
                "response_id": response_id,
                "usage": usage,
            }
        except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError):
            raise ValueError(
                "Research provider failed; no retry, host switch or fallback"
            ) from None


class RoutedReviewer:
    """Quick/deep defaults plus per-role overrides. All responses still face the same veto gates."""

    name = "routed_research_models"
    uses_network = True
    QUICK_ROLES = {"india-data", "india-news", "india-screener", "india-sentiment"}

    def __init__(self, config: dict) -> None:
        self.routes = {}
        provider = config["model_provider"]
        overrides = config.get("model_routes", {})
        if not isinstance(overrides, dict) or set(overrides) - ROLE_PURPOSES.keys():
            raise ValueError("Unknown model routing role")
        for role in ROLE_PURPOSES:
            default = (
                config.get("quick_model" if role in self.QUICK_ROLES else "deep_model")
                or config["model"]
            )
            route = overrides.get(role, {"provider": provider, "model": default})
            if not isinstance(route, dict) or set(route) != {"provider", "model"}:
                raise ValueError("Each role route needs provider and model only")
            if (
                route["provider"] not in ("openai", "anthropic", "gemini")
                or not isinstance(route["model"], str)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", route["model"])
            ):
                raise ValueError("Unsupported role provider or model identifier")
            self.routes[role] = dict(route)
        self.config = dict(config)

    def review(self, role: str, context: dict, reports: list[dict]) -> dict:
        route = self.routes[role]
        if route["provider"] == "openai":
            client = OpenAIReviewer(
                route["model"],
                timeout=self.config.get("model_timeout_seconds", 20),
                effort=self.config.get("reasoning_effort"),
                max_output_tokens=self.config.get("max_output_tokens", 1200),
            )
        else:
            client = StructuredReviewer(
                route["provider"],
                route["model"],
                self.config.get("model_timeout_seconds", 20),
                self.config.get("max_output_tokens", 1200),
            )
        return client.review(role, context, reports)


def configured_reviewer(config: dict):
    if config["model_provider"] == "disabled":
        return OfflineReviewer()
    if config["model_provider"] not in ("openai", "anthropic", "gemini"):
        raise ValueError("Supported research providers: disabled, openai, anthropic, gemini")
    return RoutedReviewer(config)

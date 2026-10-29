"""OpenRouter: one key, and the desk chooses models from what it has measured."""

import datetime as dt
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import model_providers
import openrouter

import model_router

USER = json.dumps({"session_date": "2026-10-29", "task": "x"})


def model(model_id, prompt="0", completion="0", params=("structured_outputs",), context=131072):
    return {
        "id": model_id,
        "context_length": context,
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        "pricing": {"prompt": prompt, "completion": completion, "request": "0"},
        "supported_parameters": list(params),
    }


CATALOGUE = [
    model("deepseek/deepseek-chat-v3:free"),
    model("meta-llama/llama-3.3-70b-instruct:free"),
    model("tiny/no-json:free", params=("temperature",)),
    model("short/context:free", context=8000),
    model("deepseek/deepseek-chat", prompt="0.0000003", completion="0.0000012"),
    model("anthropic/claude-opus", prompt="0.000015", completion="0.000075"),  # Over the caps.
]


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Opener:
    def __init__(self, payload):
        self.payload, self.requests = payload, []

    def open(self, request, timeout=None):
        self.requests.append(request)
        return Response(json.dumps(self.payload).encode())


class ChooseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.db = Path(self.temporary.name) / "learning.sqlite"
        model_router.ModelRouter({"routing": {}}, self.db, lambda tier: None)  # Creates calls.

    def tearDown(self):
        self.temporary.cleanup()

    def log(self, model_id, outcome, count, role="news-analyst", cost=0.0):
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with sqlite3.connect(self.db) as conn:
            for _ in range(count):
                conn.execute(
                    "INSERT INTO calls (at, role, tier, provider, model, attempt, outcome, cost_usd) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (now, role, "free", "openrouter", model_id, 1, outcome, cost),
                )

    def test_free_jobs_get_free_json_capable_models_only(self):
        order = openrouter.choose(CATALOGUE, "auto:free", "news-analyst", "s1", self.db)
        self.assertEqual(
            sorted(order),
            ["deepseek/deepseek-chat-v3:free", "meta-llama/llama-3.3-70b-instruct:free"],
        )

    def test_paid_jobs_respect_price_caps_and_the_daily_dollar_cap(self):
        order = openrouter.choose(CATALOGUE, "auto:paid", "selection-judge", "s1", self.db)
        self.assertEqual(order, ["deepseek/deepseek-chat"])
        self.log("deepseek/deepseek-chat", "ok", 1, role="selection-judge", cost=0.6)
        self.assertEqual(
            openrouter.choose(CATALOGUE, "auto:paid", "selection-judge", "s1", self.db), []
        )

    def test_measured_validity_outranks_the_starting_prior(self):
        self.log("deepseek/deepseek-chat-v3:free", "invalid", 2)
        self.log("deepseek/deepseek-chat-v3:free", "ok", 4)
        self.log("meta-llama/llama-3.3-70b-instruct:free", "ok", 10)
        ranked = sorted(
            [model for model in CATALOGUE if model["id"].endswith(":free")][:2],
            key=lambda item: openrouter.score(
                item, openrouter.measured(self.db, "auto:free", ["news-analyst"])
            ),
            reverse=True,
        )
        self.assertEqual(ranked[0]["id"], "meta-llama/llama-3.3-70b-instruct:free")

    def test_a_model_failing_a_role_today_is_skipped(self):
        self.log("deepseek/deepseek-chat-v3:free", "invalid", 3)
        order = openrouter.choose(CATALOGUE, "auto:free", "news-analyst", "s1", self.db)
        self.assertNotIn("deepseek/deepseek-chat-v3:free", order)
        other_role = openrouter.choose(CATALOGUE, "auto:free", "vibe", "s1", self.db)
        self.assertIn("deepseek/deepseek-chat-v3:free", other_role)

    def test_simple_jobs_alternate_the_two_best_free_models(self):
        firsts = {
            openrouter.choose(CATALOGUE, "auto:free", "news-analyst", f"2026-10-{day}", self.db)[0]
            for day in range(10, 30)
        }
        self.assertEqual(len(firsts), 2)


class ClientTests(unittest.TestCase):
    def test_requests_strict_json_only_from_endpoints_that_honour_it(self):
        opener = Opener(
            {
                "id": "gen-1",
                "model": "deepseek/deepseek-chat-v3:free",
                "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0},
            }
        )
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test-123456"}):
            client = openrouter.OpenRouterClient("deepseek/deepseek-chat-v3:free", opener=opener)
            result = client.structured("sys", "user", {"type": "object"}, "news_analyst")
        body = json.loads(opener.requests[0].data)
        self.assertEqual(body["response_format"]["json_schema"]["strict"], True)
        self.assertEqual(body["provider"], {"require_parameters": True})
        self.assertEqual(
            opener.requests[0].full_url, "https://openrouter.ai/api/v1/chat/completions"
        )
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["usage"]["cost_usd"], 0.0)
        with self.assertRaises(ValueError):
            openrouter.OpenRouterClient("auto:free")

    def test_key_status_reports_limits_never_the_key(self):
        opener = Opener({"data": {"is_free_tier": True, "usage_daily": 0.01,
                                  "free_model_daily_requests": {"used": 12, "limit": 50, "remaining": 38}}})  # fmt: skip
        status = openrouter.key_status("sk-or-test-123456", opener=opener)
        self.assertEqual(status["free_requests_today"]["remaining"], 38)
        self.assertNotIn("sk-or-test", json.dumps(status))


class RouterTests(unittest.TestCase):
    def test_an_openrouter_key_alone_turns_on_auto_routing_with_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "openrouter-models.json").write_text(
                json.dumps(
                    {"day": str(dt.datetime.now(dt.timezone.utc).date()), "models": CATALOGUE}
                )
            )
            config = {"model_provider": "openrouter", "openrouter": {"max_usd_per_day": 0.5}}
            calls = []

            class Fake:
                def __init__(self, model_id):
                    self.model_id = model_id

                def structured(self, system, user, schema, name):
                    calls.append(self.model_id)
                    if len(calls) == 1:
                        raise ValueError("bad JSON")  # The first free model fails...
                    return {"ok": self.model_id, "usage": {"cost_usd": 0.0}}

            with patch.object(model_providers, "client_for", lambda tier, cfg: Fake(tier["model"])):
                reviewer = model_providers.configured_reviewer(config, folder)
                result = reviewer.argue("news-analyst", "s", USER, {})
            self.assertEqual(
                [t["model"] for t in reviewer.routing["tiers"]], ["auto:free", "auto:paid"]
            )
            self.assertEqual(len(calls), 2)  # ...and the next free model answers.
            self.assertTrue(result["routed"]["model"].endswith(":free"))
            usage = {row["tier"]: row for row in reviewer.usage_today()}
            self.assertEqual(list(usage["free"]["models"].values()), [1])

    def test_free_only_when_the_dollar_cap_is_zero(self):
        routing = model_providers.openrouter_routing({"openrouter": {"max_usd_per_day": 0}})
        self.assertEqual(routing["complex"], ["free"])


if __name__ == "__main__":
    unittest.main()

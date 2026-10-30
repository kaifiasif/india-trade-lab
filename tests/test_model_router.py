"""Smart routing: free tiers first, quotas respected, bad answers escalate, reruns are free."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import model_providers
from agent_runtime import RateLimited

import model_router

NOW = dt.datetime(2026, 10, 27, 3, 10, tzinfo=dt.timezone.utc)  # 08:40 IST
USER = json.dumps({"session_date": "2026-10-27", "task": "x"})


def config(**routing):
    tiers = [
        {"name": "free", "provider": "gemini", "model": "flash", "requests_per_day": 3,
         "requests_per_minute": 0, "reset_timezone": "America/Los_Angeles"},
        {"name": "paid", "provider": "anthropic", "model": "sonnet", "requests_per_day": 50},
    ]  # fmt: skip
    base = {
        "enabled": True,
        "tiers": tiers,
        "simple": ["free", "paid"],
        "complex": ["paid", "free"],
        "escalate": True,
        "cache": True,
        "store_prompts": True,
        "max_escalations_per_day": 10,
    }
    return {"routing": {**base, **routing}}


class Fake:
    def __init__(self, name, answers):
        self.name, self.answers, self.calls = name, list(answers), 0

    def structured(self, system, user, schema, name):
        self.calls += 1
        answer = self.answers.pop(0) if self.answers else {"ok": self.name}
        if isinstance(answer, Exception):
            raise answer
        return {**answer, "usage": {"input_tokens": 100, "output_tokens": 20}}


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.db = Path(self.temporary.name) / "learning.sqlite"

    def tearDown(self):
        self.temporary.cleanup()

    def router(self, clients, cfg=None, now=NOW):
        cfg = cfg or config()

        def build(tier):
            client = clients.get(tier["name"])
            if client is None:
                raise ValueError("no key")
            return client

        return model_router.ModelRouter(cfg, self.db, build, clock=lambda: now)

    def test_simple_jobs_use_the_free_tier_and_hard_ones_the_paid_tier(self):
        free, paid = Fake("free", []), Fake("paid", [])
        router = self.router({"free": free, "paid": paid})
        self.assertEqual(router.argue("news-analyst", "s", USER, {})["routed"]["tier"], "free")
        self.assertEqual(router.argue("selection-judge", "s", USER, {})["routed"]["tier"], "paid")
        self.assertEqual((free.calls, paid.calls), (1, 1))

    def test_a_used_up_free_quota_moves_simple_jobs_to_the_next_tier(self):
        free, paid = Fake("free", []), Fake("paid", [])
        router = self.router({"free": free, "paid": paid}, config(cache=False))
        tiers = [
            router.argue("news-analyst", "s", USER + str(i), {})["routed"]["tier"] for i in range(4)
        ]
        self.assertEqual(tiers, ["free", "free", "free", "paid"])
        usage = {row["tier"]: row for row in router.usage_today()}
        self.assertEqual(usage["free"]["requests"], 3)

    def test_quota_refusals_and_invalid_answers_escalate(self):
        free = Fake("free", [RateLimited("429"), ValueError("bad json")])
        paid = Fake("paid", [])
        router = self.router({"free": free, "paid": paid}, config(cache=False))
        first = router.argue("news-analyst", "s", USER, {})
        self.assertEqual(first["routed"]["attempts"][0]["outcome"], "rate_limited")
        self.assertEqual(first["routed"]["tier"], "paid")
        # Within a minute of a 429 the free tier is skipped without a call.
        second = router.argue("news-analyst", "s", USER + "2", {})
        self.assertIn("quota", second["routed"]["attempts"][0]["skipped"])

    def test_answers_that_fail_validation_escalate_and_are_never_returned(self):
        free, paid = Fake("free", [{"stance": "nonsense"}]), Fake("paid", [{"stance": "ok"}])
        router = self.router({"free": free, "paid": paid})

        def validate(raw):
            if raw.get("stance") != "ok":
                raise ValueError("invalid")

        result = router.argue("news-analyst", "s", USER, {}, validate=validate)
        self.assertEqual(result["stance"], "ok")
        self.assertEqual(result["routed"]["tier"], "paid")

    def test_escalation_cap_stops_spending(self):
        free = Fake("free", [ValueError("bad")] * 5)
        router = self.router(
            {"free": free, "paid": Fake("paid", [])}, config(max_escalations_per_day=0)
        )
        with self.assertRaises(ValueError) as caught:
            router.argue("news-analyst", "s", USER, {})
        self.assertIn("escalation", str(caught.exception))

    def test_a_rerun_the_same_day_is_answered_from_the_cache(self):
        free = Fake("free", [])
        router = self.router({"free": free, "paid": Fake("paid", [])})
        router.argue("news-analyst", "s", USER, {})
        again = router.argue("news-analyst", "s", USER, {})
        self.assertEqual(again["routed"]["tier"], "cache")
        self.assertEqual(free.calls, 1)
        tomorrow = self.router(
            {"free": free, "paid": Fake("paid", [])}, now=NOW + dt.timedelta(days=1)
        )
        tomorrow.argue("news-analyst", "s", USER, {})
        self.assertEqual(free.calls, 2)

    def test_a_model_that_keeps_failing_a_role_is_skipped_for_that_role(self):
        free = Fake("free", [ValueError("bad")] * 3)
        router = self.router(
            {"free": free, "paid": Fake("paid", [])},
            config(
                cache=False,
                tiers=[
                    {"name": "free", "provider": "gemini", "model": "flash"},
                    {"name": "paid", "provider": "anthropic", "model": "sonnet"},
                ],
            ),  # fmt: skip
        )
        for index in range(3):
            router.argue("news-analyst", "s", USER + str(index), {})
        fourth = router.argue("news-analyst", "s", USER + "x", {})
        self.assertIn("invalid answers", fourth["routed"]["attempts"][0]["skipped"])
        self.assertEqual(free.calls, 3)

    def test_a_tier_without_a_key_is_skipped(self):
        router = self.router({"paid": Fake("paid", [])})
        result = router.argue("news-analyst", "s", USER, {})
        self.assertEqual(result["routed"]["tier"], "paid")

    def test_prompts_are_stored_only_for_good_answers_and_never_keys(self):
        router = self.router({"free": Fake("free", []), "paid": Fake("paid", [])})
        router.argue("news-analyst", "system text", USER, {})
        import sqlite3

        with sqlite3.connect(self.db) as conn:
            row = conn.execute("SELECT system, user, response, session FROM calls").fetchone()
        self.assertEqual(row[0], "system text")
        self.assertEqual(row[3], "2026-10-27")
        self.assertNotIn("usage", json.loads(row[2]))

    def test_bad_routing_is_refused_at_startup(self):
        patterns = model_providers.MODEL_PATTERNS
        for bad in (
            {"simple": ["missing"]},
            {"tiers": [{"name": "x", "provider": "mystery", "model": "m"}]},
            {"tiers": [{"name": "Bad Name", "provider": "gemini", "model": "m"}]},
            {
                "tiers": [
                    {"name": "x", "provider": "gemini", "model": "m", "reset_timezone": "Mars"}
                ]
            },
            {"max_escalations_per_day": 1000},
        ):
            routing = {**config()["routing"], **bad}
            with self.assertRaises(ValueError):
                model_router.validate_routing(routing, model_providers.PROVIDERS, patterns)

    def test_enabled_routing_replaces_the_single_reviewer(self):
        cfg = {**config(), "model_provider": "disabled"}
        reviewer = model_providers.configured_reviewer(cfg, Path(self.temporary.name))
        self.assertIsInstance(reviewer, model_router.ModelRouter)
        self.assertTrue(reviewer.uses_network)


if __name__ == "__main__":
    unittest.main()

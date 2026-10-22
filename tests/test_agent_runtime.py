"""Model outputs are untrusted evidence-bound handoffs, never trading authority."""

import datetime as dt
import json
import unittest
from unittest.mock import patch

from agent_runtime import OfflineReviewer, OpenAIReviewer, normalize_report, run_reviews
from agent_workflow import proposal_digest

NOW = dt.datetime.fromisoformat("2026-10-19T10:00:00+05:30")


def context():
    ticket = {"symbol": "NSE:TEST", "qty": 10, "price_inr": "100", "stop_inr": "98"}
    return {
        "run_id": "test",
        "symbol": "NSE:TEST",
        "as_of": NOW.isoformat(),
        "proposal": ticket,
        "proposal_sha256": proposal_digest(ticket),
        "evidence": [
            {
                "id": "fixture",
                "source": "OFFLINE TEST ONLY",
                "observed_at": NOW.isoformat(),
                "published_at": None,
                "facts": "Offline input, not market evidence",
            }
        ],
    }


class FixtureReviewer:
    name = "offline_test_reviewer"

    def __init__(self, veto=None):
        self.veto = veto
        self.observed = {}

    def review(self, role, current, reports):
        self.observed[role] = [report["role"] for report in reports]
        return {
            "role": role,
            "decision": "BLOCK" if role == self.veto else "PASS",
            "summary": "Offline fixture",
            "evidence_ids": ["fixture"],
            "blockers": ["Fixture veto"] if role == self.veto else [],
            "proposal_sha256": current["proposal_sha256"],
        }


class RuntimeTests(unittest.TestCase):
    def test_roles_run_in_dependency_order_and_never_authorize_a_trade(self):
        reviewer = FixtureReviewer()
        result = run_reviews(context(), reviewer, now=lambda: NOW)
        self.assertEqual(result["review"]["status"], "REVIEW_COMPLETE")
        self.assertFalse(result["review"]["paper_entry_allowed"])
        self.assertEqual(len(result["events"]), 12)
        self.assertEqual(result["actual_llm_reviews"], 0)
        self.assertEqual(reviewer.observed["india-data"], [])
        self.assertEqual(reviewer.observed["india-news"], [])
        self.assertIn("india-risk", reviewer.observed["india-reviewer"])

    def test_either_veto_and_missing_provider_block_the_final_result(self):
        for role in ("india-risk", "india-reviewer"):
            self.assertEqual(
                run_reviews(context(), FixtureReviewer(role), now=lambda: NOW)["review"]["status"],
                "BLOCK",
            )
        offline = run_reviews(context(), OfflineReviewer(), now=lambda: NOW)
        self.assertEqual(offline["review"]["status"], "DATA_BLOCK")
        self.assertEqual(offline["actual_llm_reviews"], 0)
        self.assertEqual(
            run_reviews(context(), FixtureReviewer(), now=lambda: NOW + dt.timedelta(seconds=121))[
                "review"
            ]["status"],
            "DATA_BLOCK",
        )

    def test_forged_evidence_and_changed_ticket_are_refused(self):
        ctx = context()
        valid = FixtureReviewer().review("india-data", ctx, [])
        for changed in (
            {"evidence_ids": ["invented"]},
            {"proposal_sha256": "wrong"},
            {"role": "india-risk"},
            {"blockers": ["unresolved"]},
        ):
            with self.assertRaises(ValueError):
                normalize_report("india-data", {**valid, **changed}, ctx)

    def test_official_model_transport_is_bounded_and_secrets_are_redacted(self):
        reviewer = OpenAIReviewer("fixture-model", key="PRIVATE_TEST_KEY")
        ctx = context()
        response = {
            "status": "completed",
            "id": "fixture-response",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(FixtureReviewer().review("india-data", ctx, [])),
                        }
                    ],
                }
            ],
        }
        with patch("urllib.request.build_opener") as build:
            build.return_value.open.return_value.__enter__.return_value.read.return_value = (
                json.dumps(response).encode()
            )
            report = reviewer.review("india-data", ctx, [])
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
            payload = json.loads(request.data)
            self.assertFalse(payload["store"])
            self.assertNotIn("tools", payload)
            self.assertNotIn("PRIVATE_TEST_KEY", request.data.decode())
            self.assertIn("Role instructions", payload["input"][0]["content"])
            self.assertEqual(report["response_id"], "fixture-response")
        with patch("urllib.request.build_opener", side_effect=OSError("PRIVATE_TEST_KEY")):
            with self.assertRaises(ValueError) as error:
                reviewer.review("india-data", ctx, [])
            self.assertNotIn("PRIVATE_TEST_KEY", str(error.exception))


if __name__ == "__main__":
    unittest.main()

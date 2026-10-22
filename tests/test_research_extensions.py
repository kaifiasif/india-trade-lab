"""Exercise debate vetoes, provider contracts, safe checkpoint reuse and paper accounting."""

import datetime as dt
import json
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import test_paper_book
from agent_runtime import OfflineReviewer, run_reviews
from model_providers import RoutedReviewer, StructuredReviewer
from paper_analytics import performance, save_performance
from test_agent_runtime import NOW, FixtureReviewer, context
from test_decision_pipeline import setup

import paper_book


class DebateTests(unittest.TestCase):
    def test_both_sides_reach_final_review_and_either_can_veto(self):
        for veto in (None, "india-bull", "india-bear", "india-sentiment"):
            reviewer = FixtureReviewer(veto)
            ctx = {**context(), "workflow": "intraday_debate"}
            report = run_reviews(ctx, reviewer, now=lambda: NOW)
            self.assertEqual(len(report["packet"]["reports"]), 10)
            self.assertEqual(
                report["review"]["status"], "REVIEW_COMPLETE" if veto is None else "BLOCK"
            )
            self.assertIn("india-bear", reviewer.observed["india-reviewer"])
            self.assertFalse(report["review"]["paper_entry_allowed"])

    def test_checkpoint_reuses_only_valid_matching_dependencies_and_preserves_blocks(self):
        ctx, saved = context(), []
        run_reviews(ctx, OfflineReviewer(), checkpoint=saved.append, now=lambda: NOW)
        reviewer = FixtureReviewer()
        result = run_reviews(ctx, reviewer, resume_reports=saved, now=lambda: NOW)
        self.assertEqual(reviewer.observed, {})
        self.assertEqual(result["review"]["status"], "DATA_BLOCK")
        for invalid in (
            [saved[-1]],
            [saved[0], saved[0]],
            [{**saved[0], "run_id": "different"}],
            [{**saved[0], "proposal_sha256": "changed"}],
        ):
            with self.assertRaises(ValueError):
                run_reviews(ctx, reviewer, resume_reports=invalid, now=lambda: NOW)

    def test_failed_review_can_be_resumed_without_turning_into_a_pass(self):
        class Broken:
            name = "broken_fixture"

            def review(self, *args):
                raise ValueError("failure")

        saved = []
        run_reviews(context(), Broken(), checkpoint=saved.append, now=lambda: NOW)
        result = run_reviews(context(), FixtureReviewer(), resume_reports=saved, now=lambda: NOW)
        self.assertEqual(result["review"]["status"], "DATA_BLOCK")

    def test_interrupted_pipeline_requires_explicit_fresh_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            coordinator, _ = setup(Path(temporary))
            save = coordinator.store.save_handoff

            def interrupted(run_id, handoff):
                save(run_id, handoff)
                raise RuntimeError("simulated process crash")

            with (
                patch.object(coordinator.store, "save_handoff", side_effect=interrupted),
                self.assertRaises(RuntimeError),
            ):
                coordinator.run_once()
            with self.assertRaises(ValueError):
                coordinator.run_once()
            reviewer = FixtureReviewer()
            coordinator.reviewer = reviewer
            result = coordinator.run_once(resume=True)
            self.assertEqual(result["status"], "RESEARCH_PROPOSALS", result)
            self.assertNotIn("india-data", reviewer.observed)
            handoffs = coordinator.store.handoffs(result["run_id"], "NSE:TEST")
            with self.assertRaises(ValueError):
                coordinator.store.save_handoff(
                    result["run_id"], {**handoffs[0], "summary": "different"}
                )

    def test_pipeline_exposes_debate_roles_and_read_only_performance(self):
        with tempfile.TemporaryDirectory() as temporary:
            coordinator, _ = setup(Path(temporary))
            coordinator.config["review_workflow"] = "intraday_debate"
            report = coordinator.run_once()
            self.assertEqual(report["status"], "RESEARCH_PROPOSALS", report)
            self.assertEqual(len(report["required_roles"]), 10)
            self.assertEqual(report["performance"]["summary"]["closed_trades"], 0)
            self.assertFalse(report["paper_recorded"])


class ProviderTests(unittest.TestCase):
    def test_quick_deep_and_role_routes_need_keys_only_when_invoked(self):
        config = {
            "model_provider": "openai",
            "model": "test-base",
            "quick_model": "test-fast",
            "deep_model": "test-deep",
            "model_routes": {"india-bear": {"provider": "anthropic", "model": "test-bear"}},
        }
        with patch.dict("os.environ", {}, clear=True):
            reviewer = RoutedReviewer(config)
        self.assertEqual(reviewer.routes["india-data"]["model"], "test-fast")
        self.assertEqual(reviewer.routes["india-risk"]["model"], "test-deep")
        self.assertEqual(reviewer.routes["india-bear"]["provider"], "anthropic")
        with self.assertRaises(ValueError):
            RoutedReviewer({**config, "model_routes": {"unknown": {}}})
        # A ":" is valid for OpenAI identifiers only; other providers are refused at startup.
        with patch.dict("os.environ", {}, clear=True):
            RoutedReviewer({**config, "model_routes": {"india-bull": {"provider": "openai", "model": "ft:x:y"}}})  # fmt: skip
        for provider in ("anthropic", "gemini"):
            route = {"india-bull": {"provider": provider, "model": "ft:x:y"}}
            with self.assertRaises(ValueError):
                RoutedReviewer({**config, "model_routes": route})
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(ValueError):
            reviewer.review("india-bear", context(), [])

    def test_official_provider_envelopes_and_redacted_failures(self):
        handoff = FixtureReviewer().review("india-data", context(), [])
        for provider in ("anthropic", "gemini"):
            with (
                self.subTest(provider=provider),
                patch.dict(
                    "os.environ",
                    {"ANTHROPIC_API_KEY": "PRIVATE_TEST", "GEMINI_API_KEY": "PRIVATE_TEST"},
                ),
            ):
                reviewer = StructuredReviewer(provider, "fixture-model")
                body = (
                    {
                        "id": "receipt",
                        "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": json.dumps(handoff)}],
                        "usage": {"input_tokens": 100, "output_tokens": 50},
                    }
                    if provider == "anthropic"
                    else {
                        "responseId": "receipt",
                        "candidates": [
                            {
                                "finishReason": "STOP",
                                "content": {"parts": [{"text": json.dumps(handoff)}]},
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 100,
                            "candidatesTokenCount": 40,
                            "thoughtsTokenCount": 10,
                        },
                    }
                )
                with patch("urllib.request.build_opener") as opener:
                    read = opener.return_value.open.return_value.__enter__.return_value.read
                    read.return_value = json.dumps(body).encode()
                    report = reviewer.review("india-data", context(), [])
                    self.assertEqual(report["usage"], {"input_tokens": 100, "output_tokens": 50})
                    request = opener.return_value.open.call_args.args[0]
                    self.assertNotIn("PRIVATE_TEST", request.full_url + request.data.decode())
                    self.assertNotIn("tools", json.loads(request.data))
                    self.assertEqual(request.method, "POST")
                    read.return_value = b"{}"
                    with self.assertRaises(ValueError):
                        reviewer.review("india-data", context(), [])
                with patch("urllib.request.build_opener", side_effect=OSError("PRIVATE_TEST")):
                    with self.assertRaises(ValueError) as error:
                        reviewer.review("india-data", context(), [])
                    self.assertNotIn("PRIVATE_TEST", str(error.exception))


class PerformanceTests(unittest.TestCase):
    def book(self):
        helper = test_paper_book.PaperBookTests()
        helper.setUp()
        return helper, helper.buy(
            target="105", research_meta={"patterns": ["ORB"], "strategy_version": "fixture-v1"}
        )

    def test_closed_pnl_fees_and_matched_window_alpha(self):
        helper, entered = self.book()
        closed = helper.sell(entered)
        benchmark = {
            "symbol": "NSE:NIFTY50",
            "price_basis": "price_return",
            "observations": [
                {
                    "as_of": "2026-10-19T10:00:00+05:30",
                    "price_inr": "100",
                    "source": "OFFLINE_TEST",
                },
                {
                    "as_of": "2026-10-19T11:00:00+05:30",
                    "price_inr": "101",
                    "source": "OFFLINE_TEST",
                },
            ],
        }
        result = performance(closed, {}, NOW + dt.timedelta(hours=2), benchmark, "5")
        self.assertEqual(Decimal(result["realized_inr"]), Decimal("70"))
        self.assertEqual(Decimal(result["total_net_after_operating_cost_inr"]), Decimal("65"))
        self.assertEqual(Decimal(result["daily"][0]["recorded_fees_inr"]), Decimal("20"))
        self.assertEqual(result["patterns"][0]["pattern"], "ORB")
        self.assertEqual(Decimal(result["outcomes"][0]["benchmark_return_pct"]), Decimal("1"))
        self.assertFalse(result["forward_record"])
        benchmark["observations"][1]["as_of"] = "2026-10-19T11:01:00+05:30"
        result = performance(closed, {}, NOW + dt.timedelta(hours=2), benchmark)
        self.assertIsNone(result["outcomes"][0]["alpha_pp"])

    def test_open_marks_missing_and_stale_cannot_report_flat_equity(self):
        _, entered = self.book()
        quotes = {
            "NSE:DEMO": {
                "as_of": NOW.isoformat(),
                "bid_inr": "99",
                "ask_inr": "99.02",
                "source": "OFFLINE_TEST",
            }
        }
        result = performance(entered, quotes, NOW)
        self.assertLess(Decimal(result["unrealized_net_inr"]), 0)
        for mark in (
            {},
            {
                "NSE:DEMO": {
                    **quotes["NSE:DEMO"],
                    "as_of": (NOW - dt.timedelta(minutes=3)).isoformat(),
                }
            },
        ):
            result = performance(entered, mark, NOW)
            self.assertIsNone(result["estimated_liquidation_equity_inr"])
            self.assertEqual(result["missing_marks"], ["NSE:DEMO"])

    def test_future_fills_block_past_reports(self):
        helper, entered = self.book()
        with self.assertRaises(ValueError):
            performance(helper.sell(entered), {}, NOW)

    def test_saved_samples_are_idempotent_immutable_and_book_specific(self):
        helper, entered = self.book()
        result = performance(helper.sell(entered), {}, NOW + dt.timedelta(hours=2))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "performance.sqlite"
            saved = save_performance(path, result)
            self.assertEqual(saved, save_performance(path, deepcopy(result)))
            for bad in (
                {**result, "realized_inr": "999"},
                {**result, "book_id": "other"},
                {**result, "as_of": NOW.isoformat()},
            ):
                with self.assertRaises(ValueError):
                    save_performance(path, bad)

    def test_target_and_metadata_are_sealed_and_invalid_targets_refused(self):
        helper, entered = self.book()
        self.assertEqual(entered["positions"]["NSE:DEMO"]["target_inr"], "105")
        tampered = deepcopy(entered)
        tampered["positions"]["NSE:DEMO"]["target_inr"] = "106"
        with self.assertRaises(ValueError):
            paper_book.verify_state(tampered)
        with self.assertRaises(ValueError):
            helper.buy(target="100")


if __name__ == "__main__":
    unittest.main()

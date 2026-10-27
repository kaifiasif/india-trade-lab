"""Debate, ratings and decision memory, exercised offline with a scripted reviewer."""

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import debate
import report_html
import technical
from history import HistoryStore
from memory import DecisionMemory
from test_agent_runtime import FixtureReviewer
from test_history import IST, fixtures

CONTEXT = {
    "symbol": "NSE:TEST",
    "as_of": "2026-10-26T10:00:00+05:30",
    "proposal": {"symbol": "NSE:TEST", "qty": 10},
    "proposal_sha256": "digest",
    "evidence": [{"id": "fixture", "source": "OFFLINE", "facts": "f"}],
}
TURN = {
    "role": "bull-researcher",
    "argument": "a",
    "rebuttal": "",
    "evidence_ids": ["fixture"],
    "proposal_sha256": "digest",
}


class ValidationTests(unittest.TestCase):
    def test_a_valid_turn_is_bound_to_role_ticket_and_evidence(self):
        result = debate.validate("bull-researcher", TURN, CONTEXT)
        self.assertEqual(result["role"], "bull-researcher")
        self.assertEqual(result["evidence_ids"], ["fixture"])

    def test_malformed_or_unbound_output_is_refused(self):
        cases = {
            "role": {**TURN, "role": "bear-researcher"},
            "digest": {**TURN, "proposal_sha256": "other"},
            "unknown evidence": {**TURN, "evidence_ids": ["ghost"]},
            "duplicate evidence": {**TURN, "evidence_ids": ["fixture", "fixture"]},
            "oversized": {**TURN, "argument": "x" * 5000},
            "empty": {**TURN, "argument": "   "},
            "not an object": ["x"],
            "evidence not a list": {**TURN, "evidence_ids": "fixture"},
        }
        for name, raw in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                debate.validate("bull-researcher", raw, CONTEXT)

    def test_a_rating_must_be_five_tier_and_a_buy_must_cite_evidence(self):
        decision = {
            "role": "portfolio-manager",
            "rating": "Buy",
            "conviction": "medium",
            "thesis": "t",
            "invalidation": "i",
            "evidence_ids": [],
            "proposal_sha256": "digest",
        }
        with self.assertRaises(ValueError):
            debate.validate("portfolio-manager", decision, CONTEXT)
        cited = {**decision, "evidence_ids": ["fixture"]}
        self.assertEqual(debate.validate("portfolio-manager", cited, CONTEXT)["rating"], "Buy")
        with self.assertRaises(ValueError):
            debate.validate("portfolio-manager", {**cited, "rating": "Strong Buy"}, CONTEXT)
        with self.assertRaises(ValueError):
            debate.validate("portfolio-manager", {**cited, "conviction": "certain"}, CONTEXT)


class DebateFlowTests(unittest.TestCase):
    def test_both_sides_argue_rebut_and_the_manager_rates(self):
        reviewer = FixtureReviewer(rating="Overweight")
        events = []
        result = debate.run_debate(
            CONTEXT, reviewer, research_rounds=2, risk_rounds=1, emit=events.append
        )
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["rating"], "Overweight")
        self.assertEqual([turn["round"] for turn in result["research"]], [1, 1, 2, 2])
        # The second round sees the first: its rebuttal is populated.
        self.assertTrue(all(turn["rebuttal"] for turn in result["research"][2:]))
        self.assertFalse(any(turn["rebuttal"] for turn in result["research"][:2]))
        self.assertEqual(len(result["risk"]), 3)
        self.assertEqual(debate.verdict(result)[0], "PROCEED")
        self.assertEqual(result["model_calls"], debate.planned_calls(2, 1))
        self.assertTrue(any(e["kind"] == "debate_completed" for e in events))

    def test_each_rating_maps_to_one_pipeline_outcome(self):
        for rating, expected in (
            ("Buy", "PROCEED"),
            ("Overweight", "PROCEED"),
            ("Hold", "WAIT"),
            ("Underweight", "NO_TRADE"),
            ("Sell", "NO_TRADE"),
        ):
            result = debate.run_debate(CONTEXT, FixtureReviewer(rating=rating))
            with self.subTest(rating=rating):
                self.assertEqual(debate.verdict(result)[0], expected)

    def test_a_failed_role_blocks_rather_than_defaulting_to_a_rating(self):
        for failing in ("bull-researcher", "research-manager", "portfolio-manager"):
            result = debate.run_debate(CONTEXT, FixtureReviewer(fail=[failing]))
            with self.subTest(role=failing):
                self.assertEqual(result["rating"], debate.REVIEW)
                self.assertEqual(debate.verdict(result)[0], "DATA_BLOCK")
                self.assertIn(failing, result["failures"])

    def test_a_risk_debate_never_runs_without_a_research_plan(self):
        result = debate.run_debate(CONTEXT, FixtureReviewer(fail=["research-manager"]))
        self.assertEqual(result["risk"], [])
        self.assertIsNone(result["decision"])

    def test_rounds_outside_one_to_three_are_refused(self):
        for rounds in (0, 4, "two"):
            with self.subTest(rounds=rounds), self.assertRaises(ValueError):
                debate.run_debate(CONTEXT, FixtureReviewer(), research_rounds=rounds)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        bars, sessions, self.dates = fixtures(directory, count=3)
        self.history = HistoryStore(directory / "history.sqlite")
        self.cutoff = dt.datetime.combine(self.dates[-1], dt.time(16), tzinfo=IST)
        self.history.ingest(bars, sessions, "NSE:TEST", "broker_export", self.cutoff)
        self.memory = DecisionMemory(directory / "memory.sqlite")
        self.decided = dt.datetime.combine(self.dates[0], dt.time(9, 35), tzinfo=IST)

    def test_one_call_per_symbol_and_session_is_recorded(self):
        self.assertTrue(self.memory.record("r1", "NSE:TEST", self.decided, "Buy", 100.0))
        self.assertFalse(self.memory.record("r2", "NSE:TEST", self.decided, "Sell", 100.0))
        for bad in (
            ("r3", "NSE:TEST", self.decided, "Strong Buy", 100.0),
            ("r4", "NSE:TEST", self.decided.replace(tzinfo=None), "Buy", 100.0),
            ("r5", "NSE:TEST", self.decided, "Buy", 0.0),
        ):
            with self.subTest(case=bad[3]), self.assertRaises(ValueError):
                self.memory.record(*bad)

    def test_settlement_waits_for_the_window_and_runs_once(self):
        self.memory.record("r1", "NSE:TEST", self.decided, "Buy", 100.0)
        early = self.memory.settle(
            self.history, dt.datetime.combine(self.dates[0], dt.time(11), tzinfo=IST)
        )
        self.assertEqual(early["settled"], [])
        settled = self.memory.settle(self.history, self.cutoff)
        self.assertEqual(settled["settled"], ["r1:NSE:TEST"])
        self.assertEqual(self.memory.settle(self.history, self.cutoff)["settled"], [])
        score = self.memory.scorecard()
        self.assertEqual(score["settled"], 1)
        self.assertEqual(score["by_rating"]["Buy"]["count"], 1)

    def test_lessons_appear_only_after_their_outcome_was_known(self):
        self.memory.record("r1", "NSE:TEST", self.decided, "Buy", 100.0)
        self.memory.settle(self.history, self.cutoff)
        before = dt.datetime.combine(self.dates[0], dt.time(10), tzinfo=IST)
        self.assertEqual(self.memory.lessons("NSE:TEST", before), [])
        after = self.memory.lessons("NSE:TEST", self.cutoff)
        self.assertEqual(len(after), 1)
        self.assertIn("Buy", after[0]["lesson"])

    def test_a_failed_reflection_keeps_the_computed_lesson(self):
        self.memory.record("r1", "NSE:TEST", self.decided, "Buy", 100.0)

        def reflect(outcome):
            raise ValueError("provider down")

        result = self.memory.settle(self.history, self.cutoff, reflect=reflect)
        self.assertEqual(result["settled"], ["r1:NSE:TEST"])
        self.assertTrue(result["failed"])
        self.assertIn("Buy", self.memory.lessons("NSE:TEST", self.cutoff)[0]["lesson"])

    def test_hold_claims_no_direction_so_it_is_never_scored_as_a_hit(self):
        self.memory.record("r1", "NSE:TEST", self.decided, "Hold", 100.0)
        self.memory.settle(self.history, self.cutoff)
        self.assertIsNone(self.memory.scorecard()["by_rating"]["Hold"]["hit_rate_pct"])


class TechnicalTests(unittest.TestCase):
    def test_indicators_use_only_sessions_closed_by_the_cutoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bars, sessions, dates = fixtures(directory, count=30)
            store = HistoryStore(directory / "history.sqlite")
            late = dt.datetime.combine(dates[-1], dt.time(16), tzinfo=IST)
            store.ingest(bars, sessions, "NSE:TEST", "broker_export", late)
            rows = technical.daily_bars(store, "NSE:TEST", late)
            self.assertEqual(len(rows), 30)
            snapshot = technical.snapshot(rows)
            self.assertEqual(snapshot["session"], str(dates[-1]))
            self.assertIsNone(snapshot["values"]["sma200"])  # too little history to claim one
            self.assertIsNotNone(snapshot["values"]["rsi14"])
            earlier = dt.datetime.combine(dates[24], dt.time(16), tzinfo=IST)
            truncated = technical.daily_bars(store, "NSE:TEST", earlier)
            self.assertEqual(len(truncated), 25)
            self.assertEqual(technical.snapshot(truncated)["session"], str(dates[24]))
            item = technical.evidence_item("NSE:TEST", snapshot)
            self.assertEqual(item["id"], "technical-snapshot")
            self.assertIn("not a forecast", item["facts"])
            with self.assertRaises(ValueError):
                technical.snapshot(rows[:5])


class ReportTests(unittest.TestCase):
    def test_model_text_is_escaped_rather_than_rendered(self):
        hostile = {
            "run_id": "r1",
            "status": "DATA_BLOCK",
            "calls": [
                {
                    "symbol": "<img src=x onerror=alert(1)>",
                    "decision": "WAIT",
                    "reasons": ["</div><script>alert(2)</script>"],
                    "debate": {
                        "research": [
                            {
                                "role": "bull-researcher",
                                "round": 1,
                                "argument": "<script>alert(3)</script>",
                                "rebuttal": "",
                                "evidence_ids": ["fixture"],
                            }
                        ],
                        "decision": {
                            "rating": "Hold",
                            "conviction": "low",
                            "thesis": "</style><script>x</script>",
                            "invalidation": "i",
                        },
                    },
                }
            ],
        }
        page = report_html.render(hostile)
        # Hostile text must appear only as escaped characters, never as live markup.
        body = page.split("<body>", 1)[1]
        self.assertNotIn("<script", body)
        self.assertNotIn("<img", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", body)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "run.html"
            report_html.write(hostile, path)
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()

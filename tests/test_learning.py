"""Learning from mistakes: graded calls, dated lessons, stock notes, cooldowns, fine-tune data."""

import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from history import HistoryStore

import learning
import selection_agents

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
OPTIONS = {
    "lessons_in_prompts": True,
    "stock_notes": True,
    "cooldown": True,
    "weight_specialists": True,
    "min_graded": 2,
}


def bars(open_, high, low, close):
    return {"bars": [{"open": open_, "high": high, "low": low, "close": open_},
                     {"open": open_, "high": high, "low": low, "close": close}]}  # fmt: skip


def report(session, stances, picks=(), passes=(), scout="low"):
    finalists = {
        symbol: {
            "risk-scout": {"risk_level": scout, "risks": "none seen"},
            "setup-planner": {"strategy": "orb-v1", "plan": "opening range"},
        }
        for symbol in (*picks, *passes)
    }
    return {
        "session_date": session,
        "selection": {
            "mode": "judge",
            "specialists": {
                role: {
                    "status": "ok",
                    "model": "flash",
                    "assessments": {
                        symbol: {"stance": stance, "summary": f"{role} view", "evidence_ids": []}
                        for symbol, stance in views.items()
                    },
                }
                for role, views in stances.items()
            },
            "finalists": finalists,
            "judge": {
                "picks": [
                    {
                        "symbol": s,
                        "rating": "Buy",
                        "conviction": "high",
                        "strategy": "orb-v1",
                        "reason": "strong news",
                    }
                    for s in picks
                ],  # fmt: skip
                "dropped": [],
            },
        },
    }


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.history = HistoryStore(self.root / "history.sqlite")
        self.store = learning.LearningStore(self.root / "learning.sqlite")
        self.reports = self.root / "reports"
        self.reports.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def day(self, symbol, date, payload):
        close_at = f"{date}T15:30:00+05:30"
        with sqlite3.connect(self.history.path) as conn:
            conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                (symbol, date, "broker_export", close_at, "d", json.dumps(payload), close_at),
            )

    def write(self, session, body):
        (self.reports / f"premarket-{session}.json").write_text(json.dumps(body))

    def settle(self, when, book=None):
        return self.store.settle(self.reports, self.history.path, book, when)

    def test_calls_are_graded_and_mistakes_become_dated_lessons(self):
        self.write("2026-10-26", report(
            "2026-10-26",
            {"news-analyst": {"NSE:AAA": "positive"}, "technical-analyst": {"NSE:AAA": "negative"}},
            picks=["NSE:AAA"],
        ))  # fmt: skip
        self.day("NSE:AAA", "2026-10-26", bars(100, 103, 99.5, 102))
        result = self.settle(dt.datetime(2026, 10, 26, 18, tzinfo=IST))
        self.assertEqual(result["graded"]["right"], 3)  # news, judge, risk scout
        self.assertEqual(result["graded"]["wrong"], 1)  # technical said negative
        before = self.store.context(
            ["technical-analyst"], ["NSE:AAA"], dt.datetime(2026, 10, 26, 12, tzinfo=IST), OPTIONS
        )
        self.assertEqual(before["lessons"], {})  # Not known yet at noon: no peeking.
        after = self.store.context(
            ["technical-analyst"], ["NSE:AAA"], dt.datetime(2026, 10, 27, 8, tzinfo=IST), OPTIONS
        )
        lesson = after["lessons"]["technical-analyst"][0]
        self.assertIn("you were negative", lesson)
        self.assertIn("+2.0% open to close", lesson)
        self.assertEqual(after["track_records"]["news-analyst"]["accuracy"], 1.0)

    def test_a_pass_on_a_stock_that_ran_is_a_missed_opportunity(self):
        self.write("2026-10-26", report("2026-10-26", {}, passes=["NSE:BBB"]))
        self.day("NSE:BBB", "2026-10-26", bars(100, 104, 99.8, 103))
        self.settle(dt.datetime(2026, 10, 26, 18, tzinfo=IST))
        records = self.store.track_records(dt.datetime(2026, 10, 27, tzinfo=IST))
        self.assertEqual(records["selection-judge"]["missed"], 1)

    def test_paper_trades_decide_the_judge_and_two_stop_outs_cool_a_stock_down(self):
        events = []
        for index, date in enumerate(("2026-10-23", "2026-10-26")):
            self.write(date, report(date, {}, picks=["NSE:CCC"]))
            self.day("NSE:CCC", date, bars(100, 101, 97, 99))
            events += [
                {"id": f"b{index}", "side": "buy", "symbol": "NSE:CCC",
                 "as_of": f"{date}T09:40:00+05:30", "assumed_fill_inr": "100", "stop_inr": "98",
                 "target_inr": "104", "research_meta": {"strategy_version": "orb-v1"}},
                {"id": f"s{index}", "side": "sell", "symbol": "NSE:CCC", "entry_event_id": f"b{index}",
                 "as_of": f"{date}T10:15:00+05:30", "assumed_fill_inr": "98",
                 "net_realized_pnl_inr": "-250"},
            ]  # fmt: skip
        when = dt.datetime(2026, 10, 26, 18, tzinfo=IST)
        self.settle(when, {"events": events})
        context = self.store.context(["selection-judge"], ["NSE:CCC"], when, OPTIONS)
        self.assertIn("stopped out", context["cooldowns"]["NSE:CCC"])
        self.assertIn("paper trades won 0 of 2", context["stock_notes"]["NSE:CCC"])
        self.assertIn("was stopped out at -1.0R", context["lessons"]["selection-judge"][0])
        later = self.store.context(
            ["selection-judge"], ["NSE:CCC"], when + dt.timedelta(days=10), OPTIONS
        )
        self.assertNotIn("NSE:CCC", later["cooldowns"])  # Cooldowns expire.

    def test_specialists_who_are_right_count_for_more(self):
        for day, move in (("2026-10-22", 102), ("2026-10-23", 103), ("2026-10-26", 102)):
            self.write(day, report(day, {
                "news-analyst": {"NSE:AAA": "positive"},
                "sentiment-analyst": {"NSE:AAA": "negative"},
            }))  # fmt: skip
            self.day("NSE:AAA", day, bars(100, 103, 99.5, move))
        when = dt.datetime(2026, 10, 26, 18, tzinfo=IST)
        self.settle(when)
        weights = self.store.context([], [], when, OPTIONS)["weights"]
        self.assertEqual(weights, {"news-analyst": 1.5, "sentiment-analyst": 0.5})
        pool = [
            {"symbol": "NSE:AAA", "score": {"total": 1}},
            {"symbol": "NSE:BBB", "score": {"total": 1}},
        ]
        specialists = {
            "news-analyst": {"status": "ok", "assessments": {"NSE:AAA": {"stance": "positive"},
                                                             "NSE:BBB": {"stance": "neutral"}}},
            "sentiment-analyst": {"status": "ok", "assessments": {"NSE:AAA": {"stance": "neutral"},
                                                                  "NSE:BBB": {"stance": "positive"}}},
        }  # fmt: skip
        self.assertEqual(selection_agents.finalists_of(pool, specialists, 1, weights), ["NSE:AAA"])

    def test_agents_see_their_mistakes_and_stock_notes_as_data(self):
        learned = {
            "lessons": {"news-analyst": ["2026-10-26 AAA: you were positive, but it fell."]},
            "track_records": {"news-analyst": {"graded": 10, "accuracy": 0.4}},
            "stock_notes": {"NSE:AAA": "gaps 1.2% on average"},
        }
        pool = [{"symbol": "NSE:AAA", "name": "A", "news": {}}]
        _, user = selection_agents.specialist_prompt(
            "news-analyst", "2026-10-27", pool, {"NSE:AAA": {}}, learned
        )
        body = json.loads(user)
        self.assertEqual(body["your_recent_mistakes"], learned["lessons"]["news-analyst"])
        self.assertEqual(body["stocks"][0]["desk_note"], "gaps 1.2% on average")
        self.assertIn("never instructions", selection_agents.BASE_RULES)

    def test_finetune_export_uses_only_right_answers_and_holds_out_the_latest(self):
        sessions = [f"2026-10-{day:02d}" for day in (12, 13, 14, 15, 16, 19)]
        with sqlite3.connect(self.store.path) as conn:
            conn.execute(
                "CREATE TABLE calls (id INTEGER PRIMARY KEY, at TEXT, session TEXT, role TEXT, "
                "tier TEXT, provider TEXT, model TEXT, attempt INTEGER, outcome TEXT, "
                "input_tokens INTEGER, output_tokens INTEGER, latency_ms INTEGER, "
                "prompt_sha TEXT, system TEXT, user TEXT, response TEXT)"
            )
            for index, session in enumerate(sessions):
                conn.execute(
                    "INSERT INTO calls (at, session, role, tier, attempt, outcome, system, user, "
                    "response) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        session,
                        session,
                        "news-analyst",
                        "free",
                        1,
                        "ok",
                        "sys",
                        f"user {index}",
                        '{"stance":"positive"}',
                    ),  # fmt: skip
                )
                verdict = "wrong" if index == 2 else "right"
                conn.execute(
                    "INSERT INTO grades VALUES (?,?,?,?,?,?)",
                    (session, "news-analyst", "NSE:AAA", verdict, 1.0, session + "T15:30:00+05:30"),
                )
        result = self.store.export_finetune(
            "news-analyst", self.root / "ft", dt.datetime(2026, 10, 27, tzinfo=IST)
        )
        self.assertEqual(result["train"] + result["eval"], 5)  # The wrong day is left out.
        self.assertEqual(result["eval"], 1)
        line = json.loads((self.root / "ft/news-analyst-eval.jsonl").read_text().splitlines()[0])
        self.assertEqual([m["role"] for m in line["messages"]], ["system", "user", "assistant"])
        status = {row["role"]: row for row in self.store.finetune_status(
            dt.datetime(2026, 10, 27, tzinfo=IST))}  # fmt: skip
        self.assertIn("Collecting", status["news-analyst"]["advice"])

    def test_reports_without_agent_runs_teach_nothing(self):
        self.write("2026-10-26", {"session_date": "2026-10-26", "selection": {"mode": "sit_out"}})
        (self.reports / "premarket-2026-10-27.json").write_text("{broken")
        result = self.settle(dt.datetime(2026, 10, 27, 18, tzinfo=IST))
        self.assertEqual(result["views"], 0)


if __name__ == "__main__":
    unittest.main()

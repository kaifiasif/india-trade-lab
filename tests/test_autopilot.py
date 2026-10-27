"""Paper autopilot: agent-approved calls are recorded in the virtual book, under every guard."""

import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from decision_pipeline import DailyCoordinator
from test_agent_runtime import FixtureReviewer
from test_decision_pipeline import setup

import autopilot
import paper_book


def book_of(coordinator):
    with sqlite3.connect(coordinator.path("book")) as conn:
        return json.loads(conn.execute("SELECT data FROM book").fetchone()[0])


def picks(coordinator, now, symbols):
    folder = coordinator.path("reports_dir")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"premarket-{now.date()}.json").write_text(
        json.dumps({"session_date": str(now.date()), "watching": symbols})
    )


def enabled(coordinator, require_pick=True):
    coordinator.config["autopilot"] = {"enabled": True, "require_premarket_pick": require_pick}
    return coordinator


class AutopilotTests(unittest.TestCase):
    def test_an_approved_judge_pick_is_recorded_with_its_stop_and_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            coordinator, now = setup(Path(temporary))
            enabled(coordinator)
            picks(coordinator, now, ["NSE:TEST"])
            report = coordinator.run_once()
            outcome = autopilot.apply(coordinator, report, now)
            self.assertEqual([item["side"] for item in outcome["recorded"]], ["buy"], outcome)
            book = book_of(coordinator)
            position = book["positions"]["NSE:TEST"]
            ticket = report["calls"][0]["proposal"]
            self.assertEqual(position["qty"], ticket["qty"])
            self.assertEqual(position["stop_inr"], ticket["stop_inr"])
            self.assertEqual(position["research_meta"]["execution_kind"], "paper_autopilot")
            self.assertEqual(book["mode"], "paper_manual")

    def test_entries_wait_for_the_judge_and_nothing_happens_when_off(self):
        with tempfile.TemporaryDirectory() as temporary:
            coordinator, now = setup(Path(temporary))
            report = coordinator.run_once()
            self.assertFalse(autopilot.apply(coordinator, report, now)["enabled"])
            enabled(coordinator)
            missing = autopilot.apply(coordinator, report, now)
            self.assertIn("no pre-market report", missing["skipped"][0]["reason"])
            picks(coordinator, now, ["NSE:OTHER"])
            other = autopilot.apply(coordinator, report, now)
            self.assertIn("not one of today's", other["skipped"][0]["reason"])
            self.assertEqual(book_of(coordinator)["events"], [])

    def test_a_changed_book_or_an_archived_result_is_never_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            coordinator, now = setup(Path(temporary))
            enabled(coordinator, require_pick=False)
            report = coordinator.run_once()
            archived = coordinator.run_once()
            self.assertEqual(autopilot.apply(coordinator, archived, now)["recorded"], [])
            state = book_of(coordinator)
            state["paused"] = True
            paper_book.seal_state(state)
            with sqlite3.connect(coordinator.path("book")) as conn:
                conn.execute("UPDATE book SET data=? WHERE id=1", (json.dumps(state),))
            outcome = autopilot.apply(coordinator, report, now)
            self.assertIn("Book changed", outcome["skipped"][0]["reason"])
            self.assertEqual(book_of(coordinator)["events"], [])

    def test_the_position_is_squared_off_automatically_at_flat_by(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            coordinator, now = setup(directory)
            enabled(coordinator, require_pick=False)
            autopilot.apply(coordinator, coordinator.run_once(), now)
            later = now.replace(hour=15, minute=16)
            quote = {
                "as_of": later.isoformat(),
                "bid_inr": "102.50",
                "ask_inr": "102.52",
                "source": "OFFLINE_TEST_QUOTE",
            }
            (directory / "quotes.json").write_text(json.dumps({"NSE:TEST": quote}))
            closing = enabled(
                DailyCoordinator(
                    directory / "pipeline.json", reviewer=FixtureReviewer(), now=lambda: later
                ),
                require_pick=False,
            )
            report = closing.run_once(allow_entries=False)
            outcome = autopilot.apply(closing, report, later)
            self.assertEqual(outcome["recorded"][0]["side"], "sell", outcome)
            self.assertEqual(outcome["recorded"][0]["reason"], "square_off")
            book = book_of(closing)
            self.assertEqual(book["positions"], {})
            self.assertEqual([event["side"] for event in book["events"]], ["buy", "sell"])
            self.assertIsInstance(
                dt.date.fromisoformat(next(iter(book["realized_by_day"]))), dt.date
            )


if __name__ == "__main__":
    unittest.main()

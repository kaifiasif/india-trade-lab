"""Exercise frozen proposals, cost-aware sizing, model vetoes and goal-independent risk."""

import csv
import datetime as dt
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from decision_pipeline import DEFAULT_CONFIG, DailyCoordinator, DecisionStore, goal_report
from history import HistoryStore
from test_agent_runtime import FixtureReviewer
from test_guardrails import forward_evidence
from test_history import IST, fixtures
from test_watchlist import master

import paper_book


def prove(directory: Path, now: dt.datetime, eligible=("orb-v1", "vwap-pullback-v1")) -> None:
    """Offline stand-in for a tournament scorecard, so entry tests exercise the gates."""
    (directory / "strategy-scorecard.json").write_text(
        json.dumps(
            {
                "as_of": now.isoformat(),
                "strategies": {name: {"eligible": True} for name in eligible},
                "notice": "OFFLINE TEST SCORECARD",
            }
        )
    )


def setup(directory: Path):
    bars, sessions, dates = fixtures(directory)
    today = dates[-1] + dt.timedelta(days=1)
    now = dt.datetime.combine(today, dt.time(9, 35), tzinfo=IST)
    history = HistoryStore(directory / "history.sqlite")
    history.ingest(bars, sessions, "NSE:TEST", "broker_export", now)
    manifest = json.loads(sessions.read_text())
    manifest["sessions"][str(today)] = {
        "open": "09:15",
        "close": "15:30",
        "entry_cutoff": "14:30",
        "flat_by": "15:15",
    }
    sessions.write_text(json.dumps(manifest))
    # The fixture series only rises (RSI 100), so the daily filters are tested separately.
    config = {**DEFAULT_CONFIG, "strategy": {**DEFAULT_CONFIG["strategy"], "filters": False}}
    config_path = directory / "pipeline.json"
    config_path.write_text(json.dumps(config))
    (directory / "universe.json").write_text(json.dumps(master(now)))
    with (directory / "current-bars.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("symbol", "timestamp", "open", "high", "low", "close", "volume", "source"))
        for index in range(4):
            at = dt.datetime.combine(today, dt.time(9, 15), tzinfo=IST) + dt.timedelta(
                minutes=5 * index
            )
            writer.writerow(
                (
                    "NSE:TEST",
                    at.isoformat(),
                    100,
                    103 if index == 3 else 101,
                    99,
                    102 if index == 3 else 100,
                    100000,
                    "OFFLINE_TEST_PROVIDER",
                )
            )
    quote = {
        "as_of": now.isoformat(),
        "bid_inr": "102",
        "ask_inr": "102.02",
        "source": "OFFLINE_TEST_QUOTE",
    }
    (directory / "quotes.json").write_text(json.dumps({"NSE:TEST": quote}))
    evidence = forward_evidence(now.isoformat())
    evidence.update(
        symbol="NSE:TEST", quote_source=quote["source"], bid_inr="102", ask_inr="102.02"
    )
    (directory / "pretrade-evidence.json").write_text(json.dumps({"NSE:TEST": evidence}))
    research = [
        {
            "id": "fixture",
            "source": "OFFLINE_TEST_ONLY",
            "observed_at": now.isoformat(),
            "published_at": None,
            "facts": "Offline unit test inputs; not real market evidence",
        }
    ]
    (directory / "research-evidence.json").write_text(json.dumps({"NSE:TEST": research}))
    book = paper_book.create("100000", "NSE:TEST", "250", "750", "15000")
    with sqlite3.connect(directory / "paper.sqlite") as conn:
        conn.execute("CREATE TABLE book (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO book VALUES (1,?)", (json.dumps(book),))
    prove(directory, now)
    calm_market(directory, now)
    return DailyCoordinator(config_path, reviewer=FixtureReviewer(), now=lambda: now), now


def calm_market(directory: Path, at: dt.datetime) -> None:
    """What the session worker writes each tick: India VIX and the Nifty read, nothing blocking."""
    (directory / "market-guard.json").write_text(
        json.dumps({"at": at.isoformat(), "india_vix": 13.2, "nifty_move_pct": 0.4, "blocks": []})
    )


class PipelineTests(unittest.TestCase):
    def test_reviewed_call_is_a_proposal_and_never_mutates_the_book(self):
        with tempfile.TemporaryDirectory() as temporary:
            coordinator, now = setup(Path(temporary))
            report = coordinator.run_once()
            self.assertEqual(report["status"], "RESEARCH_PROPOSALS", report)
            call = report["calls"][0]
            self.assertEqual(call["decision"], "BUY_PAPER_PROPOSAL", call)
            self.assertEqual(call["agent_review"]["review"]["status"], "REVIEW_COMPLETE")
            self.assertFalse(call["paper_recorded"])
            self.assertFalse(call["real_orders_allowed"])
            with sqlite3.connect(coordinator.path("book")) as conn:
                self.assertEqual(
                    json.loads(conn.execute("SELECT data FROM book").fetchone()[0])["events"], []
                )
            cached = coordinator.run_once()
            self.assertTrue(cached["cached"])
            self.assertEqual(cached["status"], "ARCHIVED_RESULT")
            self.assertEqual(cached["calls"][0]["decision"], "DATA_BLOCK")
            self.assertFalse(report["goal"]["affects_sizing"])
            self.assertEqual(report["goal"]["daily_target_inr"], "80000.00")

    def test_profit_goal_never_changes_position_size_and_risk_veto_cannot_be_outvoted(self):
        with tempfile.TemporaryDirectory() as temporary:
            coordinator, _ = setup(Path(temporary))
            first = coordinator.run_once()["calls"][0]["proposal"]["qty"]
            coordinator.config["daily_profit_goal_inr"] = "80000000"
            second = coordinator.run_once()["calls"][0]["proposal"]["qty"]
            self.assertEqual(first, second)
            coordinator.config["daily_profit_goal_inr"] = "90000"
            coordinator.reviewer = FixtureReviewer("india-risk")
            self.assertEqual(coordinator.run_once()["calls"][0]["decision"], "DATA_BLOCK")

    def test_stale_quotes_changed_book_and_missing_model_prevent_a_buy_call(self):
        for mutation in ("stale", "missing-model", "changed-book"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                coordinator, now = setup(Path(temporary))
                if mutation == "stale":
                    quotes = json.loads(coordinator.path("quotes").read_text())
                    quotes["NSE:TEST"]["as_of"] = (now - dt.timedelta(minutes=3)).isoformat()
                    coordinator.path("quotes").write_text(json.dumps(quotes))
                elif mutation == "missing-model":
                    from agent_runtime import OfflineReviewer

                    coordinator.reviewer = OfflineReviewer()
                else:
                    original = coordinator.reviewer.review

                    def change_book(
                        role, context, reports, original=original, coordinator=coordinator
                    ):
                        result = original(role, context, reports)
                        if role == "india-reviewer":
                            with sqlite3.connect(coordinator.path("book")) as conn:
                                book = json.loads(
                                    conn.execute("SELECT data FROM book").fetchone()[0]
                                )
                                book["paused"] = True
                                paper_book.seal_state(book)
                                conn.execute("UPDATE book SET data=?", (json.dumps(book),))
                        return result

                    coordinator.reviewer.review = change_book
                self.assertEqual(coordinator.run_once()["calls"][0]["decision"], "DATA_BLOCK")

    def test_exit_proposals_survive_missing_entry_evidence_and_universe(self):
        with tempfile.TemporaryDirectory() as temporary:
            coordinator, now = setup(Path(temporary))
            with sqlite3.connect(coordinator.path("book")) as conn:
                book = json.loads(conn.execute("SELECT data FROM book").fetchone()[0])
                evidence = json.loads(coordinator.path("pretrade_evidence").read_text())["NSE:TEST"]
                book = paper_book.fill(
                    book,
                    "buy",
                    "fixture",
                    "NSE:TEST",
                    "102.02",
                    now.isoformat(),
                    "OFFLINE_TEST_QUOTE",
                    "10",
                    "5",
                    10,
                    "99",
                    "10",
                    now=now,
                    evidence=evidence,
                    target="110",
                )
                conn.execute("UPDATE book SET data=?", (json.dumps(book),))
            coordinator.path("universe").unlink()
            coordinator.path("pretrade_evidence").unlink()
            quotes = json.loads(coordinator.path("quotes").read_text())
            quotes["NSE:TEST"].update(bid_inr="98", ask_inr="98.02")
            coordinator.path("quotes").write_text(json.dumps(quotes))
            result = coordinator.run_once()
            self.assertEqual(result["calls"][0]["decision"], "SELL_PAPER_PROPOSAL", result)
            self.assertEqual(result["calls"][0]["proposal"]["qty"], 10)

    def test_missing_inputs_single_writer_and_model_budget_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = directory / "pipeline.json"
            config.write_text(json.dumps(DEFAULT_CONFIG))
            coordinator = DailyCoordinator(config)
            self.assertEqual(coordinator.run_once()["status"], "DATA_BLOCK")
            one = DecisionStore(directory / "budget.sqlite")
            two = DecisionStore(one.path)
            self.assertTrue(one.acquire("one"))
            self.assertFalse(two.acquire("two"))
            one.release("one")
            self.assertTrue(two.acquire("two"))
            self.assertTrue(one.reserve_model_calls("2026-10-22", 6, 6))
            self.assertFalse(two.reserve_model_calls("2026-10-22", 1, 6))
            self.assertTrue(two.reserve_model_calls("2026-10-23", 6, 6))
            self.assertEqual(
                goal_report(None, "80000", dt.datetime.now(IST))["shortfall_inr"], "80000"
            )

    def test_shortlisted_candidates_are_reviewed_concurrently_in_ranked_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            coordinator, now = setup(Path(temporary))
            ranked = ["NSE:AAA", "NSE:BBB", "NSE:CCC"]
            # Each fake review waits until all three overlap. Sequential reviews would
            # break the barrier, which mirrors expiring the shared 120-second window.
            barrier = threading.Barrier(len(ranked), timeout=5)

            def evaluate(symbol, *_):
                try:
                    barrier.wait()
                    decision = "WAIT"
                except threading.BrokenBarrierError:
                    decision = "DATA_BLOCK"
                return {"symbol": symbol, "decision": decision, "reasons": []}

            shortlist = {"candidates": [{"symbol": symbol} for symbol in ranked]}
            with (
                patch("decision_pipeline.build_watchlist", return_value=shortlist),
                patch.object(coordinator, "evaluate", side_effect=evaluate),
            ):
                report = coordinator.run_once()
            self.assertEqual([call["symbol"] for call in report["calls"]], ranked)
            self.assertEqual({call["decision"] for call in report["calls"]}, {"WAIT"})


if __name__ == "__main__":
    unittest.main()

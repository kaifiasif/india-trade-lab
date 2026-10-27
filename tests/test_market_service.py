"""Research scheduling, entry halt and durable collector backoff require no network calls."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from market_service import MarketService
from observatory import research_state
from test_decision_pipeline import setup


class MarketServiceTests(unittest.TestCase):
    def test_routing_halt_and_durable_crypto_failure_backoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "pipeline.json"
            calendar = {
                "timezone": "Asia/Kolkata",
                "source": "OFFLINE_TEST_CALENDAR",
                "sessions": {"2026-10-22": {"open": "09:15", "close": "15:30"}},
            }
            (root / "sessions.json").write_text(json.dumps(calendar))
            gates, attempts = [], []

            def review(allow_entries):
                gates.append(allow_entries)
                return {"status": "DATA_BLOCK", "run_id": "offline-test"}

            def unavailable(symbol, days):
                attempts.append(symbol)
                raise ValueError("offline")

            coordinator = SimpleNamespace(path=lambda name: root / "sessions.json", run_once=review)
            now = dt.datetime.fromisoformat("2026-10-22T10:00:00+05:30")
            worker = MarketService(
                config, ("BTCUSDT",), coordinator=coordinator, now=lambda: now, collect=unavailable
            )
            result = worker.tick()
            self.assertTrue(gates[-1])
            self.assertEqual(result["crypto"][0]["status"], "DATA_BLOCK")
            (root / "HALT_ENTRIES").touch()
            restarted = MarketService(
                config, ("BTCUSDT",), coordinator=coordinator, now=lambda: now, collect=unavailable
            )
            restarted.tick()
            self.assertFalse(gates[-1])
            self.assertEqual(attempts, ["BTCUSDT"])
            now += dt.timedelta(hours=9)
            restarted.tick()
            self.assertFalse(gates[-1])
            self.assertEqual(len(attempts), 2)
            self.assertFalse(research_state(root)["service"]["markets"][1]["orders_allowed"])

    def test_dashboard_projects_real_audit_without_claiming_fills(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            coordinator, _ = setup(root)
            coordinator.run_once()
            projected = research_state(root)
            self.assertEqual(projected["report"]["status"], "RESEARCH_PROPOSALS")
            self.assertTrue(projected["report"]["archived"])
            self.assertFalse(projected["report"]["paper_recorded"])
            self.assertEqual(
                len([e for e in projected["events"] if e["kind"] == "agent_completed"]), 6
            )


if __name__ == "__main__":
    unittest.main()


class PrepareTests(unittest.TestCase):
    def test_preparation_failures_are_reported_and_never_stop_the_run(self):
        """A failed collector must leave the research run to refuse the entry itself."""
        import datetime as dt
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from market_service import MarketService
        from test_operations import build_project

        IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
        with tempfile.TemporaryDirectory() as temporary:
            now = dt.datetime(2026, 10, 26, 9, 36, tzinfo=IST)
            config = build_project(Path(temporary), now)
            worker = MarketService(config, now=lambda: now, prepare=True)
            with (
                patch("evidence.collect", side_effect=ValueError("news unavailable")),
                patch("pretrade.build", side_effect=ValueError("no attestation")),
            ):
                prepared = worker.prepare_inputs(now)
            self.assertEqual(prepared["evidence"]["status"], "DATA_BLOCK")
            self.assertEqual(prepared["pretrade"]["status"], "DATA_BLOCK")
            self.assertIn("news unavailable", prepared["evidence"]["reason"])

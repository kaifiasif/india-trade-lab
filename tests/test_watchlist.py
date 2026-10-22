"""Daily selection uses declared inputs, never invented stock picks or future sessions."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from history import HistoryStore
from observatory import Observatory
from test_history import IST, fixtures
from watchlist import build_watchlist


def master(cutoff: dt.datetime) -> dict:
    return {
        "source": "OFFLINE_TEST_MASTER",
        "as_of": cutoff.isoformat(),
        "instruments": [
            {"symbol": "NSE:TEST", "isin": "INE000A01001", "segment": "EQ", "active": True}
        ],
    }


class WatchlistTests(unittest.TestCase):
    def test_complete_history_shortlists_but_does_not_authorize_a_buy(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bars, sessions, dates = fixtures(directory)
            cutoff = dt.datetime.combine(dates[-1] + dt.timedelta(days=1), dt.time(9), tzinfo=IST)
            store = HistoryStore(directory / "history.sqlite")
            store.ingest(bars, sessions, "NSE:TEST", "broker_export", cutoff)
            result = build_watchlist(store, master(cutoff), cutoff)
            self.assertEqual(result["candidates"][0]["symbol"], "NSE:TEST")
            self.assertEqual(result["candidates"][0]["status"], "WAIT_FOR_SETUP")
            self.assertEqual(result["candidates"][0]["history_sessions"], 50)
            self.assertEqual(
                build_watchlist(store, master(cutoff), cutoff, min_turnover_inr=1e15)["candidates"],
                [],
            )
            before = dt.datetime.combine(dates[1], dt.time(16), tzinfo=IST)
            self.assertEqual(build_watchlist(store, master(before), before)["candidates"], [])
            inactive = master(cutoff)
            inactive["instruments"][0]["active"] = False
            self.assertEqual(build_watchlist(store, inactive, cutoff)["candidates"], [])
            stale = cutoff + dt.timedelta(days=8)
            self.assertEqual(build_watchlist(store, master(stale), stale)["candidates"], [])

    def test_missing_future_duplicate_and_stale_universe_inputs_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = HistoryStore(Path(temporary) / "history.sqlite")
            cutoff = dt.datetime(2026, 10, 22, tzinfo=IST)
            for value in (
                {},
                {**master(cutoff), "as_of": (cutoff + dt.timedelta(days=1)).isoformat()},
                {**master(cutoff), "as_of": (cutoff - dt.timedelta(days=31)).isoformat()},
                {**master(cutoff), "instruments": master(cutoff)["instruments"] * 2},
            ):
                with self.assertRaises(ValueError):
                    build_watchlist(store, value, cutoff)
            self.assertEqual(build_watchlist(store, master(cutoff), cutoff)["candidates"], [])

    def test_dashboard_requires_inputs_and_persists_a_research_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Observatory(Path(temporary))
            self.assertEqual(app.state()["watchlist"]["mode"], "data_required")
            # Empty research universes exercise storage without asserting any market readiness.
            now = dt.datetime.now(IST)
            (Path(temporary) / "universe.json").write_text(
                json.dumps(
                    {"source": "OFFLINE_TEST_MASTER", "as_of": now.isoformat(), "instruments": []}
                )
            )
            self.assertEqual(app.state()["watchlist"]["mode"], "research_only")
            self.assertTrue((Path(temporary) / "selection.sqlite").exists())
            self.assertEqual(app.state()["calls"], [])


if __name__ == "__main__":
    unittest.main()

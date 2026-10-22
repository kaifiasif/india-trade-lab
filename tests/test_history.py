"""Use generated offline fixtures to test coverage, provenance and point-in-time windows."""

import csv
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from history import HistoryStore

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "skills/day-trader-india/assets"


def fixtures(
    directory: Path, count: int = 50, omit: set[int] | None = None
) -> tuple[Path, Path, list]:
    """Generate complete five-minute sessions; provider labels are test inputs, not market data."""
    dates = []
    date = dt.date(2026, 1, 1)
    while len(dates) < count:
        if date.weekday() < 5:
            dates.append(date)
        date += dt.timedelta(days=1)
    manifest = {"timezone": "Asia/Kolkata", "source": "OFFLINE_TEST_CALENDAR", "sessions": {}}
    bars = directory / "bars.csv"
    with bars.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("symbol", "timestamp", "open", "high", "low", "close", "volume", "source"))
        for index, day in enumerate(dates):
            manifest["sessions"][str(day)] = {
                "open": "09:15",
                "close": "15:30",
                "entry_cutoff": "14:30",
                "flat_by": "15:15",
            }
            if index in (omit or set()):
                continue
            for number in range(75):
                timestamp = dt.datetime.combine(day, dt.time(9, 15), tzinfo=IST) + dt.timedelta(
                    minutes=5 * number
                )
                writer.writerow(
                    (
                        "NSE:TEST",
                        timestamp.isoformat(),
                        100 + index,
                        103 + index,
                        99 + index,
                        102 + index,
                        100000,
                        "OFFLINE_TEST_PROVIDER",
                    )
                )
    sessions = directory / "sessions.json"
    sessions.write_text(json.dumps(manifest))
    return bars, sessions, dates


class HistoryTests(unittest.TestCase):
    def test_fifty_prior_sessions_and_features_do_not_include_future_dates(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bars, sessions, dates = fixtures(directory)
            store = HistoryStore(directory / "history.sqlite")
            cutoff = dt.datetime.combine(dates[-1], dt.time(16), tzinfo=IST)
            result = store.ingest(bars, sessions, "NSE:TEST", "broker_export", cutoff)
            self.assertEqual(len(result["accepted"]), 50)
            coverage = store.coverage("NSE:TEST", cutoff)
            self.assertTrue(coverage["history_ready"])
            self.assertEqual(coverage["features"]["sma50"], 126.5)
            prior = store.coverage(
                "NSE:TEST", dt.datetime.combine(dates[1], dt.time(16), tzinfo=IST)
            )
            self.assertEqual(prior["completed_sessions"], 2)
            self.assertFalse(prior["history_ready"])
            self.assertIsNone(prior["features"]["sma50"])
            store.ingest(bars, sessions, "NSE:TEST", "broker_export", cutoff)
            self.assertEqual(store.coverage("NSE:TEST", cutoff)["completed_sessions"], 50)
            self.assertEqual(store.symbols(), ["NSE:TEST"])
            with self.assertRaises(ValueError):
                store.coverage("NSE:TEST", cutoff.replace(tzinfo=None))

    def test_synthetic_sessions_never_satisfy_the_market_history_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = HistoryStore(Path(temporary) / "history.sqlite")
            cutoff = dt.datetime(2026, 10, 20, tzinfo=IST)
            store.ingest(
                ASSETS / "synthetic-bars.csv",
                ASSETS / "synthetic-sessions.json",
                "NSE:DEMO",
                "synthetic",
                cutoff,
            )
            coverage = store.coverage("NSE:DEMO", cutoff)
            self.assertEqual(coverage["synthetic_sessions"], 1)
            self.assertEqual(coverage["completed_sessions"], 0)
            self.assertFalse(coverage["history_ready"])
            with self.assertRaisesRegex(ValueError, "Synthetic candles"):
                store.ingest(
                    ASSETS / "synthetic-bars.csv",
                    ASSETS / "synthetic-sessions.json",
                    "NSE:DEMO",
                    "broker_export",
                    cutoff,
                )

    def test_completely_missing_declared_session_blocks_even_with_fifty_others(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bars, sessions, dates = fixtures(directory, count=51, omit={30})
            store = HistoryStore(directory / "history.sqlite")
            cutoff = dt.datetime.combine(dates[-1], dt.time(16), tzinfo=IST)
            result = store.ingest(bars, sessions, "NSE:TEST", "broker_export", cutoff)
            self.assertEqual(len(result["accepted"]), 50)
            self.assertEqual(len(result["rejected"]), 1)
            coverage = store.coverage("NSE:TEST", cutoff)
            self.assertFalse(coverage["history_ready"])
            self.assertEqual(coverage["missing_declared_sessions"], [str(dates[30])])

    def test_conflicting_revision_is_refused_and_unfinished_sessions_are_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bars, sessions, dates = fixtures(directory, count=2)
            store = HistoryStore(directory / "history.sqlite")
            cutoff = dt.datetime.combine(dates[-1], dt.time(10), tzinfo=IST)
            result = store.ingest(bars, sessions, "NSE:TEST", "broker_export", cutoff)
            self.assertEqual(len(result["accepted"]), 1)
            self.assertEqual(len(result["rejected"]), 1)
            full = dt.datetime.combine(dates[-1], dt.time(16), tzinfo=IST)
            store.ingest(bars, sessions, "NSE:TEST", "broker_export", full)
            bars.write_text(bars.read_text().replace(",100000,", ",100001,"))
            with self.assertRaisesRegex(ValueError, "Conflicting historical revision"):
                store.ingest(bars, sessions, "NSE:TEST", "broker_export", full)
            self.assertEqual(store.coverage("NSE:TEST", full)["completed_sessions"], 2)


if __name__ == "__main__":
    unittest.main()

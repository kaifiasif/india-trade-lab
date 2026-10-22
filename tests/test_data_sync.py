"""Data collectors retain exports, bound batches and remove failed symbols from current feeds."""

import csv
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from data_sync import refresh_current, sync_history
from test_decision_pipeline import setup
from test_history import IST, fixtures


class DataSyncTests(unittest.TestCase):
    def test_historical_batches_and_missing_provider_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bars, _, dates = fixtures(root)
            with bars.open() as handle:
                rows = list(csv.DictReader(handle))
            config = {
                "universe": "universe.json",
                "sessions": "sessions.json",
                "history_db": "history.sqlite",
            }
            path = root / "pipeline.json"
            path.write_text(json.dumps(config))
            universe = {
                "instruments": [
                    {"symbol": "NSE:TEST", "data_provider": "kite", "instrument_id": "1"}
                ]
            }
            (root / "universe.json").write_text(json.dumps(universe))
            requests = []

            def fetch(provider, instrument, first, last):
                requests.append((first, last))
                return {
                    "status": "success",
                    "data": {
                        "candles": [
                            [
                                row["timestamp"],
                                *[
                                    float(row[key])
                                    for key in ("open", "high", "low", "close", "volume")
                                ],
                            ]
                            for row in rows
                            if first <= dt.datetime.fromisoformat(row["timestamp"]).date() <= last
                        ]
                    },
                }

            now = dt.datetime.combine(dates[-1], dt.time(16), IST)
            result = sync_history(path, days=90, now=now, fetch=fetch)
            self.assertEqual(result["results"][0]["status"], "IMPORTED", result)
            self.assertTrue(result["results"][0]["coverage"]["history_ready"])
            self.assertTrue(all((last - first).days <= 6 for first, last in requests))
            self.assertTrue(list((root / "provider-exports").glob("*.csv")))
            universe["instruments"][0].pop("data_provider")
            (root / "universe.json").write_text(json.dumps(universe))
            self.assertEqual(
                sync_history(path, now=now, fetch=fetch)["results"][0]["status"], "DATA_BLOCK"
            )

    def test_failed_refresh_removes_old_quote_and_never_carries_it_forward(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            coordinator, now = setup(root)
            universe = json.loads(coordinator.path("universe").read_text())
            universe["instruments"][0].update(data_provider="kite", instrument_id="1")
            coordinator.path("universe").write_text(json.dumps(universe))
            with coordinator.path("bars").open() as handle:
                current = list(csv.DictReader(handle))
            current_quotes = json.loads(coordinator.path("quotes").read_text())
            payload = {
                "status": "success",
                "data": {
                    "candles": [
                        [
                            row["timestamp"],
                            *[row[key] for key in ("open", "high", "low", "close", "volume")],
                        ]
                        for row in current
                    ]
                },
            }
            refreshed = refresh_current(
                coordinator.config_path,
                now,
                fetch=lambda *args: payload,
                quote_fetch=lambda *args: current_quotes["NSE:TEST"],
            )
            self.assertEqual(refreshed["refreshed"], ["NSE:TEST"])
            self.assertEqual(coordinator.run_once()["calls"][0]["decision"], "BUY_PAPER_PROPOSAL")

            def unavailable(*args):
                raise ValueError("offline test failure")

            result = refresh_current(coordinator.config_path, now, quote_fetch=unavailable)
            self.assertEqual(result["blocked"], ["NSE:TEST"])
            self.assertEqual(json.loads(coordinator.path("quotes").read_text()), {})
            self.assertEqual(coordinator.run_once()["status"], "DATA_BLOCK")


if __name__ == "__main__":
    unittest.main()

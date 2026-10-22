"""Use made-up UTC candles and mocked public endpoints; never contact an exchange in CI."""

import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from crypto_data import DAY_MS, collect, get_public, normalized_candles, save_snapshot

NOW = dt.datetime(2026, 10, 22, 12, tzinfo=dt.timezone.utc)


def candles(days=50):
    midnight = NOW.replace(hour=0)
    first = int((midnight - dt.timedelta(days=days)).timestamp() * 1000)
    return [
        [
            first + i * DAY_MS,
            "100.1",
            "102.1",
            "99.1",
            "101.1",
            "1000.1",
            first + (i + 1) * DAY_MS - 1,
        ]
        for i in range(days)
    ]


def fetch(path, params):
    if path.endswith("exchangeInfo"):
        return {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "isSpotTradingAllowed": True,
                    "quoteAsset": "USDT",
                    "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.00001"}],
                }
            ]
        }
    if path.endswith("klines"):
        return candles()
    return {
        "symbol": "BTCUSDT",
        "bidPrice": "101.1",
        "askPrice": "101.2",
        "bidQty": "0.1",
        "askQty": "0.2",
    }


class CryptoDataTests(unittest.TestCase):
    def test_spot_snapshot_keeps_currency_precision_and_cannot_trade(self):
        snapshot = collect("BTCUSDT", 50, NOW, fetch=fetch)
        self.assertEqual(snapshot["history_days"], 50)
        self.assertEqual(snapshot["decision"], "RESEARCH_ONLY")
        self.assertEqual(snapshot["quote_currency"], "USDT")
        self.assertFalse(snapshot["real_orders_allowed"])
        self.assertIn("local receipt", snapshot["quote_timestamp_kind"])
        with tempfile.TemporaryDirectory() as directory:
            save_snapshot(Path(directory) / "crypto.sqlite", snapshot)
            self.assertTrue((Path(directory) / "crypto.sqlite").is_file())

    def test_missing_duplicate_bad_ohlc_and_unfinished_history_are_blocked(self):
        rows = candles()
        for changed in (rows[:-1], rows[:20] + rows[21:], rows[:20] + [rows[19]] + rows[21:]):
            with self.assertRaises(ValueError):
                normalized_candles(changed, NOW, 50)
        bad = copy.deepcopy(rows)
        bad[-1][3] = "200"
        with self.assertRaises(ValueError):
            normalized_candles(bad, NOW, 50)
        unfinished = candles()
        unfinished[-1][6] = int((NOW + dt.timedelta(hours=1)).timestamp() * 1000)
        with self.assertRaises(ValueError):
            normalized_candles(unfinished, NOW, 50)
        with self.assertRaises(ValueError):
            collect("BTCUSDT;anything", 50, NOW, fetch=fetch)
        with self.assertRaises(ValueError):
            get_public("/api/v3/order", {})


if __name__ == "__main__":
    unittest.main()

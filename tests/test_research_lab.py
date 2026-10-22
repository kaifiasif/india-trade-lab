"""Daily research must use completed, available, aligned observations."""

import csv
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from research_lab import features, import_nifty500, load_daily, screen

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
NOW = dt.datetime(2026, 10, 19, 16, tzinfo=IST)


def series():
    dates = [NOW.date() - dt.timedelta(days=offset) for offset in range(90, 0, -1)]
    result = {}
    for symbol, growth in (("NSE:NIFTY50", 0.2), ("NSE:STRONG", 1), ("NSE:WEAK", 0.05)):
        result[symbol] = [
            dict(
                date=str(day),
                open=100 + i * growth,
                high=101 + i * growth,
                low=99 + i * growth,
                close=100 + i * growth,
                volume=1000000,
                close_at=dt.datetime.combine(day, dt.time(15, 30), IST).isoformat(),
                available_at=dt.datetime.combine(day, dt.time(16), IST).isoformat(),
                source="OFFLINE_TEST_PROVIDER",
                price_basis="price_return",
                adjustment="split_adjusted",
            )
            for i, day in enumerate(dates)
        ]
    return result


def universe():
    return {
        "source": "OFFLINE_TEST_MASTER",
        "as_of": NOW.isoformat(),
        "instruments": [
            {"symbol": symbol, "isin": "INE000000001", "active": True, "segment": "EQ"}
            for symbol in ("NSE:STRONG", "NSE:WEAK")
        ],
    }


class ResearchLabTests(unittest.TestCase):
    def test_relative_strength_and_indicators_are_research_only(self):
        report = screen(series(), universe(), "NSE:NIFTY50", NOW)
        self.assertEqual(report["candidates"][0]["symbol"], "NSE:STRONG")
        self.assertGreater(report["candidates"][0]["rs60_pp"], 0)
        self.assertEqual(report["candidates"][0]["status"], "WAIT_FOR_SETUP")
        values = features(series()["NSE:STRONG"])
        self.assertEqual(values["rsi14"], 100)
        self.assertGreater(values["sma20"], values["sma50"])
        self.assertGreater(values["atr14"], 0)
        self.assertTrue(0 <= values["bollinger_width_pct"])

    def test_missing_benchmark_misaligned_sessions_and_basis_fail(self):
        with self.assertRaises(ValueError):
            screen(series(), universe(), "NSE:MISSING", NOW)
        for change in ("date", "price_basis"):
            data = series()
            data["NSE:STRONG"][-1][change] = "2000-01-01" if change == "date" else "total_return"
            result = screen(data, universe(), "NSE:NIFTY50", NOW)
            self.assertNotIn("NSE:STRONG", [r["symbol"] for r in result["candidates"]])
            self.assertTrue(result["blocked"])

    def test_loader_filters_future_availability_and_rejects_unfinished_bar(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "daily.csv"
            data = series()["NSE:STRONG"]
            rows = [{"symbol": "NSE:STRONG", **row} for row in data]
            rows[-1]["available_at"] = (NOW + dt.timedelta(days=1)).isoformat()

            def write():
                with path.open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)

            write()
            loaded = load_daily(path, NOW)
            self.assertEqual(len(loaded["NSE:STRONG"]), 89)
            rows[-1]["available_at"] = rows[-1]["date"] + "T09:20:00+05:30"
            write()
            with self.assertRaises(ValueError):
                load_daily(path, NOW)
            rows[-1] = dict(rows[-2])
            write()
            with self.assertRaises(ValueError):
                load_daily(path, NOW)

    def test_membership_import_has_no_silent_fallback_or_broker_mapping(self):
        result = import_nifty500(
            "Symbol,Series,ISIN Code,Industry\nDEMO,EQ,INE000000001,Test\n", NOW, "OFFLINE_TEST"
        )
        self.assertEqual(result["instruments"][0]["symbol"], "NSE:DEMO")
        self.assertNotIn("kite_token", result["instruments"][0])
        for text in ("", "Symbol,Series,ISIN Code\nBAD,EQ,xxx\n"):
            with self.assertRaises(ValueError):
                import_nifty500(text, NOW, "OFFLINE_TEST")

    def test_current_membership_cannot_be_used_before_publication(self):
        with self.assertRaises(ValueError):
            screen(series(), universe(), "NSE:NIFTY50", NOW - dt.timedelta(days=1))


if __name__ == "__main__":
    unittest.main()

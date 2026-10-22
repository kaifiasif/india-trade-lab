"""Exchange-local dates, US daylight saving and early closes must route accurately."""

import datetime as dt
import unittest

from market_router import route_all, route_market


class MarketRouterTests(unittest.TestCase):
    def test_dst_and_cross_midnight_ist(self):
        calendar = {
            "timezone": "America/New_York",
            "source": "https://www.nyse.com/markets/hours-calendars",
            "sessions": {
                "2026-10-22": {"open": "09:30", "close": "16:00"},
                "2026-11-03": {"open": "09:30", "close": "16:00"},
            },
        }
        for date, opening, closing in (
            ("2026-10-22", "19:00", "01:30"),
            ("2026-11-03", "20:00", "02:30"),
        ):
            now = dt.datetime.fromisoformat(date + "T21:00:00+05:30")
            result = route_market("us", now, calendar)
            self.assertEqual(result["status"], "OPEN")
            self.assertIn("T" + opening, result["open_ist"])
            self.assertIn("T" + closing, result["close_ist"])
            self.assertEqual(result["capability"], "not_implemented")
            self.assertFalse(result["orders_allowed"])
        # 00:30 IST still belongs to the prior exchange date.
        midnight = dt.datetime.fromisoformat("2026-10-23T00:30:00+05:30")
        self.assertEqual(route_market("us", midnight, calendar)["status"], "OPEN")

    def test_early_close_holiday_unknown_and_exact_close(self):
        calendar = {
            "timezone": "America/New_York",
            "source": "https://www.nyse.com/markets/hours-calendars",
            "sessions": {
                "2026-11-26": None,
                "2026-11-27": {"open": "09:30", "close": "13:00"},
            },
        }
        for day, hour, status in (
            (26, 12, "CLOSED"),
            (27, 12, "OPEN"),
            (27, 13, "CLOSED"),
            (30, 12, "DATA_BLOCK"),
        ):
            now = dt.datetime(2026, 11, day, hour, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
            self.assertEqual(route_market("us", now, calendar)["status"], status)
        result = route_all(dt.datetime(2026, 10, 25, tzinfo=dt.timezone.utc))
        self.assertEqual(
            [r["status"] for r in result["markets"]], ["DATA_BLOCK", "DATA_BLOCK", "OBSERVE"]
        )
        calendar["source"] = "SYNTHETIC_TEST_ONLY"
        self.assertEqual(route_market("us", now, calendar)["status"], "DATA_BLOCK")


if __name__ == "__main__":
    unittest.main()

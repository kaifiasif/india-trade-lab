"""Test provider identity, timestamp provenance and refusal of stale/crossed quotes offline."""

import datetime as dt
import unittest

from quote_data import make_quote_request, normalize_quote


class QuoteDataTests(unittest.TestCase):
    def test_fixed_get_routes_and_credentials(self):
        env = {
            "PAYTM_READ_ACCESS_TOKEN": "private-test",
            "KITE_API_KEY": "test",
            "KITE_ACCESS_TOKEN": "test",
        }
        for provider, host in (("paytm", "developer.paytmmoney.com"), ("kite", "api.kite.trade")):
            request = make_quote_request(provider, "NSE:TCS", "11536", env)
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.host, host)
            self.assertNotIn("private-test", request.full_url)
        for symbol in ("BTCUSDT", "NSE:X/../../orders", "https://other.test"):
            with self.assertRaises(ValueError):
                make_quote_request("paytm", symbol, "1", env)
        with self.assertRaises(ValueError):
            make_quote_request("paytm", "NSE:TCS", "1", {})

    def test_paytm_last_trade_is_not_a_quote_update(self):
        now = dt.datetime(2026, 10, 22, 4, tzinfo=dt.timezone.utc)
        quote = {
            "security_id": 1,
            "tradable": True,
            "found": True,
            "mode": "FULL",
            "last_trade_time": now.timestamp(),
            "depth": {"buy": [{"price": 100}], "sell": [{"price": 100.1}]},
        }
        payload = {"data": [quote]}
        normalized = normalize_quote("paytm", payload, "NSE:TEST", "1", now)
        self.assertEqual(normalized["timestamp_kind"], "last_trade")
        self.assertFalse(normalized["forward_quote_usable"])
        quote["last_update_time"] = now.timestamp()
        self.assertTrue(
            normalize_quote("paytm", payload, "NSE:TEST", "1", now)["forward_quote_usable"]
        )
        quote["security_id"] = 2
        with self.assertRaises(ValueError):
            normalize_quote("paytm", payload, "NSE:TEST", "1", now)

    def test_kite_time_is_ist_and_bad_quotes_are_refused(self):
        now = dt.datetime.fromisoformat("2026-10-22T09:35:00+05:30")
        quote = {
            "timestamp": "2026-10-22 09:35:00",
            "depth": {"buy": [{"price": 100}], "sell": [{"price": 100.1}]},
        }
        payload = {"status": "success", "data": {"NSE:TEST": quote}}
        self.assertTrue(
            normalize_quote("kite", payload, "NSE:TEST", "", now)["forward_quote_usable"]
        )
        for timestamp in ("2026-10-22 09:30:00", "2026-10-22 09:36:00"):
            quote["timestamp"] = timestamp
            with self.assertRaises(ValueError):
                normalize_quote("kite", payload, "NSE:TEST", "", now)
        quote["timestamp"] = "2026-10-22 09:35:00"
        quote["depth"]["buy"][0]["price"] = 101
        with self.assertRaises(ValueError):
            normalize_quote("kite", payload, "NSE:TEST", "", now)


if __name__ == "__main__":
    unittest.main()

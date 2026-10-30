"""Offline financial-state checks with synthetic quotes, not performance tests."""

import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_guardrails import forward_evidence

from paper_book import IST, create, fill


class PaperBookTests(unittest.TestCase):
    def setUp(self):
        self.book = create("100000", "NSE:DEMO,NSE:OTHER", "500", "1000", "25000", True)

    def buy(self, book=None, **changes):
        kw = dict(
            book=self.book if book is None else book,
            side="buy",
            event_id="entry-1",
            symbol="NSE:DEMO",
            price="100",
            as_of="2026-10-19T10:00:00+05:30",
            source="SYNTHETIC FIXTURE",
            fee="10",
            slippage="5",
            qty=100,
            stop="98",
            exit_fee="10",
            target="110",
        )
        kw.update(changes)
        return fill(**kw)

    def sell(self, book, **changes):
        kw = dict(
            book=book,
            side="sell",
            event_id="exit-1",
            symbol="NSE:DEMO",
            price="101",
            as_of="2026-10-19T11:00:00+05:30",
            source="SYNTHETIC FIXTURE",
            fee="10",
            slippage="5",
        )
        kw.update(changes)
        return fill(**kw)

    def test_net_round_trip_and_input_unchanged(self):
        entered = self.buy()
        self.assertEqual(self.book["positions"], {})
        self.assertEqual(entered["cash"], "89985.00")
        result = self.sell(entered)
        self.assertEqual(result["cash"], "100070.00")
        self.assertEqual(result["realized_by_day"]["2026-10-19"], "70.00")
        self.assertEqual(result["positions"], {})
        self.assertEqual(result["mode"], "replay_demo")

    def test_duplicate_no_reentry_or_short(self):
        entered = self.buy()
        for kw in ({"event_id": "entry-1", "symbol": "NSE:OTHER"}, {"event_id": "entry-2"}):
            with self.assertRaises(ValueError):
                self.buy(entered, **kw)
        with self.assertRaises(ValueError):
            self.sell(self.book)

    def test_bounds_and_numeric_rejection(self):
        for kw in (
            {"qty": 0},
            {"qty": 1.2},
            {"qty": -1},
            {"price": "NaN"},
            {"price": "Infinity"},
            {"stop": 101},
            {"qty": 10000},
            {"fee": -1},
            {"slippage": 10000},
            {"symbol": "NSE:UNKNOWN"},
        ):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.buy(**kw)
        with self.assertRaises(ValueError):
            self.buy(create("1000", "NSE:DEMO", 500, 1000, 1000, True), qty=20)

    def test_risk_includes_costs_and_other_open_positions(self):
        b = create("100000", "NSE:DEMO,NSE:OTHER", 500, 500, 25000, True)
        entered = self.buy(b, stop="96")
        with self.assertRaises(ValueError):
            self.buy(entered, event_id="entry-2", symbol="NSE:OTHER")
        with self.assertRaises(ValueError):
            self.buy(fee="400", exit_fee="100")

    def test_realized_losses_block_new_entries_but_not_exit(self):
        entered = self.buy(create("100000", "NSE:DEMO,NSE:OTHER", 500, 500, 25000, True))
        lost = self.sell(entered, price="90")
        self.assertLess(float(lost["realized_by_day"]["2026-10-19"]), -500)
        with self.assertRaises(ValueError):
            self.buy(lost, event_id="entry-2", as_of="2026-10-19T12:00:00+05:30")

    def test_freshness_timezone_and_order(self):
        book = create("100000", "NSE:DEMO", 500, 1000, 25000)
        now = dt.datetime(2026, 10, 19, 10, 0, tzinfo=IST)
        self.buy(book, now=now, evidence=forward_evidence())
        for stamp in (
            "2026-10-19T09:57:59+05:30",
            "2026-10-19T10:00:06+05:30",
            "2026-10-19T10:00:00",
        ):
            with self.assertRaises(ValueError):
                self.buy(book, as_of=stamp, now=now)
        with self.assertRaises(ValueError):
            self.sell(self.buy(), as_of="2026-10-19T09:59:00+05:30")

    def test_exit_reserves_and_prior_day(self):
        b = create("1200", "NSE:DEMO,NSE:OTHER", 500, 1000, 1200, True)
        entered = self.buy(b, qty=5, exit_fee="200")
        with self.assertRaises(ValueError):
            self.buy(entered, event_id="entry-2", symbol="NSE:OTHER", qty=4, exit_fee="200")
        with self.assertRaises(ValueError):
            self.buy(
                entered,
                event_id="entry-3",
                symbol="NSE:OTHER",
                qty=1,
                as_of="2026-10-20T10:00:00+05:30",
            )

    def test_cli_persistence_refusal_and_no_mode_switch(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "demo.sqlite")
            base = [
                sys.executable,
                str(
                    Path(__file__).resolve().parents[1]
                    / "skills/day-trader-india/scripts/paper_book.py"
                ),
                "--book",
                db,
            ]
            init = [
                "init",
                "--cash-inr",
                "100000",
                "--symbols",
                "NSE:DEMO",
                "--risk-inr",
                "500",
                "--daily-loss-inr",
                "1000",
                "--position-limit-inr",
                "25000",
                "--replay",
            ]
            self.assertEqual(subprocess.run(base + init, capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(base + init, capture_output=True).returncode, 2)
            before = subprocess.check_output(base + ["status"])
            bad = [
                "buy",
                "--id",
                "bad",
                "--symbol",
                "NSE:DEMO",
                "--qty",
                "0",
                "--price-inr",
                "100",
                "--as-of",
                "2026-10-19T10:00:00+05:30",
                "--source",
                "SYNTHETIC",
                "--fee-inr",
                "10",
                "--slippage-bps",
                "5",
                "--stop-inr",
                "98",
                "--exit-fee-reserve-inr",
                "10",
            ]
            self.assertEqual(subprocess.run(base + bad, capture_output=True).returncode, 2)
            self.assertEqual(subprocess.check_output(base + ["status"]), before)
            self.assertEqual(json.loads(before)["mode"], "replay_demo")


if __name__ == "__main__":
    unittest.main()

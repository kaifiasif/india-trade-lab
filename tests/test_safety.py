"""Desk-wide safety rules: market guard, duplicates, reward after costs, square-off, recovery."""

import datetime as dt
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import intraday
import safety

import paper_book

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = ROOT / "skills/day-trader-india/assets/nse-sessions-2026.json"
IST = intraday.IST


def at(day: str, hhmm: str) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hhmm}:00+05:30")


def project(folder: Path) -> Path:
    shutil.copy(SESSIONS, folder / "sessions.json")
    config = folder / "pipeline.json"
    config.write_text(json.dumps({"sessions": "sessions.json", "book": "paper.sqlite",
                                  "fee_bps": "5", "fee_flat_inr": "10", "slippage_bps": "5"}))  # fmt: skip
    return config


def save(path: Path, book: dict) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS book (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT)"
        )
        conn.execute("INSERT OR REPLACE INTO book VALUES (1, ?)", (json.dumps(book),))


def evidence(symbol: str, when: dt.datetime) -> dict:
    checks = dict.fromkeys(
        ("cash_equity", "instrument_verified", "surveillance_clear", "price_band_ok",
         "no_material_event", "liquidity_ok", "sector_exposure_ok", "data_authorized",
         "strategy_rule_met", "stop_target_reviewed"), True,
    )  # fmt: skip
    return {
        "version": 1, "symbol": symbol, "quote_source": "TEST", "quote_as_of": when.isoformat(),
        "checked_at": when.isoformat(), "checks": checks,
        "evidence_sources": dict.fromkeys(checks, "test fixture"),
        "session": {"date": str(when.date()), "open": "09:15", "entry_cutoff": "14:30",
                    "close": "15:30", "source": "test"},
        "bid_inr": "99.99", "ask_inr": "100.00",
    }  # fmt: skip


def bought(book: dict, symbol: str, when: dt.datetime, target: str | None = "110") -> dict:
    return paper_book.fill(
        book, "buy", f"e-{symbol}", symbol, "100", when.isoformat(), "TEST", "10", "0",
        qty=10, stop="98", exit_fee="10", now=when, evidence=evidence(symbol, when), target=target,
    )  # fmt: skip


class GuardTests(unittest.TestCase):
    def test_high_volatility_a_big_index_move_or_no_reading_blocks_entries(self):
        cfg = safety.DEFAULTS
        now = at("2026-10-30", "10:00")
        calm = {"NSE:INDIA VIX": {"last_price": 13.0},
                "NSE:NIFTY 50": {"last_price": 22900, "ohlc": {"close": 22800}}}  # fmt: skip
        self.assertEqual(safety.read_conditions(calm, now, cfg)["blocks"], [])
        wild = {**calm, "NSE:INDIA VIX": {"last_price": 27.5}}
        self.assertIn("India VIX 27.5", safety.read_conditions(wild, now, cfg)["blocks"][0])
        crash = {**calm, "NSE:NIFTY 50": {"last_price": 22200, "ohlc": {"close": 22800}}}
        self.assertIn("-2.63%", safety.read_conditions(crash, now, cfg)["blocks"][0])
        self.assertTrue(safety.read_conditions({}, now, cfg)["blocks"])

    def test_the_guard_refuses_when_unread_stale_or_blocking_and_can_be_switched_off(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = project(Path(temporary))
            now = at("2026-10-30", "10:00")
            self.assertIn("not been read", safety.entry_guard(config, now))
            safety.refresh_conditions(config, now, lambda keys: {
                "NSE:INDIA VIX": {"last_price": 12.0},
                "NSE:NIFTY 50": {"last_price": 22900, "ohlc": {"close": 22850}}})  # fmt: skip
            self.assertEqual(safety.entry_guard(config, now + dt.timedelta(seconds=60)), "")
            self.assertIn("stale", safety.entry_guard(config, now + dt.timedelta(minutes=10)))
            settings = json.loads(config.read_text())
            settings["safety"] = {"market_guard": False}
            config.write_text(json.dumps(settings))
            self.assertEqual(safety.entry_guard(config, now + dt.timedelta(hours=2)), "")


class BookRuleTests(unittest.TestCase):
    def test_the_journal_needs_a_target_and_enough_reward_after_costs(self):
        now = at("2026-10-30", "10:00")
        book = paper_book.create("100000", "NSE:A", "250", "750", "15000")
        with self.assertRaisesRegex(ValueError, "target"):
            bought(book, "NSE:A", now, target=None)
        with self.assertRaisesRegex(ValueError, "not worth it"):
            bought(book, "NSE:A", now, target="101")  # Rs 10 a share reward vs Rs 40 risk.
        self.assertIn("NSE:A", bought(book, "NSE:A", now)["positions"])

    def test_reward_after_costs_shrinks_small_targets_most(self):
        self.assertAlmostEqual(safety.net_reward_risk(100, 98, 104, 100, 0, 0, 0), 2.0)
        with_costs = safety.net_reward_risk(100, 98, 104, 100, 12, 20, 5)
        self.assertLess(with_costs, 1.5)
        self.assertEqual(safety.net_reward_risk(100, 101, 104, 100, 0, 0, 0), 0.0)

    def test_a_stock_held_in_one_book_cannot_be_entered_in_the_other(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            config = project(folder)
            swing = paper_book.create("100000", "NSE:A", "500", "1500", "25000", style="swing")
            save(folder / "swing.sqlite", bought(swing, "NSE:A", at("2026-10-29", "10:00")))
            self.assertIn("swing book", safety.held_elsewhere(config, "NSE:A", "intraday"))
            self.assertEqual(safety.held_elsewhere(config, "NSE:B", "intraday"), "")
            self.assertEqual(safety.held_elsewhere(config, "NSE:A", "swing"), "")


class SquareOffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.config = project(self.folder)
        book = paper_book.create("100000", "NSE:A,NSE:B", "250", "750", "15000", max_open=2)
        book = bought(book, "NSE:A", at("2026-10-30", "10:00"))
        save(self.folder / "paper.sqlite", book)

    def tearDown(self):
        self.temporary.cleanup()

    def quotes(self, symbols):
        return {s: {"last_price": 101.0, "depth": {"buy": [{"price": 100.95}]}} for s in symbols}

    def test_nothing_closes_before_the_deadline_and_everything_closes_after(self):
        early = safety.square_off(self.config, at("2026-10-30", "14:00"), self.quotes)
        self.assertEqual(early["status"], "not yet")
        late = safety.square_off(self.config, at("2026-10-30", "15:15"), self.quotes)
        self.assertEqual([row["symbol"] for row in late["closed"]], ["NSE:A"])
        book = safety._read(self.folder / "paper.sqlite")
        self.assertEqual(book["positions"], {})
        self.assertEqual(book["events"][-1]["id"], "squareoff:2026-10-30:NSE:A")

    def test_after_a_restart_an_overdue_position_closes_at_the_next_open(self):
        closed = safety.square_off(self.config, at("2026-10-30", "16:30"), self.quotes)
        self.assertEqual(closed["status"], "market closed")
        report = safety.recover(self.config, at("2026-11-02", "09:20"), self.quotes)
        self.assertEqual(report["books"]["intraday"]["status"], "ok")
        self.assertEqual(
            report["square_off"]["closed"][0]["why"], "overdue square-off after a restart"
        )
        self.assertTrue((self.folder / "recovery.json").is_file())

    def test_recovery_reports_a_tampered_journal_and_touches_nothing(self):
        with sqlite3.connect(self.folder / "paper.sqlite") as conn:
            state = json.loads(conn.execute("SELECT data FROM book").fetchone()[0])
            state["cash"] = "999999.00"
            conn.execute("UPDATE book SET data=?", (json.dumps(state),))
        report = safety.recover(self.config, at("2026-10-30", "11:00"), self.quotes)
        self.assertEqual(report["books"]["intraday"]["status"], "CHECKSUM_MISMATCH")
        self.assertNotIn("square_off", report)


if __name__ == "__main__":
    unittest.main()

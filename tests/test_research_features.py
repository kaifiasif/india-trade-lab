"""Exact charges, exchange surveillance, the calendar, luck and overfitting tests,
the watchdog with Telegram controls, and backups."""

import datetime as dt
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup
import charges
import guardrails
import intraday
import surveillance
import validation
import watchdog

import secret_store

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = ROOT / "skills/day-trader-india/assets/nse-sessions-2026.json"


def at(day: str, hhmm: str) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hhmm}:00+05:30")


def project(folder: Path, **extra) -> Path:
    shutil.copy(SESSIONS, folder / "sessions.json")
    config = folder / "pipeline.json"
    config.write_text(json.dumps({"sessions": "sessions.json", **extra}))
    return config


class ChargesTests(unittest.TestCase):
    def test_intraday_charges_match_the_published_rates(self):
        buy = charges.side("intraday", "buy", 1000, 100, "2026-11-02")
        sell = charges.side("intraday", "sell", 1000, 100, "2026-11-02")
        self.assertEqual(buy["brokerage"], 20.0)  # 0.03% of ₹1 lakh is ₹30: capped at ₹20.
        self.assertEqual(buy["stamp"], 3.0)  # 0.003% on the buy only.
        self.assertEqual(buy["stt"], 0.0)
        self.assertEqual(sell["stt"], 25.0)  # 0.025% on the sell only.
        self.assertEqual(buy["transaction"], 3.07)
        self.assertEqual(buy["gst"], 4.17)  # 18% of brokerage + transaction + SEBI.
        self.assertEqual(buy["total"], 30.34)

    def test_delivery_charges_include_stt_both_sides_and_the_dp_charge(self):
        trade = charges.trade("delivery", 1500, 1560, 16, "2026-11-02")
        self.assertEqual(trade["buy"]["stt"], 24.0)
        self.assertEqual(trade["sell"]["stt"], 24.96)
        self.assertEqual(trade["buy"]["stamp"], 3.6)  # 0.015% on the buy.
        self.assertEqual(trade["sell"]["dp"], 15.34)
        self.assertEqual(trade["buy"]["brokerage"], 0.0)
        self.assertEqual(trade["total_inr"], 69.73)
        self.assertEqual(trade["net_pnl_inr"], 890.27)

    def test_old_trades_use_the_rates_of_their_day(self):
        self.assertEqual(charges.version("2025-01-01")["txn_pct"], 0.00297)
        self.assertEqual(charges.version("2026-11-02")["txn_pct"], 0.00307)
        self.assertEqual(charges.fee("intraday", "buy", 1000, 100, "2025-01-01"), 30.22)


INDICATOR = (
    "Symbol,Name,Status,GSM,Long_Term_Additional_Surveillance_Measure (Long Term ASM),"
    "Short_Term_Additional_Surveillance_Measure (Short Term ASM),ESM,"
    "Insolvency_Resolution_Process (IRP),Add-on_PB,Pledge\n"
    "CLEAN,Clean Ltd,A,100,100,100,100,100,0,0\n"
    "GSMCO,GSM Co,A,2,100,100,100,100,0,0\n"
    "LTASM,LT Co,A,100,1,100,100,100,0,0\n"
    "STASM,ST Co,A,100,100,1,100,100,1,0\n"
    "SUSP,Suspended,S,100,100,100,100,100,0,0\n"
)
BAN = "Securities in Ban For Trade Date 02-NOV-2026:\n1,BANNED\n"


class SurveillanceTests(unittest.TestCase):
    def test_measures_block_or_caution_per_the_file_codes(self):
        stocks = surveillance.parse_indicator(INDICATOR.encode())
        self.assertNotIn("NSE:CLEAN", stocks)
        self.assertIn("GSM stage 2", stocks["NSE:GSMCO"]["block"])
        self.assertTrue(stocks["NSE:LTASM"]["block"])
        self.assertEqual(stocks["NSE:STASM"]["block"], [])
        self.assertIn("short-term ASM stage 1", stocks["NSE:STASM"]["caution"])
        self.assertIn("add-on price band", stocks["NSE:STASM"]["caution"])
        self.assertIn("suspended", stocks["NSE:SUSP"]["block"])
        self.assertEqual(surveillance.parse_ban(BAN.encode()), ["NSE:BANNED"])
        with self.assertRaises(ValueError):
            surveillance.parse_indicator(b"<html>Access denied</html>")

    def test_the_gate_blocks_watched_stocks_and_unknown_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = project(Path(temporary))
            clock = at("2026-11-02", "08:45")
            self.assertIn("not been read", surveillance.gate(config, "NSE:CLEAN", clock)[0])
            calls = []

            def get(url):
                calls.append(url)
                return (INDICATOR if "REG_IND" in url else BAN).encode()

            report = surveillance.fetch(config, clock, get)
            self.assertIn("REG_IND021126", calls[0])  # The newest session not after today.
            self.assertEqual(report["sources"]["indicator"], "2026-11-02")
            self.assertEqual(surveillance.gate(config, "NSE:CLEAN", clock), ("", []))
            self.assertIn("GSM", surveillance.gate(config, "NSE:GSMCO", clock)[0])
            reason, caution = surveillance.gate(config, "NSE:BANNED", clock)
            self.assertEqual(reason, "")
            self.assertIn("F&O ban", caution[0])
            later = clock + dt.timedelta(days=2)
            self.assertIn("more than a day old", surveillance.gate(config, "NSE:CLEAN", later)[0])

    def test_nse_refusing_every_file_blocks_entries_but_can_be_switched_off(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = project(Path(temporary))
            clock = at("2026-11-02", "08:45")

            def refuse(url):
                raise OSError("403")

            report = surveillance.fetch(config, clock, refuse)
            self.assertNotIn("indicator", report["sources"])
            self.assertTrue(surveillance.gate(config, "NSE:CLEAN", clock)[0])
            project(Path(temporary), surveillance={"unknown_blocks": False})
            self.assertEqual(surveillance.gate(config, "NSE:CLEAN", clock)[0], "")


class CalendarTests(unittest.TestCase):
    def test_the_closing_auction_moves_square_off_and_muhurat_is_skipped(self):
        manifest = json.loads(SESSIONS.read_text())
        self.assertEqual(manifest["sessions"]["2026-11-02"]["flat_by"], "15:05")
        self.assertNotEqual(manifest["sessions"]["2026-07-31"].get("flat_by"), "15:05")
        self.assertIsNone(manifest["sessions"]["2026-11-08"])
        self.assertIsNone(intraday.session_times(manifest, dt.date(2026, 11, 8)))

    def test_sync_updates_an_old_project_calendar_and_keeps_a_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            config = project(folder)
            old = json.loads(SESSIONS.read_text())
            old["sessions"]["2026-11-02"]["flat_by"] = "15:20"
            (folder / "sessions.json").write_text(json.dumps(old))
            result = intraday.sync_calendar(config)
            self.assertTrue(result["changed"])
            self.assertEqual(
                intraday.sessions_manifest(config)["sessions"]["2026-11-02"]["flat_by"], "15:05"
            )
            self.assertTrue((folder / "sessions.json.before-sync").is_file())
            self.assertFalse(intraday.sync_calendar(config)["changed"])


class ValidationTests(unittest.TestCase):
    def test_luck_percentile_counts_twins_beaten(self):
        self.assertEqual(validation.percentile_beaten(10, [1, 2, 3, 10]), 87.5)
        self.assertEqual(validation.percentile_beaten(0, [1, 2]), 0.0)
        self.assertEqual(validation.percentile_beaten(5, []), 0.0)

    def test_more_trials_deflate_the_same_sharpe(self):
        returns = [1.2, -1, 0.8, -1, 1.5, 0.4, -1, 2.0, -0.5, 1.1, -1, 0.9] * 4
        one = validation.deflated_sharpe(returns, 1)["dsr"]
        many = validation.deflated_sharpe(returns, 200)["dsr"]
        self.assertGreater(one, many)
        self.assertIsNone(validation.deflated_sharpe([1, -1, 1], 5)["dsr"])  # Too few trades.

    def test_the_trial_registry_remembers_every_variant(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            first = validation.variant_id("swing", "a", {"hold": 5})
            second = validation.variant_id("swing", "a", {"hold": 4})
            self.assertNotEqual(first, second)
            validation.record_trials(
                folder, "swing", [{"id": first, "strategy": "a", "sharpe": 0.1}]
            )
            seen = validation.record_trials(
                folder, "swing", [{"id": second, "strategy": "a", "sharpe": 0.2},
                                  {"id": first, "strategy": "a", "sharpe": 0.1}],
            )  # fmt: skip
            self.assertEqual(seen["trials"], 2)
            other = validation.record_trials(folder, "intraday", [])
            self.assertEqual(other["trials"], 0)  # Desks are counted separately.


class FakeTelegram:
    """Records Bot API calls; answers getUpdates with ``updates``."""

    def __init__(self, updates=None):
        self.calls, self.updates = [], updates or []

    def open(self, request, timeout):
        method = request.full_url.rsplit("/", 1)[1]
        self.calls.append((method, json.loads(request.data)))
        body = {"ok": True, "result": self.updates if method == "getUpdates" else {}}
        if method == "getUpdates":
            self.updates = []
        return io.BytesIO(json.dumps(body).encode())


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.store = patch.dict(os.environ, {"ITL_CONFIG_DIR": str(self.folder / "store")})
        self.store.start()
        self.config = project(self.folder, notify={"telegram_chat_id": "42"})

    def tearDown(self):
        self.store.stop()
        self.temporary.cleanup()

    def test_missed_jobs_are_named_on_a_trading_morning(self):
        found = watchdog.problems(self.config, at("2026-11-02", "10:00"), login=lambda clock: False)
        keys = {item["id"].split(":")[0] for item in found}
        self.assertTrue({"login", "worker", "surveillance"} <= keys)
        quiet = watchdog.problems(self.config, at("2026-11-01", "10:00"), login=lambda clock: False)
        self.assertEqual({item["id"].split(":")[0] for item in quiet} & {"login", "worker"}, set())

    def test_each_problem_is_sent_once_and_only_the_owner_can_pause(self):
        secret_store.set_secret("TELEGRAM_BOT_TOKEN", "123456:TEST-token")
        updates = [
            {"update_id": 5, "message": {"chat": {"id": 7}, "text": "/pause"}},  # A stranger.
            {"update_id": 6, "message": {"chat": {"id": 42}, "text": "/pause"}},
        ]
        bot = FakeTelegram(updates)
        clock = at("2026-11-02", "10:00")
        first = watchdog.check(self.config, clock, bot, login=lambda clock: False)
        self.assertGreaterEqual(first["sent"], 3)
        self.assertEqual(first["commands"], ["/pause"])
        self.assertTrue((self.folder / "HALT_ENTRIES").exists())
        replies = [payload for method, payload in bot.calls if method == "sendMessage"]
        self.assertTrue(all(payload["chat_id"] == "42" for payload in replies))
        second = watchdog.check(self.config, clock + dt.timedelta(minutes=2), bot, lambda c: False)
        self.assertEqual(second["sent"], 0)  # Already sent today.
        bot.updates = [{"update_id": 7, "message": {"chat": {"id": 42}, "text": "/resume"}}]
        watchdog.check(self.config, clock + dt.timedelta(minutes=4), bot, lambda c: False)
        self.assertFalse((self.folder / "HALT_ENTRIES").exists())
        offsets = [payload["offset"] for method, payload in bot.calls if method == "getUpdates"]
        self.assertEqual(offsets[-1], 7)  # Old commands are never replayed.

    def test_without_telegram_it_falls_back_to_email(self):
        with patch("premarket.smtp_send", return_value={"sent": True}) as sent:
            self.assertEqual(watchdog.send(self.config, "Disk is full."), "email")
        self.assertIn("Paper trading only", sent.call_args[0][0].get_content())


def journal(path: Path, cash: str = "100000") -> None:
    state = guardrails.seal_state({"version": 3, "cash": cash, "positions": {}, "events": []})
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE book (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO book VALUES (1, ?)", (json.dumps(state),))


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.store = patch.dict(os.environ, {"ITL_CONFIG_DIR": str(self.folder / "store")})
        self.store.start()
        self.config = project(self.folder, backup={"keep": 2})
        journal(self.folder / "paper.sqlite")
        journal(self.folder / "swing.sqlite", "50000")

    def tearDown(self):
        self.store.stop()
        self.temporary.cleanup()

    def test_a_plain_backup_restores_with_verified_journals_and_rotates(self):
        for minute in range(3):
            result = backup.run(self.config, at("2026-11-02", f"23:3{minute}"))
        self.assertFalse(result["encrypted"])
        self.assertIn("not encrypted", result["note"])
        self.assertIn("paper.sqlite", result["included"])
        self.assertEqual(len(list((self.folder / "backups").glob("backup-*"))), 2)
        self.assertEqual(
            oct((self.folder / "backups" / result["file"]).stat().st_mode & 0o777), "0o600"
        )
        report = backup.restore_test(self.config)
        self.assertTrue(report["ok"])
        self.assertEqual(report["journals"]["swing.sqlite"]["cash"], "50000")

    @unittest.skipUnless(shutil.which("openssl"), "openssl is not installed")
    def test_with_a_passphrase_the_archive_is_encrypted(self):
        secret_store.set_secret("BACKUP_PASSPHRASE", "correct horse battery staple")
        result = backup.run(self.config, at("2026-11-02", "23:30"))
        self.assertTrue(result["encrypted"])
        self.assertTrue(result["file"].endswith(".enc"))
        sealed = (self.folder / "backups" / result["file"]).read_bytes()
        self.assertNotIn(b"paper.sqlite", sealed)
        self.assertTrue(backup.restore_test(self.config)["ok"])

    def test_a_tampered_journal_is_reported(self):
        with sqlite3.connect(self.folder / "paper.sqlite") as conn:
            state = json.loads(conn.execute("SELECT data FROM book").fetchone()[0])
            state["cash"] = "999999"
            conn.execute("UPDATE book SET data=?", (json.dumps(state),))
        backup.run(self.config, at("2026-11-02", "23:30"))
        report = backup.restore_test(self.config)
        self.assertFalse(report["ok"])
        self.assertEqual(report["journals"]["paper.sqlite"]["checksum"], "MISMATCH")


if __name__ == "__main__":
    unittest.main()

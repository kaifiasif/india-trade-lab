"""Live-data setup helpers, exercised offline with simulated Kite responses only."""

import datetime as dt
import gzip
import io
import json
import stat
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stdout
from pathlib import Path

import market_router
from history import HistoryStore
from watchlist import build_watchlist

import india_research
import kite_login
import make_universe

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "skills/day-trader-india/assets/nse-sessions-2026.json"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
# NSE circulars NSE/CMTR/71775 and NSE/CMTR/72260: CM-segment weekday holidays, 2026.
HOLIDAYS = {
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26",
    "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
}  # fmt: skip


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeOpener:
    def __init__(self, body: bytes) -> None:
        self.body, self.requests = body, []

    def open(self, request, timeout=None):
        self.requests.append(request)
        return FakeResponse(self.body)


DUMP = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
    "tick_size,lot_size,instrument_type,segment,exchange\n"
    "408065,1594,INFY,INFOSYS,0,,0,0.05,1,EQ,NSE,NSE\n"
    "2953217,11536,TCS,TATA CONSULTANCY,0,,0,0.05,1,EQ,NSE,NSE\n"
    "12345,48,NIFTY26OCTFUT,NIFTY,0,2026-10-27,0,0.05,75,FUT,NFO-FUT,NFO\n"
)
EQUITY_L = (
    "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT,"
    " ISIN NUMBER, FACE VALUE\n"
    "INFY,Infosys Limited,EQ,08-FEB-1995,5,1,INE009A01021,5\n"
    "TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1\n"
    "SMEX,Some SME Limited,SM,01-JAN-2020,10,1,INE000X01010,10\n"
)


class CalendarTests(unittest.TestCase):
    def test_bundled_nse_calendar_matches_the_circulars(self):
        manifest = json.loads(CALENDAR.read_text(encoding="utf-8"))
        self.assertIn("NSE/CMTR/71775", manifest["source"])
        sessions = manifest["sessions"]
        for day in HOLIDAYS:
            self.assertIsNone(sessions[day], day)
        self.assertIsNone(sessions["2026-11-08"])  # Muhurat-only Sunday is excluded
        monday = india_research.session(manifest, dt.date(2026, 10, 26))
        self.assertEqual(monday["open"].isoformat(), "2026-10-26T09:15:00+05:30")
        open_days = [d for d, row in sessions.items() if row]
        self.assertTrue(all(dt.date.fromisoformat(d).weekday() < 5 for d in open_days))
        self.assertEqual(
            market_router.route_market(
                "india", dt.datetime(2026, 10, 20, 10, tzinfo=IST), manifest
            )["status"],
            "CLOSED",
        )


class UniverseTests(unittest.TestCase):
    def test_builds_a_universe_the_watchlist_accepts(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "EQUITY_L.csv").write_text(EQUITY_L, encoding="utf-8")
            opener = FakeOpener(gzip.compress(DUMP.encode()))
            output = directory / "universe.json"
            env = {"KITE_API_KEY": "key", "KITE_ACCESS_TOKEN": "token"}
            raw = make_universe.fetch_kite_dump(env, opener)
            self.assertEqual(opener.requests[0].get_method(), "GET")
            tokens = make_universe.parse_kite_dump(raw)
            self.assertEqual(tokens, {"INFY": "408065", "TCS": "2953217"})
            now = dt.datetime(2026, 10, 26, 8, 30, tzinfo=IST)
            universe = make_universe.build_universe(
                ["INFY", "TCS"],
                make_universe.parse_equity_list(directory / "EQUITY_L.csv"),
                tokens,
                now,
            )
            output.write_text(json.dumps(universe))
            self.assertEqual(universe["instruments"][0]["isin"], "INE009A01021")
            self.assertEqual(universe["instruments"][1]["instrument_id"], "2953217")
            result = build_watchlist(HistoryStore(directory / "h.sqlite"), universe, now)
            self.assertEqual(result["mode"], "research_only")  # accepted; no history yet
            self.assertEqual(len(result["blocked"]), 2)

    def test_refuses_unmapped_non_eq_and_too_many_symbols(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "EQUITY_L.csv"
            path.write_text(EQUITY_L, encoding="utf-8")
            equities = make_universe.parse_equity_list(path)
            tokens = make_universe.parse_kite_dump(DUMP.encode())
            now = dt.datetime(2026, 10, 26, tzinfo=IST)
            for symbols in (["SMEX"], ["WIPRO"], ["INFY", "TCS", "A", "B"], ["INFY", "INFY"]):
                with self.assertRaises(ValueError):
                    make_universe.build_universe(symbols, equities, tokens, now)
            with self.assertRaises(ValueError):
                make_universe.fetch_kite_dump({}, FakeOpener(b""))


class LoginTests(unittest.TestCase):
    def test_exchange_saves_a_private_token_and_never_prints_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / "trade.env"
            opener = FakeOpener(json.dumps({"data": {"access_token": "AbC123tok"}}).encode())
            printed = io.StringIO()
            with redirect_stdout(printed):
                code = kite_login.main(
                    ["--env-file", str(env_file)],
                    {"KITE_API_KEY": "apikey", "KITE_API_SECRET": "secret"},
                    ask=lambda _: "http://127.0.0.1/?status=success&request_token=Req123456",
                    opener=opener,
                )
            self.assertEqual(code, 0)
            self.assertNotIn("AbC123tok", printed.getvalue())
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
            self.assertIn("KITE_ACCESS_TOKEN=AbC123tok", env_file.read_text())
            sent = dict(urllib.parse.parse_qsl(opener.requests[0].data.decode()))
            self.assertEqual(sent["checksum"], kite_login.checksum("apikey", "Req123456", "secret"))
            self.assertNotIn("secret", opener.requests[0].data.decode())

    def test_bad_input_and_failed_exchange_are_refused_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / "trade.env"
            env = {"KITE_API_KEY": "apikey", "KITE_API_SECRET": "secret"}
            for pasted, body in (
                ("not a token!", b"{}"),
                ("Req123456", b'{"status": "error", "message": "account detail"}'),
            ):
                code = kite_login.main(
                    ["--env-file", str(env_file)], env, ask=lambda _, p=pasted: p,
                    opener=FakeOpener(body),
                )  # fmt: skip
                self.assertEqual(code, 2)
            self.assertFalse(env_file.exists())
            self.assertEqual(kite_login.main([], {}, ask=lambda _: ""), 2)


if __name__ == "__main__":
    unittest.main()

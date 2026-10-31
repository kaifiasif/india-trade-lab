"""Portfolio caps across both books, quarter-Kelly, and the market-regime gate."""

import datetime as dt
import json
import math
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import portfolio
import regime

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = ROOT / "skills/day-trader-india/assets/nse-sessions-2026.json"


def book(path: Path, cash: float, positions: dict) -> None:
    state = {"initial_cash": str(cash), "cash": str(cash), "positions": positions, "events": []}
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE book (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO book VALUES (1, ?)", (json.dumps(state),))


def held(entry: float, stop: float, qty: int) -> dict:
    return {"entry_inr": str(entry), "stop_inr": str(stop), "qty": qty}


def days(count: int, end: dt.date = dt.date(2026, 10, 30)) -> list[str]:
    out, day = [], end
    while len(out) < count:
        if day.weekday() < 5:
            out.append(str(day))
        day -= dt.timedelta(days=1)
    return out[::-1]


def daily(conn: sqlite3.Connection, table: str, symbol: str, closes: list[float]) -> None:
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (symbol TEXT, date TEXT, open REAL, high REAL, "
                 "low REAL, close REAL, volume REAL, PRIMARY KEY(symbol, date))")  # fmt: skip
    conn.executemany(
        f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?)",
        [
            (symbol, day, c, c * 1.01, c * 0.99, c, 1e6)
            for day, c in zip(days(len(closes)), closes, strict=True)
        ],
    )


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        shutil.copy(SESSIONS, self.folder / "sessions.json")
        self.config = self.folder / "pipeline.json"
        self.config.write_text(json.dumps({"sessions": "sessions.json", "book": "paper.sqlite"}))
        book(
            self.folder / "paper.sqlite", 100_000, {"NSE:BANKA": held(100, 98, 500)}
        )  # ₹1,000 risk.
        book(self.folder / "swing.sqlite", 100_000, {})
        wave = [100 * (1 + 0.02 * math.sin(i / 2) + 0.001 * i) for i in range(70)]
        with sqlite3.connect(self.folder / "scan.sqlite") as conn:
            daily(conn, "daily", "NSE:BANKA", wave)
            daily(conn, "daily", "NSE:BANKB", [value * 2 for value in wave])  # Moves together.
            daily(
                conn,
                "daily",
                "NSE:PHARMA",
                [100 * (1 + 0.02 * math.cos(i * 1.7)) for i in range(70)],
            )
        with sqlite3.connect(self.folder / "reference.sqlite") as conn:
            conn.execute("CREATE TABLE reference (symbol TEXT PRIMARY KEY, sector TEXT)")
            conn.executemany("INSERT INTO reference VALUES (?,?)",
                             [("NSE:BANKA", "Banks"), ("NSE:BANKB", "Banks"), ("NSE:BANKC", "Banks"),
                              ("NSE:PHARMA", "Pharma")])  # fmt: skip

    def tearDown(self):
        self.temporary.cleanup()

    def test_heat_counts_risk_in_both_books(self):
        reason, notes = portfolio.gate(self.config, "intraday", "NSE:PHARMA", 100, 98, 500)
        self.assertEqual(reason, "")
        self.assertIn("heat after entry 1.0%", notes[0])  # (₹1,000 + ₹1,000) of ₹2 lakh.
        reason, _ = portfolio.gate(self.config, "swing", "NSE:PHARMA", 100, 90, 1000)
        self.assertIn("total open risk would be 5.5%", reason)

    def test_correlated_and_crowded_sectors_are_refused(self):
        reason, _ = portfolio.gate(self.config, "intraday", "NSE:BANKB", 200, 198, 10)
        self.assertIn("moves with NSE:BANKA", reason)
        (self.folder / "swing.sqlite").unlink()
        book(self.folder / "swing.sqlite", 100_000, {"NSE:BANKB": held(200, 199, 5)})
        reason, _ = portfolio.gate(self.config, "intraday", "NSE:BANKC", 100, 99, 10)
        self.assertIn("already 2 open in Banks", reason)

    def test_quarter_kelly_caps_risk_once_the_sample_is_large(self):
        card = {"strategies": {"orb-v1": {"doubled_costs": {"trades": 150, "win_rate_pct": 50.0, "profit_factor": 1.25}},
                               "weak-v1": {"doubled_costs": {"trades": 150, "win_rate_pct": 40.0, "profit_factor": 0.9}},
                               "young-v1": {"doubled_costs": {"trades": 30, "win_rate_pct": 80.0, "profit_factor": 3}}}}  # fmt: skip
        (self.folder / "strategy-scorecard.json").write_text(json.dumps(card))
        # Kelly = 0.5 x (1 - 1/1.25) = 0.10; a quarter of that on ₹1 lakh = ₹2,500.
        self.assertEqual(
            portfolio.gate(self.config, "intraday", "NSE:PHARMA", 100, 98, 1000, "orb-v1")[0], ""
        )
        reason, _ = portfolio.gate(self.config, "intraday", "NSE:PHARMA", 100, 97, 1000, "orb-v1")
        self.assertIn("quarter-Kelly ceiling ₹2,500", reason)
        self.assertIn(
            "no edge",
            portfolio.gate(self.config, "intraday", "NSE:PHARMA", 100, 99, 10, "weak-v1")[0],
        )
        _, notes = portfolio.gate(self.config, "intraday", "NSE:PHARMA", 100, 99, 10, "young-v1")
        self.assertIn("Kelly needs 100", notes[-1])

    def test_the_view_sums_open_risk(self):
        view = portfolio.view(self.config)
        self.assertEqual(view["open_risk_inr"], 1000.0)
        self.assertEqual(view["by_sector"], {"Banks": 1})


class RegimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.scan = Path(self.temporary.name) / "scan.sqlite"
        rising = [20000 * (1.002**i) for i in range(80)]
        with sqlite3.connect(self.scan) as conn:
            daily(conn, "index_daily", regime.NIFTY, rising)
            daily(conn, "index_daily", regime.VIX, [12.0] * 60 + [24.0] * 20)

    def tearDown(self):
        self.temporary.cleanup()

    def test_each_session_gets_a_label_from_its_own_close(self):
        known = regime.labels(self.scan)
        dates = days(80)
        self.assertNotIn(dates[50], known)  # Needs 55 sessions of Nifty.
        self.assertEqual(known[dates[58]]["label"], "up/calm")
        self.assertEqual(known[dates[-1]]["label"], "up/high")
        # A trade on day D uses the label of the session before D.
        self.assertEqual(regime.label_before(known, dates[60])["label"], "up/calm")

    def test_a_strategy_that_loses_in_todays_regime_sits_out(self):
        known = regime.labels(self.scan)
        dates = days(80)
        losers = [{"date": dates[-1 - (i % 10)], "net_inr": -50.0} for i in range(25)]
        row = {"by_regime": regime.by_regime(losers, known)}
        self.assertEqual(row["by_regime"]["up/high"]["trades"], 25)
        self.assertIn("lost on average in up/high", regime.veto(row, "up/high", 20))
        self.assertEqual(regime.veto(row, "up/high", 30), "")  # Too few trades to decide.
        self.assertEqual(regime.veto(row, "up/calm", 20), "")

    def test_kite_index_tokens_come_from_the_instrument_list(self):
        rows = [{"segment": "INDICES", "tradingsymbol": "NIFTY 50", "instrument_token": "256265"},
                {"segment": "INDICES", "tradingsymbol": "INDIA VIX", "instrument_token": "264969"},
                {"segment": "NSE", "tradingsymbol": "INFY", "instrument_token": "1"}]  # fmt: skip
        self.assertEqual(regime.index_tokens(rows), {regime.NIFTY: "256265", regime.VIX: "264969"})


if __name__ == "__main__":
    unittest.main()

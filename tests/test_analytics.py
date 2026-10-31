"""Performance analytics, tax view, drift, shadow fills, the bhavcopy archive, market
context and the monthly AI cap."""

import datetime as dt
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import analytics
import bhavcopy
import market_context
import openrouter
import shadow

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = ROOT / "skills/day-trader-india/assets/nse-sessions-2026.json"


def at(day: str, hhmm: str) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hhmm}:00+05:30")


def project(folder: Path, **extra) -> Path:
    shutil.copy(SESSIONS, folder / "sessions.json")
    config = folder / "pipeline.json"
    config.write_text(json.dumps({"sessions": "sessions.json", "book": "paper.sqlite", **extra}))
    return config


def journal(path: Path, closed: list[tuple]) -> None:
    """closed: (symbol, strategy, opened, closed, entry, exit, qty, planned_loss, net)."""
    events = []
    for index, (symbol, strategy, opened, shut, entry, exit_, qty, planned, net) in enumerate(
        closed
    ):
        events.append({"id": f"b{index}", "side": "buy", "symbol": symbol, "as_of": opened,
                       "assumed_fill_inr": str(entry), "fee_inr": "10", "qty": qty,
                       "stop_inr": str(entry - planned / qty), "planned_loss_inr": str(planned),
                       "research_meta": {"strategy_version": strategy}})  # fmt: skip
        events.append({"id": f"s{index}", "side": "sell", "symbol": symbol, "as_of": shut,
                       "entry_event_id": f"b{index}", "assumed_fill_inr": str(exit_),
                       "fee_inr": "12", "net_realized_pnl_inr": str(net)})  # fmt: skip
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE book (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute(
            "INSERT INTO book VALUES (1, ?)", (json.dumps({"events": events, "positions": {}}),)
        )


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.config = project(self.folder)
        journal(self.folder / "paper.sqlite", [
            ("NSE:INFY", "orb-v1", "2026-03-30T09:40:00+05:30", "2026-03-30T11:00:00+05:30", 1500, 1530, 20, 400, 578),
            ("NSE:TCS", "orb-v1", "2026-04-02T10:10:00+05:30", "2026-04-02T12:00:00+05:30", 4000, 3980, 10, 200, -222),
            ("NSE:SBIN", "orb-v1", "2026-04-06T09:50:00+05:30", "2026-04-06T15:05:00+05:30", 800, 796, 50, 200, -222),
        ])  # fmt: skip
        journal(self.folder / "swing.sqlite", [
            ("NSE:LT", "vol-breakout-v1", "2026-04-07T09:20:00+05:30", "2026-04-10T10:00:00+05:30", 3500, 3640, 10, 500, 1330),
        ])  # fmt: skip

    def tearDown(self):
        self.temporary.cleanup()

    def test_results_r_and_equity_come_from_both_journals(self):
        view = analytics.report(self.config)
        total = view["summary"]
        self.assertEqual(total["trades"], 4)
        self.assertEqual(total["net_inr"], 1464.0)
        self.assertEqual(total["win_rate_pct"], 50.0)
        self.assertEqual(total["charges_inr"], 88.0)
        rs = sorted(row["r"] for row in analytics.trades(self.config))
        self.assertEqual(rs, [-1.11, -1.11, 1.45, 2.66])
        self.assertEqual(view["equity"]["max_drawdown_inr"], 444.0)
        self.assertEqual(view["attribution"]["book"]["swing"]["trades"], 1)
        self.assertEqual(sum(bucket["count"] for bucket in view["r_histogram"]), 4)

    def test_tax_is_split_by_financial_year_and_kind(self):
        tax = analytics.tax_view(analytics.trades(self.config), 30)
        self.assertEqual(tax["FY2025-26"]["speculative_income_inr"], 578.0)
        self.assertEqual(tax["FY2025-26"]["speculative_tax_inr"], round(578 * 0.3 * 1.04, 2))
        self.assertEqual(tax["FY2026-27"]["speculative_income_inr"], -444.0)
        self.assertEqual(tax["FY2026-27"]["speculative_tax_inr"], 0.0)  # A loss owes nothing.
        self.assertEqual(tax["FY2026-27"]["stcg_tax_inr"], round(1330 * 0.2 * 1.04, 2))

    def test_drift_alarms_when_paper_keeps_missing_the_backtest(self):
        card = {"strategies": {"orb-v1": {"doubled_costs": {"average_r": 1.5}}}}
        (self.folder / "strategy-scorecard.json").write_text(json.dumps(card))
        drift = analytics.drift(self.config, analytics.trades(self.config))
        row = drift["intraday:orb-v1"]
        self.assertEqual(row["paper_trades"], 3)
        self.assertTrue(row["alarm"])  # 0 + (1.5-1.45-.5) -> 0, +2.11, +4.22.

    def test_each_trade_is_explained_in_plain_words(self):
        story = analytics.explain(analytics.trades(self.config)[0])
        self.assertIn("bought 20 INFY at ₹1,500.00 using orb-v1", story)
        self.assertIn("planned to lose was ₹400", story)
        self.assertIn("made ₹578.00 after ₹22.00 of charges, which is +1.45R", story)
        self.assertIn("Paper trade", story)


class ShadowTests(unittest.TestCase):
    def test_fills_are_compared_with_the_market_a_minute_later(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = project(Path(temporary), slippage_bps=5)
            clock = at("2026-11-02", "10:00")
            for minute in range(6):
                shadow.record(
                    config,
                    "intraday",
                    "NSE:INFY",
                    "buy",
                    100.0,
                    clock + dt.timedelta(minutes=minute),
                )
            shadow.record(config, "intraday", "NSE:INFY", "sell", 100.0, clock)

            def quotes(symbols):
                return {
                    "NSE:INFY": {
                        "last_price": 100.05,
                        "depth": {"buy": [{"price": 99.95}], "sell": [{"price": 100.10}]},
                    }
                }

            early = shadow.settle(config, clock + dt.timedelta(seconds=30), quotes)
            self.assertEqual(early["settled"], 0)  # Not a minute old yet.
            done = shadow.settle(config, clock + dt.timedelta(minutes=7), quotes)
            self.assertEqual(done["settled"], 7)
            samples = json.loads((Path(temporary) / "shadow-fills.json").read_text())["settled"]
            self.assertEqual(samples[0]["slippage_bps"], 10.0)  # Paid the ask, 10 bps worse.
            self.assertEqual(samples[-1]["slippage_bps"], 5.0)  # Sold at the bid.
            calibration = shadow.calibration(config)["intraday"]
            self.assertEqual(calibration["samples"], 7)
            self.assertIn("raise slippage_bps", calibration["verdict"])


BHAV = (
    "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, "
    "AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
    "INFY, EQ, 30-Oct-2026, 1500, 1505, 1530, 1495, 1520, 1520, 1515, 100000, 1515, 5000, 50000, 50\n"
    "TCS, EQ, 30-Oct-2026, 4000, 3990, 4010, 3950, 3960, 3960, 3970, 20000, 794, 3000, 9000, 45\n"
    "SBIN, EQ, 30-Oct-2026, 800, 801, 812, 798, 810, 810, 805, 300000, 2415, 9000, 90000, 30\n"
    "SBIN, BE, 30-Oct-2026, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1\n"
)


class BhavcopyTests(unittest.TestCase):
    def test_sync_stores_sessions_reports_gaps_and_cross_checks_kite(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            config = project(folder)
            urls = []

            def get(url):
                urls.append(url)
                if "30102026" in url:
                    return BHAV.encode()
                raise OSError("403")

            result = bhavcopy.sync(config, at("2026-11-02", "08:45"), 3, get)
            self.assertEqual(result["stored"], ["2026-10-30"])
            self.assertEqual(sorted(result["missing"]), ["2026-10-28", "2026-10-29"])
            self.assertIn("2026-10-29", bhavcopy.gaps(config, at("2026-11-02", "08:45"), 3))
            again = bhavcopy.sync(config, at("2026-11-02", "08:50"), 3, lambda url: BHAV.encode())
            self.assertNotIn("2026-10-30", again["stored"])  # Fetched once.
            breadth = bhavcopy.breadth(config, "2026-10-30")
            self.assertEqual((breadth["advances"], breadth["declines"]), (2, 1))
            with sqlite3.connect(folder / "scan.sqlite") as conn:
                conn.execute(
                    "CREATE TABLE daily (symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL)"
                )
                conn.executemany("INSERT INTO daily VALUES (?,?,0,0,0,?,0)",
                                 [("NSE:INFY", "2026-10-30", 1520), ("NSE:TCS", "2026-10-30", 3900)])  # fmt: skip
            check = bhavcopy.cross_check(config, "2026-10-30")
            self.assertEqual(check["compared"], 2)
            self.assertEqual([row["symbol"] for row in check["mismatches"]], ["NSE:TCS"])

    def test_context_carries_flows_breadth_and_says_what_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            config = project(folder)
            bhavcopy.sync(config, at("2026-11-02", "08:45"), 1, lambda url: BHAV.encode())
            flows = [{"category": "FII/FPI *", "date": "30-Oct-2026", "netValue": "-1,234.5"},
                     {"category": "DII **", "date": "30-Oct-2026", "netValue": "2345.6"}]  # fmt: skip
            view = market_context.build(
                config, at("2026-11-02", "08:50"), lambda url: json.dumps(flows).encode()
            )
            self.assertEqual(view["flows"]["fii_net_inr_crore"], -1234.5)
            self.assertEqual(view["flows"]["dii_net_inr_crore"], 2345.6)
            self.assertEqual(view["breadth"]["advances"], 2)
            self.assertIn("regime unknown", view["notes"][0])
            self.assertIsNotNone(market_context.load(folder, dt.date(2026, 11, 2)))
            self.assertIsNone(market_context.load(folder, dt.date(2026, 11, 3)))


class MonthlyCapTests(unittest.TestCase):
    def test_paid_models_stop_at_the_monthly_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / "routing.sqlite"
            now = dt.datetime.now(dt.timezone.utc)
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE calls (at TEXT, role TEXT, provider TEXT, cost_usd REAL, "
                             "input_tokens INTEGER, output_tokens INTEGER)")  # fmt: skip
                conn.execute("INSERT INTO calls VALUES (?,?,?,?,?,?)",
                             ((now - dt.timedelta(minutes=1)).isoformat(), "judge", "openrouter", 3.0, 1000, 200))  # fmt: skip
            model = {"id": "x/paid", "pricing": {"prompt": "0.000001", "completion": "0.000002", "request": "0"},
                     "context_length": 100000, "supported_parameters": ["structured_outputs", "response_format"],
                     "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}}  # fmt: skip
            options = {"max_usd_per_day": 50.0}
            self.assertEqual(
                openrouter.choose(
                    [model], "auto:paid", "judge", "s", db, {**options, "max_usd_per_month": 5.0}
                ),
                ["x/paid"],
            )
            self.assertEqual(
                openrouter.choose(
                    [model], "auto:paid", "judge", "s", db, {**options, "max_usd_per_month": 2.0}
                ),
                [],
            )
            ledger = openrouter.ledger(db)
            self.assertEqual(ledger["month_usd"], 3.0)
            self.assertEqual(ledger["by_role"]["judge"]["calls"], 1)


if __name__ == "__main__":
    unittest.main()


class DashboardTests(unittest.TestCase):
    def test_the_performance_endpoint_reads_files_and_live_views(self):
        import observatory

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            config = project(folder)
            journal(folder / "paper.sqlite", [("NSE:INFY", "orb-v1", "2026-10-01T09:40:00+05:30",
                                               "2026-10-01T11:00:00+05:30", 1500, 1530, 20, 400, 578)])  # fmt: skip
            (folder / "performance.json").write_text(json.dumps(analytics.report(config)))
            (folder / "watchdog-state.json").write_text(
                json.dumps({"open_problems": ["Disk is full."]})
            )
            (folder / "HALT_ENTRIES").write_text("paused")
            view = observatory.performance_state(folder)
            self.assertEqual(view["performance"]["summary"]["trades"], 1)
            self.assertEqual(view["health"]["watchdog"]["problems"], ["Disk is full."])
            self.assertTrue(view["health"]["paused"])
            self.assertIn("intraday", view["health"]["slippage"])
            self.assertNotIn("TELEGRAM", json.dumps(view))  # No secret names or values.

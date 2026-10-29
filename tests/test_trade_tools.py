"""Trade tools and the desk agent: entry, exit plan, time machine, checks, alerts, filings."""

import datetime as dt
import json
import random
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import entry_timer
import exit_planner
import insider_tracker
import intraday
import market_scan
import price_alerts
import results_analyst
import time_machine
import trade_check
import trade_desk

import paper_book

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = ROOT / "skills/day-trader-india/assets/nse-sessions-2026.json"
DAY = dt.date(2026, 10, 29)
IST = intraday.IST


def times_for(day=DAY):
    return intraday.session_times(json.loads(SESSIONS.read_text()), day)


def at(hhmm, day=DAY):
    hours, minutes = map(int, hhmm.split(":"))
    return dt.datetime(day.year, day.month, day.day, hours, minutes, tzinfo=IST)


def bar(t, o, h, low, c, v=1000.0):
    return {"t": t, "open": o, "high": h, "low": low, "close": c, "volume": v}


def opening_session():
    """09:15-09:30 range 100-102, then 101.5, a wick to 102.5 closing 101.9, a close at 102.6."""
    rows = [
        bar(at("09:15"), 100.5, 101.0, 100.0, 100.8),
        bar(at("09:20"), 100.8, 102.0, 100.6, 101.7),
        bar(at("09:25"), 101.7, 101.9, 101.2, 101.4),
        bar(at("09:30"), 101.4, 101.8, 101.1, 101.5),
        bar(at("09:35"), 101.5, 102.5, 101.4, 101.9),
        bar(at("09:40"), 101.9, 102.8, 101.8, 102.6, 2500.0),
        bar(at("09:45"), 102.6, 103.0, 102.4, 102.9),
    ]
    return rows


def project(folder: Path, history_days=30, symbol="NSE:DEMO", drift=0.0003):
    """A minimal desk project: config, NSE calendar, stored history and a picks report."""
    shutil.copy(SESSIONS, folder / "sessions.json")
    config = {
        "sessions": "sessions.json", "history_db": "history.sqlite", "book": "paper.sqlite",
        "reports_dir": "reports", "bars": "bars.csv", "target_r": "2", "fee_bps": "5",
        "fee_flat_inr": "10", "slippage_bps": "5",
        "timemachine": {"enabled": True, "replays": 1000, "require_history": False},
        "alerts": {"email": False, "on_entries": True},
    }  # fmt: skip
    (folder / "pipeline.json").write_text(json.dumps(config))
    manifest = json.loads(SESSIONS.read_text())
    days = sorted(d for d, s in manifest["sessions"].items() if s and d < str(DAY))
    rng = random.Random(7)
    with sqlite3.connect(folder / "history.sqlite") as conn:
        conn.execute(
            "CREATE TABLE sessions (symbol TEXT, date TEXT, kind TEXT, close_at TEXT, "
            "digest TEXT, payload TEXT, imported_at TEXT, PRIMARY KEY(symbol,date,kind))"
        )
        for day in days[-history_days:] if history_days else []:
            times = intraday.session_times(manifest, dt.date.fromisoformat(day))
            price, rows = 100.0, []
            for index in range(75):
                step = rng.gauss(drift, 0.003)
                close = price * (1 + step)
                high = max(price, close) * (1 + abs(rng.gauss(0, 0.0015)))
                low = min(price, close) * (1 - abs(rng.gauss(0, 0.0015)))
                rows.append({"t": (times["open"] + index * intraday.BAR).isoformat(),
                             "open": price, "high": high, "low": low, "close": close,
                             "volume": 1000})  # fmt: skip
                price = close
            payload = {"bars": rows, "session": {k: v.isoformat() for k, v in times.items()}}
            conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                (symbol, day, "broker_export", "", "", json.dumps(payload), ""),
            )
    (folder / "reports").mkdir()
    (folder / "reports" / f"premarket-{DAY}.json").write_text(
        json.dumps({"session_date": str(DAY), "watching": [symbol]})
    )
    return folder / "pipeline.json"


def plan_for(symbol="NSE:DEMO", entry=102.6):
    return exit_planner.plan(
        symbol, entry, at("09:45"), times_for(), "or-low", "2R", {"high": 102.0, "low": 100.0}
    )


class EntryTimerTests(unittest.TestCase):
    def test_statuses_through_the_morning(self):
        rows, times = opening_session(), times_for()
        self.assertEqual(entry_timer.check("NSE:DEMO", rows, None, at("10:00"))["status"], "CLOSED")
        self.assertEqual(
            entry_timer.check("NSE:DEMO", rows, times, at("09:00"))["status"], "NOT_OPEN"
        )
        self.assertEqual(
            entry_timer.check("NSE:DEMO", rows, times, at("09:25"))["status"], "FORMING"
        )
        waiting = entry_timer.check("NSE:DEMO", rows, times, at("09:40"))
        self.assertEqual(waiting["status"], "WAITING")  # A wick to 102.5 is not a close above.
        self.assertEqual(waiting["opening_range"]["high"], 102.0)

    def test_the_first_close_above_the_range_triggers_at_the_bar_close(self):
        result = entry_timer.check("NSE:DEMO", opening_session(), times_for(), at("09:46"))
        self.assertEqual(result["status"], "TRIGGERED")
        self.assertEqual(result["price"], 102.6)
        self.assertEqual(result["time"], at("09:45").isoformat())

    def test_a_forming_bar_never_counts_and_volume_can_be_required(self):
        result = entry_timer.check("NSE:DEMO", opening_session(), times_for(), at("09:44"))
        self.assertEqual(result["status"], "WAITING")
        strict = entry_timer.check(
            "NSE:DEMO", opening_session(), times_for(), at("09:50"), min_volume_x=3.0
        )
        self.assertEqual(strict["status"], "WAITING")

    def test_no_trigger_by_the_cutoff_expires(self):
        rows = opening_session()[:4]
        self.assertEqual(
            entry_timer.check("NSE:DEMO", rows, times_for(), at("14:45"))["status"], "EXPIRED"
        )


class ExitPlannerTests(unittest.TestCase):
    def test_stop_rules_round_down_and_target_is_r_multiple(self):
        plan = plan_for()
        self.assertEqual((plan["stop"], plan["risk_per_share"]), (100.0, 2.6))
        self.assertEqual(plan["target"], 107.8)
        middle = exit_planner.plan("NSE:DEMO", 102.6, at("09:45"), times_for(), "or-mid", "1R",
                                   {"high": 102.0, "low": 100.03})  # fmt: skip
        self.assertEqual(middle["stop"], 101.0)  # 101.015 rounded down to 5 paise.
        self.assertEqual(plan["flat_by"], at("15:15").isoformat())

    def test_refusals(self):
        with self.assertRaises(ValueError):  # Under 0.15% away.
            exit_planner.plan("NSE:DEMO", 102.6, at("09:45"), times_for(), "price:102.5", "2R")
        with self.assertRaises(ValueError):  # After the entry cutoff.
            exit_planner.plan("NSE:DEMO", 102.6, at("14:30"), times_for(), "pct:1", "2R")
        with self.assertRaises(ValueError):
            exit_planner.plan("NSE:DEMO", 102.6, at("09:45"), times_for(), "price:103", "2R")


class TimeMachineTests(unittest.TestCase):
    def test_same_seed_same_odds_and_history_is_counted(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = project(Path(temporary))
            first = time_machine.run(plan_for(), config, replays=1000, seed=19)
            again = time_machine.run(plan_for(), config, replays=1000, seed=19)
            self.assertEqual(first["mc"], again["mc"])
            mc = first["mc"]
            self.assertAlmostEqual(
                mc["target_first_pct"] + mc["stop_first_pct"] + mc["neither_pct"], 100, 0
            )
            self.assertEqual(mc["sessions"], 30)
            self.assertEqual(first["history"]["sessions"], 30)
            self.assertLess(first["average_r_after_costs"], mc["average_r"])
            self.assertTrue(time_machine.describe(first).startswith("1,000 replays"))

    def test_too_little_history_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = project(Path(temporary), history_days=5)
            with self.assertRaises(ValueError):
                time_machine.run(plan_for(), config, replays=500)

    def test_verdict_weighs_the_target_size(self):
        # 2R: needs 33% of decided replays. 24.1 vs 50.5 is 32%: break-even, not a loser.
        mc = {
            "target_first_pct": 24.1,
            "stop_first_pct": 50.5,
            "neither_pct": 25.4,
            "average_r": 0.0,
        }
        self.assertEqual(time_machine.verdict(mc, 2)["code"], "break_even")
        self.assertEqual(
            time_machine.verdict({**mc, "target_first_pct": 10.0}, 2)["code"], "strong_stop"
        )
        coin = {
            "target_first_pct": 29.4,
            "stop_first_pct": 25.5,
            "neither_pct": 45.1,
            "average_r": 0.03,
        }
        self.assertEqual(time_machine.verdict(coin, 1)["code"], "coin_flip")


class TradeCheckTests(unittest.TestCase):
    def book(self, symbols="NSE:DEMO"):
        return paper_book.create(
            "200000", symbols, "500", "1500", "30000", max_trades=3, max_open=2
        )

    def config(self):
        return {"fee_bps": "5", "fee_flat_inr": "10", "slippage_bps": "5"}

    def test_pass_sizes_to_the_tightest_limit(self):
        result = trade_check.review(
            plan_for(), self.book(), self.config(), at("09:46"), times_for()
        )
        self.assertEqual(result["verdict"], "PASS", result["blocks"])
        self.assertEqual(result["decided_by"], "risk per trade")
        self.assertLessEqual(result["planned_loss_inr"], 500)
        self.assertLessEqual(result["cost_inr"], 30000)
        self.assertGreater(result["qty"], 100)

    def test_blocks_name_their_reasons(self):
        late = trade_check.review(plan_for(), self.book(), self.config(), at("14:40"), times_for())
        self.assertIn("past the 14:30 entry cutoff", late["blocks"])
        other = trade_check.review(
            plan_for(), self.book("NSE:TCS"), self.config(), at("09:46"), times_for()
        )
        self.assertTrue(any("stock list" in reason for reason in other["blocks"]))
        cool = trade_check.review(plan_for(), self.book(), self.config(), at("09:46"), times_for(),
                                  cooldowns={"NSE:DEMO": "lost three times"})  # fmt: skip
        self.assertEqual(cool["verdict"], "BLOCK")

    def test_the_book_accepts_new_picks_only_by_addition(self):
        book = self.book("NSE:TCS")
        wider = paper_book.allow_symbols(book, ["NSE:DEMO"], "scan", at("09:09").isoformat())
        self.assertEqual(wider["symbols"], ["NSE:DEMO", "NSE:TCS"])
        self.assertEqual(wider["allowlist_changes"][0]["added"], ["NSE:DEMO"])
        with self.assertRaises(ValueError):
            paper_book.allow_symbols(book, ["BSE:../x"], "scan", at("09:09").isoformat())


class AlertTests(unittest.TestCase):
    def test_plan_alerts_ring_once_and_only_on_their_day(self):
        rules = price_alerts.add({"rules": []}, price_alerts.from_plan(plan_for()))
        times = times_for()
        quotes = {"NSE:DEMO": {"last": 99.9, "prev_close": 100}}
        rang, state = price_alerts.check(rules, {}, at("10:00"), times, quotes)
        self.assertEqual([item["type"] for item in rang], ["stop"])
        again, _ = price_alerts.check(rules, state, at("10:05"), times, quotes)
        self.assertEqual(again, [])
        later, state = price_alerts.check(rules, state, at("15:16"), times, {})
        self.assertEqual([item["type"] for item in later], ["time"])
        tomorrow, _ = price_alerts.check(
            rules, {}, at("10:00", dt.date(2026, 10, 30)), times, quotes
        )
        self.assertEqual(tomorrow, [])

    def test_percent_moves_and_validation(self):
        rules = price_alerts.add({"rules": []}, [{"id": "demo-pct", "type": "pct_move",
                                                  "symbol": "DEMO", "pct": 3, "direction": "down"}])  # fmt: skip
        rang, _ = price_alerts.check(rules, {}, at("11:00"), times_for(),
                                     {"NSE:DEMO": {"last": 96.5, "prev_close": 100}})  # fmt: skip
        self.assertEqual(len(rang), 1)
        with self.assertRaises(ValueError):
            price_alerts.validate({"id": "X Y", "type": "stop", "symbol": "DEMO", "price": 1})


class AlertRunTests(unittest.TestCase):
    def test_run_check_logs_what_rang_even_without_prices(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = project(Path(temporary))
            path = price_alerts.rules_path(config)
            intraday.write_json(
                path, price_alerts.add({"rules": []}, price_alerts.from_plan(plan_for()))
            )

            def no_prices(symbols):
                raise ValueError("Do today's Kite login first")

            rang = price_alerts.run_check(config, at("15:16"), no_prices)
            self.assertEqual([item["type"] for item in rang], ["time"])
            self.assertEqual(price_alerts.recent(config)[0]["id"], "demo-flat-2026-10-29")
            self.assertEqual(price_alerts.run_check(config, at("15:20"), no_prices), [])


class FilingsTests(unittest.TestCase):
    PIT = {"data": [
        {"symbol": "DEMO", "company": "Demo Ltd", "acqName": "A Promoter", "personCategory": "Promoters",
         "tdpTransactionType": "Buy", "acqMode": "Market Purchase", "secAcq": "10000",
         "secVal": "25000000", "acqfromDt": "20-Oct-2026", "acqtoDt": "21-Oct-2026",
         "date": "23-Oct-2026 18:01"},
        {"symbol": "DEMO", "acqName": "B Employee", "personCategory": "Designated Employee",
         "tdpTransactionType": "Sell", "acqMode": "Market Sale", "secVal": "900000",
         "acqtoDt": "22-Oct-2026", "date": "24-Oct-2026"},
        {"symbol": "PLEDGED", "acqName": "C", "personCategory": "Promoter Group",
         "tdpTransactionType": "Pledge Creation", "acqMode": "Pledge", "acqtoDt": "22-Oct-2026"},
    ]}  # fmt: skip

    def test_insider_rows_summary_and_score(self):
        rows = insider_tracker.parse(self.PIT)
        self.assertEqual(rows[0]["kind"], "market buy")
        self.assertEqual(rows[0]["days_to_disclose"], 2)
        summary = insider_tracker.summary(rows)
        self.assertEqual(
            summary["NSE:DEMO"]["net_market_inr"], 25_000_000
        )  # Employees not counted.
        self.assertEqual(insider_tracker.score(summary["NSE:DEMO"])[0], 1.0)
        self.assertEqual(insider_tracker.score(summary["NSE:PLEDGED"])[0], -0.5)

    XBRL = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:f="http://www.bseindia.com/xbrl/fin">
 <xbrli:context id="Q"><xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="P"><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="Y"><xbrli:period><xbrli:startDate>2025-07-01</xbrli:startDate><xbrli:endDate>2025-09-30</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="S"><xbrli:entity><xbrli:segment>x</xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
 <f:RevenueFromOperations contextRef="Q">12000000000</f:RevenueFromOperations>
 <f:RevenueFromOperations contextRef="S">99</f:RevenueFromOperations>
 <f:RevenueFromOperations contextRef="P">11000000000</f:RevenueFromOperations>
 <f:RevenueFromOperations contextRef="Y">10000000000</f:RevenueFromOperations>
 <f:ProfitBeforeTax contextRef="Q">2000000000</f:ProfitBeforeTax>
 <f:OtherIncome contextRef="Q">600000000</f:OtherIncome>
 <f:ProfitLossForPeriod contextRef="Q">1500000000</f:ProfitLossForPeriod>
 <f:ProfitLossForPeriod contextRef="Y">1200000000</f:ProfitLossForPeriod>
 <f:DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="Q">12.5</f:DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations>
</xbrli:xbrl>"""

    def test_results_compare_like_with_like_and_flag_other_income(self):
        result = results_analyst.analyse(results_analyst.read_xbrl(self.XBRL))
        revenue = result["figures"]["revenue"]
        self.assertEqual(result["quarter_end"], "2026-09-30")
        self.assertEqual(
            (revenue["value"], revenue["yoy_pct"], revenue["qoq_pct"]), (1200.0, 20.0, 9.1)
        )
        self.assertEqual(result["figures"]["net_profit"]["yoy_pct"], 25.0)
        self.assertEqual(result["margins"]["net_margin_pct"], 12.5)
        self.assertTrue(any("other income" in flag for flag in result["flags"]))
        with self.assertRaises(ValueError):
            results_analyst.read_xbrl(b'<!DOCTYPE x [<!ENTITY a "b">]><x/>')


class ScanSetupTests(unittest.TestCase):
    def test_breakout_and_reclaim_tags(self):
        closes = [100 - i * 0.2 for i in range(25)] + [101.0]
        tags = market_scan.setups([{"close": value} for value in closes])
        self.assertIn("breakout_20d", tags)
        self.assertIn("reclaim_ma20", tags)
        self.assertEqual(market_scan.setups([{"close": 1.0}] * 10), [])


class Coordinator:
    def __init__(self, config_path):
        self.config_path = config_path
        self.config = json.loads(config_path.read_text())

    def path(self, name):
        return self.config_path.parent / self.config[name]


class DeskAgentTests(unittest.TestCase):
    def test_a_trigger_is_planned_replayed_and_logged_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = project(Path(temporary))
            coordinator = Coordinator(config)
            fetched = []

            def bars(_, symbol, clock):
                fetched.append(clock)
                return intraday.completed(opening_session(), clock)

            first = trade_desk.tick(coordinator, at("09:46"), bars, lambda symbols: {})
            self.assertEqual(first["cards"][0]["entry"], "TRIGGERED")
            self.assertEqual(first["triggers"], 1)
            card = json.loads((Path(temporary) / "desk" / str(DAY) / "DEMO.json").read_text())
            self.assertEqual(card["plan"]["stop"], 100.0)
            self.assertIn(card["odds"]["verdict"]["code"], time_machine.VERDICTS)
            self.assertIn("no forward paper book", card["check_unavailable"])
            second = trade_desk.tick(coordinator, at("09:51"), bars, lambda symbols: {})
            self.assertEqual(second["triggers"], 0)  # Worked up once per stock per day.
            self.assertEqual(len(fetched), 1)
            logged = price_alerts.recent(config)
            self.assertEqual(len(logged), 1)
            self.assertIn("TRIGGERED", logged[0]["message"])

    def test_the_time_machine_gate_vetoes_only_when_replays_lean_to_the_stop(self):
        ticket = {"price_inr": "102.60", "stop_inr": "102.30", "target_inr": "102.90",
                  "quote_as_of": at("09:45").isoformat()}  # fmt: skip
        with tempfile.TemporaryDirectory() as temporary:
            coordinator = Coordinator(project(Path(temporary), drift=-0.002))
            veto = time_machine.odds_gate(coordinator, "NSE:DEMO", ticket, at("09:46"))
            self.assertIn("time machine: Strongly toward the stop", veto)
            none = time_machine.odds_gate(coordinator, "NSE:NOHISTORY", ticket, at("09:46"))
            self.assertEqual(none, "")  # No stored history: the gate lets it through.
            coordinator.config["timemachine"]["enabled"] = False
            self.assertEqual(
                time_machine.odds_gate(coordinator, "NSE:DEMO", ticket, at("09:46")), ""
            )
        with tempfile.TemporaryDirectory() as temporary:
            rising = Coordinator(project(Path(temporary), drift=0.002))
            self.assertEqual(time_machine.odds_gate(rising, "NSE:DEMO", ticket, at("09:46")), "")


if __name__ == "__main__":
    unittest.main()

"""Strategy rules, loss-avoidance filters, managed exits and the tournament's eligibility."""

import csv
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from decision_pipeline import DailyCoordinator
from test_agent_runtime import FixtureReviewer
from test_autopilot import book_of, enabled
from test_decision_pipeline import setup

import autopilot
import strategies
import tournament

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
DAY = dt.date(2026, 10, 26)
TIMES = {
    "open": dt.datetime(2026, 10, 26, 9, 15, tzinfo=IST),
    "entry_cutoff": dt.datetime(2026, 10, 26, 14, 30, tzinfo=IST),
    "flat_by": dt.datetime(2026, 10, 26, 15, 15, tzinfo=IST),
    "close": dt.datetime(2026, 10, 26, 15, 30, tzinfo=IST),
}


def bars(*ohlc, volume=1000):
    start = TIMES["open"]
    return [
        {
            "t": start + dt.timedelta(minutes=5 * index),
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "volume": volume,
        }
        for index, (o, h, low, c) in enumerate(ohlc)
    ]


RANGE = [(100, 101, 99, 100.5), (100.5, 101, 99.5, 100.8), (100.8, 101, 99.8, 100.6)]
HEALTHY = {"values": {"close": 100, "sma20": 98, "sma50": 95, "rsi14": 60, "atr14": 3}}


class RuleTests(unittest.TestCase):
    def test_orb_fires_once_on_the_first_close_above_the_range(self):
        rows = bars(*RANGE, (100.6, 101.6, 100.5, 101.4))
        signal = strategies.latest_signal(rows, TIMES, [strategies.ORB], HEALTHY)
        self.assertEqual((signal["version"], signal["stop"]), ("orb-v1", 99))
        later = bars(*RANGE, (100.6, 101.6, 100.5, 101.4), (101.4, 102, 101.2, 101.8))
        self.assertIsNone(strategies.latest_signal(later, TIMES, [strategies.ORB], HEALTHY))

    def test_vwap_pullback_needs_a_trend_day_and_a_close_back_above_vwap(self):
        rows = bars(
            *RANGE,
            (100.6, 102, 100.5, 101.8),
            (101.8, 102.5, 101.5, 102.2),
            (102.2, 102.3, 100.9, 101.0),
            (101.0, 101.8, 100.95, 101.7),
        )
        vwap = strategies.session_vwap(rows)
        self.assertLess(min(rows[-1]["low"], rows[-2]["low"]), vwap * 1.001)
        signal = strategies.latest_signal(rows, TIMES, [strategies.VWAP], HEALTHY)
        self.assertEqual(signal["version"], "vwap-pullback-v1", signal)
        self.assertLess(signal["stop"], rows[-1]["low"])
        flat = bars(*RANGE, *[(100.6, 100.9, 100.4, 100.7)] * 4)
        self.assertIsNone(strategies.latest_signal(flat, TIMES, [strategies.VWAP], HEALTHY))

    def test_no_signal_after_the_entry_cutoff(self):
        rows = bars(*RANGE, (100.6, 101.6, 100.5, 101.4))
        late = {**TIMES, "entry_cutoff": rows[-1]["t"]}
        self.assertIsNone(strategies.latest_signal(rows, late, [strategies.ORB], HEALTHY))


class FilterTests(unittest.TestCase):
    def test_each_filter_blocks_with_its_own_reason(self):
        cases = {
            "stretched": {"values": {**HEALTHY["values"], "rsi14": 80}},
            "trend is down": {"values": {"close": 90, "sma20": 95, "sma50": 99, "atr14": 3}},
            "wider than one daily ATR": {"values": {**HEALTHY["values"], "atr14": 1}},
        }
        for words, context in cases.items():
            self.assertIn(words, strategies.regime_block(context, 101.4, 99))
        self.assertIn("noise", strategies.regime_block(HEALTHY, 100, 99.95))
        self.assertIsNone(strategies.regime_block(HEALTHY, 101.4, 99))
        rows = bars(*RANGE, (100.6, 101.6, 100.5, 101.4))
        blocked = strategies.latest_signal(rows, TIMES, [strategies.ORB], cases["stretched"])
        self.assertIn("orb-v1: daily RSI 80", blocked["blocked"][0])


class ManagedExitTests(unittest.TestCase):
    def test_breakeven_then_trailing_then_time_stop(self):
        flat = bars(*[(100, 100.5, 99.8, 100.2)] * 3)
        self.assertEqual(strategies.managed_stop(100, 98, 0.1, flat)["rule"], "initial")
        up_one_r = bars((100, 102.1, 99.9, 102))
        breakeven = strategies.managed_stop(100, 98, 0.1, up_one_r)
        self.assertEqual((breakeven["rule"], breakeven["stop"]), ("breakeven", 100.1))
        trailing = strategies.managed_stop(100, 98, 0.1, bars((100, 104, 99.9, 103.5)))
        self.assertEqual((trailing["rule"], trailing["stop"]), ("trailing", 102))
        stalled = bars(*[(100, 100.5, 99.8, 100.2)] * 12)
        self.assertTrue(strategies.managed_stop(100, 98, 0.1, stalled)["time_stop"])

    def test_the_coordinator_exits_at_breakeven_once_price_has_reached_one_r(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            coordinator, now = setup(directory)
            enabled(coordinator, require_pick=False)
            autopilot.apply(coordinator, coordinator.run_once(), now)
            held = book_of(coordinator)["positions"]["NSE:TEST"]
            entry, stop = float(held["entry_inr"]), float(held["stop_inr"])
            with (directory / "current-bars.csv").open("a", newline="") as stream:
                writer = csv.writer(stream)
                for index in range(4):
                    at = now + dt.timedelta(minutes=5 * index)
                    peak = entry + 1.2 * (entry - stop) if index == 1 else entry + 0.2
                    writer.writerow(
                        ("NSE:TEST", at.isoformat(), entry, round(peak, 2), entry - 0.1,
                         entry, 100000, "OFFLINE_TEST_PROVIDER")
                    )  # fmt: skip
            later = now + dt.timedelta(minutes=20)
            quote = {
                "as_of": later.isoformat(),
                "bid_inr": f"{entry:.2f}",
                "ask_inr": f"{entry + 0.02:.2f}",
                "source": "OFFLINE_TEST_QUOTE",
            }
            (directory / "quotes.json").write_text(json.dumps({"NSE:TEST": quote}))
            closing = enabled(
                DailyCoordinator(
                    directory / "pipeline.json", reviewer=FixtureReviewer(), now=lambda: later
                ),
                require_pick=False,
            )
            report = closing.run_once(allow_entries=False)
            call = report["calls"][0]
            self.assertEqual(call["decision"], "SELL_PAPER_PROPOSAL", call)
            self.assertEqual(call["proposal"]["reason"], "breakeven_stop")
            self.assertGreater(float(call["managed_exit"]["stop"]), entry)


class PlaybookTests(unittest.TestCase):
    def test_unproven_stale_and_judge_narrowed_playbooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = {"require_proven": True, "enabled": list(strategies.STRATEGIES)}
            empty = strategies.allowed_for(root, settings, "NSE:TEST", "2026-10-26")
            self.assertEqual(empty["allowed"], [])
            card = {"as_of": "2026-10-10T16:00:00+05:30", "strategies": {}}
            card["strategies"] = {name: {"eligible": True} for name in strategies.STRATEGIES}
            strategies.scorecard_path(root).write_text(json.dumps(card))
            stale = strategies.allowed_for(root, settings, "NSE:TEST", "2026-10-26")
            self.assertIn("days old", stale["basis"])
            card["as_of"] = "2026-10-25T16:00:00+05:30"
            strategies.scorecard_path(root).write_text(json.dumps(card))
            reports = root / "reports"
            reports.mkdir()
            (reports / "premarket-2026-10-26.json").write_text(
                json.dumps(
                    {
                        "selection": {
                            "judge": {"picks": [{"symbol": "NSE:TEST", "strategy": "orb-v1"}]}
                        }
                    }
                )
            )
            narrowed = strategies.allowed_for(root, settings, "NSE:TEST", "2026-10-26", reports)
            self.assertEqual(narrowed["allowed"], ["orb-v1"])
            other = strategies.allowed_for(root, settings, "NSE:OTHER", "2026-10-26", reports)
            self.assertEqual(other["allowed"], list(strategies.STRATEGIES))


class TournamentTests(unittest.TestCase):
    CFG = {**tournament.DEFAULTS}

    def day(self, *later):
        return {
            "date": str(DAY),
            "times": TIMES,
            "bars": bars(*RANGE, (100.6, 101.6, 100.5, 101.4), *later),
        }

    def test_a_bar_touching_stop_and_target_counts_as_a_loss(self):
        trade = tournament.simulate_day(
            "NSE:T", self.day((101.4, 110, 98, 101)), "orb-v1", HEALTHY, self.CFG, 1.0
        )
        self.assertEqual(trade["exit_reason"], "initial_stop")
        self.assertLess(trade["net_inr"], 0)

    def test_a_gap_through_the_stop_fills_at_the_open_not_the_stop(self):
        trade = tournament.simulate_day(
            "NSE:T",
            self.day((101.4, 101.5, 101.3, 101.4), (97, 97.5, 96.5, 97)),
            "orb-v1",
            HEALTHY,
            self.CFG,
            1.0,
        )
        self.assertEqual(trade["exit_reason"], "initial_stop")
        self.assertLess(trade["exit"], 97)

    def test_eligibility_names_every_failed_condition(self):
        dates = [f"2026-0{month}-01" for month in range(1, 7)]
        losing = [
            {"date": dates[i % 6], "net_inr": -100.0, "r": -1.0, "exit_reason": "stop"}
            for i in range(12)
        ]
        eligible, reasons, folds = tournament.judge(losing, dates, tournament.RULES)
        self.assertFalse(eligible)
        joined = " ".join(reasons)
        for words in ("only 12 trades", "lost INR", "profitable in 0 of 3", "most recent"):
            self.assertIn(words, joined)
        winning = [
            {
                "date": dates[i % 6],
                "net_inr": 300.0 if i % 2 else -100.0,
                "r": 1.0,
                "exit_reason": "target",
            }
            for i in range(60)
        ]
        self.assertTrue(tournament.judge(winning, dates, tournament.RULES)[0])
        self.assertEqual(len(folds), 3)


if __name__ == "__main__":
    unittest.main()

"""Swing Monte Carlo: odds over several sessions, overnight gaps and rupees after costs."""

import json
import random
import tempfile
import unittest
from pathlib import Path

import swing
import swing_machine
from test_swing import breakout_day, calm, dated, project, store, trend

COSTS = {"fee_bps": 12, "fee_flat_inr": 20, "slippage_bps": 5}


def drifting(count: int, drift: float, gap: float = 0.0, seed: int = 3) -> list[dict]:
    """Daily candles with a chosen drift and occasional overnight gaps of ``gap``."""
    rng, bars, price = random.Random(seed), [], 100.0
    for index in range(count):
        jump = -gap if gap and index % 9 == 0 else 0.0
        opened = price * (1 + jump)
        close = opened * (1 + rng.gauss(drift, 0.012))
        bars.append({"open": opened, "high": max(opened, close) * 1.006, "low": min(opened, close) * 0.994,
                     "close": close, "volume": 1e6, "date": f"d{index:03d}"})  # fmt: skip
        price = close
    return bars


class MonteCarloTests(unittest.TestCase):
    def test_same_seed_same_result_and_the_odds_add_up(self):
        bars = drifting(260, 0.001)
        first = swing_machine.for_plan(bars, 100, 96, 108, 5, 100, COSTS, replays=2000)
        again = swing_machine.for_plan(bars, 100, 96, 108, 5, 100, COSTS, replays=2000)
        first.pop("computed_at"), again.pop("computed_at")
        self.assertEqual(first, again)
        self.assertAlmostEqual(
            first["target_pct"] + first["stopped_pct"] + first["time_exit_pct"], 100, delta=0.2
        )
        self.assertEqual(sum(first["histogram"]["counts"]), 2000)
        days = first["by_day"]
        self.assertEqual(len(days), 5)
        self.assertTrue(
            all(a["target_pct"] <= b["target_pct"] for a, b in zip(days, days[1:], strict=False))
        )
        self.assertLessEqual(first["p5_pnl_inr"], first["median_pnl_inr"])
        self.assertLessEqual(first["median_pnl_inr"], first["p95_pnl_inr"])

    def test_a_falling_stock_expects_a_loss_and_gaps_show_up_as_gap_stops(self):
        falling = swing_machine.for_plan(
            drifting(260, -0.004), 100, 96, 108, 5, 100, COSTS, replays=2000
        )
        rising = swing_machine.for_plan(
            drifting(260, 0.004), 100, 96, 108, 5, 100, COSTS, replays=2000
        )
        self.assertLess(falling["expected_pnl_inr"], 0)
        self.assertGreater(rising["expected_pnl_inr"], falling["expected_pnl_inr"])
        gappy = swing_machine.for_plan(
            drifting(260, 0.0, gap=0.06), 100, 97, 106, 5, 100, COSTS, replays=2000
        )
        self.assertGreater(gappy["exits_pct"]["gap stop"], 0)
        self.assertLess(gappy["worst_inr"], -gappy["planned_loss_inr"])  # A gap can cost more.

    def test_costs_lower_every_outcome_and_bad_plans_are_refused(self):
        bars = drifting(260, 0.001)
        free = swing_machine.for_plan(
            bars,
            100,
            96,
            108,
            5,
            100,
            {"fee_bps": 0, "fee_flat_inr": 0, "slippage_bps": 0},
            replays=1000,
        )
        paid = swing_machine.for_plan(bars, 100, 96, 108, 5, 100, COSTS, replays=1000)
        self.assertLess(paid["expected_pnl_inr"], free["expected_pnl_inr"])
        with self.assertRaises(ValueError):
            swing_machine.for_plan(bars, 100, 101, 108, 5, 100, COSTS)
        with self.assertRaises(ValueError):
            swing_machine.for_plan(bars[:30], 100, 96, 108, 5, 100, COSTS)


class DeskOddsTests(unittest.TestCase):
    def test_scan_candidates_carry_odds_and_a_losing_simulation_blocks_entry(self):
        import datetime as dt

        import intraday

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            config = project(folder)
            bars = dated(breakout_day(trend(80)), last="2026-10-29")
            store(folder, {"NSE:DEMO": bars})
            intraday.write_json(
                folder / "swing-scorecard.json", {"eligible": ["vol-breakout-v1"], "as_of": "x"}
            )
            report = swing.scan(config, dt.date(2026, 10, 29), lambda day, window: {})
            odds = report["candidates"][0]["odds"]
            self.assertIn("expected_pnl_inr", odds)
            self.assertEqual(odds["hold_days"], 5)
            # Force the simulation to expect a loss: the entry must be skipped.
            path = folder / "swing-candidates-2026-10-29.json"
            saved = json.loads(path.read_text())
            saved["candidates"][0]["odds"]["expected_pnl_inr"] = -50.0
            path.write_text(json.dumps(saved))
            swing.create_book(config, "100000", "500", "1500", "25000")
            morning = dt.datetime(2026, 10, 30, 9, 20, tzinfo=intraday.IST)
            calm(folder, morning)
            price = round(bars[-1]["close"] * 1.005, 2)
            quote = {"last_price": price, "ohlc": {"open": price}, "timestamp": "2026-10-30 09:19:55",
                     "lower_circuit_limit": price * 0.8, "upper_circuit_limit": price * 1.2,
                     "depth": {"buy": [{"price": price - 0.05}], "sell": [{"price": price}]}}  # fmt: skip
            result = swing.enter(config, morning, lambda s: {"NSE:DEMO": quote})
            self.assertIn("expects a loss", result["skipped"]["NSE:DEMO"])

    def test_the_dashboard_action_simulates_a_typed_plan_and_validates_it(self):
        from setup_api import ApiError, SetupApi

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            config = project(folder)
            store(folder, {"NSE:DEMO": dated(trend(120), last="2026-10-29")})
            api = SetupApi(folder)
            api.config = config
            close = trend(120)[-1]["close"]
            result, _, _ = api.do_swing_simulate({"symbol": "demo", "entry": close, "stop": close * 0.96,
                                                  "target": close * 1.08, "hold_days": 3})  # fmt: skip
            self.assertEqual(result["symbol"], "NSE:DEMO")
            self.assertEqual(len(result["by_day"]), 3)
            for bad in ({"symbol": "DEMO", "entry": "x", "stop": 1, "target": 2},
                        {"symbol": "DEMO", "entry": 100, "stop": 96, "target": 108, "hold_days": 99},
                        {"symbol": "NOPE", "entry": 100, "stop": 96, "target": 108}):  # fmt: skip
                with self.assertRaises(ApiError):
                    api.do_swing_simulate(bad)


if __name__ == "__main__":
    unittest.main()

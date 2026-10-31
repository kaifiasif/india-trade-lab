"""Swing desk: volume-confirmed setups, the swing tournament, entries and exits in the journal."""

import datetime as dt
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import intraday
import market_service
import price_alerts
import swing

import paper_book

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = ROOT / "skills/day-trader-india/assets/nse-sessions-2026.json"
MANIFEST = json.loads(SESSIONS.read_text())
DAYS = sorted(day for day, s in MANIFEST["sessions"].items() if s)


def days_before(last: str, count: int) -> list[str]:
    earlier = [day for day in DAYS if day <= last]
    return earlier[-count:]


def trend(count: int, start: float = 100.0, step: float = 0.004, volume: float = 1_000_000):
    """A steady uptrend with ordinary volume and alternating small down days."""
    bars, price = [], start
    for index in range(count):
        move = step if index % 3 else -step / 2
        close = price * (1 + move)
        bars.append({"open": price, "high": max(price, close) * 1.004, "low": min(price, close) * 0.996,
                     "close": close, "volume": volume})  # fmt: skip
        price = close
    return bars


def dated(bars: list[dict], last: str = "2026-10-29") -> list[dict]:
    return [
        {**bar, "date": day} for bar, day in zip(bars, days_before(last, len(bars)), strict=True)
    ]


def breakout_day(bars: list[dict], ratio: float = 3.0) -> list[dict]:
    """Append a strong close above the 20-day high on ``ratio`` x volume."""
    prior = bars[-20:]
    high = max(bar["high"] for bar in prior)
    close = high * 1.02
    low = close * 0.97
    return bars + [{"open": low * 1.002, "high": close * 1.001, "low": low, "close": close,
                    "volume": prior[0]["volume"] * ratio}]  # fmt: skip


CFG = {**swing.DEFAULTS}


class SetupTests(unittest.TestCase):
    def test_a_breakout_needs_volume_and_a_strong_close(self):
        bars = dated(breakout_day(trend(80)))
        hit = swing.signal(bars, list(swing.SETUPS), CFG, 0)
        self.assertEqual(hit["strategy"], "vol-breakout-v1")
        self.assertGreaterEqual(hit["vol_ratio"], 2.0)
        self.assertLess(hit["stop"], hit["close"])
        quiet = dated(breakout_day(trend(80), ratio=1.2))
        self.assertIsNone(swing.vol_breakout(quiet, CFG))
        weak = [dict(bar) for bar in bars]
        weak[-1]["close"] = weak[-1]["low"] + 0.2 * (weak[-1]["high"] - weak[-1]["low"])
        self.assertIsNone(swing.vol_breakout(weak, CFG))

    def test_a_pocket_pivot_beats_every_recent_down_day(self):
        bars = trend(80)
        last = bars[-1]
        bars.append({"open": last["close"], "high": last["close"] * 1.012, "low": last["close"] * 0.998,
                     "close": last["close"] * 1.01, "volume": 2_500_000})  # fmt: skip
        self.assertIsNotNone(swing.pocket_pivot(dated(bars), CFG))
        bars[-1]["volume"] = 900_000  # Below the down days' volume.
        self.assertIsNone(swing.pocket_pivot(dated(bars), CFG))

    def test_a_dryup_pullback_reverses_on_expanding_volume(self):
        bars = trend(80, step=0.006)
        peak = bars[-1]["close"]
        for index in range(4):  # Pull back 4% on thin volume.
            price = peak * (1 - 0.01 * (index + 1))
            bars.append({"open": price * 1.004, "high": price * 1.006, "low": price * 0.997, "close": price,
                         "volume": 450_000})  # fmt: skip
        prior = bars[-1]
        close = prior["high"] * 1.01
        bars.append({"open": prior["close"], "high": close * 1.002, "low": prior["close"] * 0.998,
                     "close": close, "volume": 1_200_000})  # fmt: skip
        hit = swing.dryup_pullback(dated(bars), CFG)
        self.assertIsNotNone(hit)
        self.assertIn("normal volume", hit["reason"])

    def test_filters_skip_climaxes_and_bad_stops(self):
        bars = dated(trend(80))
        bars[-6]["close"] = bars[-1]["close"] / 1.2
        self.assertIn("15%", swing.blocked(bars, bars[-1]["close"] * 0.97, 0))
        self.assertIn("too much", swing.blocked(dated(trend(80)), 50.0, 0))
        self.assertIn("noise", swing.blocked(dated(trend(80)), trend(80)[-1]["close"] * 0.999, 0))


class TournamentTests(unittest.TestCase):
    def test_trades_exit_by_stop_target_or_day_five_and_costs_double(self):
        bars = dated(
            breakout_day(trend(80)) + trend(10, start=breakout_day(trend(80))[-1]["close"] * 1.01)
        )
        base = swing.simulate("NSE:DEMO", bars, "vol-breakout-v1", CFG, 1.0)
        doubled = swing.simulate("NSE:DEMO", bars, "vol-breakout-v1", CFG, 2.0)
        self.assertEqual(len(base), 1)
        trade = base[0]
        self.assertIn(trade["exit_reason"], ("target", "stop", "trailing stop", "gap stop", "time"))
        held = DAYS.index(trade["exit_date"]) - DAYS.index(trade["date"])
        self.assertLessEqual(held, CFG["max_hold_days"] - 1)
        self.assertLess(doubled[0]["net_inr"], trade["net_inr"])

    def test_scorecard_judges_each_setup_at_double_costs(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = project(Path(temporary))
            data = {"NSE:DEMO": dated(breakout_day(trend(80)) + trend(5, start=130))}
            card = swing.tournament(config, data)
            self.assertEqual(set(card["strategies"]), set(swing.SETUPS))
            self.assertEqual(card["eligible"], [])  # One trade proves nothing.
            self.assertIn("only", card["strategies"]["vol-breakout-v1"]["reasons"][0])
            self.assertTrue((Path(temporary) / "swing-scorecard.json").is_file())
            row = card["strategies"]["vol-breakout-v1"]
            self.assertIn("luck_percentile", row)  # Compared with random-entry twins.
            self.assertIn("deflated_sharpe", row)
            self.assertEqual(card["trials"], len(swing.SETUPS))  # Every variant is counted.
            self.assertTrue((Path(temporary) / "trials.json").is_file())


def calm(folder: Path, at: dt.datetime) -> None:
    (folder / "market-guard.json").write_text(json.dumps({"at": at.isoformat(), "blocks": []}))
    (folder / "surveillance.json").write_text(
        json.dumps(
            {"checked_at": at.isoformat(), "sources": {"indicator": str(at.date())}, "stocks": {}}
        )
    )


def project(folder: Path) -> Path:
    shutil.copy(SESSIONS, folder / "sessions.json")
    (folder / "pipeline.json").write_text(json.dumps({
        "sessions": "sessions.json", "book": "paper.sqlite", "min_turnover_inr": 0,
        "swing": {"require_proven": True},
        # Mechanics tests: the 1.5x desk default is tested on its own below.
        "safety": {"min_net_reward_risk": 1.0},
    }))  # fmt: skip
    return folder / "pipeline.json"


def store(folder: Path, data: dict[str, list[dict]]) -> None:
    with sqlite3.connect(folder / "scan.sqlite") as conn:
        conn.execute("CREATE TABLE daily (symbol TEXT, date TEXT, open REAL, high REAL, low REAL, "
                     "close REAL, volume REAL, PRIMARY KEY(symbol, date))")  # fmt: skip
        for symbol, bars in data.items():
            conn.executemany(
                "INSERT INTO daily VALUES (?,?,?,?,?,?,?)",
                [
                    (symbol, b["date"], b["open"], b["high"], b["low"], b["close"], b["volume"])
                    for b in bars
                ],
            )


def quote(price: float, opened: float, low: float | None = None, at: str = "") -> dict:
    return {"last_price": price, "ohlc": {"open": opened, "low": low or price * 0.99}, "timestamp": at,
            "lower_circuit_limit": price * 0.8, "upper_circuit_limit": price * 1.2,
            "depth": {"buy": [{"price": round(price - 0.05, 2)}], "sell": [{"price": price}]}}  # fmt: skip


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.config = project(self.folder)
        bars = dated(breakout_day(trend(80)), last="2026-10-29")
        store(self.folder, {"NSE:DEMO": bars, "NSE:STALE": dated(breakout_day(trend(80)), last="2026-10-20"),
                            "NSE:EVENT": dated(breakout_day(trend(80)), last="2026-10-29")})  # fmt: skip
        self.signal_bar = bars[-1]
        intraday.write_json(
            self.folder / "swing-scorecard.json", {"eligible": ["vol-breakout-v1"], "as_of": "x"}
        )

    def tearDown(self):
        self.temporary.cleanup()

    def scan(self):
        return swing.scan(
            self.config,
            dt.date(2026, 10, 29),
            lambda day, window: {"EVENT": [{"purpose": "Financial Results", "date": "2026-11-02"}]},
        )

    def test_scan_skips_stale_candles_and_events(self):
        report = self.scan()
        self.assertEqual([row["symbol"] for row in report["candidates"]], ["NSE:DEMO"])
        self.assertTrue(report["candidates"][0]["proven"])
        self.assertIn("NSE:EVENT", report["skipped_for_events"])

    def test_entry_is_recorded_with_evidence_and_exits_follow_the_rules(self):
        self.scan()
        swing.create_book(self.config, "100000", "500", "1500", "25000")
        close, stop = (
            self.signal_bar["close"],
            swing.scan(self.config, dt.date(2026, 10, 29), lambda d, w: {})["candidates"][0][
                "stop"
            ],
        )
        morning = dt.datetime(2026, 10, 30, 9, 20, tzinfo=intraday.IST)
        price = round(close * 1.005, 2)
        calm(self.folder, morning)
        result = swing.enter(
            self.config,
            morning,
            lambda symbols: {"NSE:DEMO": quote(price, price, at="2026-10-30 09:19:50")},
        )
        self.assertEqual([row["symbol"] for row in result["entered"]], ["NSE:DEMO"], result)
        book = swing.read_book(self.config)
        position = book["positions"]["NSE:DEMO"]
        self.assertLessEqual(float(position["planned_loss_inr"]), 500)
        self.assertEqual(
            book["events"][-1]["pretrade_evidence"]["checks"]["no_material_event"], True
        )
        ids = {
            rule["id"]
            for rule in price_alerts.load(price_alerts.rules_path(self.config), {"rules": []})[
                "rules"
            ]
        }
        self.assertIn("demo-swing-stop", ids)
        again = swing.enter(self.config, morning + dt.timedelta(minutes=5), lambda s: {})
        self.assertEqual(again["status"], "already entered today")
        # Held overnight: the swing book allows it; no exit while between stop and target.
        next_day = dt.datetime(2026, 11, 2, 11, 0, tzinfo=intraday.IST)
        hold = swing.manage(
            self.config, next_day, lambda s: {"NSE:DEMO": quote(price * 1.01, price)}
        )
        self.assertEqual(hold["exited"], [])
        stopped = swing.manage(self.config, next_day + dt.timedelta(hours=1),
                               lambda s: {"NSE:DEMO": quote(stop * 0.995, price)})  # fmt: skip
        self.assertEqual(stopped["exited"][0]["why"], "stop")
        self.assertLess(float(stopped["exited"][0]["net_inr"]), 0)
        self.assertEqual(swing.read_book(self.config)["positions"], {})
        ids = {
            rule["id"]
            for rule in price_alerts.load(price_alerts.rules_path(self.config), {"rules": []})[
                "rules"
            ]
        }
        self.assertNotIn("demo-swing-stop", ids)

    def test_time_exit_after_five_sessions_and_trailing(self):
        self.scan()
        swing.create_book(self.config, "100000", "500", "1500", "25000")
        price = round(self.signal_bar["close"] * 1.005, 2)
        calm(self.folder, dt.datetime(2026, 10, 30, 9, 20, tzinfo=intraday.IST))
        swing.enter(self.config, dt.datetime(2026, 10, 30, 9, 20, tzinfo=intraday.IST),
                    lambda s: {"NSE:DEMO": quote(price, price, at="2026-10-30 09:19:55")})  # fmt: skip
        state = json.loads((self.folder / "swing-state.json").read_text())["positions"]["NSE:DEMO"]
        risk = state["entry"] - state["initial_stop"]
        up = state["entry"] + 1.2 * risk
        close_of_day = dt.datetime(2026, 11, 2, 15, 25, tzinfo=intraday.IST)
        trailed = swing.manage(
            self.config, close_of_day, lambda s: {"NSE:DEMO": quote(up, price, low=up * 0.99)}
        )
        self.assertEqual(trailed["trailed"][0]["rule"], "breakeven")
        fifth = dt.datetime(2026, 11, 6, 15, 25, tzinfo=intraday.IST)
        done = swing.manage(
            self.config, fifth, lambda s: {"NSE:DEMO": quote(up, price, low=up * 0.99)}
        )
        self.assertTrue(done["exited"][0]["why"].startswith("time exit"))

    def test_reward_after_costs_below_the_desk_minimum_is_refused(self):
        self.scan()
        swing.create_book(self.config, "100000", "500", "1500", "25000")
        settings = json.loads(self.config.read_text())
        settings["safety"]["min_net_reward_risk"] = 1.5
        self.config.write_text(json.dumps(settings))
        morning = dt.datetime(2026, 10, 30, 9, 20, tzinfo=intraday.IST)
        calm(self.folder, morning)
        price = round(self.signal_bar["close"] * 1.005, 2)
        result = swing.enter(
            self.config,
            morning,
            lambda s: {"NSE:DEMO": quote(price, price, at="2026-10-30 09:19:50")},
        )
        self.assertIn("reward after costs", result["skipped"]["NSE:DEMO"])

    def test_no_entries_when_nothing_is_proven_or_events_unchecked(self):
        intraday.write_json(self.folder / "swing-scorecard.json", {"eligible": [], "as_of": "x"})
        self.scan()
        swing.create_book(self.config, "100000", "500", "1500", "25000")
        result = swing.enter(
            self.config, dt.datetime(2026, 10, 30, 9, 20, tzinfo=intraday.IST), lambda s: {}
        )
        self.assertIn("sitting out", result["status"])

    def test_the_swing_book_is_separate_and_holds_overnight(self):
        book = paper_book.create(
            "100000", "NSE:A", "500", "1500", "25000", style="swing", max_open=3
        )
        self.assertEqual(book["style"], "swing")
        intraday_book = paper_book.create("100000", "NSE:A", "250", "750", "15000")
        self.assertNotIn("style", intraday_book)
        swing.create_book(self.config, "100000", "500", "1500", "25000")
        with self.assertRaises(ValueError):  # Never overwritten.
            swing.create_book(self.config, "100000", "500", "1500", "25000")


class WorkerTests(unittest.TestCase):
    def test_the_session_worker_runs_the_desk_agent_and_the_swing_desk(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy(SESSIONS, root / "sessions.json")
            coordinator = SimpleNamespace(
                path=lambda name: root / "sessions.json", config_path=root / "pipeline.json",
                config={"trade_desk": {"enabled": True}, "swing": {"enabled": True}},
                run_once=lambda allow_entries: {"status": "OK", "run_id": "r1"},
            )  # fmt: skip
            now = dt.datetime.fromisoformat("2026-10-30T10:00:00+05:30")
            with (
                patch.object(market_service.autopilot, "apply", return_value={"enabled": False}),
                patch.object(
                    market_service.trade_desk,
                    "tick",
                    return_value={"status": "OPEN", "triggers": 1},
                ) as desk,
                patch.object(
                    market_service.swing, "tick", return_value={"enter": {}, "manage": {}}
                ) as swing_tick,
            ):
                result = market_service.MarketService(
                    root / "pipeline.json", coordinator=coordinator, now=lambda: now
                ).tick()
            desk.assert_called_once()
            swing_tick.assert_called_once()
            self.assertEqual(result["desk"]["triggers"], 1)

    def test_the_worker_recovers_once_then_reads_conditions_and_squares_off_every_tick(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy(SESSIONS, root / "sessions.json")
            coordinator = SimpleNamespace(
                path=lambda name: root / "sessions.json", config_path=root / "pipeline.json",
                config={"trade_desk": {"enabled": False}, "swing": {"enabled": False}},
                run_once=lambda allow_entries: {"status": "OK", "run_id": "r1"},
            )  # fmt: skip
            now = dt.datetime.fromisoformat("2026-10-30T10:00:00+05:30")
            safety = market_service.safety
            with (
                patch.object(market_service.autopilot, "apply", return_value={"enabled": False}),
                patch.object(safety, "recover", return_value={"books": {}}) as recover,
                patch.object(safety, "refresh_conditions", return_value={"blocks": []}) as read,
                patch.object(safety, "square_off", return_value={"status": "not yet"}) as close,
            ):
                worker = market_service.MarketService(root / "pipeline.json", coordinator=coordinator,
                                                      now=lambda: now, quotes=lambda s: {})  # fmt: skip
                worker.tick()
                worker.tick()
            self.assertEqual(recover.call_count, 1)
            self.assertEqual((read.call_count, close.call_count), (2, 2))


if __name__ == "__main__":
    unittest.main()

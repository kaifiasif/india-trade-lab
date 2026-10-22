"""Exercise the session engine with synthetic quotes only; no broker or network calls."""

import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from engine import (
    BAR,
    Engine,
    EngineConfig,
    EngineStore,
    EntryIntent,
    OpeningRangeBreakout,
    PaperBroker,
    Phase,
    Quote,
)
from paper_book import create, fill

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "skills/day-trader-india/assets"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SYMBOL = "NSE:DEMO"


def at(clock: str) -> dt.datetime:
    return dt.datetime.fromisoformat(f"2026-10-19T{clock}:00+05:30")


SESSION = {
    "open": at("09:15"),
    "entry_cutoff": at("14:30"),
    "flat_by": at("15:15"),
    "close": at("15:30"),
}


def quote(clock: str, bid: str, ask: str | None = None, **bar: str) -> Quote:
    """Return a made-up quote for software tests, never evidence for a real symbol."""
    return Quote(
        symbol=bar.pop("symbol", SYMBOL),
        as_of=at(clock),
        bid=Decimal(bid),
        ask=Decimal(ask or bid),
        source="SYNTHETIC TEST ONLY",
        **{key: Decimal(value) for key, value in bar.items()},
    )


class Scripted:
    """Propose one entry when told to; records how often it was consulted."""

    def __init__(self, stop: str = "98", target: str = "106", qty: int = 10) -> None:
        self.armed = False
        self.calls = 0
        self.intent = (Decimal(stop), Decimal(target), qty)

    def on_quote(self, q: Quote, context: dict) -> EntryIntent | None:
        self.calls += 1
        if not self.armed:
            return None
        self.armed = False
        stop, target, qty = self.intent
        return EntryIntent(q.symbol, qty, stop, target, "scripted")


def build(strategy=None, **overrides) -> tuple[Engine, PaperBroker, list]:
    book = create("100000", SYMBOL, "250", "750", "15000", replay=True, max_open=1)
    broker = PaperBroker(book, Decimal(5))
    settings = {
        "symbols": (SYMBOL,),
        "fee_bps": Decimal(5),
        "fee_flat": Decimal(10),
        "slippage_bps": Decimal(5),
    }
    settings.update(overrides)
    alerts: list = []
    engine = Engine(
        EngineConfig(**settings),
        SESSION,
        broker,
        strategy or Scripted(),
        notifier=lambda kind, payload: alerts.append(kind),
    )
    return engine, broker, alerts


def enter(engine: Engine, clock: str = "10:00", bid: str = "100") -> list:
    engine.strategy.armed = True
    return engine.on_quote(quote(clock, bid), at(clock))


class EngineTests(unittest.TestCase):
    def test_phases_follow_the_session_clock(self):
        engine, _, _ = build()
        engine.tick(at("09:00"))
        self.assertEqual(engine.phase, Phase.PRE_OPEN)
        engine.tick(at("09:20"))
        self.assertEqual(engine.phase, Phase.SCANNING)
        enter(engine)
        self.assertEqual(engine.phase, Phase.IN_TRADE)
        engine.on_quote(quote("15:16", "101"), at("15:16"))
        self.assertEqual(engine.phase, Phase.CLOSED)
        with self.assertRaises(ValueError):
            engine.tick(at("15:00"))

    def test_entry_fills_through_journal_and_tracks_exit_plan(self):
        engine, broker, alerts = build()
        [result] = enter(engine)
        self.assertEqual(result.status, "filled")
        self.assertEqual(broker.positions(), {SYMBOL: 10})
        self.assertEqual(engine.trades[SYMBOL]["stop"], "98")
        self.assertEqual(broker.book["events"][0]["id"], "2026-10-19:NSE:DEMO:E1")
        self.assertIn("order", alerts)

    def test_stop_is_assumed_before_target_in_an_ambiguous_bar(self):
        engine, broker, _ = build()
        enter(engine)
        bar = quote("10:05", "101", open="100", high="107", low="97")
        [result] = engine.on_quote(bar, at("10:05"))
        self.assertEqual([e for e in engine.log if e["kind"] == "order"][-1]["reason"], "stop")
        self.assertEqual(result.status, "filled")
        self.assertEqual(broker.positions(), {})

    def test_gap_through_stop_fills_at_the_worse_open(self):
        engine, broker, _ = build()
        enter(engine)
        engine.on_quote(quote("10:05", "95", open="95", high="96", low="94"), at("10:05"))
        exit_event = broker.book["events"][-1]
        self.assertEqual(exit_event["quote_inr"], "95")

    def test_target_and_square_off_exits(self):
        engine, broker, _ = build()
        enter(engine)
        engine.on_quote(quote("10:05", "105", open="104", high="106.5", low="103"), at("10:05"))
        self.assertEqual([e for e in engine.log if e["kind"] == "order"][-1]["reason"], "target")
        engine, broker, _ = build()
        enter(engine)
        engine.on_quote(quote("15:15", "100.5"), at("15:15"))
        self.assertEqual(engine.log[-1]["reason"], "square_off")
        self.assertEqual(broker.positions(), {})

    def test_retried_order_id_never_double_fills(self):
        engine, broker, _ = build()
        [first] = enter(engine)
        order_id = first.client_order_id
        engine.trades.clear()
        engine.entries.clear()
        [retry] = enter(engine, clock="10:01")
        self.assertEqual(retry.client_order_id, order_id)
        self.assertEqual(retry.status, "duplicate")
        self.assertEqual(sum(e["side"] == "buy" for e in broker.book["events"]), 1)

    def test_bad_quotes_are_rejected_without_consulting_the_strategy(self):
        engine, _, _ = build()
        cases = [
            (quote("10:00", "100"), at("10:03")),  # stale
            (quote("10:00", "100"), at("09:59")),  # future
            (quote("10:00", "101", "100"), at("10:00")),  # crossed
            (quote("10:00", "100", symbol="NSE:OTHER"), at("10:00")),
        ]
        for bad, now in cases:
            self.assertEqual(engine.on_quote(bad, max(now, engine.clock or now)), [])
        self.assertEqual(engine.strategy.calls, 0)
        self.assertEqual(sum(e["kind"] == "quote_rejected" for e in engine.log), 4)

    def test_gate_blocks_late_wide_and_invalid_entries(self):
        engine, broker, _ = build()
        enter(engine, clock="14:30")
        self.assertEqual(engine.log[-1]["reason"], "Outside the entry window")
        engine, broker, _ = build()
        engine.strategy.armed = True
        engine.on_quote(quote("10:00", "100", "101"), at("10:00"))
        self.assertEqual(engine.log[-1]["reason"], "Spread exceeds the configured ceiling")
        engine, broker, _ = build(Scripted(stop="100.5"))
        enter(engine)
        self.assertIn("Stop must be below", engine.log[-1]["reason"])
        self.assertEqual(broker.positions(), {})

    def test_journal_caps_still_apply_behind_the_gate(self):
        engine, broker, _ = build(Scripted(qty=1000))
        [result] = enter(engine)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(engine.trades, {})

    def test_order_rate_limit_blocks_entries(self):
        engine, _, _ = build(max_orders_per_second=1)
        enter(engine)
        engine.on_quote(quote("10:00", "105", high="106.5", low="103"), at("10:00"))
        enter(engine, clock="10:00")
        self.assertEqual(engine.log[-1]["reason"], "Order rate limit reached")

    def test_global_halt_variable_blocks_entries(self):
        engine, broker, _ = build()
        with patch.dict(os.environ, {"INDIA_TRADE_LAB_HALT": "1"}):
            enter(engine)
        self.assertEqual(engine.log[-1]["reason"], "Global entry halt is active")
        self.assertEqual(broker.positions(), {})

    def test_silent_feed_halts_entries_but_exits_still_work(self):
        engine, broker, alerts = build(heartbeat_timeout_seconds=30)
        enter(engine)
        engine.tick(at("10:01"))
        self.assertEqual(engine.phase, Phase.HALTED)
        self.assertEqual(alerts.count("manual_attention"), 1)
        engine.on_quote(quote("10:02", "97", low="97", high="98"), at("10:02"))
        self.assertEqual(broker.positions(), {})
        calls = engine.strategy.calls
        self.assertEqual(enter(engine, clock="10:03"), [])
        self.assertEqual(engine.strategy.calls, calls)  # Halted: no entry is even proposed.
        self.assertEqual(sum(e["side"] == "buy" for e in broker.book["events"]), 1)

    def test_session_close_with_open_position_halts(self):
        engine, _, _ = build()
        enter(engine)
        engine.tick(at("15:30"))
        self.assertIn("open virtual positions", engine.halt_reason)

    def test_reconcile_mismatch_halts(self):
        engine, broker, alerts = build()
        enter(engine)
        broker.book["positions"].clear()
        self.assertFalse(engine.reconcile())
        self.assertIn("reconcile_mismatch", alerts)
        self.assertEqual(engine.phase, Phase.HALTED)

    def test_restart_resumes_from_store_and_refuses_changed_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "engine.sqlite"
            engine, broker, _ = build()
            store = EngineStore(path)
            store.create(broker.book)
            with self.assertRaises(ValueError):
                EngineStore(path).create(broker.book)
            enter(engine)
            store.save(engine)
            book, snapshot = EngineStore(path).load()
            resumed, _, _ = build()
            resumed.broker = PaperBroker(book, Decimal(5))
            resumed.restore(snapshot)
            self.assertEqual(resumed.phase, Phase.IN_TRADE)
            resumed.on_quote(quote("10:10", "97", low="97", high="98"), at("10:10"))
            self.assertEqual(resumed.broker.positions(), {})
            changed, _, _ = build(fee_bps=Decimal(6))
            with self.assertRaises(ValueError):
                changed.restore(snapshot)

    def test_forward_paper_requires_history_before_the_existing_evidence_gate(self):
        runner, broker, _ = build()
        broker.book["mode"] = "paper_manual"
        intent = EntryIntent(SYMBOL, 10, Decimal(98), Decimal(106), "test")
        observed = quote("10:00", "100")
        self.assertIn(
            "Historical coverage is required",
            runner.gate.entry_block(runner, intent, observed, at("10:00")),
        )
        runner.history_provider = lambda *_: {
            "history_ready": False,
            "symbol": SYMBOL,
            "completed_sessions": 2,
        }
        self.assertIn(
            "insufficient", runner.gate.entry_block(runner, intent, observed, at("10:00"))
        )
        runner.history_provider = lambda symbol, now, minimum: {
            "history_ready": True,
            "symbol": symbol,
            "completed_sessions": 50,
            "missing_declared_sessions": [],
            "as_of": now.isoformat(),
        }
        self.assertIsNone(runner.gate.entry_block(runner, intent, observed, at("10:00")))
        runner.history_provider = lambda *_: {
            "history_ready": True,
            "symbol": SYMBOL,
            "completed_sessions": 50,
            "as_of": at("10:05").isoformat(),
        }
        self.assertIn(
            "insufficient", runner.gate.entry_block(runner, intent, observed, at("10:00"))
        )

    def test_config_rejects_unsafe_values(self):
        with self.assertRaises(ValueError):
            build(max_orders_per_second=0)
        with self.assertRaises(ValueError):
            build(fee_bps=Decimal(-1))

    def test_orb_sizing_respects_risk_and_cap(self):
        config = build()[0].config
        orb = OpeningRangeBreakout(Decimal(250), Decimal(15000), Decimal(2))
        qty = orb.size(Decimal("102"), Decimal("99"), config)
        loss = (Decimal("102") * Decimal("1.0005") - Decimal("99") * Decimal("0.9995")) * qty
        self.assertGreater(qty, 0)
        self.assertLessEqual(loss + config.fee(Decimal(102), qty) * 2, 250)
        self.assertEqual(orb.size(Decimal("100"), Decimal("101"), config), 0)
        self.assertEqual(BAR, dt.timedelta(minutes=5))


class RecoveryRegressionTests(unittest.TestCase):
    def test_quantity_mismatch_halts_entries_but_stop_exits_held_shares(self):
        runner, broker, alerts = build()
        enter(runner)
        with patch.object(broker, "positions", return_value={SYMBOL: 5}):
            self.assertFalse(runner.reconcile())
            submitted = []
            original = broker.submit
            with patch.object(
                broker,
                "submit",
                side_effect=lambda order, *rest: submitted.append(order) or original(order, *rest),
            ):
                [result] = runner.on_quote(quote("10:05", "97"), at("10:05"))
        self.assertEqual(result.status, "filled")
        self.assertEqual(submitted[0].qty, 5)  # Never more than the broker holds.
        self.assertIn("manual_attention", alerts)
        self.assertEqual(runner.phase, Phase.HALTED)  # Entries stay blocked for review.

    def test_mismatch_on_another_symbol_never_blocks_a_stop_exit(self):
        book = create("100000", "NSE:AAA,NSE:BBB", "250", "750", "15000", replay=True, max_open=2)
        broker = PaperBroker(book, Decimal(5))

        class Both:
            pending = {"NSE:AAA", "NSE:BBB"}

            def on_quote(self, q, context):
                if q.symbol in self.pending:
                    self.pending.discard(q.symbol)
                    return EntryIntent(q.symbol, 10, Decimal(98), Decimal(106), "fixture")
                return None

        config = EngineConfig(("NSE:AAA", "NSE:BBB"), Decimal(5), Decimal(10), Decimal(5))
        runner = Engine(config, SESSION, broker, Both(), notifier=lambda *_: None)
        runner.on_quote(quote("10:00", "100", symbol="NSE:AAA"), at("10:00"))
        runner.on_quote(quote("10:00", "100", symbol="NSE:BBB"), at("10:00"))
        # A manual journal exit outside the engine leaves the engine out of sync on BBB.
        broker.book = fill(
            broker.book, "sell", "manual-1", "NSE:BBB", "100", at("10:01").isoformat(),
            "SYNTHETIC TEST ONLY", "10", "5", now=at("10:01"),
        )  # fmt: skip
        bar = quote("10:02", "95", symbol="NSE:AAA", open="96", high="96", low="95")
        [result] = runner.on_quote(bar, at("10:02"))
        self.assertEqual(result.status, "filled")
        self.assertEqual(broker.positions(), {})
        self.assertEqual(runner.phase, Phase.HALTED)

    def test_exit_when_broker_holds_nothing_drops_the_trade_with_an_alert(self):
        runner, broker, alerts = build()
        enter(runner)
        with patch.object(broker, "positions", return_value={}):
            self.assertEqual(runner.on_quote(quote("10:05", "97"), at("10:05")), [])
        self.assertEqual(runner.trades, {})
        self.assertIn("manual_attention", alerts)

    def test_stale_snapshot_cannot_erase_an_external_journal_fill(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner, broker, _ = build()
            store = EngineStore(Path(temporary) / "run.sqlite")
            store.create(broker.book)
            other, changed, _ = build()
            enter(other)
            with sqlite3.connect(store.path) as conn:
                conn.execute("UPDATE book SET data=? WHERE id=1", (json.dumps(changed.book),))
            with self.assertRaisesRegex(ValueError, "stale engine save"):
                store.save(runner)
            self.assertEqual(len(EngineStore(store.path).load()[0]["events"]), 1)

    def test_concurrent_engine_state_writer_is_detected_even_without_a_fill(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner, broker, _ = build()
            first = EngineStore(Path(temporary) / "run.sqlite")
            first.create(broker.book)
            second = EngineStore(first.path)
            second.load()
            first.save(runner)
            with self.assertRaisesRegex(ValueError, "stale engine save"):
                second.save(runner)

    def orb_engine(self, **parameters):
        return build(
            OpeningRangeBreakout(Decimal(parameters.get("risk", 250)), Decimal(15000), Decimal(2))
        )[0]

    def opening_bars(self, runner):
        for clock in ("09:20", "09:25", "09:30"):
            runner.on_quote(quote(clock, "100", high="101", low="99"), at(clock))

    def test_orb_restart_produces_the_same_entry_and_rejects_changed_parameters(self):
        original = self.orb_engine()
        self.opening_bars(original)
        snapshot = json.loads(json.dumps(original.snapshot()))
        restored = self.orb_engine()
        restored.restore(snapshot)
        breakout = quote("09:35", "102", high="103", low="100")
        self.assertEqual(
            original.on_quote(breakout, at("09:35")), restored.on_quote(breakout, at("09:35"))
        )
        with self.assertRaisesRegex(ValueError, "Strategy or session changed"):
            self.orb_engine(risk=300).restore(snapshot)
        changed_session = self.orb_engine()
        changed_session.session = {**SESSION, "flat_by": at("15:10")}
        with self.assertRaisesRegex(ValueError, "Strategy or session changed"):
            changed_session.restore(snapshot)
        with self.assertRaisesRegex(ValueError, "snapshot version"):
            self.orb_engine().restore({**snapshot, "version": 1})

    def test_missing_duplicate_or_off_grid_bars_never_create_an_entry(self):
        for clocks in (
            ("09:20",),
            ("09:20", "09:20", "09:25", "09:30"),
            ("09:21", "09:25", "09:30"),
            ("09:25", "09:30"),
        ):
            with self.subTest(clocks=clocks):
                runner = self.orb_engine()
                for clock in clocks:
                    runner.on_quote(quote(clock, "100", high="101", low="99"), at(clock))
                self.assertEqual(
                    runner.on_quote(quote("09:35", "102", high="103", low="100"), at("09:35")), []
                )
                self.assertEqual(runner.broker.positions(), {})
                self.assertIn("DATA BLOCK", runner.strategy.last_reason[SYMBOL])

    def test_invalid_data_state_remains_blocked_after_restart(self):
        runner = self.orb_engine()
        runner.on_quote(quote("09:25", "100", high="101", low="99"), at("09:25"))
        restored = self.orb_engine()
        restored.restore(json.loads(json.dumps(runner.snapshot())))
        self.assertEqual(
            restored.on_quote(quote("09:35", "102", high="103", low="100"), at("09:35")), []
        )
        self.assertIn(SYMBOL, restored.strategy.invalid)


class EngineCliTests(unittest.TestCase):
    def test_replay_cli_writes_a_journal_the_book_cli_can_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            book = Path(temporary) / "replay.sqlite"
            command = [
                sys.executable,
                str(ROOT / "scripts/engine.py"),
                "replay",
                "--bars",
                str(ASSETS / "synthetic-bars.csv"),
                "--sessions",
                str(ASSETS / "synthetic-sessions.json"),
                "--symbol",
                SYMBOL,
                "--date",
                "2026-10-19",
                "--book",
                str(book),
                "--cash",
                "100000",
                "--risk",
                "250",
                "--daily-loss",
                "750",
                "--position-cap",
                "15000",
                "--target-r",
                "2",
                "--fee-bps",
                "5",
                "--fee-flat",
                "10",
                "--slippage-bps",
                "5",
            ]
            report = json.loads(subprocess.check_output(command, text=True))
            self.assertEqual(report["mode"], "replay_demo")
            self.assertEqual(report["phase"], "CLOSED")
            self.assertEqual([o["side"] for o in report["orders"]], ["buy", "sell"])
            status = subprocess.check_output(
                [sys.executable, str(ROOT / "scripts/paper_book.py"), "--book", str(book), "status"]
            )
            self.assertEqual(json.loads(status)["positions"], {})
            again = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(again.returncode, 2)
            self.assertIn("refusing to overwrite", again.stderr)


if __name__ == "__main__":
    unittest.main()

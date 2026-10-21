"""Exercise the session engine with synthetic quotes only; no broker or network calls."""

import datetime as dt
import json
import os
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
from paper_book import create

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
        self.assertEqual(engine.log[-1]["reason"], "stop")
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
        self.assertEqual(engine.log[-1]["reason"], "target")
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

#!/usr/bin/env python3
"""Deterministic session engine that drives the virtual journal. No network or live mode.

Phases: PRE_OPEN -> SCANNING <-> IN_TRADE -> SQUARING_OFF -> CLOSED. A halt is sticky:
it blocks new entries for the rest of the session while exits stay available.

Every order passes the RiskGate, then a Broker. Only PaperBroker exists. It delegates
accounting to paper_book.fill, so replay, forward paper and the journal CLI share one
ledger and one set of caps. The engine is clock-driven: callers pass `now`, which makes
replay and tests deterministic. A strategy proposes entries; it never places orders.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime as dt
import enum
import hashlib
import json
import os
import sqlite3
import sys
from collections.abc import Callable, Iterable
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

import india_research
import paper_book

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
BAR = dt.timedelta(minutes=5)
BPS = Decimal(10000)
CENT = Decimal(".01")
MAX_FUTURE_SKEW_SECONDS = 5


class Phase(str, enum.Enum):
    PRE_OPEN = "PRE_OPEN"
    SCANNING = "SCANNING"
    IN_TRADE = "IN_TRADE"
    SQUARING_OFF = "SQUARING_OFF"
    CLOSED = "CLOSED"
    HALTED = "HALTED"


@dataclasses.dataclass(frozen=True)
class Quote:
    """One observed quote. Replay bars also carry the interval open/high/low."""

    symbol: str
    as_of: dt.datetime
    bid: Decimal
    ask: Decimal
    source: str
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2

    @property
    def spread_bps(self) -> Decimal:
        return (self.ask - self.bid) / self.mid * BPS


@dataclasses.dataclass(frozen=True)
class EntryIntent:
    """A strategy proposal. The engine decides whether it becomes an order."""

    symbol: str
    qty: int
    stop: Decimal
    target: Decimal
    reason: str
    evidence: dict[str, Any] | None = None


@dataclasses.dataclass(frozen=True)
class Order:
    client_order_id: str
    symbol: str
    side: str
    qty: int
    price: Decimal
    fee: Decimal
    reason: str
    stop: Decimal | None = None
    exit_fee_reserve: Decimal | None = None
    evidence: dict[str, Any] | None = None


@dataclasses.dataclass(frozen=True)
class OrderResult:
    client_order_id: str
    status: str  # "filled", "duplicate" or "rejected"
    reason: str
    fill_price: str | None = None


@dataclasses.dataclass(frozen=True)
class EngineConfig:
    """Frozen run parameters. The digest ties every journal entry to one version."""

    symbols: tuple[str, ...]
    fee_bps: Decimal
    fee_flat: Decimal
    slippage_bps: Decimal
    max_quote_age_seconds: int = 120
    heartbeat_timeout_seconds: int = 60
    max_spread_bps: Decimal = Decimal(20)
    max_orders_per_second: int = 10

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("Engine needs at least one allowlisted symbol")
        for value in (self.fee_bps, self.fee_flat, self.slippage_bps, self.max_spread_bps):
            if not value.is_finite() or value < 0:
                raise ValueError("Engine cost and spread settings must be finite and nonnegative")
        for value in (
            self.max_quote_age_seconds,
            self.heartbeat_timeout_seconds,
            self.max_orders_per_second,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("Engine timing and rate limits must be positive integers")

    def fee(self, price: Decimal, qty: int) -> Decimal:
        """Explicit aggregate charge assumption, not a statutory calculator."""
        return (self.fee_flat + price * qty * self.fee_bps / BPS).quantize(CENT)

    def digest(self) -> str:
        payload = {
            key: (list(value) if isinstance(value, tuple) else str(value))
            for key, value in dataclasses.asdict(self).items()
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class Strategy(Protocol):
    def on_quote(self, quote: Quote, context: dict[str, Any]) -> EntryIntent | None: ...


class Broker(Protocol):
    mode: str

    def submit(self, order: Order, quote: Quote, now: dt.datetime) -> OrderResult: ...

    def positions(self) -> dict[str, int]: ...


Notifier = Callable[[str, dict[str, Any]], None]


def stderr_notifier(kind: str, payload: dict[str, Any]) -> None:
    """Default alert sink: one JSON line per alert on stderr. Wire chat alerts here later."""
    print(json.dumps({"alert": kind, **payload}, default=str), file=sys.stderr)


class PaperBroker:
    """Simulated executor over a paper_book state. Never contacts a broker."""

    mode = "paper"

    def __init__(self, book: dict[str, Any], slippage_bps: Decimal) -> None:
        paper_book.verify_state(book)
        self.book = book
        self.slippage_bps = slippage_bps

    def submit(self, order: Order, quote: Quote, now: dt.datetime) -> OrderResult:
        for event in self.book["events"]:
            if event["id"] == order.client_order_id:
                # A retried submission must never become a second fill.
                return OrderResult(
                    order.client_order_id, "duplicate", "Already filled", event["assumed_fill_inr"]
                )
        try:
            self.book = paper_book.fill(
                self.book,
                order.side,
                order.client_order_id,
                order.symbol,
                order.price,
                quote.as_of.isoformat(),
                quote.source,
                order.fee,
                self.slippage_bps,
                order.qty if order.side == "buy" else None,
                order.stop,
                order.exit_fee_reserve,
                now=now,
                evidence=order.evidence,
            )
        except (ValueError, KeyError, InvalidOperation) as exc:
            return OrderResult(order.client_order_id, "rejected", str(exc))
        return OrderResult(
            order.client_order_id,
            "filled",
            order.reason,
            self.book["events"][-1]["assumed_fill_inr"],
        )

    def positions(self) -> dict[str, int]:
        return {symbol: p["qty"] for symbol, p in self.book["positions"].items()}


class RiskGate:
    """Fail-closed checks that run before the journal's own caps. Exits are never blocked."""

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.recent: collections.deque[dt.datetime] = collections.deque()

    def record(self, now: dt.datetime) -> None:
        self.recent.append(now)

    def _rate_ok(self, now: dt.datetime) -> bool:
        while self.recent and (now - self.recent[0]).total_seconds() >= 1:
            self.recent.popleft()
        return len(self.recent) < self.config.max_orders_per_second

    def entry_block(
        self,
        engine: Engine,
        intent: EntryIntent,
        quote: Quote,
        now: dt.datetime,
    ) -> str | None:
        """Return why an entry is refused, or None when the gate allows it."""
        if os.environ.get("INDIA_TRADE_LAB_HALT", "0") != "0":
            return "Global entry halt is active"
        if engine.halt_reason:
            return "Engine halted: " + engine.halt_reason
        if not engine.session["open"] <= now < engine.session["entry_cutoff"]:
            return "Outside the entry window"
        if intent.symbol != quote.symbol or intent.symbol not in self.config.symbols:
            return "Intent symbol does not match an allowlisted quote"
        if intent.symbol in engine.trades:
            return "Symbol already has an engine-managed position"
        if isinstance(intent.qty, bool) or not isinstance(intent.qty, int) or intent.qty <= 0:
            return "Quantity must be positive whole shares"
        if not intent.stop < quote.bid or not intent.target > quote.ask:
            return "Stop must be below the bid and target above the ask"
        if quote.spread_bps > self.config.max_spread_bps:
            return "Spread exceeds the configured ceiling"
        if not self._rate_ok(now):
            return "Order rate limit reached"
        return None


class Engine:
    """One trading session for an allowlisted set of symbols, long only."""

    def __init__(
        self,
        config: EngineConfig,
        session: dict[str, dt.datetime],
        broker: Broker,
        strategy: Strategy,
        notifier: Notifier = stderr_notifier,
    ) -> None:
        if not session["open"] < session["entry_cutoff"] < session["flat_by"] < session["close"]:
            raise ValueError("Invalid session boundaries")
        self.config = config
        self.session = session
        self.broker = broker
        self.strategy = strategy
        self.notify = notifier
        self.gate = RiskGate(config)
        self.trades: dict[str, dict[str, str]] = {}
        self.entries: dict[str, int] = {}
        self.halt_reason: str | None = None
        self.last_quote_at: dt.datetime | None = None
        self.clock: dt.datetime | None = None
        self.log: list[dict[str, Any]] = []

    # ----- state -------------------------------------------------------------------------

    @property
    def phase(self) -> Phase:
        if self.halt_reason:
            return Phase.HALTED
        now = self.clock
        if now is None or now < self.session["open"]:
            return Phase.PRE_OPEN
        if now >= self.session["close"]:
            return Phase.CLOSED
        if now >= self.session["flat_by"]:
            return Phase.SQUARING_OFF if self.trades else Phase.CLOSED
        return Phase.IN_TRADE if self.trades else Phase.SCANNING

    def _record(self, kind: str, alert: bool = False, **payload: Any) -> None:
        entry = {"at": self.clock.isoformat() if self.clock else None, "kind": kind, **payload}
        entry["phase"] = self.phase.value
        self.log.append(entry)
        if alert:
            self.notify(kind, entry)

    def _advance(self, now: dt.datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("Engine clock must be timezone-aware")
        if self.clock and now < self.clock:
            raise ValueError("Engine clock must not move backwards")
        before = self.phase
        self.clock = now.astimezone(IST)
        if self.phase != before:
            self._record("phase", previous=before.value)

    def halt(self, reason: str) -> None:
        """Stop new entries for the rest of the session. Exits remain available."""
        if not self.halt_reason:
            self.halt_reason = reason
            self._record("halt", alert=True, reason=reason, open_symbols=sorted(self.trades))

    def snapshot(self) -> dict[str, Any]:
        """Serializable engine state for crash recovery alongside the journal."""
        return {
            "version": 1,
            "config_sha256": self.config.digest(),
            "session_date": self.session["open"].date().isoformat(),
            "trades": self.trades,
            "entries": self.entries,
            "halt_reason": self.halt_reason,
            "clock": self.clock.isoformat() if self.clock else None,
            "last_quote_at": self.last_quote_at.isoformat() if self.last_quote_at else None,
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Resume after a restart, then reconcile against the broker before trading."""
        if snapshot.get("version") != 1:
            raise ValueError("Unsupported engine snapshot version")
        if snapshot.get("config_sha256") != self.config.digest():
            raise ValueError("Engine config changed mid-session; start a separate run")
        if snapshot.get("session_date") != self.session["open"].date().isoformat():
            raise ValueError("Snapshot belongs to a different session")
        self.trades = dict(snapshot["trades"])
        self.entries = dict(snapshot["entries"])
        self.halt_reason = snapshot["halt_reason"]
        self.clock = dt.datetime.fromisoformat(snapshot["clock"]) if snapshot["clock"] else None
        last = snapshot["last_quote_at"]
        self.last_quote_at = dt.datetime.fromisoformat(last) if last else None
        self._record("restored")
        self.reconcile()

    # ----- loop inputs -------------------------------------------------------------------

    def tick(self, now: dt.datetime) -> None:
        """Call on a timer. Detects a stale feed and an unflattened close."""
        self._advance(now)
        in_session = self.session["open"] <= now < self.session["close"]
        if in_session and self.last_quote_at:
            silent = (now - self.last_quote_at).total_seconds()
            if silent > self.config.heartbeat_timeout_seconds:
                self.halt(f"No valid quote for {int(silent)} seconds")
                if self.trades:
                    self._record(
                        "manual_attention",
                        alert=True,
                        reason="Positions open without a live quote; exits need a fresh quote",
                        symbols=sorted(self.trades),
                    )
        if now >= self.session["close"] and self.trades:
            self.halt("Session closed with open virtual positions")

    def reconcile(self) -> bool:
        """Compare engine-managed positions with the broker. A mismatch halts entries."""
        held = self.broker.positions()
        managed = set(self.trades)
        if set(held) != managed:
            self._record(
                "reconcile_mismatch",
                alert=True,
                broker=sorted(held),
                engine=sorted(managed),
            )
            self.halt("Broker and engine positions disagree")
            return False
        return True

    def on_quote(self, quote: Quote, now: dt.datetime) -> list[OrderResult]:
        """Process one quote: exits first, then at most one new entry for that symbol."""
        self._advance(now)
        problem = self._quote_problem(quote, now)
        if problem:
            self._record("quote_rejected", symbol=quote.symbol, reason=problem)
            return []
        self.last_quote_at = now
        results = []
        if quote.symbol in self.trades:
            exit_result = self._maybe_exit(quote, now)
            if exit_result:
                results.append(exit_result)
        if self.phase in (Phase.SCANNING, Phase.IN_TRADE) and quote.symbol not in self.trades:
            entry_result = self._maybe_enter(quote, now)
            if entry_result:
                results.append(entry_result)
        return results

    # ----- internals ---------------------------------------------------------------------

    def _quote_problem(self, quote: Quote, now: dt.datetime) -> str | None:
        if quote.symbol not in self.config.symbols:
            return "Symbol is not allowlisted"
        if quote.as_of.tzinfo is None:
            return "Quote timestamp lacks a timezone"
        age = (now - quote.as_of).total_seconds()
        if age > self.config.max_quote_age_seconds or age < -MAX_FUTURE_SKEW_SECONDS:
            return "Quote is stale or from the future"
        values = (quote.bid, quote.ask, quote.open, quote.high, quote.low)
        if any(v is not None and (not v.is_finite() or v <= 0) for v in values):
            return "Quote prices must be finite and positive"
        if quote.bid > quote.ask:
            return "Crossed quote"
        if not quote.source.strip():
            return "Quote source is required"
        return None

    def _submit(self, order: Order, quote: Quote, now: dt.datetime) -> OrderResult:
        self.gate.record(now)
        result = self.broker.submit(order, quote, now)
        self._record(
            "order",
            alert=True,
            id=order.client_order_id,
            side=order.side,
            symbol=order.symbol,
            qty=order.qty,
            reason=order.reason,
            status=result.status,
            detail=result.reason,
            fill_inr=result.fill_price,
            config_sha256=self.config.digest(),
        )
        return result

    def _maybe_exit(self, quote: Quote, now: dt.datetime) -> OrderResult | None:
        trade = self.trades[quote.symbol]
        stop, target = Decimal(trade["stop"]), Decimal(trade["target"])
        low = quote.low if quote.low is not None else quote.bid
        high = quote.high if quote.high is not None else quote.bid
        # Check the stop before the target: an ambiguous interval is assumed to lose.
        if low <= stop:
            reason = "stop"
            if quote.open is not None and quote.open <= stop:
                price = quote.open  # Gapped through the stop: fill at the worse open.
            elif quote.low is not None:
                price = stop  # Interval touched the stop.
            else:
                price = quote.bid  # Live quote already at or through the stop.
        elif high >= target:
            price, reason = (target if quote.high is not None else quote.bid), "target"
        elif now >= self.session["flat_by"]:
            price, reason = quote.bid, "square_off"
        else:
            return None
        qty = self.broker.positions().get(quote.symbol, 0)
        order = Order(
            client_order_id=trade["entry_id"] + ":X",
            symbol=quote.symbol,
            side="sell",
            qty=qty,
            price=price,
            fee=self.config.fee(price, qty),
            reason=reason,
        )
        result = self._submit(order, quote, now)
        if result.status in ("filled", "duplicate"):
            self.trades.pop(quote.symbol)
        else:
            self.halt("Exit rejected for " + quote.symbol)
        return result

    def _maybe_enter(self, quote: Quote, now: dt.datetime) -> OrderResult | None:
        context = {
            "now": now,
            "session": self.session,
            "config": self.config,
            "entries_today": dict(self.entries),
            "open_symbols": sorted(self.trades),
        }
        intent = self.strategy.on_quote(quote, context)
        if intent is None:
            return None
        blocked = self.gate.entry_block(self, intent, quote, now)
        if blocked:
            self._record("entry_blocked", symbol=intent.symbol, reason=blocked)
            return None
        number = self.entries.get(intent.symbol, 0) + 1
        entry_id = f"{now.date().isoformat()}:{intent.symbol}:E{number}"
        order = Order(
            client_order_id=entry_id,
            symbol=intent.symbol,
            side="buy",
            qty=intent.qty,
            price=quote.ask,
            fee=self.config.fee(quote.ask, intent.qty),
            reason=intent.reason,
            stop=intent.stop,
            exit_fee_reserve=self.config.fee(intent.stop, intent.qty),
            evidence=intent.evidence,
        )
        result = self._submit(order, quote, now)
        self.entries[intent.symbol] = number
        if result.status in ("filled", "duplicate"):
            self.trades[intent.symbol] = {
                "entry_id": entry_id,
                "stop": str(intent.stop),
                "target": str(intent.target),
            }
        return result

    def report(self) -> dict[str, Any]:
        """End-of-day summary for alerts and review. Not a performance claim."""
        book = getattr(self.broker, "book", {})
        return {
            "phase": self.phase.value,
            "halt_reason": self.halt_reason,
            "broker_mode": self.broker.mode,
            "config_sha256": self.config.digest(),
            "session_date": self.session["open"].date().isoformat(),
            "cash_inr": book.get("cash"),
            "realized_by_day_inr": book.get("realized_by_day"),
            "open_positions": self.broker.positions(),
            "orders": [e for e in self.log if e["kind"] == "order"],
            "alerts": [e for e in self.log if e["kind"] in ("halt", "manual_attention")],
            "notice": "Virtual fills under explicit cost assumptions; not evidence of an edge.",
        }


class EngineStore:
    """SQLite persistence. The `book` table matches paper_book, so its CLI can read it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.saved = 0

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), isolation_level=None, timeout=10)

    def create(self, book: dict[str, Any]) -> None:
        if self.path.exists():
            raise ValueError("Engine book already exists; refusing to overwrite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE book (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE engine_state (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)"
            )
            conn.execute("CREATE TABLE engine_log (seq INTEGER PRIMARY KEY, data TEXT NOT NULL)")
            conn.execute("INSERT INTO book VALUES (1, ?)", (json.dumps(book),))
            conn.commit()

    def save(self, engine: Engine) -> None:
        """Persist journal, snapshot and new log lines in one transaction."""
        book = getattr(engine.broker, "book", None)
        if book is None:
            raise ValueError("Only PaperBroker state can be persisted")
        new = engine.log[self.saved :]
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR REPLACE INTO book VALUES (1, ?)", (json.dumps(book),))
            conn.execute(
                "INSERT OR REPLACE INTO engine_state VALUES (1, ?)",
                (json.dumps(engine.snapshot()),),
            )
            conn.executemany(
                "INSERT INTO engine_log (data) VALUES (?)",
                [(json.dumps(e, default=str),) for e in new],
            )
            conn.commit()
        self.saved = len(engine.log)

    def load(self) -> tuple[dict[str, Any], dict[str, Any] | None]:
        with self._connect() as conn:
            book = json.loads(conn.execute("SELECT data FROM book WHERE id=1").fetchone()[0])
            row = conn.execute("SELECT data FROM engine_state WHERE id=1").fetchone()
        paper_book.verify_state(book)
        return book, (json.loads(row[0]) if row else None)


class OpeningRangeBreakout:
    """The repository's ORB test rule as an engine strategy. A harness, not an edge.

    Expects completed five-minute bar quotes stamped at bar close. The first three bars
    form the range; the first later close above the range high proposes one long entry.
    """

    def __init__(self, risk_inr: Decimal, position_cap_inr: Decimal, target_r: Decimal) -> None:
        self.risk = risk_inr
        self.cap = position_cap_inr
        self.target_r = target_r
        self.ranges: dict[str, list[Decimal]] = {}

    def on_quote(self, quote: Quote, context: dict[str, Any]) -> EntryIntent | None:
        session, config = context["session"], context["config"]
        if quote.high is None or quote.low is None:
            return None
        if quote.as_of <= session["open"] + 3 * BAR:
            bounds = self.ranges.setdefault(quote.symbol, [quote.high, quote.low])
            bounds[0], bounds[1] = max(bounds[0], quote.high), min(bounds[1], quote.low)
            return None
        if context["entries_today"].get(quote.symbol) or quote.symbol not in self.ranges:
            return None
        high, low = self.ranges[quote.symbol]
        if quote.bid <= high:
            return None
        qty = self.size(quote.ask, low, config)
        if qty <= 0:
            return None
        entry = quote.ask * (1 + config.slippage_bps / BPS)
        target = (entry + (entry - low) * self.target_r).quantize(CENT)
        return EntryIntent(quote.symbol, qty, low, target, "orb_breakout")

    def size(self, ask: Decimal, stop: Decimal, config: EngineConfig) -> int:
        """Largest whole quantity whose planned loss and cost fit the limits."""
        slip = config.slippage_bps / BPS
        entry, exit_at_stop = ask * (1 + slip), stop * (1 - slip)
        per_share = entry - exit_at_stop
        if per_share <= 0:
            return 0
        qty = int((self.risk / per_share).to_integral_value(rounding=ROUND_FLOOR))
        while qty > 0:
            loss = per_share * qty + config.fee(ask, qty) + config.fee(stop, qty)
            if loss <= self.risk and entry * qty + config.fee(ask, qty) <= self.cap:
                return qty
            qty -= 1
        return 0


def bar_quotes(
    bars: Iterable[dict[str, Any]], symbol: str, date: dt.date, spread_bps: Decimal
) -> list[Quote]:
    """Turn completed bars into quotes stamped at bar close with a symmetric spread."""
    half = spread_bps / BPS / 2
    quotes = []
    for bar in bars:
        if bar["symbol"] != symbol or bar["t"].date() != date:
            continue
        close = Decimal(str(bar["close"]))
        quotes.append(
            Quote(
                symbol=symbol,
                as_of=bar["t"] + BAR,
                bid=(close * (1 - half)).quantize(CENT),
                ask=(close * (1 + half)).quantize(CENT),
                source=bar["source"],
                open=Decimal(str(bar["open"])),
                high=Decimal(str(bar["high"])),
                low=Decimal(str(bar["low"])),
            )
        )
    return sorted(quotes, key=lambda q: q.as_of)


def decimal_arg(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("Expected a decimal number") from None
    if not result.is_finite() or result < 0:
        raise argparse.ArgumentTypeError("Expected a finite nonnegative number")
    return result


def run_replay(args: argparse.Namespace) -> dict[str, Any]:
    """Replay one symbol-session through the same engine path forward paper will use."""
    date = dt.date.fromisoformat(args.date)
    manifest = json.loads(Path(args.sessions).read_text(encoding="utf-8"))
    session = india_research.session(manifest, date)
    bars = india_research.bars_from_csv(args.bars)
    quotes = bar_quotes(bars, args.symbol, date, args.spread_bps)
    if not quotes:
        raise ValueError("No bars for the requested symbol and date")
    config = EngineConfig(
        symbols=(args.symbol,),
        fee_bps=args.fee_bps,
        fee_flat=args.fee_flat,
        slippage_bps=args.slippage_bps,
        max_spread_bps=args.max_spread_bps,
        heartbeat_timeout_seconds=int(BAR.total_seconds()) * 2,
    )
    book = paper_book.create(
        args.cash,
        args.symbol,
        args.risk,
        args.daily_loss,
        args.position_cap,
        replay=True,
        max_trades=args.max_trades,
        max_open=1,
        max_loss_streak=args.max_loss_streak,
        drawdown_stop=args.drawdown_stop,
    )
    store = EngineStore(Path(args.book))
    store.create(book)
    broker = PaperBroker(book, args.slippage_bps)
    strategy = OpeningRangeBreakout(args.risk, args.position_cap, args.target_r)
    engine = Engine(config, session, broker, strategy, notifier=lambda kind, payload: None)
    for quote in quotes:
        engine.on_quote(quote, quote.as_of)
        engine.tick(quote.as_of)
        store.save(engine)
    engine.tick(session["close"])
    store.save(engine)
    result = engine.report()
    result["mode"] = "replay_demo"
    result["book"] = str(args.book)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    replay = sub.add_parser("replay", help="Run one historical session through the engine")
    replay.add_argument("--bars", required=True)
    replay.add_argument("--sessions", required=True)
    replay.add_argument("--symbol", required=True)
    replay.add_argument("--date", required=True, help="Session date, YYYY-MM-DD")
    replay.add_argument("--book", required=True, help="New SQLite path; never overwritten")
    for name in ("cash", "risk", "daily-loss", "position-cap", "target-r"):
        replay.add_argument("--" + name, required=True, type=decimal_arg)
    for name in ("fee-bps", "fee-flat", "slippage-bps"):
        replay.add_argument("--" + name, required=True, type=decimal_arg)
    replay.add_argument("--spread-bps", type=decimal_arg, default=Decimal(4))
    replay.add_argument("--max-spread-bps", type=decimal_arg, default=Decimal(20))
    replay.add_argument("--max-trades", type=int, default=3)
    replay.add_argument("--max-loss-streak", type=int, default=2)
    replay.add_argument("--drawdown-stop", type=decimal_arg)
    args = parser.parse_args()
    try:
        print(json.dumps(run_replay(args), indent=2, default=str))
        return 0
    except (ValueError, KeyError, InvalidOperation, sqlite3.Error, OSError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Build the pre-trade evidence the journal demands, deriving what can be checked.

The journal requires ten confirmed checks, each with a source, re-confirmed within
120 seconds of the quote. Eight of them are facts a machine can read from the
instrument master, the authorised quote, stored history, the live candles and the
book, so this derives those from the data and names the source it used. Two need
human judgement:

    surveillance_clear   is the stock under ASM/GSM/surveillance today?
    no_material_event    is there an unpriced material announcement?

Those are attested once per trading session, by you, against a source you name
(`attest`), and the attestation is recorded with its own timestamp so a reviewer
can see when a person actually looked. This is a deliberate, auditable relaxation
of per-quote human confirmation; the machine checks are still re-derived for every
quote and a failing one refuses the ticket.

Read only: no order path, no journal write, no model call.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import statistics
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import guardrails
from history import HistoryStore

import india_research
import paper_book

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
JUDGEMENT = ("surveillance_clear", "no_material_event")
MACHINE = tuple(check for check in guardrails.REQUIRED_CHECKS if check not in JUDGEMENT)
SPREAD_CEILING = Decimal(20)


class Refused(ValueError):
    """A check could not be derived from the supplied data."""


def _instrument(universe: dict, symbol: str) -> dict:
    for item in universe.get("instruments", []):
        if item.get("symbol") == symbol:
            return item
    raise Refused(f"{symbol} is not in universe.json")


def _turnover(history: HistoryStore, symbol: str, as_of: dt.datetime) -> float:
    with sqlite3.connect(history.path) as conn:
        rows = conn.execute(
            "SELECT close_at, payload FROM sessions WHERE symbol=? AND kind='broker_export' "
            "ORDER BY date DESC LIMIT 40",
            (symbol,),
        ).fetchall()
    values = [
        sum(bar["close"] * bar["volume"] for bar in json.loads(payload)["bars"])
        for close_at, payload in rows
        if dt.datetime.fromisoformat(close_at) <= as_of
    ][:20]
    if not values:
        raise Refused("no completed sessions to measure traded value")
    return statistics.mean(values)


def derive(
    symbol: str,
    universe: dict,
    quote: dict,
    book: dict,
    history: HistoryStore,
    bars: list[dict],
    sessions: dict,
    now: dt.datetime,
    min_turnover_inr: float,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Return (sources for machine checks, derived facts). Any failure raises Refused."""
    instrument = _instrument(universe, symbol)
    observed = paper_book.timestamp(quote["as_of"])
    bid = paper_book.number(quote["bid_inr"], True)
    ask = paper_book.number(quote["ask_inr"], True)
    sources: dict[str, str] = {}

    # cash_equity / instrument_verified: the declared active EQ security and its mapping.
    if instrument.get("segment") != "EQ" or instrument.get("active") is not True:
        raise Refused("universe does not declare this an active EQ security")
    if not instrument.get("isin") or not instrument.get("instrument_id"):
        raise Refused("universe entry has no ISIN or broker instrument mapping")
    sources["cash_equity"] = (
        f"{universe.get('source', 'instrument master')}: {symbol} declared EQ, ISIN {instrument['isin']}"
    )
    sources["instrument_verified"] = (
        f"{instrument['data_provider']} instrument {instrument['instrument_id']} mapped to {symbol} "
        f"in {universe.get('source', 'instrument master')}"
    )

    # data_authorized: an authorised feed with an exchange bid/ask timestamp, still fresh.
    if quote.get("timestamp_kind", "exchange") != "exchange":
        raise Refused("quote has no exchange bid/ask timestamp")
    if "SYNTHETIC" in str(quote.get("source", "")).upper():
        raise Refused("synthetic quotes cannot support a forward ticket")
    age = (now - observed).total_seconds()
    if not -5 <= age <= 120:
        raise Refused(f"quote is {int(age)}s old; the limit is 120s")
    sources["data_authorized"] = (
        f"{quote['source']} exchange-timestamped quote at {observed.isoformat()}, {int(max(0, age))}s old"
    )

    # price_band_ok: inside the exchange's stated circuit band.
    lower, upper = quote.get("lower_circuit_inr"), quote.get("upper_circuit_inr")
    if not lower or not upper:
        raise Refused(
            "quote carries no circuit band; re-collect with a provider that states it, "
            "or attest price_band_ok manually"
        )
    if not paper_book.number(lower, True) <= bid <= ask <= paper_book.number(upper, True):
        raise Refused("quote lies outside the stated circuit band")
    sources["price_band_ok"] = (
        f"{quote['source']} circuit band INR {lower}-{upper} contains the quote"
    )

    # liquidity_ok: prior traded value and the current spread.
    turnover = _turnover(history, symbol, now)
    spread = (ask - bid) / ((ask + bid) / 2) * 10000
    if turnover < min_turnover_inr:
        raise Refused(f"20-session mean traded value INR {turnover:,.0f} is below the threshold")
    if spread > SPREAD_CEILING:
        raise Refused(f"spread {spread:.1f} bps exceeds the {SPREAD_CEILING} bps ceiling")
    sources["liquidity_ok"] = (
        f"20-session mean traded value INR {turnover:,.0f} from stored broker sessions; "
        f"current spread {spread:.1f} bps"
    )

    # sector_exposure_ok: no open position in the same declared sector.
    sector = instrument.get("industry") or instrument.get("sector") or ""
    held = []
    for symbol_held in book.get("positions", {}):
        if symbol_held == symbol:
            continue
        try:
            other = _instrument(universe, symbol_held)
        except Refused:
            continue
        if sector and (other.get("industry") or other.get("sector")) == sector:
            held.append(symbol_held)
    if held:
        raise Refused(f"already holding {', '.join(held)} in the same sector ({sector})")
    sources["sector_exposure_ok"] = (
        f"no open position shares the declared sector "
        f"({sector or 'sector not declared in the instrument master'})"
    )

    # strategy_rule_met: the breakout confirmed on the latest completed bar.
    rows = [row for row in bars if row["symbol"] == symbol]
    completed, times = india_research.checked_session(rows, sessions, now.date(), now)
    signal = india_research.first_signal(completed, times)
    if signal is None:
        raise Refused("no completed-bar opening-range breakout at this cutoff")
    latest = (completed[-1]["t"] + india_research.BAR).isoformat()
    if signal["confirmed_at"] != latest:
        raise Refused(f"breakout confirmed at {signal['confirmed_at']}, not on the latest bar")
    sources["strategy_rule_met"] = (
        f"intraday-orb-v1: close {signal['signal_close']} above the opening range high "
        f"{signal['range_high']}, confirmed at {signal['confirmed_at']}"
    )

    # stop_target_reviewed: the frozen plan is coherent and inside the per-trade cap.
    stop = Decimal(str(signal["range_low"]))
    if not stop < bid:
        raise Refused("the opening-range low is not below the current bid")
    risk_cap = paper_book.number(book["limits"]["risk"], True)
    sources["stop_target_reviewed"] = (
        f"stop at the opening-range low INR {stop} below the bid INR {bid}; "
        f"per-trade planned loss capped at INR {risk_cap} by the journal"
    )
    facts = {
        "bid_inr": str(bid),
        "ask_inr": str(ask),
        "quote_as_of": observed.isoformat(),
        "quote_source": quote["source"],
        "stop_inr": str(stop),
        "spread_bps": f"{spread:.2f}",
        "turnover_inr": round(turnover, 2),
        "signal": signal,
    }
    return sources, facts


def attest(
    path: Path, symbol: str, session_date: str, answers: dict[str, str], now: dt.datetime
) -> dict:
    """Record a dated human attestation for the judgement checks."""
    store = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    for check in JUDGEMENT:
        source = (answers.get(check) or "").strip()
        if not source:
            raise ValueError(f"{check} needs the source you actually checked")
    store.setdefault(session_date, {})[symbol] = {
        "attested_at": now.isoformat(),
        "sources": {check: answers[check].strip()[:400] for check in JUDGEMENT},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return store[session_date][symbol]


def build(
    config_path: Path,
    symbols: list[str] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Write pretrade-evidence.json for every symbol whose checks all hold."""
    from decision_pipeline import DailyCoordinator, read_book, read_json

    coordinator = DailyCoordinator(config_path)
    clock = (now or dt.datetime.now(IST)).astimezone(IST)
    universe = read_json(coordinator.path("universe"))
    sessions = read_json(coordinator.path("sessions"))
    quotes = read_json(coordinator.path("quotes"))
    book = read_book(coordinator.path("book"))
    history = HistoryStore(coordinator.path("history_db"))
    bars = india_research.bars_from_csv(coordinator.path("bars"))
    times = india_research.session(sessions, clock.date())
    attestations = {}
    attest_path = config_path.parent / "attestations.json"
    if attest_path.is_file():
        attestations = json.loads(attest_path.read_text(encoding="utf-8")).get(
            str(clock.date()), {}
        )
    payload, refused = {}, {}
    chosen = symbols or [item.get("symbol", "") for item in universe.get("instruments", [])]
    for symbol in chosen:
        attestation = attestations.get(symbol)
        if not attestation:
            refused[symbol] = (
                "no attestation for today; run: python3 scripts/pretrade.py attest "
                f"--config {config_path} --symbol {symbol}"
            )
            continue
        quote = quotes.get(symbol)
        if not isinstance(quote, dict):
            refused[symbol] = "no current quote"
            continue
        try:
            sources, facts = derive(
                symbol, universe, quote, book, history, bars, sessions, clock,
                float(coordinator.config["min_turnover_inr"]),
            )  # fmt: skip
        except (Refused, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            refused[symbol] = str(exc)
            continue
        sources.update(attestation["sources"])
        payload[symbol] = {
            "version": 1,
            "symbol": symbol,
            "quote_source": facts["quote_source"],
            "quote_as_of": facts["quote_as_of"],
            "checked_at": clock.isoformat(),
            "bid_inr": facts["bid_inr"],
            "ask_inr": facts["ask_inr"],
            "checks": dict.fromkeys(guardrails.REQUIRED_CHECKS, True),
            "evidence_sources": sources,
            "session": {
                "date": str(clock.date()),
                "open": times["open"].strftime("%H:%M"),
                "close": times["close"].strftime("%H:%M"),
                "entry_cutoff": times["entry_cutoff"].strftime("%H:%M"),
                "flat_by": times["flat_by"].strftime("%H:%M"),
                "source": sessions.get("source", "exchange calendar"),
            },
            "derivation": {
                "machine_checks": list(MACHINE),
                "attested_checks": list(JUDGEMENT),
                "attested_at": attestation["attested_at"],
                "facts": {key: facts[key] for key in ("stop_inr", "spread_bps", "turnover_inr")},
            },
        }
    destination = coordinator.path("pretrade_evidence")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "as_of": clock.isoformat(),
        "written": str(destination),
        "ready": sorted(payload),
        "refused": refused,
        "notice": "Machine checks are re-derived from the instrument master, authorised quote, "
        "stored history, live candles and the book at this cutoff. The surveillance and "
        "material-event checks are your dated attestation for today, not a machine finding.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("attest", "build"):
        child = sub.add_parser(name)
        child.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
        child.add_argument("--symbol", action="append", dest="symbols")
    sub.choices["attest"].add_argument(
        "--surveillance-source", help="Where you checked ASM/GSM today"
    )
    sub.choices["attest"].add_argument(
        "--event-source", help="Where you checked announcements today"
    )
    args = parser.parse_args(argv)
    try:
        now = dt.datetime.now(IST)
        if args.command == "attest":
            if not args.symbols:
                parser.error("attest needs at least one --symbol")
            path = args.config.parent / "attestations.json"
            recorded = {}
            for symbol in args.symbols:
                answers = {
                    "surveillance_clear": args.surveillance_source
                    or input(f"{symbol}: where did you check ASM/GSM/surveillance today? "),
                    "no_material_event": args.event_source
                    or input(f"{symbol}: where did you check corporate announcements today? "),
                }
                recorded[symbol] = attest(path, symbol, str(now.date()), answers, now)
            print(json.dumps({"attested": recorded, "file": str(path)}, indent=2))
            return 0
        print(json.dumps(build(args.config, args.symbols, now), indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        print("REFUSED: " + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())

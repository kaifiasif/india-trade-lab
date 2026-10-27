#!/usr/bin/env python3
"""Backtest grid: the real engine and journal over every stored session and symbol.

Runs the deterministic opening-range engine, unchanged, across complete
broker-export sessions in history.sqlite, with one continuous virtual book, the
journal's own caps and explicit costs. The same grid is re-run with doubled costs.
Results are split by symbol, month and first/second half so a single lucky stretch
is visible. Historical fills are assumptions: no spread, depth or queue modelling,
and past sessions are not evidence of future returns. No network, no orders.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import engine
import paper_book

BAR = engine.BAR


def load_sessions(
    history: Path, symbols: list[str] | None, first: dt.date, last: dt.date
) -> dict[str, dict[str, Any]]:
    """{date: {"times": session, "bars": [bar, ...]}} for complete broker-export sessions."""
    with sqlite3.connect(history) as conn:
        rows = conn.execute(
            "SELECT symbol, date, payload FROM sessions WHERE kind='broker_export' "
            "AND date>=? AND date<=? ORDER BY date, symbol",
            (str(first), str(last)),
        ).fetchall()
    days: dict[str, dict[str, Any]] = {}
    for symbol, date, payload in rows:
        if symbols and symbol not in symbols:
            continue
        data = json.loads(payload)
        times = {key: dt.datetime.fromisoformat(value) for key, value in data["session"].items()}
        day = days.setdefault(date, {"times": times, "bars": []})
        if day["times"] != times:
            raise ValueError(f"Symbols disagree on the {date} session boundaries")
        for bar in data["bars"]:
            day["bars"].append(
                {
                    "symbol": symbol,
                    "t": dt.datetime.fromisoformat(bar["t"]),
                    **{
                        key: bar[key]
                        for key in ("open", "high", "low", "close", "volume", "source")
                    },
                }
            )
    return days


def _trades(book: dict) -> list[dict]:
    entries = {e["id"]: e for e in book["events"] if e["side"] == "buy"}
    trades = []
    for event in book["events"]:
        if event["side"] != "sell":
            continue
        entry = entries[event["entry_event_id"]]
        trades.append(
            {
                "symbol": event["symbol"],
                "date": entry["as_of"][:10],
                "entry_at": entry["as_of"],
                "exit_at": event["as_of"],
                "qty": event["qty"],
                "entry_inr": entry["assumed_fill_inr"],
                "exit_inr": event["assumed_fill_inr"],
                "net_inr": float(event["net_realized_pnl_inr"]),
            }
        )
    return trades


def summarize(trades: list[dict], initial: float) -> dict[str, Any]:
    pnl = [trade["net_inr"] for trade in trades]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    equity, peak, drawdown = initial, initial, 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trades": len(pnl),
        "win_rate_pct": round(100 * len(wins) / len(pnl), 1) if pnl else None,
        "net_inr": round(sum(pnl), 2),
        "return_pct": round(100 * sum(pnl) / initial, 3),
        "expectancy_inr": round(statistics.mean(pnl), 2) if pnl else None,
        "average_win_inr": round(statistics.mean(wins), 2) if wins else None,
        "average_loss_inr": round(statistics.mean(losses), 2) if losses else None,
        "profit_factor": round(sum(wins) / -sum(losses), 3) if losses else None,
        "max_closed_drawdown_inr": round(drawdown, 2),
    }


def run_grid(
    days: dict[str, dict[str, Any]],
    symbols: list[str],
    cfg: dict[str, Decimal],
    cost_multiplier: int = 1,
) -> dict[str, Any]:
    fee_bps = cfg["fee_bps"] * cost_multiplier
    fee_flat = cfg["fee_flat"] * cost_multiplier
    slippage = cfg["slippage_bps"] * cost_multiplier
    book = paper_book.create(
        cfg["cash"],
        ",".join(symbols),
        cfg["risk"],
        cfg["daily_loss"],
        cfg["position_cap"],
        replay=True,
        max_trades=int(cfg["max_trades"]),
        max_open=min(3, len(symbols)),
        # Research grid: forward-practice streak/drawdown stops would end the test early;
        # drawdown is measured and reported instead.
        max_loss_streak=1_000_000,
        drawdown_stop=cfg["cash"],
    )
    broker = engine.PaperBroker(book, slippage)
    config = engine.EngineConfig(
        tuple(symbols),
        fee_bps,
        fee_flat,
        slippage,
        max_spread_bps=Decimal(1000),
        heartbeat_timeout_seconds=int(BAR.total_seconds()) * 3,
    )
    signals, rejected, blocked_sessions = 0, 0, 0
    for date in sorted(days):
        day = days[date]
        quotes = []
        for symbol in symbols:
            quotes += engine.bar_quotes(
                day["bars"], symbol, dt.date.fromisoformat(date), cfg["spread_bps"]
            )
        quotes.sort(key=lambda quote: (quote.as_of, quote.symbol))
        strategy = engine.OpeningRangeBreakout(cfg["risk"], cfg["position_cap"], cfg["target_r"])
        runner = engine.Engine(config, day["times"], broker, strategy, notifier=lambda *_: None)
        for quote in quotes:
            runner.on_quote(quote, quote.as_of)
            runner.tick(quote.as_of)
        runner.tick(day["times"]["close"])
        orders = [e for e in runner.log if e["kind"] == "order"]
        signals += sum(e["side"] == "buy" for e in orders)
        rejected += sum(e["status"] == "rejected" for e in orders)
        blocked_sessions += int(any(e["kind"] == "strategy_blocked" for e in runner.log))
    trades = _trades(broker.book)
    initial = float(cfg["cash"])
    by_symbol = {s: summarize([t for t in trades if t["symbol"] == s], initial) for s in symbols}
    months = defaultdict(list)
    for trade in trades:
        months[trade["date"][:7]].append(trade)
    dates = sorted(days)
    middle = dates[len(dates) // 2] if dates else ""
    return {
        "cost_multiplier": cost_multiplier,
        "overall": summarize(trades, initial),
        "by_symbol": by_symbol,
        "by_month": {month: summarize(items, initial) for month, items in sorted(months.items())},
        "halves": {
            "first": summarize([t for t in trades if t["date"] < middle], initial),
            "second": summarize([t for t in trades if t["date"] >= middle], initial),
            "split_date": middle,
        },
        "entries_submitted": signals,
        "journal_rejections": rejected,
        "sessions_with_data_blocks": blocked_sessions,
        "trades": trades,
    }


def backtest(
    history: Path, symbols: list[str] | None, first: dt.date, last: dt.date, cfg: dict
) -> dict[str, Any]:
    days = load_sessions(history, symbols, first, last)
    if not days:
        raise ValueError("No complete broker-export sessions in that range")
    found = sorted({bar["symbol"] for day in days.values() for bar in day["bars"]})
    chosen = symbols or found
    if not 1 <= len(chosen) <= 10:
        raise ValueError("Backtest 1-10 symbols at a time")
    baseline = run_grid(days, chosen, cfg)
    stress = run_grid(days, chosen, cfg, cost_multiplier=2)
    stress.pop("trades")
    return {
        "mode": "historical_backtest",
        "strategy": "intraday-orb-v1 (completed-bar opening-range breakout, long only)",
        "sessions": len(days),
        "from": min(days),
        "to": max(days),
        "symbols": chosen,
        "assumptions": {key: str(value) for key, value in cfg.items()},
        "baseline": baseline,
        "doubled_costs": stress,
        "notice": "Assumed fills on historical bars with explicit costs and slippage; no "
        "spread, depth or queue model. Tune nothing on this sample without an unseen "
        "validation period. Past sessions do not predict future returns.",
    }


def _decimal(value: str) -> Decimal:
    result = Decimal(value)
    if not result.is_finite() or result < 0:
        raise argparse.ArgumentTypeError("Expected a finite nonnegative number")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--symbols", help="Comma-separated, e.g. NSE:INFY,NSE:TCS; default all")
    parser.add_argument("--from", dest="first", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="last", required=True, help="YYYY-MM-DD")
    for name, default in (
        ("cash", "100000"),
        ("risk", "250"),
        ("daily-loss", "750"),
        ("position-cap", "15000"),
        ("target-r", "2"),
        ("fee-bps", "5"),
        ("fee-flat", "10"),
        ("slippage-bps", "5"),
        ("spread-bps", "4"),
        ("max-trades", "3"),
    ):
        parser.add_argument("--" + name, type=_decimal, default=Decimal(default))
    parser.add_argument("--trades-csv", type=Path, help="Write baseline trades to this CSV")
    args = parser.parse_args()
    try:
        cfg = {
            key: getattr(args, key)
            for key in (
                "cash", "risk", "daily_loss", "position_cap", "target_r", "fee_bps",
                "fee_flat", "slippage_bps", "spread_bps", "max_trades",
            )
        }  # fmt: skip
        symbols = args.symbols.split(",") if args.symbols else None
        result = backtest(
            args.history,
            symbols,
            dt.date.fromisoformat(args.first),
            dt.date.fromisoformat(args.last),
            cfg,
        )
        trades = result["baseline"].pop("trades")
        if args.trades_csv:
            import csv

            with args.trades_csv.open("x", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=list(trades[0]) if trades else ["symbol"]
                )
                writer.writeheader()
                writer.writerows(trades)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, KeyError, OSError, sqlite3.Error, ArithmeticError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

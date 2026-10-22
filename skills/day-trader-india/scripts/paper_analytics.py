#!/usr/bin/env python3
"""Auditable paper performance, fresh liquidation marks and matched-window benchmarks."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from guardrails import evidence_time

import paper_book


def read_snapshot(path: Path) -> dict:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
        row = conn.execute("SELECT data FROM book WHERE id=1").fetchone()
    if not row:
        raise ValueError("Paper book is empty")
    book = json.loads(row[0])
    paper_book.verify_state(book)
    return book


def benchmark_return(benchmark: dict | None, entry: dict, exit: dict) -> dict:
    """Use observations at/before each fill, at most 120 seconds old; never daily-close proxies."""
    missing = {"benchmark_return_pct": None, "alpha_pp": None, "benchmark_status": "DATA_REQUIRED"}
    if (
        not benchmark
        or benchmark.get("price_basis") != "price_return"
        or not benchmark.get("symbol")
    ):
        return missing
    try:
        points = benchmark["observations"]
        if (
            not isinstance(points, list)
            or len(points) > 100_000
            or any(
                not isinstance(point, dict) or not isinstance(point.get("source"), str)
                for point in points
            )
        ):
            return missing
        matched = []
        matched_points = []
        for event in (entry, exit):
            cutoff = evidence_time(event["as_of"])
            eligible = [
                point
                for point in points
                if point.get("source")
                and "SYNTHETIC" not in point["source"].upper()
                and 0 <= (cutoff - evidence_time(point["as_of"])).total_seconds() <= 120
            ]
            if not eligible:
                return missing
            latest = max(eligible, key=lambda item: evidence_time(item["as_of"]))
            matched.append(paper_book.number(latest["price_inr"], True))
            matched_points.append({key: latest[key] for key in ("as_of", "price_inr", "source")})
        return {
            "benchmark": benchmark["symbol"],
            "benchmark_observations": matched_points,
            "benchmark_return_pct": str(100 * (matched[1] / matched[0] - 1)),
            "benchmark_status": "MATCHED_FILL_WINDOWS",
        }
    except (ValueError, TypeError, KeyError):
        return missing


def closed_outcomes(book: dict, as_of: dt.datetime, benchmark: dict | None = None) -> list[dict]:
    entries = {event["id"]: event for event in book["events"] if event["side"] == "buy"}
    results = []
    for event in book["events"]:
        if evidence_time(event["as_of"]) > as_of:
            raise ValueError("Current book contains future fills; cannot reconstruct a past cutoff")
        if event["side"] != "sell":
            continue
        entry = entries[event["entry_event_id"]]
        pnl, cost = (
            Decimal(event["net_realized_pnl_inr"]),
            Decimal(entry["assumed_fill_inr"]) * entry["qty"] + Decimal(entry["fee_inr"]),
        )
        result = {
            "entry_event_id": entry["id"],
            "exit_event_id": event["id"],
            "symbol": event["symbol"],
            "opened_at": entry["as_of"],
            "closed_at": event["as_of"],
            "net_pnl_inr": str(pnl),
            "return_pct": str(100 * pnl / cost),
            "patterns": entry.get("research_meta", {}).get("patterns", ["UNLABELLED"]),
            "strategy_version": entry.get("research_meta", {}).get(
                "strategy_version", "manual_unversioned"
            ),
            **benchmark_return(benchmark, entry, event),
        }
        if result["benchmark_return_pct"] is not None:
            result["alpha_pp"] = str(
                Decimal(result["return_pct"]) - Decimal(result["benchmark_return_pct"])
            )
        results.append(result)
    return results


def summarize(values: list[Decimal]) -> dict:
    wins, losses = [n for n in values if n > 0], [n for n in values if n < 0]
    return {
        "closed_trades": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": str(Decimal(100) * len(wins) / len(values)) if values else None,
        "net_pnl_inr": str(sum(values, Decimal(0))),
        "expectancy_inr": str(sum(values, Decimal(0)) / len(values)) if values else None,
        "profit_factor": str(sum(wins) / -sum(losses)) if losses else None,
        "profit_factor_note": "Undefined without losing trades" if not losses else None,
    }


def performance(
    book: dict,
    quotes: dict,
    as_of: dt.datetime,
    benchmark: dict | None = None,
    operating_cost_inr: str = "0",
    fee_bps: str = "5",
    fee_flat: str = "10",
    slippage_bps: str = "5",
) -> dict:
    """Closed-trade P&L and mark-to-market are separate; missing marks never default to entry cost."""
    if as_of.tzinfo is None or book.get("currency") != "INR":
        raise ValueError("Require aware cutoff and INR paper book")
    paper_book.verify_state(book)
    outcomes = closed_outcomes(book, as_of, benchmark)
    costs = paper_book.number(operating_cost_inr)
    bps, flat, slip = (paper_book.number(value) for value in (fee_bps, fee_flat, slippage_bps))
    if slip >= 10000:
        raise ValueError("Invalid liquidation slippage")
    marks, missing = [], []
    for symbol, position in book["positions"].items():
        try:
            quote = quotes[symbol]
            if (
                quote.get("timestamp_kind", "exchange") != "exchange"
                or not isinstance(quote.get("source"), str)
                or not quote["source"]
                or "SYNTHETIC" in quote["source"].upper()
            ):
                raise ValueError("Original quote source/timestamp is unavailable")
            if not -5 <= (as_of - evidence_time(quote["as_of"])).total_seconds() <= 120:
                raise ValueError("Liquidation mark is stale")
            bid, ask = (
                paper_book.number(quote["bid_inr"], True),
                paper_book.number(quote["ask_inr"], True),
            )
            if bid > ask:
                raise ValueError("Crossed liquidation quote")
            price = Decimal(paper_book.money(bid * (1 - slip / 10000)))
            exit_fee = Decimal(paper_book.money(bid * position["qty"] * bps / 10000 + flat))
            liquidation = price * position["qty"] - exit_fee
            marks.append(
                {
                    "symbol": symbol,
                    "quote_as_of": quote["as_of"],
                    "source": quote["source"],
                    "estimated_liquidation_inr": str(liquidation),
                    "estimated_exit_fee_inr": str(exit_fee),
                    "unrealized_net_inr": str(liquidation - Decimal(position["cost_inr"])),
                }
            )
        except (ValueError, TypeError, KeyError):
            missing.append(symbol)
    realized = sum((Decimal(item["net_pnl_inr"]) for item in outcomes), Decimal(0))
    unrealized = (
        sum((Decimal(item["unrealized_net_inr"]) for item in marks), Decimal(0))
        if not missing
        else None
    )
    equity = (
        Decimal(book["cash"])
        + sum((Decimal(item["estimated_liquidation_inr"]) for item in marks), Decimal(0))
        if not missing
        else None
    )
    daily: dict[str, dict] = {}
    patterns: dict[str, list[Decimal]] = {}
    peak, curve, max_dd = Decimal(book["initial_cash"]), Decimal(book["initial_cash"]), Decimal(0)
    for item in outcomes:
        value = Decimal(item["net_pnl_inr"])
        curve += value
        peak = max(peak, curve)
        max_dd = max(max_dd, peak - curve)
        day = str(evidence_time(item["closed_at"]).astimezone(paper_book.IST).date())
        daily.setdefault(day, {"values": [], "fees": Decimal(0)})["values"].append(value)
        for pattern in set(item["patterns"]):
            patterns.setdefault(pattern, []).append(value)
    for event in book["events"]:
        day = str(evidence_time(event["as_of"]).astimezone(paper_book.IST).date())
        daily.setdefault(day, {"values": [], "fees": Decimal(0)})["fees"] += Decimal(
            event["fee_inr"]
        )
    return {
        "as_of": as_of.isoformat(),
        "mode": book["mode"],
        "forward_record": book["mode"] == "paper_manual",
        "book_state_sha256": book.get("state_sha256"),
        "book_id": book.get("book_id"),
        "initial_cash_inr": book["initial_cash"],
        "summary": summarize([Decimal(r["net_pnl_inr"]) for r in outcomes]),
        "realized_inr": str(realized),
        "unrealized_net_inr": str(unrealized) if unrealized is not None else None,
        "estimated_liquidation_equity_inr": str(equity) if equity is not None else None,
        "total_net_after_operating_cost_inr": str(realized + unrealized - costs)
        if unrealized is not None
        else None,
        "operating_cost_inr": str(costs),
        "missing_marks": missing,
        "marks": marks,
        "maximum_closed_trade_drawdown_inr": str(max_dd),
        "current_closed_trade_drawdown_inr": book.get("closed_trade_drawdown_inr"),
        "loss_streak": book.get("loss_streak"),
        "outcomes": outcomes,
        "daily": [
            {"date": day, **summarize(row["values"]), "recorded_fees_inr": str(row["fees"])}
            for day, row in sorted(daily.items())
        ],
        "patterns": [
            {"pattern": name, **summarize(values)} for name, values in sorted(patterns.items())
        ],
        "notice": "Virtual outcomes only. Pattern groups overlap and must not be added. Marks include assumed exit costs/slippage; income tax is not calculated. Missing benchmark windows remain unscored.",
    }


def save_performance(path: Path, report: dict) -> dict:
    """Persist sampled equity and observed drawdown; never label it continuous intraday drawdown."""
    if not isinstance(report.get("book_id"), str) or not report["book_id"]:
        raise ValueError(
            "Persistent performance requires a book identity; preserve legacy reports separately"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    cutoff = evidence_time(report["as_of"])
    with sqlite3.connect(path, isolation_level=None) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS performance (at TEXT PRIMARY KEY, data TEXT)")
        samples = [json.loads(row[0]) for row in conn.execute("SELECT data FROM performance")]
        if any(item.get("book_id") != report["book_id"] for item in samples):
            raise ValueError("Cannot mix paper books in one performance history")
        same = next((item for item in samples if evidence_time(item["as_of"]) == cutoff), None)
        if same:
            derived = {"maximum_sampled_equity_drawdown_inr", "equity_sampling_note"}
            if {k: v for k, v in same.items() if k not in derived} != {
                k: v for k, v in report.items() if k not in derived
            }:
                raise ValueError("Conflicting snapshot at the same observation time")
            conn.commit()
            return same
        if any(evidence_time(item["as_of"]) > cutoff for item in samples):
            raise ValueError("Performance snapshots must be chronological")
        samples.sort(key=lambda item: evidence_time(item["as_of"]))
        peak, drawdown = Decimal(report["initial_cash_inr"]), Decimal(0)
        for item in samples + [report]:
            if item.get("estimated_liquidation_equity_inr") is None:
                continue
            value = Decimal(item["estimated_liquidation_equity_inr"])
            peak = max(peak, value)
            drawdown = max(drawdown, peak - value)
        result = {
            **report,
            "maximum_sampled_equity_drawdown_inr": str(drawdown),
            "equity_sampling_note": "Observed snapshot drawdown; unsampled moves are unknown",
        }
        conn.execute("INSERT INTO performance VALUES (?,?)", (report["as_of"], json.dumps(result)))
        conn.commit()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", type=Path, required=True)
    parser.add_argument("--quotes", type=Path)
    parser.add_argument("--benchmark", type=Path)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--operating-cost-inr", default="0")
    parser.add_argument("--save", type=Path)
    args = parser.parse_args()
    try:
        result = performance(
            read_snapshot(args.book),
            json.loads(args.quotes.read_text()) if args.quotes else {},
            evidence_time(args.as_of),
            json.loads(args.benchmark.read_text()) if args.benchmark else None,
            args.operating_cost_inr,
        )
        if args.save:
            result = save_performance(args.save, result)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
        print("DATA_BLOCK: valid paper book and correctly dated observations required")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

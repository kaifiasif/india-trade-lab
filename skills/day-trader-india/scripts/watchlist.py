#!/usr/bin/env python3
"""Build a dated research watchlist from declared equity instruments and retained history."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any

from history import HistoryStore


def build_watchlist(
    store: HistoryStore,
    universe: dict,
    as_of: dt.datetime,
    minimum: int = 50,
    top: int = 10,
    min_turnover_inr: float = 20_000_000,
) -> dict[str, Any]:
    """Rank eligible cash equities by prior 20-session average traded-value proxy.

    This shortlist is not a buy signal. Current quotes, events, surveillance evidence,
    completed-bar confirmation and risk checks remain required before any paper entry.
    """
    if as_of.tzinfo is None or not 1 <= top <= 50 or minimum < 50:
        raise ValueError("Require an aware cutoff, at least 50 sessions and 1–50 candidates")
    if not math.isfinite(min_turnover_inr) or min_turnover_inr <= 0:
        raise ValueError("Turnover threshold must be finite and positive")
    if not isinstance(universe, dict):
        raise ValueError("Expected an instrument master object")
    published = dt.datetime.fromisoformat(universe.get("as_of", ""))
    age = (as_of - published).total_seconds() if published.tzinfo else -1
    if not universe.get("source") or not 0 <= age <= 30 * 86400:
        raise ValueError("Need a sourced instrument master dated within 30 days, never future")
    instruments = universe.get("instruments")
    if not isinstance(instruments, list) or len(instruments) > 5000:
        raise ValueError("Expected a bounded instrument-master list")
    candidates, blocked, seen = [], [], set()
    for instrument in instruments:
        if not isinstance(instrument, dict):
            raise ValueError("Expected an instrument object")
        symbol = instrument.get("symbol", "")
        if not re.fullmatch(r"(NSE|BSE):[A-Z0-9&.\-]+", symbol) or symbol in seen:
            raise ValueError("Invalid or duplicate exchange-qualified instrument")
        seen.add(symbol)
        reason = None
        if (
            instrument.get("segment") != "EQ"
            or instrument.get("active") is not True
            or not re.fullmatch(r"IN[A-Z0-9]{10}", instrument.get("isin", ""))
        ):
            reason = "Instrument is not a declared active EQ security with an ISIN"
        coverage = store.coverage(symbol, as_of, minimum)
        if not coverage["history_ready"]:
            reason = coverage["reason"]
        elif (as_of.date() - dt.date.fromisoformat(coverage["last_session"])).days > 7:
            reason = "Latest complete session is older than seven calendar days"
        if reason:
            blocked.append({"symbol": symbol, "reason": reason})
            continue
        with sqlite3.connect(store.path) as conn:
            rows = conn.execute(
                "SELECT close_at,payload FROM sessions WHERE symbol=? "
                "AND kind='broker_export' ORDER BY date",
                (symbol,),
            ).fetchall()
        days = [
            json.loads(row[1])["bars"] for row in rows if dt.datetime.fromisoformat(row[0]) <= as_of
        ][-20:]
        turnover = sum(sum(bar["close"] * bar["volume"] for bar in day) for day in days) / len(days)
        if turnover < min_turnover_inr:
            blocked.append(
                {"symbol": symbol, "reason": "Prior average traded value below threshold"}
            )
            continue
        candidates.append(
            {
                "symbol": symbol,
                "status": "WAIT_FOR_SETUP",
                "reason": "History and traded-value checks passed; current setup still required",
                "average_turnover_inr": round(turnover, 2),
                "last_close": days[-1][-1]["close"],
                "history_sessions": coverage["completed_sessions"],
                "last_session": coverage["last_session"],
                "source": universe["source"],
            }
        )
    candidates.sort(key=lambda item: (-item["average_turnover_inr"], item["symbol"]))
    return {
        "as_of": as_of.isoformat(),
        "mode": "research_only",
        "source": universe["source"],
        "policy": {
            "minimum_sessions": minimum,
            "top": top,
            "min_average_turnover_inr": min_turnover_inr,
            "ranking": "Prior 20-session mean of sum(close × volume); turnover proxy",
        },
        "candidates": [
            {"rank": index + 1, **candidate} for index, candidate in enumerate(candidates[:top])
        ],
        "blocked": blocked,
        "notice": "Watchlist inclusion is not BUY approval. No current market feed or news is fetched.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/observatory/history.sqlite"))
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--min-turnover-inr", type=float, default=20_000_000)
    args = parser.parse_args()
    try:
        result = build_watchlist(
            HistoryStore(args.db),
            json.loads(args.universe.read_text()),
            dt.datetime.fromisoformat(args.as_of),
            top=args.top,
            min_turnover_inr=args.min_turnover_inr,
        )
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

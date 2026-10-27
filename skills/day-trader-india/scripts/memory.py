#!/usr/bin/env python3
"""Decision memory: record each rated call, settle it on later prices, keep the lesson.

Every debate that reaches a rating is logged once per symbol and session, with
the quote it was made on. Once the holding window has closed in history.sqlite,
the call is settled: raw return from the decision quote to the window's last
close, alpha against matched benchmark observations when supplied, and whether
the rating's direction was right. Lessons are offered to later debates only if
their outcome was known by that debate's cutoff, so nothing learns from the future.
Settlement and scoring are deterministic; a model reflection is optional.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import statistics
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from guardrails import evidence_time
from history import HistoryStore

DIRECTION = {"Buy": 1, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -1}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _benchmark_at(benchmark: dict | None, cutoff: dt.datetime, window: int) -> float | None:
    """Latest non-synthetic benchmark price at or before the cutoff, within the window."""
    if not benchmark or benchmark.get("price_basis") != "price_return":
        return None
    eligible = []
    for point in benchmark.get("observations", [])[:100_000]:
        try:
            observed = evidence_time(point["as_of"])
            source = str(point["source"])
            price = float(point["price_inr"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            "SYNTHETIC" not in source.upper()
            and price > 0
            and 0 <= (cutoff - observed).total_seconds() <= window
        ):
            eligible.append((observed, price))
    return max(eligible)[1] if eligible else None


class DecisionMemory:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS decisions ("
                "id TEXT PRIMARY KEY, symbol TEXT NOT NULL, session_date TEXT NOT NULL, "
                "decided_at TEXT NOT NULL, rating TEXT NOT NULL, conviction TEXT, "
                "reference_inr REAL NOT NULL, horizon_sessions INTEGER NOT NULL, "
                "proposal_sha256 TEXT, thesis TEXT, status TEXT NOT NULL, resolved_at TEXT, "
                "exit_session TEXT, raw_return_pct REAL, benchmark_return_pct REAL, "
                "alpha_pp REAL, hit INTEGER, lesson TEXT, lesson_source TEXT, "
                "UNIQUE(symbol, session_date))"
            )

    def record(
        self,
        run_id: str,
        symbol: str,
        decided_at: dt.datetime,
        rating: str,
        reference_inr: float,
        horizon_sessions: int = 1,
        conviction: str | None = None,
        proposal_sha256: str | None = None,
        thesis: str = "",
    ) -> bool:
        """Log a rated call. The first call per symbol and session wins; reruns add nothing."""
        if rating not in DIRECTION or decided_at.tzinfo is None or not reference_inr > 0:
            raise ValueError("Record needs a five-tier rating, aware time and positive price")
        if type(horizon_sessions) is not int or not 1 <= horizon_sessions <= 20:
            raise ValueError("Holding window must be 1-20 sessions")
        local = decided_at.astimezone(IST)
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO decisions (id, symbol, session_date, decided_at, rating, "
                "conviction, reference_inr, horizon_sessions, proposal_sha256, thesis, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?, 'pending')",
                (
                    f"{run_id}:{symbol}",
                    symbol,
                    str(local.date()),
                    local.isoformat(),
                    rating,
                    conviction,
                    float(reference_inr),
                    horizon_sessions,
                    proposal_sha256,
                    thesis[:600],
                ),
            )
            return cursor.rowcount == 1

    def settle(
        self,
        history: HistoryStore,
        as_of: dt.datetime,
        benchmark: dict | None = None,
        reflect: Callable[[dict], str] | None = None,
    ) -> dict[str, Any]:
        """Settle every pending call whose holding window has closed in stored history."""
        if as_of.tzinfo is None:
            raise ValueError("Settlement cutoff must be timezone-aware")
        settled, failed = [], []
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            pending = [
                dict(row) for row in conn.execute("SELECT * FROM decisions WHERE status='pending'")
            ]
        for entry in pending:
            with sqlite3.connect(history.path) as conn:
                sessions = conn.execute(
                    "SELECT date, close_at, payload FROM sessions WHERE symbol=? "
                    "AND kind='broker_export' AND date>=? ORDER BY date",
                    (entry["symbol"], entry["session_date"]),
                ).fetchall()
            if len(sessions) < entry["horizon_sessions"] or sessions[0][0] != entry["session_date"]:
                continue  # Window not complete in history yet; retry on a later run.
            exit_date, close_at, payload = sessions[entry["horizon_sessions"] - 1]
            closed = dt.datetime.fromisoformat(close_at)
            if closed > as_of:
                continue
            exit_price = float(json.loads(payload)["bars"][-1]["close"])
            raw = 100 * (exit_price / entry["reference_inr"] - 1)
            start = _benchmark_at(benchmark, evidence_time(entry["decided_at"]), 120)
            end = _benchmark_at(benchmark, closed, 1800)
            bench = 100 * (end / start - 1) if start and end else None
            alpha = raw - bench if bench is not None else None
            direction = DIRECTION[entry["rating"]]
            measure = alpha if alpha is not None else raw
            hit = None if direction == 0 else int(measure * direction > 0)
            outcome = {
                **entry,
                "exit_session": exit_date,
                "exit_inr": exit_price,
                "raw_return_pct": round(raw, 3),
                "benchmark_return_pct": round(bench, 3) if bench is not None else None,
                "alpha_pp": round(alpha, 3) if alpha is not None else None,
                "hit": hit,
            }
            lesson, source = self.lesson(outcome), "deterministic"
            if reflect:
                try:
                    lesson, source = reflect(outcome), "model"
                except (ValueError, OSError, KeyError, TypeError):
                    failed.append(
                        {
                            "id": entry["id"],
                            "reason": "Reflection unavailable; kept the computed lesson",
                        }
                    )
            with sqlite3.connect(self.path) as conn:
                conn.execute(
                    "UPDATE decisions SET status='settled', resolved_at=?, exit_session=?, "
                    "raw_return_pct=?, benchmark_return_pct=?, alpha_pp=?, hit=?, lesson=?, "
                    "lesson_source=? WHERE id=? AND status='pending'",
                    (
                        close_at,
                        exit_date,
                        outcome["raw_return_pct"],
                        outcome["benchmark_return_pct"],
                        outcome["alpha_pp"],
                        hit,
                        lesson[:800],
                        source,
                        entry["id"],
                    ),
                )
            settled.append(entry["id"])
        return {"settled": settled, "failed": failed, "pending": len(pending) - len(settled)}

    @staticmethod
    def lesson(outcome: dict) -> str:
        window = outcome["horizon_sessions"]
        span = "same-session close" if window == 1 else f"close {window} sessions later"
        text = (
            f"{outcome['rating']} ({outcome.get('conviction') or 'n/a'} conviction) on "
            f"{outcome['session_date']} at INR {outcome['reference_inr']:.2f}: "
            f"{outcome['raw_return_pct']:+.2f}% to the {span}"
        )
        if outcome.get("alpha_pp") is not None:
            text += f", {outcome['alpha_pp']:+.2f} pp versus the benchmark"
        if outcome["hit"] is None:
            text += ". Hold claims no direction."
        else:
            text += ". Direction " + ("confirmed." if outcome["hit"] else "not confirmed.")
        if window == 1:
            text += " One session is a short window; treat this as one observation, not a verdict."
        return text

    def lessons(self, symbol: str, as_of: dt.datetime, same: int = 5, cross: int = 3) -> list[dict]:
        """Settled lessons known by the cutoff: recent same-symbol ones, then other symbols."""
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT symbol, session_date, rating, conviction, raw_return_pct, alpha_pp, "
                    "hit, lesson, resolved_at FROM decisions WHERE status='settled' "
                    "ORDER BY resolved_at DESC"
                )
            ]
        known = [row for row in rows if dt.datetime.fromisoformat(row["resolved_at"]) <= as_of]
        mine = [row for row in known if row["symbol"] == symbol][:same]
        others = [row for row in known if row["symbol"] != symbol][:cross]
        return mine + others

    def scorecard(self) -> dict[str, Any]:
        """Hit rate and mean returns by rating. Small samples are reported, not hidden."""
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(row) for row in conn.execute("SELECT * FROM decisions")]
        settled = [row for row in rows if row["status"] == "settled"]
        by_rating = {}
        for rating in DIRECTION:
            group = [row for row in settled if row["rating"] == rating]
            if not group:
                continue
            scored = [row["hit"] for row in group if row["hit"] is not None]
            alphas = [row["alpha_pp"] for row in group if row["alpha_pp"] is not None]
            by_rating[rating] = {
                "count": len(group),
                "hit_rate_pct": round(100 * sum(scored) / len(scored), 1) if scored else None,
                "mean_raw_return_pct": round(
                    statistics.mean(row["raw_return_pct"] for row in group), 3
                ),
                "mean_alpha_pp": round(statistics.mean(alphas), 3) if alphas else None,
            }
        return {
            "settled": len(settled),
            "pending": len(rows) - len(settled),
            "by_rating": by_rating,
            "notice": "Scores describe recorded paper research calls, not executable returns. "
            "Fewer than about 30 settled calls per rating is too few to judge.",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="memory.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scorecard")
    lessons = sub.add_parser("lessons")
    lessons.add_argument("--symbol", required=True)
    lessons.add_argument("--as-of", help="Aware ISO timestamp; defaults to now")
    settle = sub.add_parser("settle")
    settle.add_argument("--history", type=Path, required=True)
    settle.add_argument("--benchmark", type=Path, help="Benchmark observations JSON")
    args = parser.parse_args()
    try:
        memory = DecisionMemory(args.db)
        now = dt.datetime.now(IST)
        if args.command == "scorecard":
            result: Any = memory.scorecard()
        elif args.command == "lessons":
            cutoff = dt.datetime.fromisoformat(args.as_of) if args.as_of else now
            result = memory.lessons(args.symbol, cutoff)
        else:
            benchmark = json.loads(args.benchmark.read_text()) if args.benchmark else None
            result = memory.settle(HistoryStore(args.history), now, benchmark)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print("REFUSED: " + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())

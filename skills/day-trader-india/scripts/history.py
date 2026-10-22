#!/usr/bin/env python3
"""Immutable local candle history and an explicit 50-session research coverage policy."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import india_research

DEFAULT_MIN_SESSIONS = 50


class HistoryStore:
    """Retain imported complete five-minute sessions; never silently replace source history."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sessions (symbol TEXT, date TEXT, kind TEXT, "
                "close_at TEXT, digest TEXT, payload TEXT, imported_at TEXT, "
                "PRIMARY KEY(symbol,date,kind))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS calendar (symbol TEXT, date TEXT, kind TEXT, "
                "close_at TEXT, source TEXT, PRIMARY KEY(symbol,date,kind))"
            )

    def ingest(
        self, bars_path: Path, manifest_path: Path, symbol: str, kind: str, as_of: dt.datetime
    ) -> dict[str, Any]:
        """Import only complete sessions available at the supplied cutoff; reject revisions."""
        if kind not in ("synthetic", "broker_export") or as_of.tzinfo is None:
            raise ValueError("Require a history kind and timezone-aware cutoff")
        rows = [row for row in india_research.bars_from_csv(bars_path) if row["symbol"] == symbol]
        if not rows:
            raise ValueError("No bars for the requested symbol")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if kind == "broker_export" and any("SYNTHETIC" in row["source"].upper() for row in rows):
            raise ValueError("Synthetic candles cannot count as broker history")
        dates = sorted(
            {row["t"].date() for row in rows}
            | {dt.date.fromisoformat(value) for value in manifest.get("sessions", {})}
        )
        accepted, rejected = [], []
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        declared = manifest.get("sessions", {})
        with sqlite3.connect(self.path) as conn:
            for date in dates:
                if str(date) in declared and declared[str(date)] is None:
                    # Explicit closure (the router's convention): not a trading session,
                    # so it is neither imported nor counted as a missing declared session.
                    reason = "Declared exchange closure"
                    if any(row["t"].date() == date for row in rows):
                        reason += "; bars on a closed date were ignored"
                    rejected.append({"date": str(date), "reason": reason})
                    continue
                try:
                    times = india_research.session(manifest, date)
                except ValueError as exc:
                    # One undeclared or invalid date blocks that date only, not the import.
                    rejected.append({"date": str(date), "reason": str(exc)})
                    continue
                if times["close"] > as_of:
                    rejected.append({"date": str(date), "reason": "Session not complete at cutoff"})
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO calendar VALUES (?,?,?,?,?)",
                    (symbol, str(date), kind, times["close"].isoformat(), manifest["source"]),
                )
                try:
                    day, _ = india_research.checked_session(rows, manifest, date, as_of, full=True)
                except ValueError as exc:
                    rejected.append({"date": str(date), "reason": str(exc)})
                    continue
                payload = json.dumps({"bars": day, "session": times}, sort_keys=True, default=str)
                digest = hashlib.sha256(payload.encode()).hexdigest()
                existing = conn.execute(
                    "SELECT digest FROM sessions WHERE symbol=? AND date=? AND kind=?",
                    (symbol, str(date), kind),
                ).fetchone()
                if existing and existing[0] != digest:
                    raise ValueError(
                        "Conflicting historical revision; use a separate history database"
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO sessions VALUES (?,?,?,?,?,?,?)",
                    (symbol, str(date), kind, times["close"].isoformat(), digest, payload, now),
                )
                accepted.append(str(date))
        return {
            "accepted": accepted,
            "rejected": rejected,
            "kind": kind,
            "retention": "Retained until explicitly archived; no automatic deletion",
        }

    def symbols(self) -> list[str]:
        """List instruments with persisted source history."""
        with sqlite3.connect(self.path) as conn:
            return [
                row[0]
                for row in conn.execute("SELECT DISTINCT symbol FROM sessions ORDER BY symbol")
            ]

    def coverage(
        self, symbol: str, as_of: dt.datetime, minimum: int = DEFAULT_MIN_SESSIONS
    ) -> dict:
        """Use only prior completed sessions. Coverage is a data gate, never proof of an edge."""
        if (
            as_of.tzinfo is None
            or isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or minimum < 1
        ):
            raise ValueError("Require a timezone-aware cutoff and positive minimum sessions")
        with sqlite3.connect(self.path) as conn:
            sessions = conn.execute(
                "SELECT date,kind,close_at,payload,imported_at,digest FROM sessions "
                "WHERE symbol=? ORDER BY date",
                (symbol,),
            ).fetchall()
            calendar = conn.execute(
                "SELECT date,kind,close_at,source FROM calendar WHERE symbol=? ORDER BY date",
                (symbol,),
            ).fetchall()
        available = [row for row in sessions if dt.datetime.fromisoformat(row[2]) <= as_of]
        real = [row for row in available if row[1] == "broker_export"]
        synthetic = [row for row in available if row[1] == "synthetic"]
        declared = [
            row
            for row in calendar
            if row[1] == "broker_export" and dt.datetime.fromisoformat(row[2]) <= as_of
        ][-minimum:]
        complete_dates = {row[0] for row in real}
        gaps = [row[0] for row in declared if row[0] not in complete_dates]
        closes = [json.loads(row[3])["bars"][-1]["close"] for row in real]

        def average(length: int) -> float | None:
            return sum(closes[-length:]) / length if len(closes) >= length else None

        ready = len(real) >= minimum and len(declared) >= minimum and not gaps
        return {
            "symbol": symbol,
            "minimum_sessions": minimum,
            "completed_sessions": len(real),
            "synthetic_sessions": len(synthetic),
            "stored_sessions": len(available),
            "first_session": real[0][0] if real else None,
            "last_session": real[-1][0] if real else None,
            "as_of": as_of.isoformat(),
            "missing_declared_sessions": gaps,
            "history_ready": ready,
            "decision": "RESEARCH ONLY" if ready else "DATA BLOCK",
            "reason": "Coverage threshold met; strategy validation still required"
            if ready
            else (
                f"Missing {len(gaps)} declared sessions in the research window"
                if gaps
                else f"Need {minimum} complete broker-export sessions; have {len(real)}"
            ),
            "features": {"sma20": average(20), "sma50": average(50)},
            "daily_context_target": 252,
            "retention": "All imported sessions and paper-run events retained; no automatic purge",
            "provenance": "Broker export is a user-declared source, not provider authentication",
            "notice": "50 sessions is a configurable research baseline, not a safe-trading threshold. "
            "Data imports do not train an AI or authorize entries.",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/observatory/history.sqlite"))
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("import", help="Retain complete five-minute CSV sessions")
    ingest.add_argument("--bars", type=Path, required=True)
    ingest.add_argument("--sessions", type=Path, required=True)
    ingest.add_argument("--kind", choices=("synthetic", "broker_export"), required=True)
    for child in (ingest, sub.add_parser("coverage")):
        child.add_argument("--symbol", required=True)
        child.add_argument("--as-of", required=True, help="Timezone-aware evidence cutoff")
    sub.choices["coverage"].add_argument(
        "--minimum-sessions", type=int, default=DEFAULT_MIN_SESSIONS
    )
    args = parser.parse_args()
    try:
        store = HistoryStore(args.db)
        cutoff = dt.datetime.fromisoformat(args.as_of)
        result = (
            store.ingest(args.bars, args.sessions, args.symbol, args.kind, cutoff)
            if args.command == "import"
            else store.coverage(args.symbol, cutoff, args.minimum_sessions)
        )
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

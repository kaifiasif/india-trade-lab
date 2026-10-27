#!/usr/bin/env python3
"""Supervised research worker: India session reviews and optional continuous crypto data."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path

import crypto_data
from data_sync import refresh_current
from decision_pipeline import DailyCoordinator, read_json
from market_router import route_all

import evidence
import pretrade


class MarketService:
    """One process; the coordinator's durable lease prevents concurrent decision runs."""

    def __init__(
        self,
        config: Path,
        symbols: tuple[str, ...] = (),
        us_calendar: Path | None = None,
        coordinator=None,
        now=None,
        collect=crypto_data.collect,
        refresh_india: bool = False,
        prepare: bool = False,
    ) -> None:
        if len(symbols) > 5 or len(set(symbols)) != len(symbols):
            raise ValueError("Use at most five distinct crypto spot pairs")
        self.coordinator = coordinator or DailyCoordinator(config)
        self.root = config.resolve().parent
        self.path = self.root / "service.sqlite"
        self.symbols = symbols
        self.us_calendar = us_calendar
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        self.collect = collect
        self.refresh_india = refresh_india
        self.prepare = prepare
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS collected (symbol TEXT PRIMARY KEY, at REAL)")

    def tick(self) -> dict:
        now = self.now()
        calendars = []
        for path in (self.coordinator.path("sessions"), self.us_calendar):
            try:
                calendars.append(read_json(path) if path else None)
            except (ValueError, OSError, TypeError):
                calendars.append(None)
        result = route_all(now, *calendars)
        halted = (self.root / "HALT_ENTRIES").exists()
        result.update(halted=halted, crypto=[], india={"status": "DATA_BLOCK"})
        india = result["markets"][0]
        # Closed sessions may still need protective exit reviews. No entry/model reviews run.
        if india["status"] != "DATA_BLOCK":
            try:
                if self.refresh_india:
                    result["feed"] = refresh_current(self.coordinator.config_path)
                if self.prepare and india["status"] == "OPEN" and not halted:
                    result["prepared"] = self.prepare_inputs(now)
                report = self.coordinator.run_once(
                    allow_entries=india["status"] == "OPEN" and not halted
                )
                result["india"] = {"status": report["status"], "run_id": report["run_id"]}
            except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
                result["india"] = {"status": "DATA_BLOCK", "reason": "Research run unavailable"}
        for symbol in self.symbols:
            with sqlite3.connect(self.path, isolation_level=None) as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT at FROM collected WHERE symbol=?", (symbol,)).fetchone()
                if row and 0 <= now.timestamp() - row[0] < 900:
                    conn.rollback()
                    continue
                # Reserve before network access; failures are also rate limited after restart.
                conn.execute(
                    "INSERT OR REPLACE INTO collected VALUES (?,?)", (symbol, now.timestamp())
                )
                conn.commit()
            try:
                snapshot = self.collect(symbol, days=90)
                crypto_data.save_snapshot(self.root / "crypto.sqlite", snapshot)
                result["crypto"].append({"symbol": symbol, "status": "OBSERVED"})
            except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
                result["crypto"].append({"symbol": symbol, "status": "DATA_BLOCK"})
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT OR REPLACE INTO state VALUES (1,?)", (json.dumps(result),))
        return result

    def prepare_inputs(self, now: dt.datetime) -> dict:
        """Refresh collected evidence and re-derive pre-trade checks for this cutoff.

        Each step is reported separately and a failure never stops the research run:
        the coordinator still refuses the entry when an input is missing.
        """
        prepared: dict = {}
        try:
            collected = evidence.collect(self.coordinator.config_path, now)
            prepared["evidence"] = {"symbols": collected["symbols"], "notes": collected["notes"]}
        except (ValueError, KeyError, TypeError, OSError) as exc:
            prepared["evidence"] = {"status": "DATA_BLOCK", "reason": str(exc)[:200]}
        try:
            built = pretrade.build(self.coordinator.config_path, None, now)
            prepared["pretrade"] = {"ready": built["ready"], "refused": built["refused"]}
        except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
            prepared["pretrade"] = {"status": "DATA_BLOCK", "reason": str(exc)[:200]}
        return prepared


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
    parser.add_argument("--us-calendar", type=Path)
    parser.add_argument(
        "--crypto-symbols", default="", help="Opt in to public data, e.g. BTCUSDT,ETHUSDT"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--refresh-india", action="store_true", help="Opt in to mapped read-only broker feeds"
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Collect news evidence and re-derive pre-trade checks each open tick",
    )
    args = parser.parse_args()
    try:
        worker = MarketService(
            args.config,
            tuple(filter(None, args.crypto_symbols.split(","))),
            args.us_calendar,
            refresh_india=args.refresh_india,
            prepare=args.prepare,
        )
        while True:
            print(json.dumps(worker.tick()), flush=True)
            if args.once:
                return 0
            threading.Event().wait(worker.coordinator.config["poll_seconds"])
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
        print("DATA_BLOCK: invalid service configuration. No orders were sent.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

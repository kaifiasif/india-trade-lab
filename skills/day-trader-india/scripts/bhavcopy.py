#!/usr/bin/env python3
"""NSE end-of-day archive: an official second copy of every session, and market breadth.

Kite's historical candles are the desk's main data, but they are re-adjusted after
corporate actions and come from one source. Each evening this stores NSE's own full
bhavcopy (``sec_bhavdata_full_DDMMYYYY.csv``: open, high, low, close, previous close,
volume, turnover, trades, delivery) for every EQ stock in ``bhavcopy.sqlite``.

- ``gaps``: trading sessions in the calendar that the archive is missing;
- ``cross-check``: stored Kite daily closes that differ from NSE's close by more than
  0.5% (a data fault, or a corporate action Kite has adjusted for);
- ``breadth``: advances, declines, the advance/decline ratio and the share of traded
  value in rising stocks, for the market-context evidence.

One file a session, fetched once; NSE may refuse scripted requests, and then the
session is reported as a gap.

    python3 bhavcopy.py sync --days 10
    python3 bhavcopy.py gaps
    python3 bhavcopy.py cross-check 2026-10-30
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date:%d%m%Y}.csv"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS eod (symbol TEXT, date TEXT, prev_close REAL, open REAL, "
    "high REAL, low REAL, close REAL, volume REAL, turnover_lacs REAL, trades REAL, "
    "deliv_pct REAL, PRIMARY KEY(symbol, date))"
)
MISMATCH_PCT = 0.5


def _db(config_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(intraday.config_folder(config_path) / "bhavcopy.sqlite", timeout=10)
    conn.execute(SCHEMA)
    return conn


def _number(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def parse(raw: bytes, day: str) -> list[tuple]:
    import market_scan

    rows = []
    for row in market_scan._csv(raw):
        if row.get("SERIES") != "EQ" or not row.get("SYMBOL"):
            continue
        close = _number(row.get("CLOSE_PRICE", ""))
        if close is None:
            continue
        rows.append((
            f"NSE:{row['SYMBOL']}", day, _number(row.get("PREV_CLOSE", "")), _number(row.get("OPEN_PRICE", "")),
            _number(row.get("HIGH_PRICE", "")), _number(row.get("LOW_PRICE", "")), close,
            _number(row.get("TTL_TRD_QNTY", "")), _number(row.get("TURNOVER_LACS", "")),
            _number(row.get("NO_OF_TRADES", "")), _number(row.get("DELIV_PER", "")),
        ))  # fmt: skip
    if not rows:
        raise ValueError("That is not NSE's full bhavcopy")
    return rows


def _sessions(config_path: Path, before: dt.date, count: int) -> list[str]:
    manifest = intraday.sessions_manifest(config_path)
    days = sorted(day for day, value in manifest["sessions"].items() if value and day < str(before))
    return days[-count:]


def stored_days(config_path: Path) -> set[str]:
    with _db(config_path) as conn:
        return {row[0] for row in conn.execute("SELECT DISTINCT date FROM eod")}


def sync(
    config_path: Path, clock: dt.datetime, days: int = 10, get: Callable[[str], bytes] | None = None
) -> dict:
    """Fetch the sessions of the last ``days`` that are not stored yet (today after 18:00)."""
    import market_scan

    get = get or market_scan.nse_fetch
    cutoff = clock.date() + dt.timedelta(days=1) if clock.hour >= 18 else clock.date()
    have = stored_days(config_path)
    stored, missing = [], {}
    for day in _sessions(config_path, cutoff, days):
        if day in have:
            continue
        try:
            rows = parse(get(URL.format(date=dt.date.fromisoformat(day))), day)
        except (ValueError, OSError) as exc:
            missing[day] = str(exc)[:100]
            continue
        with _db(config_path) as conn:
            conn.executemany("INSERT OR REPLACE INTO eod VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        stored.append(day)
    return {"stored": stored, "missing": missing}


def gaps(config_path: Path, clock: dt.datetime, days: int = 30) -> list[str]:
    have = stored_days(config_path)
    return [day for day in _sessions(config_path, clock.date(), days) if day not in have]


def cross_check(config_path: Path, day: str) -> dict[str, Any]:
    """Kite daily closes (scan.sqlite) against NSE's close for one session."""
    folder = intraday.config_folder(config_path)
    with _db(config_path) as conn:
        nse = dict(conn.execute("SELECT symbol, close FROM eod WHERE date=?", (day,)).fetchall())
    if not nse:
        raise ValueError(f"No NSE bhavcopy stored for {day}; run: bhavcopy.py sync")
    try:
        with sqlite3.connect(folder / "scan.sqlite") as conn:
            kite = dict(
                conn.execute("SELECT symbol, close FROM daily WHERE date=?", (day,)).fetchall()
            )
    except sqlite3.Error:
        kite = {}
    compared, mismatches = 0, []
    for symbol, close in sorted(kite.items()):
        official = nse.get(symbol)
        if not official:
            continue
        compared += 1
        gap = 100 * (close / official - 1)
        if abs(gap) > MISMATCH_PCT:
            mismatches.append(
                {"symbol": symbol, "kite": close, "nse": official, "diff_pct": round(gap, 2)}
            )
    return {"date": day, "compared": compared, "mismatches": mismatches,
            "note": "a mismatch is a data fault or a corporate action Kite adjusted for"}  # fmt: skip


def breadth(config_path: Path, day: str | None = None) -> dict[str, Any] | None:
    """Advances, declines and the share of traded value in rising stocks for one session."""
    with _db(config_path) as conn:
        day = day or conn.execute("SELECT MAX(date) FROM eod").fetchone()[0]
        if not day:
            return None
        rows = conn.execute(
            "SELECT close, prev_close, turnover_lacs FROM eod WHERE date=? AND prev_close > 0",
            (day,),
        ).fetchall()
    if not rows:
        return None
    up = [row for row in rows if row[0] > row[1]]
    down = [row for row in rows if row[0] < row[1]]
    value = sum(row[2] or 0 for row in rows)
    return {
        "date": day, "advances": len(up), "declines": len(down),
        "unchanged": len(rows) - len(up) - len(down),
        "advance_decline_ratio": round(len(up) / len(down), 2) if down else None,
        "value_in_advancers_pct": round(100 * sum(row[2] or 0 for row in up) / value, 1) if value else None,
        "source": "NSE full bhavcopy, EQ series",
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    syncing = sub.add_parser("sync")
    syncing.add_argument("--days", type=int, default=10)
    sub.add_parser("gaps")
    checking = sub.add_parser("cross-check")
    checking.add_argument("date")
    sub.add_parser("breadth")
    args = parser.parse_args(argv)
    clock = intraday.now_ist()
    try:
        if args.command == "sync":
            result: Any = sync(args.config, clock, max(1, min(args.days, 60)))
        elif args.command == "gaps":
            result = gaps(args.config, clock)
        elif args.command == "cross-check":
            result = cross_check(args.config, args.date)
        else:
            result = breadth(args.config)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"Bhavcopy refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

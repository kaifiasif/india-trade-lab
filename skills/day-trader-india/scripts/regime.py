#!/usr/bin/env python3
"""Market regime: what kind of market each day was, and how each strategy did in it.

A breakout strategy can earn in a trending, calm market and bleed in a choppy, fearful
one. An average over every day hides that. Each completed session gets a label from
data known at its close:

| Part | Rule |
| --- | --- |
| Trend | Nifty 50 above its 50-day average and the average rising: ``up``; below and falling: ``down``; else ``sideways`` |
| Volatility | India VIX close under 13: ``calm``; 13 to 20: ``normal``; above 20: ``high`` |
| Breadth (shown, not in the label) | share of stored stocks closing above their own 50-day average |

The label is ``trend/volatility``, for example ``up/calm``. A trade on day D uses the
label of the session before D, so no trade knows its own day's close.

Both tournaments record each strategy's results per label (``by_regime``). Gate: when
today's label has at least ``min_trades`` (20) past trades for a strategy and their
expectancy at doubled costs is not positive, that strategy sits out today. With fewer
trades the label is shown but does not decide. The gate can only remove strategies.

Nifty and VIX daily candles are stored by ``market_scan.py nightly`` in the
``index_daily`` table of ``scan.sqlite``.

    python3 regime.py today
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
NIFTY, VIX = "NSE:NIFTY 50", "NSE:INDIA VIX"
INDEX_NAMES = {"NIFTY 50": NIFTY, "INDIA VIX": VIX}
DEFAULTS = {"enabled": True, "min_trades": 20}
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS index_daily (symbol TEXT, date TEXT, open REAL, high REAL, "
    "low REAL, close REAL, volume REAL, PRIMARY KEY(symbol, date))"
)


def index_tokens(rows: list[dict[str, str]]) -> dict[str, str]:
    """Kite instrument tokens of the Nifty 50 and India VIX from the instrument list."""
    found = {}
    for row in rows:
        if row.get("segment") == "INDICES" and row.get("tradingsymbol") in INDEX_NAMES:
            found[INDEX_NAMES[row["tradingsymbol"]]] = row["instrument_token"]
    return found


def store_indices(
    scan_db: Path, client: Any, rows: list[dict], before: dt.date, days: int = 400
) -> dict:
    """Fetch the missing daily candles of both indices into ``index_daily``."""
    stored = {}
    with sqlite3.connect(scan_db) as conn:
        conn.execute(SCHEMA)
        for symbol, token in index_tokens(rows).items():
            last = conn.execute(
                "SELECT MAX(date) FROM index_daily WHERE symbol=?", (symbol,)
            ).fetchone()[0]
            start = (
                dt.date.fromisoformat(last) + dt.timedelta(days=1)
                if last
                else before - dt.timedelta(days=days)
            )
            if start >= before:
                stored[symbol] = 0
                continue
            values = []
            for candle in client.candles(token, "day", start, before):
                day = intraday.kite_time(candle[0]).date()
                if day < before:
                    values.append((symbol, str(day), *(float(value or 0) for value in candle[1:6])))
            conn.executemany("INSERT OR REPLACE INTO index_daily VALUES (?,?,?,?,?,?,?)", values)
            stored[symbol] = len(values)
    return stored


def _closes(conn: sqlite3.Connection, table: str, symbol: str) -> list[tuple[str, float]]:
    return conn.execute(
        f"SELECT date, close FROM {table} WHERE symbol=? ORDER BY date",  # noqa: S608 - fixed names.
        (symbol,),
    ).fetchall()


def _breadth(conn: sqlite3.Connection) -> dict[str, float]:
    """Per date: share (0-100) of stocks closing above their own 50-day average."""
    above: dict[str, list[int]] = {}
    symbols = [row[0] for row in conn.execute("SELECT DISTINCT symbol FROM daily")]
    for symbol in symbols:
        closes = _closes(conn, "daily", symbol)
        window: list[float] = []
        for day, close in closes:
            window.append(close)
            if len(window) > 50:
                window.pop(0)
            if len(window) == 50:
                above.setdefault(day, []).append(int(close > statistics.fmean(window)))
    return {
        day: round(100 * sum(flags) / len(flags), 1)
        for day, flags in above.items()
        if len(flags) >= 5
    }


def labels(scan_db: Path) -> dict[str, dict[str, Any]]:
    """Per completed session: trend, volatility, breadth and the ``trend/volatility`` label."""
    if not scan_db.is_file():
        return {}
    with sqlite3.connect(scan_db) as conn:
        conn.execute(SCHEMA)
        has_daily = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily'"
        ).fetchone()
        nifty = _closes(conn, "index_daily", NIFTY)
        vix = dict(_closes(conn, "index_daily", VIX))
        breadth = _breadth(conn) if has_daily else {}
    result: dict[str, dict[str, Any]] = {}
    closes = [close for _, close in nifty]
    for index, (day, close) in enumerate(nifty):
        if index < 54 or day not in vix:
            continue
        average = statistics.fmean(closes[index - 49 : index + 1])
        earlier = statistics.fmean(closes[index - 54 : index - 4])
        if close > average and average > earlier:
            trend = "up"
        elif close < average and average < earlier:
            trend = "down"
        else:
            trend = "sideways"
        level = vix[day]
        volatility = "calm" if level < 13 else "normal" if level <= 20 else "high"
        result[day] = {"trend": trend, "volatility": volatility, "vix": round(level, 2),
                       "nifty_vs_50d_pct": round(100 * (close / average - 1), 2),
                       "breadth_pct": breadth.get(day), "label": f"{trend}/{volatility}"}  # fmt: skip
    return result


def label_before(known: dict[str, dict], day: str) -> dict[str, Any] | None:
    """The label of the last completed session before ``day``."""
    earlier = [key for key in known if key < day]
    return known[max(earlier)] if earlier else None


def by_regime(trades: list[dict], known: dict[str, dict]) -> dict[str, dict[str, Any]]:
    """Trades, expectancy and win rate per label; trades on unlabelled days are left out."""
    groups: dict[str, list[float]] = {}
    for trade in trades:
        label = label_before(known, trade["date"])
        if label:
            groups.setdefault(label["label"], []).append(float(trade["net_inr"]))
    return {
        label: {
            "trades": len(values),
            "expectancy_inr": round(statistics.fmean(values), 2),
            "win_rate_pct": round(100 * sum(value > 0 for value in values) / len(values), 1),
        }
        for label, values in sorted(groups.items())
    }


def veto(row: dict, label: str | None, min_trades: int) -> str:
    """Why a strategy sits out in today's regime, or ""."""
    if not label:
        return ""
    past = (row.get("by_regime") or {}).get(label)
    if past and past["trades"] >= min_trades and past["expectancy_inr"] <= 0:
        return (f"lost on average in {label} markets ({past['trades']} trades, "
                f"₹{past['expectancy_inr']:,.2f} a trade at double costs)")  # fmt: skip
    return ""


def settings(config: dict) -> dict[str, Any]:
    return {**DEFAULTS, **(config.get("regime") or {})}


def filter_allowed(
    root: Path, card: dict, names: list[str], session_date: str, config: dict | None = None
) -> tuple[list[str], list[str]]:
    """Remove the strategies today's regime argues against. Returns (kept, notes)."""
    if config is None:
        try:
            config = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            config = {}
    cfg = settings(config)
    if not cfg["enabled"]:
        return names, []
    today = label_before(labels(root / "scan.sqlite"), session_date)
    if today is None:
        return names, ["regime unknown (no Nifty and VIX history yet)"]
    kept, notes = [], [f"market regime {today['label']}"]
    for name in names:
        reason = veto(
            card.get("strategies", {}).get(name, {}), today["label"], int(cfg["min_trades"])
        )
        if reason:
            notes.append(f"{name} sits out: {reason}")
        else:
            kept.append(name)
    return kept, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("command", choices=["today", "history"])
    args = parser.parse_args(argv)
    known = labels(intraday.config_folder(args.config) / "scan.sqlite")
    if not known:
        print(
            "No regime yet: run market_scan.py nightly to store Nifty and VIX candles.",
            file=sys.stderr,
        )
        return 1
    if args.command == "today":
        print(
            json.dumps(label_before(known, str(dt.date.today() + dt.timedelta(days=1))), indent=2)
        )
    else:
        print(json.dumps(dict(list(known.items())[-30:]), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

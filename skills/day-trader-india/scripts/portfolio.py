#!/usr/bin/env python3
"""Portfolio caps across both paper books: one view of all the risk the desk carries.

Each book checks its own trade. These caps check the trade against everything already
open in the intraday book *and* the swing book together:

| Cap | Default | Rule |
| --- | --- | --- |
| Heat | 5% | Total open risk after this entry, as % of both books' starting capital. Risk is (entry - stop) x qty; an overnight swing position counts at least one daily ATR(14) a share, because a gap can open through the stop |
| Sector | 2 | Open positions in the same NSE sector (from the reference store) |
| Correlation | 0.7 | Correlation of daily returns over 60 sessions with any held stock |
| Quarter-Kelly | 0.25 | With at least 100 tournament trades: the trade's risk may not exceed a quarter of the Kelly fraction (p x (1 - 1/profit factor) at doubled costs) of the book's capital. A strategy whose Kelly fraction is not positive is refused |

Unknown data (no sector, too few candles) is noted, not blocked: the per-book rules
still apply. Every cap can only refuse an entry.

    python3 portfolio.py --kind swing check INFY --entry 1500 --stop 1460 --qty 20
    python3 portfolio.py view
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
DEFAULTS = {
    "enabled": True, "max_heat_pct": 5.0, "max_per_sector": 2, "max_correlation": 0.7,
    "correlation_days": 60, "kelly_fraction": 0.25, "kelly_min_trades": 100,
}  # fmt: skip
SCORECARDS = {"intraday": "strategy-scorecard.json", "swing": "swing-scorecard.json"}


def settings(config: dict) -> dict[str, Any]:
    return {**DEFAULTS, **(config.get("portfolio") or {})}


def _closes(scan_db: Path, symbol: str, days: int) -> list[float]:
    try:
        with sqlite3.connect(scan_db) as conn:
            rows = conn.execute(
                "SELECT close FROM daily WHERE symbol=? ORDER BY date DESC LIMIT ?",
                (symbol, days + 1),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [row[0] for row in reversed(rows)]


def atr(scan_db: Path, symbol: str, period: int = 14) -> float | None:
    """Average true range of the last ``period`` stored daily candles."""
    try:
        with sqlite3.connect(scan_db) as conn:
            rows = conn.execute(
                "SELECT high, low, close FROM daily WHERE symbol=? ORDER BY date DESC LIMIT ?",
                (symbol, period + 1),
            ).fetchall()[::-1]
    except sqlite3.Error:
        return None
    if len(rows) <= period:
        return None
    ranges = [
        max(high - low, abs(high - rows[index][2]), abs(low - rows[index][2]))
        for index, (high, low, _) in enumerate(rows[1:])
    ]
    return statistics.fmean(ranges)


def correlation(first: list[float], second: list[float]) -> float | None:
    count = min(len(first), len(second))
    if count < 21:
        return None
    a = [first[-count:][i + 1] / first[-count:][i] - 1 for i in range(count - 1)]
    b = [second[-count:][i + 1] / second[-count:][i] - 1 for i in range(count - 1)]
    try:
        return statistics.correlation(a, b)
    except statistics.StatisticsError:
        return None


def sector_of(folder: Path, symbol: str) -> str | None:
    try:
        with sqlite3.connect(folder / "reference.sqlite") as conn:
            row = conn.execute("SELECT sector FROM reference WHERE symbol=?", (symbol,)).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row and row[0] else None


def open_positions(config_path: Path) -> tuple[list[dict], float, list[str]]:
    """Open positions of both books, their combined starting capital, and notes."""
    import safety

    folder = intraday.config_folder(config_path)
    positions, capital, notes = [], 0.0, []
    for kind, path in safety.book_paths(config_path).items():
        try:
            book = safety._read(path)
        except (ValueError, OSError, sqlite3.Error):
            notes.append(f"the {kind} book could not be read")
            continue
        if not book:
            continue
        capital += float(book.get("initial_cash") or book.get("cash") or 0)
        for symbol, held in book.get("positions", {}).items():
            entry, stop, qty = float(held["entry_inr"]), float(held["stop_inr"]), int(held["qty"])
            risk = max(entry - stop, 0) * qty
            if kind == "swing":
                daily = atr(folder / "scan.sqlite", symbol)
                if daily:
                    risk = max(risk, daily * qty)  # A gap can open through the stop.
            positions.append({"book": kind, "symbol": symbol, "qty": qty, "entry": entry,
                              "stop": stop, "risk_inr": round(risk, 2)})  # fmt: skip
    return positions, capital, notes


def kelly_ceiling(
    config_path: Path, kind: str, strategy: str | None, capital: float, cfg: dict
) -> tuple[float | None, str]:
    """(largest risk in rupees, note). None means no ceiling (too few trades)."""
    if not strategy:
        return None, "no strategy named; Kelly not applied"
    folder = intraday.config_folder(config_path)
    try:
        card = json.loads((folder / SCORECARDS[kind]).read_text(encoding="utf-8"))
        row = card["strategies"][strategy]["doubled_costs"]
    except (OSError, ValueError, KeyError, TypeError):
        return None, f"no {kind} scorecard row for {strategy}; Kelly not applied"
    trades = int(row.get("trades") or 0)
    if trades < int(cfg["kelly_min_trades"]):
        return None, f"{trades} tournament trades; Kelly needs {cfg['kelly_min_trades']}"
    win = (row.get("win_rate_pct") or 0) / 100
    factor = row.get("profit_factor")
    if not factor or factor <= 0:
        return 0.0, "profit factor unknown or zero"
    kelly = win * (1 - 1 / factor)
    if kelly <= 0:
        return 0.0, f"Kelly fraction {kelly:.3f} is not positive"
    return capital * kelly * float(cfg["kelly_fraction"]), f"Kelly fraction {kelly:.3f}"


def gate(
    config_path: Path, kind: str, symbol: str, entry: float, stop: float, qty: int,
    strategy: str | None = None,
) -> tuple[str, list[str]]:  # fmt: skip
    """(why the entry is refused or "", notes) for a new entry into the ``kind`` book."""
    config = intraday.load_config(config_path)
    cfg = settings(config)
    if not cfg["enabled"]:
        return "", []
    folder = intraday.config_folder(config_path)
    positions, capital, notes = open_positions(config_path)
    if capital <= 0:
        return "", notes + ["no starting capital found; portfolio caps not applied"]
    risk = max(entry - stop, 0) * qty
    if kind == "swing":
        daily = atr(folder / "scan.sqlite", symbol)
        if daily:
            risk = max(risk, daily * qty)
    heat = 100 * (sum(item["risk_inr"] for item in positions) + risk) / capital
    if heat > float(cfg["max_heat_pct"]):
        return (f"total open risk would be {heat:.1f}% of both books' capital; the cap is "
                f"{float(cfg['max_heat_pct']):g}%"), notes  # fmt: skip
    notes.append(f"heat after entry {heat:.1f}% of ₹{capital:,.0f}")
    sector = sector_of(folder, symbol)
    if sector:
        same = [
            item["symbol"]
            for item in positions
            if item["symbol"] != symbol and sector_of(folder, item["symbol"]) == sector
        ]
        if len(same) >= int(cfg["max_per_sector"]):
            return f"already {len(same)} open in {sector} ({', '.join(same)})", notes
    else:
        notes.append("sector unknown; sector cap not applied")
    mine = _closes(folder / "scan.sqlite", symbol, int(cfg["correlation_days"]))
    for item in positions:
        if item["symbol"] == symbol:
            continue
        value = correlation(
            mine, _closes(folder / "scan.sqlite", item["symbol"], int(cfg["correlation_days"]))
        )
        if value is not None and value > float(cfg["max_correlation"]):
            return (f"moves with {item['symbol']} (correlation {value:.2f} over "
                    f"{cfg['correlation_days']} sessions; cap {float(cfg['max_correlation']):g})"), notes  # fmt: skip
    book_capital = capital
    try:
        import safety

        book = safety._read(safety.book_paths(config_path)[kind]) or {}
        book_capital = float(book.get("initial_cash") or capital)
    except (ValueError, OSError, sqlite3.Error, KeyError):
        pass
    ceiling, note = kelly_ceiling(config_path, kind, strategy, book_capital, cfg)
    notes.append(note)
    if ceiling is not None and risk > ceiling:
        if ceiling == 0:
            return f"{strategy}: {note}; no edge to size", notes
        return f"risk ₹{risk:,.0f} exceeds the quarter-Kelly ceiling ₹{ceiling:,.0f}", notes
    return "", notes


def view(config_path: Path) -> dict[str, Any]:
    """Open risk across both books, for the dashboard and the CLI."""
    cfg = settings(intraday.load_config(config_path))
    positions, capital, notes = open_positions(config_path)
    folder = intraday.config_folder(config_path)
    sectors: dict[str, int] = {}
    for item in positions:
        item["sector"] = sector_of(folder, item["symbol"])
        sectors[item["sector"] or "unknown"] = sectors.get(item["sector"] or "unknown", 0) + 1
    total = sum(item["risk_inr"] for item in positions)
    return {
        "capital_inr": round(capital, 2), "open_risk_inr": round(total, 2),
        "heat_pct": round(100 * total / capital, 2) if capital else None,
        "max_heat_pct": cfg["max_heat_pct"], "by_sector": sectors, "positions": positions,
        "notes": notes,
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--kind", choices=["intraday", "swing"], default="intraday")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("view")
    checking = sub.add_parser("check")
    checking.add_argument("symbol")
    checking.add_argument("--entry", type=float, required=True)
    checking.add_argument("--stop", type=float, required=True)
    checking.add_argument("--qty", type=int, required=True)
    checking.add_argument("--strategy")
    args = parser.parse_args(argv)
    try:
        if args.command == "view":
            print(json.dumps(view(args.config), indent=2))
            return 0
        reason, notes = gate(args.config, args.kind, intraday.normalise_symbol(args.symbol),
                             args.entry, args.stop, args.qty, args.strategy)  # fmt: skip
    except (ValueError, OSError, KeyError) as exc:
        print(f"Portfolio check refused: {exc}", file=sys.stderr)
        return 2
    print(reason or "clear", *notes, sep="\n")
    return 1 if reason else 0


if __name__ == "__main__":
    sys.exit(main())

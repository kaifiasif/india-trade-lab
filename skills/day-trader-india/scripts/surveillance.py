#!/usr/bin/env python3
"""Surveillance and F&O-ban gate: keep the desk away from stocks the exchange is watching.

Reads two NSE files once a day:

- the **regulatory indicator file** ``REG_IND{DDMMYY}.csv`` (nsearchives, content/cm):
  one row per stock with its GSM, ASM, ESM, insolvency, default, pledge and other flags,
  coded per NSE's published file structure (100 means "not under this measure");
- the **F&O ban list** ``fo_secban_{DDMMYYYY}.csv``: stocks whose open interest crossed
  95% of the market-wide position limit. They are not in the indicator file.

| Outcome | Flags |
| --- | --- |
| Blocked: no new entry | GSM (any stage), long-term ASM, ESM, suspended or inactive, insolvency (IBC stage I/II), BZ/SZ series |
| Caution: shown to the agents and on the dashboard | short-term ASM, add-on price band, high promoter pledge, F&O ban period, leaving F&O |

In a watched stock, paper fills are fiction: trade-for-trade settlement, narrow bands and
higher margins. If neither file can be read for the last session, ``unknown_blocks``
(on by default) stops new entries until it can. NSE may refuse scripted requests; the
tool fetches each file once and caches it.

    python3 surveillance.py fetch
    python3 surveillance.py check INFY
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
REG_IND = "https://nsearchives.nseindia.com/content/cm/REG_IND{date:%d%m%y}.csv"
BAN = "https://nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_{date:%d%m%Y}.csv"
DEFAULTS = {"enabled": True, "unknown_blocks": True}
NOT_UNDER = "100"


def _norm(key: str) -> str:
    return "".join(char for char in key.lower() if char.isalnum())


def _column(row: dict[str, str], *names: str) -> str:
    wanted = {_norm(name) for name in names}
    for key, value in row.items():
        if _norm(key or "") in wanted:
            return (value or "").strip()
    return ""


def classify(row: dict[str, str]) -> tuple[list[str], list[str]]:
    """(blocking reasons, caution reasons) for one indicator-file row."""
    block, caution = [], []
    gsm = _column(row, "GSM")
    if gsm and gsm != NOT_UNDER:
        block.append("GSM" + (f" stage {gsm}" if gsm not in ("0",) else ""))
    long_asm = _column(row, "Long_Term_Additional_Surveillance_Measure (Long Term ASM)",
                       "Long_Term_Additional_Surveillance_Measure", "Long Term ASM")  # fmt: skip
    if long_asm and long_asm != NOT_UNDER:
        block.append(f"long-term ASM stage {long_asm}")
    esm = _column(row, "ESM")
    if esm and esm != NOT_UNDER:
        block.append(f"ESM stage {esm}")
    status = _column(row, "Status")
    if status and status.upper() != "A":
        block.append({"S": "suspended", "I": "inactive"}.get(status.upper(), f"status {status}"))
    irp = _column(
        row, "Insolvency_Resolution_Process (IRP)", "Insolvency_Resolution_Process", "IRP"
    )
    if irp in ("1", "2"):
        block.append(f"insolvency (IBC stage {irp})")
    bz = _column(row, "Under BZ/SZ Series", "Under BZ SZ Series")
    if bz == "0":
        block.append("moved to BZ/SZ series")
    short_asm = _column(row, "Short_Term_Additional_Surveillance_Measure (Short Term ASM)",
                        "Short_Term_Additional_Surveillance_Measure", "Short Term ASM")  # fmt: skip
    if short_asm and short_asm != NOT_UNDER:
        caution.append(f"short-term ASM stage {short_asm}")
    if _column(row, "Add-on_PB", "Add-on PB") == "1":
        caution.append("add-on price band")
    if _column(row, "Pledge") == "1" or _column(row, "Total Pledge") == "1":
        caution.append("high pledge surveillance")
    if _column(row, "Derivative contracts moved out of F&O") == "0":
        caution.append("leaving F&O")
    return block, caution


def parse_indicator(raw: bytes) -> dict[str, dict[str, list[str]]]:
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace")))
    result = {}
    for row in rows:
        symbol = _column(row, "Symbol").upper()
        if not symbol:
            continue
        block, caution = classify(row)
        if block or caution:
            result[f"NSE:{symbol}"] = {"block": block, "caution": caution}
    if not rows.fieldnames or "symbol" not in {_norm(name) for name in rows.fieldnames}:
        raise ValueError("That is not NSE's regulatory indicator file")
    return result


def parse_ban(raw: bytes) -> list[str]:
    symbols = []
    for line in raw.decode("utf-8-sig", errors="replace").splitlines()[1:]:
        cells = [cell.strip() for cell in line.split(",")]
        name = cells[-1] if cells else ""
        if name and name.replace("&", "").replace("-", "").isalnum():
            symbols.append(f"NSE:{name.upper()}")
    return symbols


def fetch(config_path: Path, clock: dt.datetime, get: Callable[[str], bytes] | None = None) -> dict:
    """Read both files for the most recent session they exist for; save surveillance.json."""
    import market_scan

    get = get or market_scan.nse_fetch
    manifest = intraday.sessions_manifest(config_path)
    days = sorted(
        (d for d, s in manifest["sessions"].items() if s and d <= str(clock.date())), reverse=True
    )[:4]
    report: dict[str, Any] = {
        "checked_at": clock.isoformat(),
        "stocks": {},
        "sources": {},
        "notes": [],
    }
    for day in days:
        try:
            report["stocks"] = parse_indicator(get(REG_IND.format(date=dt.date.fromisoformat(day))))
            report["sources"]["indicator"] = day
            break
        except (ValueError, OSError) as exc:
            report["notes"].append(f"indicator file for {day}: {str(exc)[:80]}")
    ban_days = [str(clock.date())] + days
    for day in ban_days:
        try:
            banned = parse_ban(get(BAN.format(date=dt.date.fromisoformat(day))))
        except (ValueError, OSError) as exc:
            report["notes"].append(f"ban list for {day}: {str(exc)[:80]}")
            continue
        report["sources"]["ban"] = day
        for symbol in banned:
            entry = report["stocks"].setdefault(symbol, {"block": [], "caution": []})
            entry["caution"].append("F&O ban period (open interest above 95% of the limit)")
        break
    intraday.write_json(intraday.config_folder(config_path) / "surveillance.json", report)
    return report


def gate(config_path: Path, symbol: str, clock: dt.datetime) -> tuple[str, list[str]]:
    """(why an entry is blocked or "", caution notes) for one stock."""
    config = intraday.load_config(config_path)
    cfg = {**DEFAULTS, **(config.get("surveillance") or {})}
    if not cfg["enabled"]:
        return "", []
    path = intraday.config_folder(config_path) / "surveillance.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        checked = dt.datetime.fromisoformat(report["checked_at"])
    except (OSError, ValueError, KeyError):
        return (
            "surveillance lists (ASM/GSM/ESM, F&O ban) have not been read"
            if cfg["unknown_blocks"]
            else ""
        ), []
    stale = (clock - checked).total_seconds() > 36 * 3600
    if (stale or "indicator" not in report.get("sources", {})) and cfg["unknown_blocks"]:
        return "surveillance lists are missing or more than a day old", []
    found = report.get("stocks", {}).get(symbol) or {}
    if found.get("block"):
        return "under exchange surveillance: " + ", ".join(found["block"]), found.get("caution", [])
    return "", found.get("caution", [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" IST')
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch")
    checking = sub.add_parser("check")
    checking.add_argument("symbol")
    args = parser.parse_args(argv)
    clock = intraday.now_ist(args.now)
    try:
        if args.command == "fetch":
            report = fetch(args.config, clock)
            blocked = sum(bool(item["block"]) for item in report["stocks"].values())
            print(json.dumps({"sources": report["sources"], "blocked": blocked,
                              "caution": len(report["stocks"]) - blocked, "notes": report["notes"]}, indent=2))  # fmt: skip
            return 0 if "indicator" in report["sources"] else 1
        reason, caution = gate(args.config, intraday.normalise_symbol(args.symbol), clock)
        print(reason or "clear", *(f"caution: {note}" for note in caution), sep="\n")
        return 1 if reason else 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"Surveillance check refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

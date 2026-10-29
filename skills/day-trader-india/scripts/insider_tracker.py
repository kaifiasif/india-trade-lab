#!/usr/bin/env python3
"""Insider Tracker: who inside a listed company bought or sold its shares, from SEBI filings.

India's answer to a Congress-trades tracker. Under SEBI's Prohibition of Insider
Trading Regulations (Regulation 7(2)), promoters, directors, key managerial
people and designated employees must tell the company within two trading days
of trading more than ₹10 lakh in a quarter, and the company must tell the
exchange within two more. NSE publishes those disclosures; this tool reads them.

It is fast, not early: a filing describes a trade already done, days ago. There
is no inside information here, only public filings read quickly.

Each row keeps: the company, the person and their category (promoter, promoter
group, director, KMP, designated employee, immediate relative), buy or sell or
pledge, how (market purchase, market sale, off-market, ESOP...), shares and
value, the trade dates, the disclosure date and how many days it took.

The overnight market scan reads the last 30 days: net market buying by
promoters, directors and KMPs is a small plus, net selling or new pledges a
small minus. Nothing here is a recommendation; ESOP and off-market moves are
listed but not scored.

    python3 insider_tracker.py recent --days 7
    python3 insider_tracker.py recent --symbol TATAMOTORS --days 90
    python3 insider_tracker.py new           # only filings not shown before; exit 1 when none
    python3 insider_tracker.py recent --file saved-pit.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
NSE_PIT = "https://www.nseindia.com/api/corporates-pit"
INSIDER_CATEGORIES = ("promoter", "director", "key managerial", "kmp")
MAX_ROWS = 20_000


def _date(value: Any) -> dt.date | None:
    text = str(value or "").strip()
    for pattern in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d-%b-%Y %H:%M", "%d-%b-%Y %H:%M:%S"):
        try:
            return dt.datetime.strptime(text.title() if "%b" in pattern else text, pattern).date()
        except ValueError:
            continue
    return None


def _number(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def classify(transaction: str, mode: str) -> str:
    text = f"{transaction} {mode}".lower()
    if "pledge" in text or "invocation" in text or "revok" in text:
        return "pledge"
    if "esop" in text or "off market" in text or "inter-se" in text or "gift" in text:
        return "other"
    if "buy" in transaction.lower() or "acqui" in text or "purchase" in text:
        return "market buy" if "market" in text else "buy"
    if "sell" in transaction.lower() or "sale" in text or "dispos" in text:
        return "market sell" if "market" in text else "sell"
    return "other"


def parse(payload: Any) -> list[dict[str, Any]]:
    """NSE's PIT JSON as clean rows. Rows without a symbol or a transaction are dropped."""
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("Expected NSE insider-trading JSON with a data list")
    clean = []
    for raw in rows[:MAX_ROWS]:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get("symbol") or "").strip().upper()
        transaction = str(raw.get("tdpTransactionType") or raw.get("acqType") or "").strip()
        if not symbol or not transaction:
            continue
        mode = str(raw.get("acqMode") or "").strip()
        traded_to = _date(raw.get("acqtoDt")) or _date(raw.get("acqfromDt"))
        disclosed = _date(raw.get("date")) or _date(raw.get("intimDt"))
        row = {
            "symbol": f"NSE:{symbol}",
            "company": str(raw.get("company") or "")[:120],
            "person": str(raw.get("acqName") or "")[:120],
            "category": str(raw.get("personCategory") or "")[:60],
            "transaction": transaction[:40],
            "mode": mode[:60],
            "kind": classify(transaction, mode),
            "shares": _number(raw.get("secAcq")),
            "value_inr": _number(raw.get("secVal")),
            "holding_after_pct": _number(raw.get("afterAcqSharesPer")),
            "traded_from": str(_date(raw.get("acqfromDt")) or ""),
            "traded_to": str(traded_to or ""),
            "disclosed": str(disclosed or ""),
            "days_to_disclose": (disclosed - traded_to).days if disclosed and traded_to else None,
        }
        row["id"] = hashlib.sha256(
            json.dumps(
                [
                    row[key]
                    for key in (
                        "symbol",
                        "person",
                        "transaction",
                        "shares",
                        "traded_to",
                        "disclosed",
                    )
                ]
            ).encode()  # fmt: skip
        ).hexdigest()[:16]
        clean.append(row)
    return clean


def fetch(start: dt.date, end: dt.date, symbol: str | None, get: Callable[[str], bytes]) -> list:
    query = {"index": "equities", "from_date": f"{start:%d-%m-%Y}", "to_date": f"{end:%d-%m-%Y}"}
    if symbol:
        query["symbol"] = symbol.split(":")[-1]
    return parse(json.loads(get(f"{NSE_PIT}?{urllib.parse.urlencode(query)}")))


def is_insider(row: dict) -> bool:
    return any(word in row["category"].lower() for word in INSIDER_CATEGORIES)


def summary(rows: list[dict]) -> dict[str, dict[str, Any]]:
    """Per symbol: net market value bought by promoters, directors and KMPs, and pledges."""
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = result.setdefault(
            row["symbol"],
            {"net_market_inr": 0.0, "buys": 0, "sells": 0, "pledges": 0, "latest": ""},
        )
        if row["kind"] == "pledge":
            if "creat" in row["transaction"].lower() or "invoc" in row["transaction"].lower():
                item["pledges"] += 1
        elif is_insider(row) and row["kind"] in ("market buy", "market sell"):
            sign = 1 if row["kind"] == "market buy" else -1
            item["net_market_inr"] += sign * (row["value_inr"] or 0)
            item["buys" if sign > 0 else "sells"] += 1
        item["latest"] = max(item["latest"], row["disclosed"])
    for item in result.values():
        item["net_market_inr"] = round(item["net_market_inr"])
    return result


def score(item: dict | None) -> tuple[float, str] | None:
    """Scan points for one symbol's last-30-day summary, or None when nothing counts."""
    if not item:
        return None
    if item["pledges"]:
        return -0.5, f"{item['pledges']} new promoter pledge(s) disclosed"
    net = item["net_market_inr"]
    if item["buys"] and net > 0:
        return (
            1.0,
            f"insiders net bought ₹{net / 1e7:.2f} crore in the market ({item['buys']} filings)",
        )
    if item["sells"] and net < 0:
        return (
            -0.5,
            f"insiders net sold ₹{-net / 1e7:.2f} crore in the market ({item['sells']} filings)",
        )
    return None


def describe(row: dict) -> str:
    value = f"₹{row['value_inr'] / 1e5:,.1f} lakh" if row["value_inr"] else "value not given"
    shares = f"{row['shares']:,.0f} shares" if row["shares"] else "shares not given"
    lag = (
        f", disclosed {row['days_to_disclose']} days later"
        if row["days_to_disclose"] is not None
        else ""
    )
    return (
        f"{row['symbol']}: {row['person']} ({row['category'] or 'category not given'}) "
        f"{row['kind']} via {row['mode'] or row['transaction']}, {shares}, {value}, "
        f"traded {row['traded_from']} to {row['traded_to']}{lag}"
    )


def main(argv: list[str] | None = None) -> int:
    import market_scan

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("recent", "new"):
        command = sub.add_parser(name)
        command.add_argument("--days", type=int, default=7)
        command.add_argument("--symbol")
        command.add_argument("--file", type=Path, help="a saved NSE PIT JSON instead of NSE")
        command.add_argument("--insiders-only", action="store_true")
        command.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.days <= 365:
            raise ValueError("--days must be 1-365")
        end = intraday.now_ist().date()
        if args.file:
            rows = parse(json.loads(args.file.read_text(encoding="utf-8")))
        else:
            symbol = intraday.normalise_symbol(args.symbol) if args.symbol else None
            rows = fetch(end - dt.timedelta(days=args.days), end, symbol, market_scan.nse_fetch)
        if args.insiders_only:
            rows = [row for row in rows if is_insider(row)]
        if args.command == "new":
            seen_path = intraday.desk_dir(args.config) / "insiders-seen.json"
            seen = (
                set(intraday.read_json(seen_path).get("ids", [])) if seen_path.is_file() else set()
            )
            fresh = [row for row in rows if row["id"] not in seen]
            intraday.write_json(
                seen_path, {"ids": sorted(seen | {row["id"] for row in rows})[-50_000:]}
            )
            rows = fresh
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Insider tracker refused: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"rows": rows, "summary": summary(rows)}, indent=2))
    else:
        for row in rows[:200]:
            print(describe(row))
        print(f"{len(rows)} filing(s). Public disclosures of trades already made; not advice.")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())

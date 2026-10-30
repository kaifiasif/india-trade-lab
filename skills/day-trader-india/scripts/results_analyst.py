#!/usr/bin/env python3
"""Earnings Analyst: reads a company's filed quarterly results from NSE and says what changed.

Indian listed companies file each quarter's results with the exchange under SEBI's
LODR Regulation 33, with a machine-readable XBRL copy. This tool lists the
company's filings on NSE, takes the newest quarterly XBRL (consolidated when filed,
otherwise standalone) and reads the numbers the company tagged:

- revenue from operations (interest earned for banks) and total income;
- profit before tax, tax and net profit (and the part owed to the parent's owners);
- basic and diluted EPS;
- finance costs, depreciation, other income and exceptional items.

Each figure is shown for the quarter, the quarter before and the same quarter a
year earlier, as filed in that one XBRL. Margins are computed here and marked as
derived: profit-before-tax margin, net margin and an EBITDA estimate (profit
before tax + finance costs + depreciation - other income). It flags exceptional
items and other income above a quarter of profit before tax, because those flatter
or hide the business's own earnings.

Filed numbers only: it never calls a stock cheap, dear, a buy or a sell. If NSE
refuses the request, it says so and does not evade the refusal.

    python3 results_analyst.py LT
    python3 results_analyst.py LT --json --write       # desk/results-LT.json
    python3 results_analyst.py LT --xbrl saved.xml     # read a saved XBRL file
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
NSE_RESULTS = "https://www.nseindia.com/api/corporates-financial-results"
MAX_XBRL_BYTES = 8_000_000
CRORE = 1e7
TAGS = {
    "revenue": ("RevenueFromOperations", "InterestEarned", "Revenue"),
    "total_income": ("Income", "TotalIncome"),
    "expenses": ("Expenses",),
    "finance_costs": ("FinanceCosts", "InterestExpended"),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",),
    "other_income": ("OtherIncome",),
    "exceptional": ("ExceptionalItemsBeforeTax",),
    "profit_before_tax": ("ProfitBeforeTax", "ProfitLossBeforeTax"),
    "tax": ("TaxExpense",),
    "net_profit": ("ProfitLossForPeriod", "ProfitLossForThePeriod"),
    "owners_profit": ("ProfitOrLossAttributableToOwnersOfParent",),
    "eps_basic": (
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsLossPerShareFromContinuingOperations",
    ),
    "eps_diluted": (
        "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "DilutedEarningsLossPerShareFromContinuingOperations",
    ),
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_xbrl(raw: bytes) -> dict[str, dict[str, float]]:
    """{"YYYY-MM-DD/YYYY-MM-DD": {field: value}} for whole-company (no dimension) periods."""
    if len(raw) > MAX_XBRL_BYTES:
        raise ValueError("XBRL file exceeds its size limit")
    if b"<!DOCTYPE" in raw[:4096].upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("XBRL with a DOCTYPE or entities is refused")
    root = ET.fromstring(raw)
    periods: dict[str, str] = {}
    for context in root.iter():
        if _local(context.tag) != "context":
            continue
        if any(_local(child.tag) in ("segment", "scenario") for child in context.iter()):
            continue  # Segment or dimensional figures are not the whole company.
        dates = {_local(child.tag): (child.text or "").strip() for child in context.iter()}
        if dates.get("startDate") and dates.get("endDate"):
            periods[context.get("id", "")] = f"{dates['startDate']}/{dates['endDate']}"
    names = {tag: field for field, tags in TAGS.items() for tag in tags}
    facts: dict[str, dict[str, float]] = {}
    for element in root.iter():
        field = names.get(_local(element.tag))
        period = periods.get(element.get("contextRef", ""))
        if not field or not period or element.text is None:
            continue
        try:
            value = float(element.text.strip())
        except ValueError:
            continue
        facts.setdefault(period, {}).setdefault(field, value)
    return facts


def quarters(facts: dict[str, dict[str, float]]) -> list[tuple[str, dict[str, float]]]:
    """Three-month periods, newest first."""
    rows = []
    for period, values in facts.items():
        start, end = (dt.date.fromisoformat(part) for part in period.split("/"))
        if 80 <= (end - start).days <= 100:
            rows.append((str(end), values))
    return sorted(rows, reverse=True)


def _change(now: float | None, before: float | None) -> float | None:
    if now is None or before in (None, 0):
        return None
    return round(100 * (now / before - 1) if before > 0 else 100 * (now - before) / abs(before), 1)


def analyse(facts: dict[str, dict[str, float]]) -> dict[str, Any]:
    """The latest quarter against the one before and the same quarter a year earlier."""
    rows = quarters(facts)
    if not rows:
        raise ValueError("No quarterly figures in this filing")
    latest_end, latest = rows[0]
    end = dt.date.fromisoformat(latest_end)

    def near(days: int) -> dict[str, float] | None:
        for other_end, values in rows[1:]:
            if abs((end - dt.date.fromisoformat(other_end)).days - days) <= 10:
                return values
        return None

    previous, year_ago = near(91), near(365)

    def money(values: dict | None, key: str) -> float | None:
        if not values or values.get(key) is None:
            return None
        return round(values[key] / CRORE, 2)

    figures = {}
    for key in TAGS:
        is_eps = key.startswith("eps")
        now = latest.get(key) if is_eps else money(latest, key)
        prev = (previous or {}).get(key) if is_eps else money(previous, key)
        last_year = (year_ago or {}).get(key) if is_eps else money(year_ago, key)
        figures[key] = {
            "value": now,
            "qoq_pct": _change(now, prev),
            "yoy_pct": _change(now, last_year),
            "year_ago": last_year,
        }
    revenue = latest.get("revenue") or latest.get("total_income")
    pbt, net = latest.get("profit_before_tax"), latest.get("net_profit")
    ebitda = None
    if pbt is not None:
        ebitda = pbt + latest.get("finance_costs", 0) + latest.get("depreciation", 0)
        ebitda -= latest.get("other_income", 0)
    margins = {
        "pbt_margin_pct": round(100 * pbt / revenue, 1) if revenue and pbt is not None else None,
        "net_margin_pct": round(100 * net / revenue, 1) if revenue and net is not None else None,
        "ebitda_margin_pct": round(100 * ebitda / revenue, 1)
        if revenue and ebitda is not None
        else None,
        "derived": True,
    }
    flags = []
    exceptional = latest.get("exceptional")
    if exceptional:
        flags.append(
            f"exceptional items of ₹{exceptional / CRORE:,.2f} crore are inside profit before tax"
        )
    other = latest.get("other_income")
    if other and pbt and pbt > 0 and other > 0.25 * pbt:
        flags.append(
            f"other income is {100 * other / pbt:.0f}% of profit before tax: much of the profit "
            "is not from operations"
        )
    if year_ago is None:
        flags.append("no year-ago quarter in this filing; growth is not shown")
    return {
        "quarter_end": latest_end,
        "unit": "₹ crore (EPS in ₹)",
        "figures": figures,
        "margins": margins,
        "flags": flags,
    }


def filings(symbol: str, get: Callable[[str], bytes]) -> list[dict[str, Any]]:
    """The company's quarterly filings on NSE, newest first, consolidated before standalone."""
    query = urllib.parse.urlencode(
        {"index": "equities", "symbol": symbol.split(":")[-1], "period": "Quarterly"}
    )
    payload = json.loads(get(f"{NSE_RESULTS}?{query}"))
    rows = payload if isinstance(payload, list) else payload.get("data", [])
    clean = []
    for row in rows if isinstance(rows, list) else []:
        url = str(row.get("xbrl") or "")
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname != "nsearchives.nseindia.com":
            continue
        try:
            ended = dt.datetime.strptime(str(row.get("toDate", "")).title(), "%d-%b-%Y").date()
        except ValueError:
            continue
        clean.append({
            "quarter_end": str(ended),
            "consolidated": "non" not in str(row.get("consolidated", "")).lower(),
            "audited": str(row.get("audited", "")),
            "filed": str(row.get("filingDate") or row.get("broadCastDate") or ""),
            "xbrl": url,
        })  # fmt: skip
    clean.sort(key=lambda item: (item["quarter_end"], item["consolidated"]), reverse=True)
    return clean


def latest(symbol: str, get: Callable[[str], bytes]) -> dict[str, Any]:
    found = filings(symbol, get)
    if not found:
        raise ValueError(f"No quarterly results with XBRL on NSE for {symbol}")
    chosen = found[0]
    result = analyse(read_xbrl(get(chosen["xbrl"])))
    return {"symbol": symbol, "source": chosen, **result}


def describe(result: dict) -> str:
    figures = result["figures"]

    def line(label: str, key: str, eps: bool = False) -> str:
        item = figures[key]
        if item["value"] is None:
            return f"  {label:<18} not filed"
        value = f"₹{item['value']:,.2f}" + ("" if eps else " cr")
        yoy = f"{item['yoy_pct']:+.1f}% YoY" if item["yoy_pct"] is not None else "YoY n/a"
        qoq = f"{item['qoq_pct']:+.1f}% QoQ" if item["qoq_pct"] is not None else "QoQ n/a"
        return f"  {label:<18} {value:>16}   {yoy}, {qoq}"

    source = result.get("source") or {}
    margins = result["margins"]
    lines = [
        f"{result.get('symbol', '')} quarter ended {result['quarter_end']}"
        + (
            f", {'consolidated' if source.get('consolidated') else 'standalone'}, "
            f"filed {source.get('filed', '?')}"
            if source
            else ""
        ),  # fmt: skip
        line("Revenue", "revenue"),
        line("Profit before tax", "profit_before_tax"),
        line("Net profit", "net_profit"),
        line("EPS (diluted)", "eps_diluted", eps=True),
        "  Margins (derived): "
        + ", ".join(
            f"{name} {value}%"
            for name, value in (
                ("PBT", margins["pbt_margin_pct"]),
                ("net", margins["net_margin_pct"]),
                ("EBITDA est.", margins["ebitda_margin_pct"]),
            )
            if value is not None
        ),
    ]
    lines += [f"  Note: {flag}" for flag in result["flags"]]
    if source.get("xbrl"):
        lines.append(f"  Filing: {source['xbrl']}")
    lines.append("Filed numbers only; not a view on the price.")
    return "\n".join(lines)


def brief(result: dict) -> dict[str, Any]:
    """The few numbers the agents read, for the scan's #results evidence item."""
    figures = result["figures"]
    return {
        "quarter_end": result["quarter_end"],
        "revenue_yoy_pct": figures["revenue"]["yoy_pct"],
        "net_profit_yoy_pct": figures["net_profit"]["yoy_pct"],
        "eps_diluted": figures["eps_diluted"]["value"],
        "net_margin_pct": result["margins"]["net_margin_pct"],
        "flags": result["flags"][:3],
        "filed": (result.get("source") or {}).get("filed"),
    }


def main(argv: list[str] | None = None) -> int:
    import market_scan

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("symbol")
    parser.add_argument("--xbrl", type=Path, help="read a saved XBRL file instead of NSE")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        symbol = intraday.normalise_symbol(args.symbol)
        if args.xbrl:
            result = {"symbol": symbol, **analyse(read_xbrl(args.xbrl.read_bytes()))}
        else:
            result = latest(symbol, market_scan.nse_fetch)
    except (ValueError, OSError, ET.ParseError, json.JSONDecodeError) as exc:
        print(f"Results analyst refused: {exc}", file=sys.stderr)
        return 2
    if args.write:
        plain = symbol.split(":")[-1]
        intraday.write_json(intraday.desk_dir(args.config) / f"results-{plain}.json", result)
    print(json.dumps(result, indent=2) if args.json else describe(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

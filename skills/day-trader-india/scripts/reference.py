#!/usr/bin/env python3
"""Reference data per symbol: sector, market-cap tier, F&O eligibility and lot size.

Built from NSE's own published files, cached locally with the date each one was
read. Nothing here is inferred: a symbol absent from a file is reported as unknown
rather than guessed, and the source of every field is recorded alongside it.

Market-cap tier uses NSE's own index membership (NIFTY 100 / MIDCAP 150 /
SMALLCAP 250) rather than a computed capitalisation. NSE classifies by full
market capitalisation when it builds those indices, so membership is a sourced
classification; a number scraped from an unofficial page would not be.

Sector index closes come from your own Kite login (daily candles for an index
instrument token, read from the environment) or from a CSV you downloaded. Only
completed sessions are stored, so a pre-market run never sees a partial day.

GET only, fixed hosts from the configured catalogue, no redirects, bounded bytes.
Nothing here places an order.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from broker_data import NoRedirect

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MAX_BYTES = 10_000_000
SYMBOL = re.compile(r"[A-Z0-9&.\-]{1,30}")

# NSE publishes each index's constituents as a CSV with Company Name, Industry,
# Symbol, Series and ISIN Code. Tier order matters: the first match wins, so a
# NIFTY 100 member is large even though it also appears in broader lists.
DEFAULT_CATALOGUE = {
    "tiers": [
        {
            "tier": "large",
            "index": "NIFTY 100",
            "url": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
        },
        {
            "tier": "mid",
            "index": "NIFTY MIDCAP 150",
            "url": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
        },
        {
            "tier": "small",
            "index": "NIFTY SMALLCAP 250",
            "url": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
        },
    ],
    "lot_sizes": "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv",
    "sector_indices": {
        "Information Technology": "NIFTY IT",
        "Financial Services": "NIFTY FINANCIAL SERVICES",
        "Bank": "NIFTY BANK",
        "Automobile and Auto Components": "NIFTY AUTO",
        "Fast Moving Consumer Goods": "NIFTY FMCG",
        "Healthcare": "NIFTY PHARMA",
        "Metals & Mining": "NIFTY METAL",
        "Oil Gas & Consumable Fuels": "NIFTY ENERGY",
        "Realty": "NIFTY REALTY",
    },
}
BROWSER_HEADERS = {
    # NSE refuses obvious automation. These are the headers a normal browser sends;
    # if the site still refuses, the collector reports it instead of evading further.
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Accept": "text/csv,application/csv,text/plain,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
}


def fetch(url: str, timeout: int = 30) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("reference sources must be https")
    request = urllib.request.Request(url, headers=BROWSER_HEADERS, method="GET")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
    except (OSError, urllib.error.URLError, ValueError):
        raise ValueError(f"source unavailable: {urllib.parse.urlsplit(url).netloc}") from None
    if len(raw) > MAX_BYTES:
        raise ValueError("source response exceeds its size limit")
    return raw


def _rows(raw: bytes) -> list[dict[str, str]]:
    text = raw.decode("utf-8-sig", errors="replace")
    rows = [
        {(key or "").strip(): (value or "").strip() for key, value in row.items()}
        for row in csv.DictReader(io.StringIO(text))
    ]
    if not rows:
        raise ValueError("source returned no rows")
    return rows


def parse_constituents(raw: bytes) -> dict[str, str]:
    """{symbol: industry} from an NSE index constituent CSV."""
    rows = _rows(raw)
    if "Symbol" not in rows[0]:
        raise ValueError("not an NSE index constituent file (no Symbol column)")
    result = {}
    for row in rows:
        symbol = row.get("Symbol", "").upper()
        if SYMBOL.fullmatch(symbol):
            result[symbol] = row.get("Industry", "")
    if not result:
        raise ValueError("constituent file contained no usable symbols")
    return result


def parse_lot_sizes(raw: bytes) -> dict[str, int]:
    """{symbol: lot size} from NSE's F&O market-lot file, taking the nearest expiry.

    The file is published with a leading underscore in its header names and one
    column per expiry month; the first numeric column is the nearest contract.
    """
    rows = _rows(raw)
    headers = list(rows[0])
    symbol_key = next((key for key in headers if key.upper().startswith("SYMBOL")), None)
    if symbol_key is None:
        raise ValueError("not an NSE market-lot file (no SYMBOL column)")
    months = [key for key in headers if key != symbol_key and key.upper() != "UNDERLYING"]
    result = {}
    for row in rows:
        symbol = row.get(symbol_key, "").upper()
        if not SYMBOL.fullmatch(symbol):
            continue
        for key in months:
            value = row.get(key, "").replace(",", "")
            if value.isdigit() and int(value) > 0:
                result[symbol] = int(value)
                break
    if not result:
        raise ValueError("market-lot file contained no usable lot sizes")
    return result


class ReferenceStore:
    """Cached reference facts with the date each source was read."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS reference (symbol TEXT PRIMARY KEY, sector TEXT, "
                "tier TEXT, tier_index TEXT, fno INTEGER, lot_size INTEGER, "
                "sector_index TEXT, refreshed_at TEXT NOT NULL, sources TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sector_closes (index_name TEXT, date TEXT, "
                "close REAL NOT NULL, source TEXT NOT NULL, PRIMARY KEY(index_name, date))"
            )

    def refresh(
        self, catalogue: dict | None = None, fetcher=fetch, now: dt.datetime | None = None
    ) -> dict:
        """Read every catalogue source; a source that fails leaves its fields untouched."""
        catalogue = catalogue or DEFAULT_CATALOGUE
        clock = (now or dt.datetime.now(IST)).astimezone(IST)
        notes: list[str] = []
        sectors: dict[str, str] = {}
        tiers: dict[str, tuple[str, str]] = {}
        for entry in catalogue["tiers"]:
            try:
                members = parse_constituents(fetcher(entry["url"]))
            except ValueError as exc:
                notes.append(f"{entry['index']}: {exc}")
                continue
            for symbol, industry in members.items():
                tiers.setdefault(symbol, (entry["tier"], entry["index"]))
                if industry and symbol not in sectors:
                    sectors[symbol] = industry
        lots: dict[str, int] = {}
        lots_read = False
        try:
            lots = parse_lot_sizes(fetcher(catalogue["lot_sizes"]))
            lots_read = True
        except ValueError as exc:
            notes.append(f"F&O lot sizes: {exc}; kept the previously cached values")
        if not tiers and not lots:
            raise ValueError("no reference source could be read; " + "; ".join(notes))
        sector_map = catalogue.get("sector_indices", {})
        written = 0
        with sqlite3.connect(self.path) as conn:
            for symbol in sorted(set(tiers) | set(lots) | set(sectors)):
                tier, tier_index = tiers.get(symbol, (None, None))
                sector = sectors.get(symbol)
                existing = conn.execute(
                    "SELECT sector, tier, tier_index, fno, lot_size FROM reference WHERE symbol=?",
                    (symbol,),
                ).fetchone()
                fno, lot = int(symbol in lots), lots.get(symbol)
                if existing:
                    sector = sector or existing[0]
                    tier = tier or existing[1]
                    tier_index = tier_index or existing[2]
                    if not lots_read:
                        # The lot file was unreadable: an outage is not a delisting.
                        fno, lot = existing[3], existing[4]
                conn.execute(
                    "INSERT OR REPLACE INTO reference VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        symbol,
                        sector,
                        tier,
                        tier_index,
                        fno,
                        lot,
                        sector_map.get(sector or ""),
                        clock.isoformat(),
                        json.dumps(
                            {
                                "tier": tier_index,
                                "lot_size": catalogue["lot_sizes"] if lot else None,
                            }
                        ),
                    ),
                )
                written += 1
        return {
            "as_of": clock.isoformat(),
            "symbols": written,
            "with_lot_size": len(lots),
            "notes": notes,
            "notice": "Sector and market-cap tier come from NSE index membership, not a "
            "computed capitalisation. A symbol missing from a file is unknown, not excluded.",
        }

    def lookup(self, symbol: str, as_of: dt.datetime | None = None) -> dict[str, Any]:
        """Reference facts for one exchange-qualified symbol; unknown fields stay None."""
        plain = symbol.split(":")[-1].upper()
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM reference WHERE symbol=?", (plain,)).fetchone()
        if row is None:
            return {
                "symbol": symbol,
                "known": False,
                "reason": "not present in any cached NSE reference file",
            }
        refreshed = dt.datetime.fromisoformat(row["refreshed_at"])
        age = ((as_of or dt.datetime.now(IST)) - refreshed).days
        return {
            "symbol": symbol,
            "known": True,
            "sector": row["sector"] or None,
            "market_cap_tier": row["tier"],
            "tier_source": row["tier_index"],
            "fno_eligible": bool(row["fno"]),
            "lot_size": row["lot_size"],
            "sector_index": row["sector_index"],
            "refreshed_at": row["refreshed_at"],
            "stale_days": age,
            "stale": age > 7,
        }

    def record_sector_closes(
        self, index_name: str, closes: list[tuple[str, float]], source: str
    ) -> int:
        with sqlite3.connect(self.path) as conn:
            written = 0
            for date, close in closes:
                if close > 0:
                    conn.execute(
                        "INSERT OR REPLACE INTO sector_closes VALUES (?,?,?,?)",
                        (index_name, date, float(close), source),
                    )
                    written += 1
        return written

    def sector_performance(self, index_name: str, as_of: dt.datetime) -> dict[str, Any]:
        """Index returns over 1, 5 and 20 completed sessions, or a clear absence."""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT date, close, source FROM sector_closes WHERE index_name=? AND date<=? "
                "ORDER BY date",
                (index_name, str(as_of.astimezone(IST).date())),
            ).fetchall()
        known = set(completed([(row[0], row[1]) for row in rows], as_of))
        rows = [row for row in rows if (row[0], row[1]) in known]
        if len(rows) < 2:
            return {
                "index": index_name,
                "available": False,
                "reason": "no stored index closes; sync this sector index before relying on it",
            }
        closes = [row[1] for row in rows]

        def change(span: int) -> float | None:
            if len(closes) <= span:
                return None
            return round(100 * (closes[-1] / closes[-1 - span] - 1), 2)

        latest = change(1)
        return {
            "index": index_name,
            "available": True,
            "last_session": rows[-1][0],
            "sessions": len(rows),
            "source": rows[-1][2],
            "return1_pct": latest,
            "return5_pct": change(5),
            "return20_pct": change(20),
            "direction": "up" if (latest or 0) > 0 else "down" if (latest or 0) < 0 else "flat",
        }


def completed(rows: list[tuple[str, float]], now: dt.datetime) -> list[tuple[str, float]]:
    """Drop today's row until the session has closed; a partial day is not a close."""
    local = now.astimezone(IST)
    closed = local.time() >= dt.time(15, 35)
    today = str(local.date())
    return [(date, close) for date, close in rows if date < today or (date == today and closed)]


def read_sector_csv(raw: bytes) -> list[tuple[str, float]]:
    """Date and Close columns from a downloaded index history (niftyindices.com or similar)."""
    rows = []
    for row in _rows(raw):
        date_text = row.get("Date") or row.get("date") or row.get("HistoricalDate") or ""
        close_text = (row.get("Close") or row.get("close") or "").replace(",", "")
        parsed = None
        for pattern in ("%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d-%m-%Y"):
            try:
                parsed = dt.datetime.strptime(date_text.strip(), pattern).date()
                break
            except ValueError:
                continue
        try:
            close = float(close_text)
        except ValueError:
            continue
        if parsed and close > 0:
            rows.append((str(parsed), close))
    if not rows:
        raise ValueError("no Date/Close rows found in the index file")
    return sorted(rows)


def kite_sector_closes(token: str, days: int, now: dt.datetime, opener=None) -> list[tuple]:
    """Daily index closes from Kite for an index instrument token, using your own login."""
    if not token.isdigit() or not 5 <= days <= 400:
        raise ValueError("Use a numeric Kite index token and 5-400 days")
    key, access = os.environ.get("KITE_API_KEY", ""), os.environ.get("KITE_ACCESS_TOKEN", "")
    if not key or not access:
        raise ValueError("Set KITE_API_KEY and KITE_ACCESS_TOKEN privately outside chat")
    last = now.astimezone(IST).date()
    query = urllib.parse.urlencode(
        {"from": f"{last - dt.timedelta(days=days)} 00:00:00", "to": f"{last} 23:59:59"}
    )
    request = urllib.request.Request(
        f"https://api.kite.trade/instruments/historical/{token}/day?{query}",
        headers={"Authorization": f"token {key}:{access}", "X-Kite-Version": "3"},
        method="GET",
    )
    try:
        handle = (opener or urllib.request.build_opener(NoRedirect)).open(request, timeout=20)
        with handle as response:
            raw = response.read(MAX_BYTES + 1)
        payload = json.loads(raw)
        candles = payload["data"]["candles"]
    except (OSError, urllib.error.URLError, ValueError, KeyError, TypeError):
        raise ValueError("Kite index history request failed; no retries") from None
    rows = []
    for candle in candles:
        try:
            rows.append((str(dt.datetime.fromisoformat(candle[0]).date()), float(candle[4])))
        except (ValueError, TypeError, IndexError):
            continue
    return sorted(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/observatory/reference.sqlite"))
    sub = parser.add_subparsers(dest="command", required=True)
    refresh = sub.add_parser("refresh", help="Read the NSE reference files")
    refresh.add_argument("--catalogue", type=Path, help="JSON overriding the default source URLs")
    look = sub.add_parser("lookup")
    look.add_argument("--symbol", required=True)
    sector = sub.add_parser("sector")
    sector.add_argument("--index", required=True)
    sync = sub.add_parser("sync-sector", help="Store completed daily closes for a sector index")
    sync.add_argument("--index", required=True, help='Index name, e.g. "NIFTY IT"')
    source = sync.add_mutually_exclusive_group(required=True)
    source.add_argument("--kite-token", help="Kite instrument token of the index (INDICES)")
    source.add_argument("--csv", type=Path, help="Downloaded index history with Date, Close")
    sync.add_argument("--days", type=int, default=60)
    args = parser.parse_args(argv)
    try:
        store = ReferenceStore(args.db)
        if args.command == "refresh":
            catalogue = json.loads(args.catalogue.read_text()) if args.catalogue else None
            result: Any = store.refresh(catalogue)
        elif args.command == "lookup":
            result = store.lookup(args.symbol)
        elif args.command == "sync-sector":
            now = dt.datetime.now(IST)
            if args.kite_token:
                rows, origin = kite_sector_closes(args.kite_token, args.days, now), "kite:day"
            else:
                rows, origin = read_sector_csv(args.csv.read_bytes()), f"csv:{args.csv.name}"
            kept = completed(rows, now)
            result = {
                "index": args.index,
                "stored": store.record_sector_closes(args.index, kept, origin),
                "skipped_incomplete": len(rows) - len(kept),
                "performance": store.sector_performance(args.index, now),
            }
        else:
            result = store.sector_performance(args.index, dt.datetime.now(IST))
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print("DATA_BLOCK: " + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())

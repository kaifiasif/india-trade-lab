#!/usr/bin/env python3
"""Build a sourced universe.json for 1-3 NSE cash equities. GET-only, never orders.

Combines two official sources:

- NSE's equity list EQUITY_L.csv, for the ISIN and EQ series. Download it in a
  browser from https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
- Kite's NSE instrument dump, for each stock's numeric instrument_token, fetched
  with today's KITE_API_KEY / KITE_ACCESS_TOKEN.

    source ~/.india-trade-lab.env
    python3 scripts/make_universe.py --equity-list ~/Downloads/EQUITY_L.csv \
        --symbols INFY,TCS,RELIANCE --output data/observatory/universe.json

The watchlist refuses a universe older than 30 days, so rebuild it monthly.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path

from broker_data import NoRedirect

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
INSTRUMENTS_URL = "https://api.kite.trade/instruments/NSE"
MAX_DUMP_BYTES = 50_000_000


def parse_kite_dump(raw: bytes) -> dict[str, str]:
    """Map NSE EQ trading symbols to Kite instrument tokens."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    tokens = {}
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        if row.get("instrument_type") == "EQ" and row.get("segment") == "NSE":
            if not str(row.get("instrument_token", "")).isdigit():
                raise ValueError("Kite dump has a non-numeric instrument token")
            tokens[row["tradingsymbol"]] = row["instrument_token"]
    if not tokens:
        raise ValueError("Kite dump contained no NSE EQ instruments")
    return tokens


def fetch_kite_dump(environ: Mapping[str, str] | None = None, opener=None) -> bytes:
    env = os.environ if environ is None else environ
    key, token = env.get("KITE_API_KEY", ""), env.get("KITE_ACCESS_TOKEN", "")
    if not key or not token:
        raise ValueError("Load today's Kite token first: source ~/.india-trade-lab.env")
    request = urllib.request.Request(
        INSTRUMENTS_URL,
        headers={"X-Kite-Version": "3", "Authorization": f"token {key}:{token}"},
        method="GET",
    )
    opener = opener or urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=60) as response:
            raw = response.read(MAX_DUMP_BYTES + 1)
    except (OSError, urllib.error.URLError):
        raise ValueError("Kite instrument dump unavailable; check today's token") from None
    if len(raw) > MAX_DUMP_BYTES:
        raise ValueError("Kite instrument dump exceeds its size limit")
    return raw


def parse_equity_list(path: Path) -> dict[str, dict[str, str]]:
    """Read NSE's EQUITY_L.csv, whose headers carry stray leading spaces."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = [
            {key.strip(): (value or "").strip() for key, value in row.items() if key}
            for row in csv.DictReader(handle)
        ]
    if not rows or "ISIN NUMBER" not in rows[0] or "SERIES" not in rows[0]:
        raise ValueError("Expected NSE's EQUITY_L.csv with SYMBOL, SERIES and ISIN NUMBER")
    return {row["SYMBOL"]: row for row in rows}


def build_universe(
    symbols: list[str],
    equities: dict[str, dict[str, str]],
    tokens: dict[str, str],
    now: dt.datetime,
) -> dict:
    if not 1 <= len(symbols) <= 3 or len(set(symbols)) != len(symbols):
        raise ValueError("Choose 1-3 distinct symbols; the current feed maps at most three")
    instruments = []
    for symbol in symbols:
        if not re.fullmatch(r"[A-Z0-9&\-]+", symbol):
            raise ValueError(f"{symbol}: use the plain NSE symbol, e.g. INFY")
        row = equities.get(symbol)
        if not row or row.get("SERIES") != "EQ":
            raise ValueError(f"{symbol}: not an EQ-series stock in EQUITY_L.csv")
        if not re.fullmatch(r"IN[A-Z0-9]{10}", row.get("ISIN NUMBER", "")):
            raise ValueError(f"{symbol}: EQUITY_L.csv has no valid ISIN")
        if symbol not in tokens:
            raise ValueError(f"{symbol}: no NSE EQ instrument in today's Kite dump")
        instruments.append(
            {
                "symbol": f"NSE:{symbol}",
                "name": row.get("NAME OF COMPANY", ""),
                "segment": "EQ",
                "active": True,
                "isin": row["ISIN NUMBER"],
                "data_provider": "kite",
                "instrument_id": tokens[symbol],
                "quote_provider": "kite",
            }
        )
    stamp = now.astimezone(IST).replace(microsecond=0)
    return {
        "source": "NSE EQUITY_L.csv (ISIN, EQ series) and Kite NSE instrument dump, "
        f"built {stamp.date()}",
        "as_of": stamp.isoformat(),
        "instruments": instruments,
    }


def main(argv: list[str] | None = None, opener=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--equity-list", type=Path, required=True)
    parser.add_argument("--symbols", required=True, help="Comma-separated NSE symbols, 1-3")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
        universe = build_universe(
            symbols,
            parse_equity_list(args.equity_list),
            parse_kite_dump(fetch_kite_dump(opener=opener)),
            dt.datetime.now(IST),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(universe, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        print("REFUSED: " + str(exc))
        return 2
    print(f"Wrote {args.output}: " + ", ".join(i["symbol"] for i in universe["instruments"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

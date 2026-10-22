#!/usr/bin/env python3
"""Read-only Binance spot history, metadata and bid/ask snapshots. No API keys or orders."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from broker_data import NoRedirect

BASE = "https://data-api.binance.vision"
ROUTES = {"/api/v3/exchangeInfo", "/api/v3/klines", "/api/v3/ticker/bookTicker"}
DAY_MS = 86400000


def get_public(path: str, params: dict) -> Any:
    """Fixed market-data-only host and routes, finite size/timeout, no redirect or fallback."""
    if path not in ROUTES:
        raise ValueError("Only public market-data routes are allowed")
    request = urllib.request.Request(
        BASE + path + "?" + urllib.parse.urlencode(params),
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError("Crypto response exceeds size limit")
        return json.loads(raw)
    except (OSError, ValueError, urllib.error.URLError):
        raise ValueError(
            "Public crypto data unavailable; no host switching or order attempt"
        ) from None


def positive(value: Any, zero: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid crypto numeric value") from None
    if not result.is_finite() or result < 0 or (result == 0 and not zero):
        raise ValueError("Crypto prices/volumes must be finite and nonnegative")
    return result


def normalized_candles(payload: object, as_of: dt.datetime, days: int) -> list[dict]:
    """Require 50+ complete consecutive UTC days; never treat a current candle as closed."""
    if as_of.tzinfo is None or not isinstance(payload, list) or not 50 <= days <= 365:
        raise ValueError("Require aware cutoff, candle list and 50–365 days")
    now_ms = int(as_of.timestamp() * 1000)
    completed = []
    for row in payload:
        if (
            not isinstance(row, list)
            or len(row) < 7
            or type(row[0]) is not int
            or type(row[6]) is not int
        ):
            raise ValueError("Malformed crypto candle")
        opening, closing = row[0], row[6]
        if opening % DAY_MS or closing != opening + DAY_MS - 1:
            raise ValueError("Expected complete UTC daily candle boundaries")
        if closing >= now_ms:
            continue
        o, high, low, close = [positive(value) for value in row[1:5]]
        volume = positive(row[5], zero=True)
        if low > min(o, close) or high < max(o, close) or low > high:
            raise ValueError("Invalid crypto OHLC range")
        completed.append(
            {
                "open_ms": opening,
                "close_ms": closing,
                "open": str(o),
                "high": str(high),
                "low": str(low),
                "close": str(close),
                "volume": str(volume),
            }
        )
    if len(completed) < days:
        raise ValueError("Insufficient completed daily crypto history")
    completed = completed[-days:]
    if any(
        b["open_ms"] - a["open_ms"] != DAY_MS
        for a, b in zip(completed, completed[1:], strict=False)
    ):
        raise ValueError("Missing, duplicate or unordered daily crypto candles")
    if now_ms - completed[-1]["close_ms"] > DAY_MS + 3600000:
        raise ValueError("Latest daily crypto candle is stale")
    return completed


def collect(
    symbol: str, days: int = 90, as_of: dt.datetime | None = None, fetch=get_public
) -> dict:
    """Create a research-only spot snapshot; USD/USDT is never silently converted to INR."""
    if not re.fullmatch(r"[A-Z0-9]{2,16}USDT", symbol) or not 50 <= days <= 365:
        raise ValueError("Use an explicitly allowlisted USDT spot pair and 50–365 days")
    clock = as_of or dt.datetime.now(dt.timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("Crypto collection cutoff must be timezone-aware")
    metadata = fetch("/api/v3/exchangeInfo", {"symbol": symbol})
    entries = metadata.get("symbols") if isinstance(metadata, dict) else None
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("Crypto instrument metadata is missing")
    instrument = entries[0]
    if (
        not isinstance(instrument, dict)
        or instrument.get("symbol") != symbol
        or instrument.get("status") != "TRADING"
        or instrument.get("isSpotTradingAllowed") is not True
        or instrument.get("quoteAsset") != "USDT"
    ):
        raise ValueError("Pair is not a currently declared tradable USDT spot instrument")
    candles = normalized_candles(
        fetch(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": "1d",
                "limit": days + 1,
                "endTime": int(clock.timestamp() * 1000),
            },
        ),
        clock,
        days,
    )
    book = fetch("/api/v3/ticker/bookTicker", {"symbol": symbol})
    if not isinstance(book, dict) or book.get("symbol") != symbol:
        raise ValueError("Crypto quote symbol mismatch")
    bid, ask = positive(book["bidPrice"]), positive(book["askPrice"])
    if bid > ask:
        raise ValueError("Crossed crypto market")
    positive(book["bidQty"], zero=True)
    positive(book["askQty"], zero=True)
    closes = [Decimal(row["close"]) for row in candles]
    prior_high = max(Decimal(row["high"]) for row in candles[-21:-1])
    source = BASE + "/api/v3/klines"
    return {
        "market": "crypto_spot",
        "symbol": symbol,
        "quote_currency": "USDT",
        "source": source,
        "received_at": (as_of or dt.datetime.now(dt.timezone.utc)).isoformat(),
        "history_days": len(candles),
        "candles": candles,
        "bid": str(bid),
        "ask": str(ask),
        "quote_timestamp_kind": "local receipt; bookTicker has no exchange quote timestamp",
        "filters": instrument.get("filters", []),
        "sma20": str(sum(closes[-20:]) / 20),
        "sma50": str(sum(closes[-50:]) / 50),
        "pattern": "DAILY_BREAKOUT_RESEARCH" if closes[-1] > prior_high else "WAIT",
        "decision": "RESEARCH_ONLY",
        "real_orders_allowed": False,
        "notice": "Daily research context only. No intraday entry, crypto ledger, INR conversion or exchange order.",
    }


def save_snapshot(path: Path, snapshot: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS snapshots "
            "(id INTEGER PRIMARY KEY,symbol TEXT,received_at TEXT,data TEXT)"
        )
        conn.execute(
            "INSERT INTO snapshots (symbol,received_at,data) VALUES (?,?,?)",
            (snapshot["symbol"], snapshot["received_at"], json.dumps(snapshot)),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--db", type=Path, default=Path("data/observatory/crypto.sqlite"))
    args = parser.parse_args()
    try:
        symbols = args.symbols.split(",")
        if not 1 <= len(symbols) <= 5 or len(set(symbols)) != len(symbols):
            raise ValueError("Allowlist 1–5 distinct spot pairs")
        results = []
        for symbol in symbols:
            snapshot = collect(symbol, args.days)
            save_snapshot(args.db, snapshot)
            results.append({key: value for key, value in snapshot.items() if key != "candles"})
        print(json.dumps({"snapshots": results}, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
        print("DATA_BLOCK: crypto inputs or public data are unavailable. No orders were sent.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

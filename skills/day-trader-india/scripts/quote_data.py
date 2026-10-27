#!/usr/bin/env python3
"""Read-only Kite/Paytm Money bid/ask snapshots with explicit timestamp provenance."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path

import broker_data
import paper_book


def make_quote_request(
    provider: str, symbol: str, instrument: str = "", environ: Mapping[str, str] | None = None
) -> urllib.request.Request:
    env = os.environ if environ is None else environ
    if not re.fullmatch(r"(NSE|BSE):[A-Z0-9&.\-]+", symbol):
        raise ValueError("Use an exchange-qualified cash-equity symbol")
    if provider == "kite":
        key, token = env.get("KITE_API_KEY"), env.get("KITE_ACCESS_TOKEN")
        if not key or not token:
            raise ValueError("Configure Kite credentials privately")
        url = "https://api.kite.trade/quote?" + urllib.parse.urlencode({"i": symbol})
        headers = {"Authorization": f"token {key}:{token}", "X-Kite-Version": "3"}
    elif provider == "paytm":
        token = env.get("PAYTM_READ_ACCESS_TOKEN")
        if not token or not re.fullmatch(r"[0-9]{1,15}", instrument):
            raise ValueError(
                "Configure a Paytm read token and verified cash-equity security ID privately"
            )
        pref = f"{symbol.split(':')[0]}:{instrument}:EQUITY"
        url = "https://developer.paytmmoney.com/data/v1/price/live?" + urllib.parse.urlencode(
            {"mode": "FULL", "pref": pref}
        )
        headers = {"x-jwt-token": token, "Accept": "application/json"}
    else:
        raise ValueError("Quote provider must be kite or paytm")
    return urllib.request.Request(url, headers=headers, method="GET")


def normalize_quote(
    provider: str, payload: object, symbol: str, instrument: str, received: dt.datetime
) -> dict:
    if received.tzinfo is None or not isinstance(payload, dict):
        raise ValueError("Expected a JSON quote and aware receipt time")
    if provider == "kite":
        if payload.get("status") != "success":
            raise ValueError("Kite quote request did not succeed")
        quote = payload["data"][symbol]
        observed = dt.datetime.fromisoformat(quote["timestamp"])
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=paper_book.IST)
        kind = "exchange"
    elif provider == "paytm":
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != 1:
            raise ValueError("Expected one unambiguous Paytm quote")
        quote = data[0]
        if (
            str(quote.get("security_id")) != instrument
            or quote.get("found") is not True
            or quote.get("tradable") is not True
            or quote.get("mode") != "FULL"
        ):
            raise ValueError("Paytm quote is absent, nontradable or mismatched")
        timestamp = quote.get("last_update_time", quote.get("last_trade_time"))
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not math.isfinite(timestamp)
            or not 0 <= timestamp <= 253402300799
        ):
            raise ValueError("Paytm quote has no usable original timestamp")
        observed = dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
        kind = "exchange" if "last_update_time" in quote else "last_trade"
    else:
        raise ValueError("Unsupported provider")
    depth = quote["depth"]
    bid, ask = (
        paper_book.number(depth["buy"][0]["price"], True),
        paper_book.number(depth["sell"][0]["price"], True),
    )
    if bid > ask or not -5 <= (received - observed).total_seconds() <= 120:
        raise ValueError("Quote is crossed, stale or future dated")
    # Circuit limits when the provider states them, so the price-band check can be
    # verified against the exchange's own bounds instead of being asserted by hand.
    band = {}
    for field, name in (
        ("lower_circuit_limit", "lower_circuit_inr"),
        ("upper_circuit_limit", "upper_circuit_inr"),
    ):
        value = quote.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            band[name] = str(paper_book.number(value, True))
    if len(band) == 2 and not (
        paper_book.number(band["lower_circuit_inr"], True)
        <= bid
        <= ask
        <= paper_book.number(band["upper_circuit_inr"], True)
    ):
        raise ValueError("Quote lies outside the stated circuit band")
    return {
        **band,
        "symbol": symbol,
        "bid_inr": str(bid),
        "ask_inr": str(ask),
        "as_of": observed.isoformat(),
        "received_at": received.isoformat(),
        "timestamp_kind": kind,
        "source": f"{provider}:full_quote:{instrument or symbol}",
        "forward_quote_usable": kind == "exchange",
        "notice": "A last-trade timestamp alone does not establish bid/ask freshness"
        if kind != "exchange"
        else "Market-data snapshot only",
    }


def collect_quote(provider: str, symbol: str, instrument: str = "") -> dict:
    request = make_quote_request(provider, symbol, instrument)
    try:
        with urllib.request.build_opener(broker_data.NoRedirect).open(
            request, timeout=15
        ) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Quote response exceeds size limit")
        return normalize_quote(
            provider, json.loads(raw), symbol, instrument, dt.datetime.now(paper_book.IST)
        )
    except (ValueError, KeyError, TypeError, IndexError, OSError, urllib.error.URLError):
        raise ValueError("Authorized quote unavailable or failed freshness checks") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("kite", "paytm"), required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--instrument", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        quote = collect_quote(args.provider, args.symbol, args.instrument)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # A snapshot export never silently replaces another provider or symbol's evidence.
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps({args.symbol: quote}, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": "data_only",
                    "symbol": args.symbol,
                    "forward_quote_usable": quote["forward_quote_usable"],
                }
            )
        )
        return 0
    except (ValueError, OSError, TypeError):
        print(
            "DATA_BLOCK: quote could not be exported. No credentials or orders were sent to another host."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

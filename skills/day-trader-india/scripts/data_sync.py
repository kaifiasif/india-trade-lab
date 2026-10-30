#!/usr/bin/env python3
"""Collect entitled Kite/Upstox candles into immutable history. GET-only, never orders."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from decision_pipeline import read_json
from history import HistoryStore
from quote_data import collect_quote

import broker_data
import india_research


def refresh_current(
    config_path: Path, now: dt.datetime | None = None, fetch=None, quote_fetch=collect_quote
) -> dict:
    """Refresh explicitly mapped quotes/current candles; failed symbols are omitted, never carried over."""
    clock = now or dt.datetime.now(india_research.IST)
    if clock.tzinfo is None:
        raise ValueError("Refresh cutoff must be aware")
    clock = clock.astimezone(india_research.IST)
    config = read_json(config_path)
    root = config_path.resolve().parent
    india_research.session(read_json(root / config["sessions"]), clock.date())
    instruments = read_json(root / config["universe"])["instruments"]
    if not 1 <= len(instruments) <= 10:
        raise ValueError("Current feed is limited to 1–10 explicitly mapped instruments")
    fetch = fetch or fetch_history
    rows, quotes, blocked = [], {}, []
    exports = root / "provider-exports"
    exports.mkdir(parents=True, exist_ok=True)
    for item in instruments:
        symbol = item.get("symbol", "")
        try:
            provider, identifier = item["data_provider"], item["instrument_id"]
            quote_provider = item.get("quote_provider", provider)
            quote = quote_fetch(quote_provider, symbol, item.get("quote_instrument_id", identifier))
            payload = fetch(provider, identifier, clock.date(), clock.date())
            with tempfile.TemporaryDirectory(dir=exports) as directory:
                output = Path(directory) / "current.csv"
                broker_data.export(
                    payload, symbol, f"{provider}:historical:5minute:{identifier}", output
                )
                with output.open(newline="") as handle:
                    collected = list(csv.DictReader(handle))
                for row in collected:
                    india_research.validate_bar(row)
            rows.extend(collected)
            quotes[symbol] = quote
        except (ValueError, OSError, KeyError, TypeError):
            blocked.append(symbol)
    fields = ("symbol", "timestamp", "open", "high", "low", "close", "volume", "source")
    for key in ("bars", "quotes"):
        destination = root / config[key]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=destination.parent, delete=False, encoding="utf-8", newline=""
        ) as handle:
            temporary = Path(handle.name)
            if key == "quotes":
                json.dump(quotes, handle)
            else:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    return {"as_of": clock.isoformat(), "refreshed": sorted(quotes), "blocked": blocked}


def fetch_history(provider: str, instrument: str, first: dt.date, last: dt.date) -> dict:
    request = broker_data.make_request(provider, instrument, str(first), str(last))
    time.sleep(0.5)  # Bound this single collector to at most two requests per second.
    try:
        with urllib.request.build_opener(broker_data.NoRedirect).open(
            request, timeout=20
        ) as response:
            raw = response.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError("Broker history response is too large")
        return json.loads(raw)
    except (ValueError, OSError, urllib.error.URLError):
        raise ValueError(
            "Authorized historical data request failed; no retries or provider switching"
        ) from None


def sync_history(
    config_path: Path,
    days: int = 180,
    max_symbols: int = 3,
    now: dt.datetime | None = None,
    fetch=fetch_history,
) -> dict[str, Any]:
    """Fetch bounded seven-day batches, preserving all provider exports and import results."""
    if not 90 <= days <= 365 or not 1 <= max_symbols <= 10:
        raise ValueError("Use 90–365 calendar days and 1–10 explicitly configured instruments")
    clock = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30)))
    if clock.tzinfo is None:
        raise ValueError("Need an aware collection cutoff")
    config = read_json(config_path)
    root = config_path.resolve().parent
    universe = read_json(root / config["universe"])
    manifest = root / config["sessions"]
    read_json(manifest)  # Require a sourced calendar before spending data calls.
    instruments = universe.get("instruments", [])
    if len(instruments) > max_symbols:
        raise ValueError(
            "Universe exceeds this explicit collection budget; choose a bounded universe"
        )
    store = HistoryStore(root / config["history_db"])
    results = []
    exports = root / "provider-exports"
    exports.mkdir(parents=True, exist_ok=True)
    for instrument in instruments:
        symbol = instrument.get("symbol", "")
        provider, identifier = instrument.get("data_provider"), instrument.get("instrument_id")
        if provider not in ("kite", "upstox") or not isinstance(identifier, str):
            results.append(
                {
                    "symbol": symbol,
                    "status": "DATA_BLOCK",
                    "reason": "Missing entitled provider and verified instrument mapping",
                }
            )
            continue
        try:
            first = clock.date() - dt.timedelta(days=days)
            rows = []
            while first <= clock.date():
                last = min(first + dt.timedelta(days=6), clock.date())
                payload = fetch(provider, identifier, first, last)
                candles = (
                    payload.get("data", {}).get("candles") if isinstance(payload, dict) else None
                )
                if candles == [] and payload.get("status") == "success":
                    first = last + dt.timedelta(days=1)
                    continue
                with tempfile.NamedTemporaryFile(dir=exports, suffix=".csv", delete=True) as handle:
                    temporary = Path(handle.name)
                source = f"{provider}:historical:5minute:{identifier}"
                broker_data.export(payload, symbol, source, temporary)
                try:
                    with temporary.open(newline="") as handle:
                        rows.extend(csv.DictReader(handle))
                finally:
                    temporary.unlink(missing_ok=True)
                first = last + dt.timedelta(days=1)
            if not rows:
                raise ValueError("No historical candles were returned")
            rows.sort(key=lambda row: row["timestamp"])
            if len({row["timestamp"] for row in rows}) != len(rows):
                raise ValueError("Provider batches overlap or duplicate observations")
            filename = symbol.replace(":", "-") + "-" + clock.strftime("%Y%m%dT%H%M%S%f") + ".csv"
            exported = exports / filename
            with exported.open("x", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            imported = store.ingest(exported, manifest, symbol, "broker_export", clock)
            results.append(
                {
                    "symbol": symbol,
                    "status": "IMPORTED",
                    "import": imported,
                    "coverage": store.coverage(symbol, clock),
                }
            )
        except (ValueError, OSError, TypeError, KeyError):
            results.append(
                {
                    "symbol": symbol,
                    "status": "DATA_BLOCK",
                    "reason": "Data collection, mapping or completeness check failed",
                }
            )
    return {
        "as_of": clock.isoformat(),
        "results": results,
        "mode": "data_only",
        "notice": "Historical candles are not current executable quotes or trade approvals.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--max-symbols", type=int, default=3)
    parser.add_argument(
        "--current", action="store_true", help="Refresh mapped current quotes/candles only"
    )
    args = parser.parse_args()
    try:
        result = (
            refresh_current(args.config)
            if args.current
            else sync_history(args.config, args.days, args.max_symbols)
        )
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        print(
            "DATA_BLOCK: configure authorized data, verified mappings and sourced sessions privately"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

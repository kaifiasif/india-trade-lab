#!/usr/bin/env python3
"""Shadow fills: how far real prices moved from the paper fill a minute later.

A paper fill happens at the quoted price the instant the desk decides. A real order
would arrive later and pay the spread, so the paper book flatters itself. For every
paper entry and exit this module notes the assumed fill, then, ``delay_seconds`` (60)
later, reads a fresh quote: the ask for a buy, the bid for a sell. The difference, in
basis points (positive = worse than assumed), is a measured slippage sample.

``calibration`` summarises the samples (median, 75th and 90th percentile) and compares
them with the configured ``slippage_bps``. When the 75th percentile is higher, the
tournaments' cost assumption is too kind and the dashboard says so. Nothing here
changes a fill; it only measures. No order is ever sent.

    python3 shadow.py calibration
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
DEFAULTS = {"enabled": True, "delay_seconds": 60, "max_wait_seconds": 600}
KEEP = 500


def _path(config_path: Path) -> Path:
    return intraday.config_folder(config_path) / "shadow-fills.json"


def _load(config_path: Path) -> dict[str, Any]:
    try:
        return json.loads(_path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pending": [], "settled": []}


def record(
    config_path: Path, book: str, symbol: str, side: str, assumed: float, clock: dt.datetime
) -> None:
    """Note one paper fill to compare with the market a minute later."""
    cfg = {**DEFAULTS, **(intraday.load_config(config_path).get("shadow") or {})}
    if not cfg["enabled"] or side not in ("buy", "sell") or assumed <= 0:
        return
    state = _load(config_path)
    state["pending"].append({"book": book, "symbol": symbol, "side": side,
                             "assumed": float(assumed), "at": clock.isoformat()})  # fmt: skip
    intraday.write_json(_path(config_path), state)


def _real_price(quote: dict, side: str) -> float:
    depth = quote.get("depth") or {}
    level = (depth.get("sell" if side == "buy" else "buy") or [{}])[0]
    return float(level.get("price") or quote.get("last_price") or 0)


def settle(config_path: Path, clock: dt.datetime, quotes_for: Callable[[list[str]], dict]) -> dict:
    """Read fresh quotes for fills old enough to compare; keep the samples."""
    cfg = {**DEFAULTS, **(intraday.load_config(config_path).get("shadow") or {})}
    state = _load(config_path)
    if not state["pending"]:
        return {"settled": 0, "waiting": 0}
    due, waiting, dropped = [], [], 0
    for item in state["pending"]:
        age = (clock - dt.datetime.fromisoformat(item["at"])).total_seconds()
        if age > float(cfg["max_wait_seconds"]):
            dropped += 1
        elif age >= float(cfg["delay_seconds"]):
            due.append(item)
        else:
            waiting.append(item)
    settled = 0
    if due:
        try:
            quotes = quotes_for(sorted({item["symbol"] for item in due}))
        except (ValueError, OSError, KeyError):
            quotes = {}
        for item in due:
            real = _real_price(quotes.get(item["symbol"]) or {}, item["side"])
            if real <= 0:
                waiting.append(item)
                continue
            sign = 1 if item["side"] == "buy" else -1
            bps = sign * (real - item["assumed"]) / item["assumed"] * 10_000
            state["settled"].append({**item, "real": real, "slippage_bps": round(bps, 2),
                                     "checked_at": clock.isoformat()})  # fmt: skip
            settled += 1
    state["pending"] = waiting
    state["settled"] = state["settled"][-KEEP:]
    intraday.write_json(_path(config_path), state)
    return {"settled": settled, "waiting": len(waiting), "dropped": dropped}


def calibration(config_path: Path) -> dict[str, Any]:
    """Measured slippage against the configured assumption, per book."""
    config = intraday.load_config(config_path)
    samples = _load(config_path)["settled"]
    configured = {
        "intraday": float(config.get("slippage_bps", 5)),
        "swing": float((config.get("swing") or {}).get("slippage_bps", 5)),
    }
    result: dict[str, Any] = {}
    for book, assumed in configured.items():
        values = sorted(item["slippage_bps"] for item in samples if item["book"] == book)
        row: dict[str, Any] = {"samples": len(values), "configured_bps": assumed}
        if len(values) >= 5:
            cuts = statistics.quantiles(values, n=20)
            row.update(median_bps=round(statistics.median(values), 2), p75_bps=round(cuts[14], 2),
                       p90_bps=round(cuts[17], 2))  # fmt: skip
            row["verdict"] = (
                f"real fills were worse than assumed: raise slippage_bps to about {cuts[14]:.0f}"
                if cuts[14] > assumed
                else "the configured slippage covers 75% of measured fills"
            )
        else:
            row["verdict"] = "fewer than 5 samples; keep paper trading"
        result[book] = row
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("command", choices=["calibration"])
    args = parser.parse_args(argv)
    try:
        print(json.dumps(calibration(args.config), indent=2))
    except (ValueError, OSError) as exc:
        print(f"Shadow calibration refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

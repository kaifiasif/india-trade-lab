#!/usr/bin/env python3
"""Market context for the agents: who bought yesterday, how broad the move was, what regime.

Written to ``market-context.json`` before the morning report and shown to the sector
and technical analysts and the judge as ``#market`` evidence, with its source:

- **FII and DII cash flows** for the last session (NSE's ``fiidiiTradeReact`` feed;
  scripted access may be refused, then it is left out and said so);
- **breadth** from NSE's bhavcopy archive (``bhavcopy.py``): advances, declines and the
  share of traded value in rising stocks;
- **regime** (``regime.py``): Nifty trend and India VIX band at the last close.

It is context, not a signal: no rule trades on it.

    python3 market_context.py build
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
FII_DII = "https://www.nseindia.com/api/fiidiiTradeReact"


def parse_flows(raw: bytes) -> dict[str, Any]:
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError("Unexpected FII/DII response")
    flows: dict[str, Any] = {}
    for row in rows:
        category = str(row.get("category", "")).upper()
        key = (
            "fii"
            if "FII" in category or "FPI" in category
            else "dii"
            if "DII" in category
            else None
        )
        if key is None:
            continue
        try:
            flows[f"{key}_net_inr_crore"] = round(
                float(str(row.get("netValue")).replace(",", "")), 2
            )
        except ValueError:
            continue
        flows["date"] = row.get("date")
    if not flows:
        raise ValueError("No FII/DII rows")
    return flows


def build(
    config_path: Path, clock: dt.datetime, get: Callable[[str], bytes] | None = None
) -> dict[str, Any]:
    import bhavcopy
    import market_scan
    import regime

    get = get or market_scan.nse_fetch
    folder = intraday.config_folder(config_path)
    view: dict[str, Any] = {"as_of": clock.isoformat(), "notes": []}
    try:
        view["flows"] = {
            **parse_flows(get(FII_DII)),
            "source": "NSE fiidiiTradeReact (provisional)",
        }
    except (ValueError, OSError) as exc:
        view["notes"].append(f"FII/DII flows unavailable ({str(exc)[:80]})")
    try:
        view["breadth"] = bhavcopy.breadth(config_path)
    except (ValueError, OSError, sqlite3.Error) as exc:
        view["notes"].append(f"breadth unavailable ({str(exc)[:80]})")
    label = regime.label_before(regime.labels(folder / "scan.sqlite"), str(clock.date()))
    if label:
        view["regime"] = {**label, "source": "Nifty 50 vs its 50-day average; India VIX close"}
    else:
        view["notes"].append("regime unknown (no Nifty and VIX history yet)")
    intraday.write_json(folder / "market-context.json", view)
    return view


def load(folder: Path, day: dt.date) -> dict[str, Any] | None:
    """Today's context, or None when it is missing or from another day."""
    try:
        view = json.loads((folder / "market-context.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return view if str(view.get("as_of", ""))[:10] == str(day) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("command", choices=["build"])
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args.config, intraday.now_ist()), indent=2))
    except (ValueError, OSError) as exc:
        print(f"Market context refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

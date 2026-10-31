#!/usr/bin/env python3
"""Exact Indian equity trading charges, versioned by date, with a per-trade breakdown.

"Double costs" in the tournaments only means something if single costs are right.
Rates follow Zerodha's published charges for NSE cash equity. Each version has the
date it applies from, so old trades are replayed at the costs of their time.

| Charge | Intraday | Delivery (swing) |
| --- | --- | --- |
| Brokerage | 0.03% or ₹20 an executed order, whichever is lower | ₹0 |
| STT | 0.025% on the sell side | 0.1% on buy and sell |
| NSE transaction charge | 0.00307% (0.00297% before) | same |
| SEBI fee | ₹10 a crore | same |
| Stamp duty | 0.003% on the buy side | 0.015% on the buy side |
| IPFT | ₹0.01 a crore | same |
| GST | 18% of brokerage, transaction charge, SEBI fee and IPFT | same |
| DP charge | none | ₹15.34 a stock on each sale, whatever the quantity |

Rates change (NSE's transaction charge moved from 0.00297% to 0.00307%). When they
do, add a version here; never edit an old one. Check against the broker's own
calculator when a version is added. These are estimates for paper research, not a
contract note.

    python3 charges.py --kind delivery --buy 1500 --sell 1560 --qty 16
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

VERSIONS: list[dict[str, Any]] = [
    {
        "from": "2024-10-01",
        "source": "Zerodha bulletin: revision in transaction charges from 1 Oct 2024",
        "brokerage_pct": 0.03, "brokerage_cap_inr": 20.0,
        "stt_intraday_sell_pct": 0.025, "stt_delivery_pct": 0.1,
        "txn_pct": 0.00297, "sebi_per_crore": 10.0, "ipft_per_crore": 0.01,
        "stamp_intraday_buy_pct": 0.003, "stamp_delivery_buy_pct": 0.015,
        "gst_pct": 18.0, "dp_per_sale_inr": 15.34,
    },
    {
        # The page was read on this date; the change happened on or before it.
        "from": "2026-10-31",
        "source": "zerodha.com/charges, read 31 Oct 2026",
        "brokerage_pct": 0.03, "brokerage_cap_inr": 20.0,
        "stt_intraday_sell_pct": 0.025, "stt_delivery_pct": 0.1,
        "txn_pct": 0.00307, "sebi_per_crore": 10.0, "ipft_per_crore": 0.01,
        "stamp_intraday_buy_pct": 0.003, "stamp_delivery_buy_pct": 0.015,
        "gst_pct": 18.0, "dp_per_sale_inr": 15.34,
    },
]  # fmt: skip
CRORE = 1e7


def version(day: dt.date | str | None = None) -> dict[str, Any]:
    """The rate version in force on ``day`` (today when not given)."""
    when = str(day or dt.date.today())
    applicable = [item for item in VERSIONS if item["from"] <= when]
    return applicable[-1] if applicable else VERSIONS[0]


def side(
    kind: str, which: str, price: float, qty: int, day: dt.date | str | None = None
) -> dict[str, float]:
    """Every charge for one order (one side of a trade), in rupees."""
    if kind not in ("intraday", "delivery") or which not in ("buy", "sell"):
        raise ValueError("kind is intraday or delivery; side is buy or sell")
    if price <= 0 or qty < 1:
        raise ValueError("A side needs a positive price and at least one share")
    rates = version(day)
    value = price * qty
    brokerage = (
        min(value * rates["brokerage_pct"] / 100, rates["brokerage_cap_inr"])
        if kind == "intraday"
        else 0.0
    )
    if kind == "intraday":
        stt = value * rates["stt_intraday_sell_pct"] / 100 if which == "sell" else 0.0
        stamp = value * rates["stamp_intraday_buy_pct"] / 100 if which == "buy" else 0.0
        dp = 0.0
    else:
        stt = value * rates["stt_delivery_pct"] / 100
        stamp = value * rates["stamp_delivery_buy_pct"] / 100 if which == "buy" else 0.0
        dp = rates["dp_per_sale_inr"] if which == "sell" else 0.0
    txn = value * rates["txn_pct"] / 100
    sebi = value * rates["sebi_per_crore"] / CRORE
    ipft = value * rates["ipft_per_crore"] / CRORE
    gst = (brokerage + txn + sebi + ipft) * rates["gst_pct"] / 100
    parts = {
        "brokerage": brokerage, "stt": stt, "transaction": txn, "sebi": sebi, "ipft": ipft,
        "stamp": stamp, "gst": gst, "dp": dp,
    }  # fmt: skip
    rounded = {key: round(amount, 2) for key, amount in parts.items()}
    rounded["total"] = round(sum(parts.values()), 2)
    return rounded


def trade(
    kind: str, buy: float, sell: float, qty: int, day: dt.date | str | None = None
) -> dict[str, Any]:
    """Both sides of a round trip: the breakdown, the total and the version used."""
    bought, sold = side(kind, "buy", buy, qty, day), side(kind, "sell", sell, qty, day)
    return {
        "kind": kind,
        "version_from": version(day)["from"],
        "buy": bought,
        "sell": sold,
        "total_inr": round(bought["total"] + sold["total"], 2),
        "gross_pnl_inr": round((sell - buy) * qty, 2),
        "net_pnl_inr": round((sell - buy) * qty - bought["total"] - sold["total"], 2),
    }


def fee(kind: str, which: str, price: float, qty: int, day: dt.date | str | None = None) -> float:
    return side(kind, which, price, qty, day)["total"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--kind", choices=("intraday", "delivery"), required=True)
    parser.add_argument("--buy", type=float, required=True)
    parser.add_argument("--sell", type=float, required=True)
    parser.add_argument("--qty", type=int, required=True)
    parser.add_argument("--date")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(trade(args.kind, args.buy, args.sell, args.qty, args.date), indent=2))
    except ValueError as exc:
        print(f"Charges refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

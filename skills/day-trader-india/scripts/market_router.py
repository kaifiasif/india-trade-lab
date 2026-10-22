#!/usr/bin/env python3
"""Route research by explicit exchange sessions. This module grants no trade permission."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEZONES = {"india": "Asia/Kolkata", "us": "America/New_York", "crypto": "UTC"}
CAPABILITIES = {
    "india": "paper_research_proposals",
    "us": "not_implemented",
    "crypto": "read_only_spot_observations",
}


def route_market(market: str, now: dt.datetime, calendar: dict | None = None) -> dict:
    """Missing dates block routing; an explicit null date means exchange holiday."""
    if market not in TIMEZONES or now.tzinfo is None:
        raise ValueError("Need a known market and timezone-aware clock")
    local = now.astimezone(ZoneInfo(TIMEZONES[market]))
    result = {
        "market": market,
        "local_time": local.isoformat(),
        "timezone": TIMEZONES[market],
        "capability": CAPABILITIES[market],
        "orders_allowed": False,
        "status": "DATA_BLOCK",
    }
    if market == "crypto":
        return {**result, "status": "OBSERVE", "reason": "Continuous public-data collection"}
    if (
        not isinstance(calendar, dict)
        or calendar.get("timezone") != TIMEZONES[market]
        or not isinstance(calendar.get("source"), str)
        or not calendar["source"].strip()
        or "SYNTHETIC" in calendar["source"].upper()
    ):
        return {**result, "reason": "Sourced exchange calendar required"}
    dates = calendar.get("sessions", {})
    date = str(local.date())
    if not isinstance(dates, dict) or date not in dates:
        return {**result, "reason": "Unknown date; no weekday or holiday fallback"}
    row = dates[date]
    if row is None:
        return {**result, "status": "CLOSED", "reason": "Explicit exchange closure"}
    try:
        start, end = (
            dt.datetime.combine(local.date(), dt.time.fromisoformat(row[key]), local.tzinfo)
            for key in ("open", "close")
        )
        if start >= end or any(value.second or value.microsecond for value in (start, end)):
            raise ValueError("Invalid core session")
    except (KeyError, TypeError, ValueError):
        return {**result, "reason": "Invalid dated session boundaries"}
    return {
        **result,
        "status": "OPEN" if start <= local < end else "CLOSED",
        "open_at": start.isoformat(),
        "close_at": end.isoformat(),
        "open_ist": start.astimezone(ZoneInfo("Asia/Kolkata")).isoformat(),
        "close_ist": end.astimezone(ZoneInfo("Asia/Kolkata")).isoformat(),
        "source": calendar["source"],
        "reason": "Dated core session; routing is independent of trade approval",
    }


def route_all(now: dt.datetime, india: dict | None = None, us: dict | None = None) -> dict:
    return {
        "as_of": now.isoformat(),
        "markets": [
            route_market("india", now, india),
            route_market("us", now, us),
            route_market("crypto", now),
        ],
        "execution": "disabled",
        "shared_multi_currency_risk": "required_before_any_cross_market_execution",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--india-calendar", type=Path)
    parser.add_argument("--us-calendar", type=Path)
    parser.add_argument("--as-of", help="Aware ISO timestamp; defaults to current UTC")
    args = parser.parse_args()
    try:
        now = (
            dt.datetime.fromisoformat(args.as_of)
            if args.as_of
            else dt.datetime.now(dt.timezone.utc)
        )
        calendars = [
            json.loads(path.read_text()) if path else None
            for path in (args.india_calendar, args.us_calendar)
        ]
        print(json.dumps(route_all(now, *calendars), indent=2))
        return 0
    except (ValueError, OSError, TypeError):
        print("DATA_BLOCK: invalid calendar or timestamp. No orders allowed.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

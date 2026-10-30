#!/usr/bin/env python3
"""Shared NSE intraday helpers for the trade tools: session clock, bars and paths.

The trade tools (entry timer, exit planner, time machine, trade check, price
alerts) all work on completed five-minute bars in Asia/Kolkata time, on the
session calendar in ``sessions.json`` (09:15-15:30, entries until 14:30, square-off
at 15:15 on a normal day). Nothing here places an order.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from pathlib import Path
from typing import Any

import india_research

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
BAR = dt.timedelta(minutes=5)
TICK = 0.05  # Prices are rounded to 5 paise; check the exchange tick size for live use.
DESK_DIR = "desk"


def config_folder(config_path: Path) -> Path:
    return config_path.resolve().parent


def desk_dir(config_path: Path) -> Path:
    """Where the trade tools write their JSON (entry, plan, odds, tickets, alerts)."""
    folder = config_folder(config_path) / DESK_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        raise ValueError(f"No desk project at {config_path}; create one in Setup first")
    return json.loads(config_path.read_text(encoding="utf-8"))


def sessions_manifest(config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    path = config_folder(config_path) / config.get("sessions", "sessions.json")
    if not path.is_file():
        raise ValueError("The NSE session calendar (sessions.json) is missing")
    return json.loads(path.read_text(encoding="utf-8"))


def session_times(manifest: dict[str, Any], day: dt.date) -> dict[str, dt.datetime] | None:
    """Open, close, entry cutoff and square-off for one date, or None when NSE is closed."""
    if manifest.get("sessions", {}).get(str(day)) is None:
        return None
    return india_research.session(manifest, day)


def now_ist(value: str | None = None) -> dt.datetime:
    """The clock in IST, or a pinned "YYYY-MM-DD HH:MM" (read as IST) for replays and tests."""
    if not value:
        return dt.datetime.now(IST)
    parsed = dt.datetime.fromisoformat(value.replace(" ", "T"))
    return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)


def kite_time(value: object) -> dt.datetime:
    """Kite's candle time, e.g. ``2026-09-28T09:15:00+0530``; Python 3.10 needs ``+05:30``."""
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(value).strip())
    return dt.datetime.fromisoformat(text)


def parse_candles(candles: list[list], day: dt.date | None = None) -> list[dict[str, Any]]:
    """Kite candles ``[time, open, high, low, close, volume]`` as bar dicts, in time order."""
    bars = []
    for candle in candles:
        if not isinstance(candle, (list, tuple)) or len(candle) < 6:
            raise ValueError("Malformed candle")
        stamp = kite_time(candle[0]).astimezone(IST)
        if day is not None and stamp.date() != day:
            continue
        values = [float(value) for value in candle[1:6]]
        if not all(math.isfinite(value) for value in values) or min(values[:4]) <= 0:
            raise ValueError("Candle prices must be positive numbers")
        bars.append(
            dict(zip(("open", "high", "low", "close", "volume"), values, strict=True), t=stamp)
        )
    bars.sort(key=lambda bar: bar["t"])
    return bars


def completed(bars: list[dict], clock: dt.datetime) -> list[dict]:
    """Only bars that have finished by ``clock``; a forming bar never counts."""
    return [bar for bar in bars if bar["t"] + BAR <= clock]


def read_bars_file(path: Path, day: dt.date | None = None) -> list[dict[str, Any]]:
    """Saved bars: a Kite historical JSON (``data.candles``) or a plain list of candles."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    candles = payload.get("data", {}).get("candles") if isinstance(payload, dict) else payload
    if not isinstance(candles, list):
        raise ValueError("Expected Kite candles: {'data': {'candles': [...]}} or a list")
    return parse_candles(candles, day)


def instrument_token(config_path: Path, symbol: str, day: dt.date) -> str:
    """Kite instrument token for an NSE equity, from today's cached instrument list."""
    import market_scan

    import make_universe

    rows = market_scan.load_dump(
        config_folder(config_path), day, lambda: make_universe.fetch_kite_dump()
    )
    plain = symbol.split(":")[-1]
    for row in rows:
        if (
            row.get("tradingsymbol") == plain
            and row.get("exchange") == "NSE"
            and row.get("instrument_type") == "EQ"
        ):
            return str(row["instrument_token"])
    raise ValueError(f"{plain} is not an NSE equity in today's Kite instrument list")


def today_bars(config_path: Path, symbol: str, clock: dt.datetime, client: Any = None) -> list:
    """Today's completed five-minute bars from Kite (your login, read-only)."""
    import market_scan

    client = client or market_scan.KiteClient()
    token = instrument_token(config_path, symbol, clock.date())
    candles = client.candles(token, "5minute", clock.date(), clock.date())
    return completed(parse_candles(candles, clock.date()), clock)


def normalise_symbol(symbol: str) -> str:
    plain = symbol.strip().upper().split(":")[-1]
    if not plain or not all(char.isalnum() or char in "&-" for char in plain) or len(plain) > 20:
        raise ValueError("Use a plain NSE symbol, for example INFY or NSE:INFY")
    return f"NSE:{plain}"


def round_down(price: float) -> float:
    return round(math.floor(price / TICK + 1e-9) * TICK, 2)


def round_up(price: float) -> float:
    return round(math.ceil(price / TICK - 1e-9) * TICK, 2)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{path.name} does not exist yet")
    if path.stat().st_size > 5_000_000:
        raise ValueError(f"{path.name} exceeds its size limit")
    return json.loads(path.read_text(encoding="utf-8"))

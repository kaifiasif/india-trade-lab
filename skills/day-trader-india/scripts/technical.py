#!/usr/bin/env python3
"""Verified technical snapshot from stored broker-export sessions. Point in time, no network.

Each complete five-minute session in history.sqlite is folded into one daily bar
(first open, high, low, last close, summed volume). Indicators are computed only
from sessions closed by the cutoff, and anything without enough history is None
rather than estimated. The snapshot is attached to agent context as citable
evidence, so a model quoting a level can be checked against this one source.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any

from history import HistoryStore
from research_lab import ema, rsi

RULE = "technical-v1"


def daily_bars(store: HistoryStore, symbol: str, as_of: dt.datetime) -> list[dict]:
    """Daily bars from complete broker-export sessions closed at or before the cutoff."""
    if as_of.tzinfo is None:
        raise ValueError("Technical cutoff must be timezone-aware")
    with sqlite3.connect(store.path) as conn:
        rows = conn.execute(
            "SELECT date, close_at, payload FROM sessions "
            "WHERE symbol=? AND kind='broker_export' ORDER BY date",
            (symbol,),
        ).fetchall()
    days = []
    for date, close_at, payload in rows:
        if dt.datetime.fromisoformat(close_at) > as_of:
            continue
        bars = json.loads(payload)["bars"]
        days.append(
            {
                "date": date,
                "close_at": close_at,
                "open": float(bars[0]["open"]),
                "high": max(float(bar["high"]) for bar in bars),
                "low": min(float(bar["low"]) for bar in bars),
                "close": float(bars[-1]["close"]),
                "volume": sum(float(bar["volume"]) for bar in bars),
            }
        )
    return days


def _wilder_atr(rows: list[dict], length: int = 14) -> float | None:
    if len(rows) <= length:
        return None
    ranges = [
        max(
            row["high"] - row["low"],
            abs(row["high"] - prior["close"]),
            abs(row["low"] - prior["close"]),
        )
        for prior, row in zip(rows, rows[1:], strict=False)
    ]
    value = sum(ranges[:length]) / length
    for item in ranges[length:]:
        value = (value * (length - 1) + item) / length
    return value


def snapshot(rows: list[dict]) -> dict[str, Any]:
    """Indicator values for the latest completed session; None where history is short."""
    if len(rows) < 20:
        raise ValueError("Need at least 20 completed sessions for a technical snapshot")
    closes = [row["close"] for row in rows]
    last = rows[-1]

    def sma(length: int) -> float | None:
        return statistics.mean(closes[-length:]) if len(closes) >= length else None

    mid = statistics.mean(closes[-20:])
    spread = statistics.pstdev(closes[-20:])
    macd_line = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26), strict=True)]
    signal = ema(macd_line, 9)
    window = rows[-20:]
    volume20 = sum(row["volume"] for row in window)
    prior_volume = (
        statistics.mean(row["volume"] for row in rows[-21:-1]) if len(rows) > 20 else None
    )
    values = {
        "close": last["close"],
        "sma10": sma(10),
        "sma20": sma(20),
        "sma50": sma(50),
        "sma200": sma(200),
        "ema10": ema(closes, 10)[-1],
        "rsi14": rsi(closes) if len(closes) > 14 else None,
        "macd": macd_line[-1] if len(closes) >= 35 else None,
        "macd_signal": signal[-1] if len(closes) >= 35 else None,
        "macd_histogram": macd_line[-1] - signal[-1] if len(closes) >= 35 else None,
        "bollinger_mid": mid,
        "bollinger_upper": mid + 2 * spread,
        "bollinger_lower": mid - 2 * spread,
        "atr14": _wilder_atr(rows),
        "vwma20": sum(row["close"] * row["volume"] for row in window) / volume20
        if volume20
        else None,
        "volume_ratio20": last["volume"] / prior_volume if prior_volume else None,
        "high20": max(row["high"] for row in window),
        "low20": min(row["low"] for row in window),
        "return5_pct": 100 * (closes[-1] / closes[-6] - 1) if len(closes) > 5 else None,
        "return20_pct": 100 * (closes[-1] / closes[-21] - 1) if len(closes) > 20 else None,
    }
    return {
        "rule": RULE,
        "session": last["date"],
        "close_at": last["close_at"],
        "sessions_used": len(rows),
        "values": {
            key: (round(value, 4) if value is not None else None) for key, value in values.items()
        },
    }


def evidence_item(symbol: str, technical: dict) -> dict[str, Any]:
    """Present the snapshot in the research-evidence shape so roles can cite it."""
    values = technical["values"]
    shown = ", ".join(
        f"{key} {value}" for key, value in values.items() if value is not None and key != "close"
    )
    return {
        "id": "technical-snapshot",
        "source": f"Computed by {RULE} from {technical['sessions_used']} stored broker-export sessions",
        "observed_at": technical["close_at"],
        "published_at": None,
        "facts": (
            f"{symbol} closed at INR {values['close']} on {technical['session']} (latest completed "
            f"session). {shown}. Indicators describe past prices only; they are not a forecast."
        ),
        "values": values,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="history.sqlite")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--as-of", required=True, help="Aware ISO timestamp")
    args = parser.parse_args()
    try:
        cutoff = dt.datetime.fromisoformat(args.as_of)
        technical = snapshot(daily_bars(HistoryStore(args.db), args.symbol, cutoff))
        print(json.dumps(technical, indent=2))
        return 0
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        print("DATA_BLOCK: " + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())

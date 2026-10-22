#!/usr/bin/env python3
"""Point-in-time daily technical and relative-strength research. Never entry approval."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import statistics
import urllib.request
from pathlib import Path

from guardrails import evidence_time

from broker_data import NoRedirect

NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
VERSION = "daily-research-v1"


def load_daily(path: Path, as_of: dt.datetime) -> dict[str, list[dict]]:
    """Require explicit availability, price basis and provenance; exclude future observations."""
    if as_of.tzinfo is None or path.stat().st_size > 100_000_000:
        raise ValueError("Require an aware cutoff and daily CSV no larger than 100 MB")
    series: dict[str, list[dict]] = {}
    seen = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            if index >= 500_000:
                raise ValueError("Daily input exceeds 500,000 observations")
            symbol, date = row["symbol"], dt.date.fromisoformat(row["date"])
            if not re.fullmatch(r"(NSE|BSE):[A-Z0-9&.\-]+", symbol) or (symbol, date) in seen:
                raise ValueError("Invalid symbol or duplicate daily observation")
            seen.add((symbol, date))
            available = evidence_time(row["available_at"])
            closed = evidence_time(row["close_at"])
            if (
                closed.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).date() != date
                or available < closed
                or not row["source"].strip()
            ):
                raise ValueError("Daily bar needs a valid source and availability time")
            if "SYNTHETIC" in row["source"].upper():
                raise ValueError("Synthetic history cannot support forward research")
            if row["price_basis"] not in ("price_return", "total_return"):
                raise ValueError("Declare price_return or total_return price basis")
            if row["adjustment"] not in ("split_adjusted", "index_level"):
                raise ValueError("Declare split-adjusted equity data or index levels")
            values = {key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}
            if any(not math.isfinite(value) or value < 0 for value in values.values()):
                raise ValueError("Nonfinite or negative daily OHLCV")
            if (
                min(values[key] for key in ("open", "high", "low", "close")) <= 0
                or values["low"] > min(values["open"], values["close"])
                or values["high"] < max(values["open"], values["close"])
            ):
                raise ValueError("Invalid daily OHLC range")
            if available <= as_of:
                series.setdefault(symbol, []).append(
                    {
                        **values,
                        "date": str(date),
                        "available_at": available.isoformat(),
                        "source": row["source"],
                        "close_at": closed.isoformat(),
                        "price_basis": row["price_basis"],
                        "adjustment": row["adjustment"],
                    }
                )
    for rows in series.values():
        rows.sort(key=lambda row: row["date"])
    return series


def ema(values: list[float], length: int) -> list[float]:
    result = [values[0]]
    alpha = 2 / (length + 1)
    for value in values[1:]:
        result.append(result[-1] + alpha * (value - result[-1]))
    return result


def rsi(values: list[float], length: int = 14) -> float:
    changes = [b - a for a, b in zip(values, values[1:], strict=False)]
    gains = sum(max(0, value) for value in changes[:length]) / length
    losses = sum(max(0, -value) for value in changes[:length]) / length
    for value in changes[length:]:
        gains = (gains * (length - 1) + max(0, value)) / length
        losses = (losses * (length - 1) + max(0, -value)) / length
    return 100 - 100 / (1 + gains / losses) if losses else 100 if gains else 50


def features(rows: list[dict]) -> dict:
    """Transparent daily heuristics; pattern names are approximate research labels."""
    if len(rows) < 61:
        raise ValueError("Need at least 61 completed daily observations")
    closes = [row["close"] for row in rows]
    sma20, sma50 = statistics.mean(closes[-20:]), statistics.mean(closes[-50:])
    fast, slow = ema(closes, 12), ema(closes, 26)
    macd = [a - b for a, b in zip(fast, slow, strict=True)]
    atr = statistics.mean(
        [
            max(
                row["high"] - row["low"],
                abs(row["high"] - prior["close"]),
                abs(row["low"] - prior["close"]),
            )
            for prior, row in zip(rows[-15:-1], rows[-14:], strict=True)
        ]
    )
    previous_high = max(row["high"] for row in rows[-21:-1])
    width = 400 * statistics.pstdev(closes[-20:]) / sma20
    momentum, previous_momentum = rsi(closes), rsi(closes[:-1])
    prior_volume = statistics.mean(row["volume"] for row in rows[-21:-1])
    patterns = []
    if closes[-1] > previous_high:
        patterns.append("CLOSING_HIGH_BREAKOUT")
    if previous_momentum <= 50 < momentum:
        patterns.append("RSI_RECLAIM_50")
    if 0 <= (previous_high / closes[-1] - 1) <= 0.02 and width <= 8:
        patterns.append("BREAKOUT_SOON_SQUEEZE")
    if sma20 > sma50 and rows[-1]["low"] <= sma20 * 1.01 and closes[-1] >= sma20 * 0.99:
        patterns.append("PULLBACK_IN_UPTREND")
    highs = [
        max(row["high"] for row in rows[start:end])
        for start, end in ((-30, -20), (-20, -10), (-10, None))
    ]
    lows = [
        min(row["low"] for row in rows[start:end])
        for start, end in ((-30, -20), (-20, -10), (-10, None))
    ]
    if max(highs) / min(highs) <= 1.02 and lows[0] < lows[1] < lows[2]:
        patterns.append("ASCENDING_TRIANGLE_APPROX")
    left = max(row["high"] for row in rows[-60:-40])
    bottom = min(row["low"] for row in rows[-40:-15])
    right = max(row["high"] for row in rows[-15:-5])
    handle = min(row["low"] for row in rows[-5:])
    if (
        0.05 <= 1 - bottom / left <= 0.35
        and abs(right / left - 1) <= 0.03
        and handle / right >= 0.9
        and closes[-1] >= right * 0.97
    ):
        patterns.append("CUP_HANDLE_APPROX")
    return {
        "rule_version": VERSION,
        "sma20": sma20,
        "sma50": sma50,
        "rsi14": momentum,
        "macd": macd[-1],
        "macd_signal": ema(macd, 9)[-1],
        "atr14": atr,
        "bollinger_width_pct": width,
        "volume_ratio20": rows[-1]["volume"] / prior_volume if prior_volume else None,
        "return20_pct": 100 * (closes[-1] / closes[-21] - 1),
        "return60_pct": 100 * (closes[-1] / closes[-61] - 1),
        "patterns": patterns or ["NO_PATTERN"],
        "average_turnover_inr": statistics.mean(row["close"] * row["volume"] for row in rows[-20:]),
    }


def screen(
    series: dict,
    universe: dict,
    benchmark: str,
    as_of: dt.datetime,
    top: int = 10,
    minimum_percentile: float = 50,
    min_turnover: float = 20_000_000,
) -> dict:
    """Rank a declared universe against the same dated benchmark; never silently substitute it."""
    if as_of.tzinfo is None or type(top) is not int or not 1 <= top <= 50:
        raise ValueError("Require aware cutoff and 1–50 shortlisted symbols")
    if not 0 <= minimum_percentile <= 100 or not math.isfinite(min_turnover) or min_turnover <= 0:
        raise ValueError("Invalid percentile or turnover gate")
    published = evidence_time(universe["as_of"])
    if not universe.get("source") or not 0 <= (as_of - published).total_seconds() <= 30 * 86400:
        raise ValueError("Need a source-backed universe available within 30 days of cutoff")
    instruments = universe["instruments"]
    if not isinstance(instruments, list) or not 1 <= len(instruments) <= 5000:
        raise ValueError("Declare 1–5,000 equity instruments")
    reference = series.get(benchmark, [])
    if (
        len(reference) < 61
        or (as_of.date() - dt.date.fromisoformat(reference[-1]["date"])).days > 7
    ):
        raise ValueError("Missing or stale benchmark history; no benchmark fallback")
    benchmark_features = features(reference)
    candidates, blocked, seen = [], [], set()
    for item in instruments:
        symbol = item["symbol"]
        if symbol in seen:
            raise ValueError("Duplicate universe instrument")
        seen.add(symbol)
        try:
            if (
                item.get("active") is not True
                or item.get("segment") != "EQ"
                or not re.fullmatch(r"IN[A-Z0-9]{10}", item.get("isin", ""))
            ):
                raise ValueError("Need an active cash-equity instrument with verified ISIN")
            rows = series.get(symbol, [])
            if len(rows) < 61 or [r["date"] for r in rows[-61:]] != [
                r["date"] for r in reference[-61:]
            ]:
                raise ValueError("Stock/benchmark sessions are incomplete or misaligned")
            if len({r["price_basis"] for r in rows[-61:] + reference[-61:]}) != 1:
                raise ValueError("Stock/benchmark return bases do not match")
            current = features(rows)
            if current["average_turnover_inr"] < min_turnover:
                raise ValueError("Average traded-value proxy is below the liquidity gate")
            relative20 = current["return20_pct"] - benchmark_features["return20_pct"]
            relative60 = current["return60_pct"] - benchmark_features["return60_pct"]
            candidates.append(
                {
                    "symbol": symbol,
                    "sector": item.get("sector"),
                    "status": "WAIT_FOR_SETUP",
                    "features": current,
                    "last_session": rows[-1]["date"],
                    "rs20_pp": relative20,
                    "rs60_pp": relative60,
                    "rs_score": 0.4 * relative20 + 0.6 * relative60,
                    "source": rows[-1]["source"],
                }
            )
        except (ValueError, KeyError, TypeError) as exc:
            blocked.append({"symbol": symbol, "reason": str(exc)})
    for candidate in candidates:
        candidate["rs_percentile"] = (
            100 * sum(c["rs_score"] <= candidate["rs_score"] for c in candidates) / len(candidates)
        )
        candidate["composite_score"] = 0.8 * candidate["rs_percentile"] + min(
            20, 5 * len([p for p in candidate["features"]["patterns"] if p != "NO_PATTERN"])
        )
    selected = [c for c in candidates if c["rs_percentile"] >= minimum_percentile]
    selected.sort(key=lambda c: (-c["composite_score"], -c["rs_score"], c["symbol"]))
    return {
        "mode": "research_only",
        "as_of": as_of.isoformat(),
        "benchmark": benchmark,
        "rule_version": VERSION,
        "universe_source": universe["source"],
        "eligible_count": len(candidates),
        "candidates": [{"rank": i + 1, **c} for i, c in enumerate(selected[:top])],
        "blocked": blocked,
        "notice": "Heuristic daily research, not an intraday entry or forecast. No model calls or orders.",
    }


def import_nifty500(text: str, as_of: dt.datetime, source: str) -> dict:
    """Convert an explicit membership snapshot, retaining its sector and source."""
    import io

    instruments = []
    for row in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        if row.get("Series") != "EQ":
            continue
        symbol, isin = row["Symbol"], row["ISIN Code"]
        if not re.fullmatch(r"[A-Z0-9&.\-]+", symbol) or not re.fullmatch(r"IN[A-Z0-9]{10}", isin):
            raise ValueError("Invalid Nifty membership identifier")
        instruments.append(
            {
                "symbol": "NSE:" + symbol,
                "isin": isin,
                "segment": "EQ",
                "active": True,
                "sector": row.get("Industry"),
            }
        )
    if (
        as_of.tzinfo is None
        or not source.strip()
        or not 1 <= len(instruments) <= 1000
        or len({r["symbol"] for r in instruments}) != len(instruments)
    ):
        raise ValueError("Invalid membership snapshot")
    return {
        "as_of": as_of.isoformat(),
        "source": source,
        "instruments": instruments,
        "notice": "Current membership snapshot; not a historical point-in-time universe or broker mapping",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("screen")
    scan.add_argument("--daily-bars", type=Path, required=True)
    scan.add_argument("--universe", type=Path, required=True)
    scan.add_argument("--benchmark", default="NSE:NIFTY50")
    scan.add_argument("--as-of", required=True)
    scan.add_argument("--top", type=int, default=10)
    scan.add_argument("--minimum-percentile", type=float, default=50)
    member = sub.add_parser("universe")
    member.add_argument("--csv", type=Path)
    member.add_argument("--download", action="store_true")
    member.add_argument("--source")
    member.add_argument("--as-of", required=True)
    member.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        cutoff = evidence_time(args.as_of)
        if args.command == "screen":
            result = screen(
                load_daily(args.daily_bars, cutoff),
                json.loads(args.universe.read_text()),
                args.benchmark,
                cutoff,
                args.top,
                args.minimum_percentile,
            )
        else:
            if bool(args.csv) == args.download:
                raise ValueError("Choose exactly one membership CSV or explicit download")
            if args.download:
                with urllib.request.build_opener(NoRedirect).open(
                    NIFTY500_URL, timeout=15
                ) as response:
                    raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("Membership export exceeds size limit")
                text, source = raw.decode("utf-8-sig"), NIFTY500_URL
            else:
                text, source = args.csv.read_text(), args.source or ""
            result = import_nifty500(text, cutoff, source)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, UnicodeError):
        print("DATA_BLOCK: verify sourced daily history, benchmark, membership and cutoff")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

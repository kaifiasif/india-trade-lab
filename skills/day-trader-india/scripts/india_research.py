#!/usr/bin/env python3
"""Indian market research from timestamped local data. No broker/order/network code.

Scanner = completed-bar observations. Replay = hypothetical historical fills.
Requires an explicit date-by-date session manifest; unknown dates are blocked.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
BAR = dt.timedelta(minutes=5)


def stamp(s: str | dt.datetime) -> dt.datetime:
    """Require timezone-aware evidence and normalize it to IST."""
    t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("All timestamps must have an explicit timezone")
    return t.astimezone(IST)


def finite(value: str | float | int, positive: bool = False) -> float:
    """Reject missing, nonfinite and out-of-domain numeric inputs."""
    n = float(value)
    if not math.isfinite(n) or n < 0 or (positive and n <= 0):
        raise ValueError("Invalid or missing nonnegative numeric input")
    return n


def validate_bar(row: dict[str, Any]) -> dict[str, Any]:
    """Validate source, timestamp and OHLCV relationships for one candle."""
    if not re.fullmatch(r"(NSE|BSE):[A-Z0-9&.\-]+", str(row["symbol"])):
        raise ValueError("Invalid exchange-qualified symbol")
    t = stamp(row["timestamp"])
    opening, high, low, close = (finite(row[k], True) for k in ("open", "high", "low", "close"))
    volume = finite(row["volume"])
    if (
        low > min(opening, close)
        or high < max(opening, close)
        or high < low
        or not str(row["source"]).strip()
    ):
        raise ValueError("Invalid OHLC or missing source")
    return {
        "symbol": row["symbol"],
        "t": t,
        "open": opening,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "source": row["source"],
    }


def bars_from_csv(path: str | Path) -> list[dict[str, Any]]:
    """Read a nonempty UTF-8 candle series and reject duplicate observations."""
    with open(path, newline="", encoding="utf-8") as f:
        bars = [validate_bar(r) for r in csv.DictReader(f)]
    if not bars:
        raise ValueError("No bars in input")
    keys = [(r["symbol"], r["t"]) for r in bars]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate symbol/timestamp bars")
    return sorted(bars, key=lambda r: (r["symbol"], r["t"]))


def session(manifest: dict[str, Any], date: dt.date) -> dict[str, dt.datetime]:
    """Resolve one explicit exchange session and validate its five-minute grid."""
    if manifest.get("timezone") != "Asia/Kolkata" or not manifest.get("source"):
        raise ValueError("Session manifest needs Asia/Kolkata and a source")
    s = manifest.get("sessions", {}).get(str(date))
    if not s:
        raise ValueError("Unknown/closed session; no weekday-based fallback")
    times = {
        k: stamp(f"{date}T{s[k]}:00+05:30") for k in ("open", "close", "entry_cutoff", "flat_by")
    }
    if not times["open"] + 4 * BAR <= times["entry_cutoff"] < times["flat_by"] < times["close"]:
        raise ValueError("Invalid session/entry/flatten boundaries")
    if any((v - times["open"]).total_seconds() % 300 for v in times.values()):
        raise ValueError("Session boundaries must lie on the five-minute grid")
    return times


def checked_session(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    date: dt.date,
    as_of: dt.datetime,
    full: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, dt.datetime]]:
    """Require every completed candle from session open to the evidence cutoff."""
    times = session(manifest, date)
    selected = [
        r for r in rows if r["t"].date() == date and times["open"] <= r["t"] < times["close"]
    ]
    completed = [r for r in selected if r["t"] + BAR <= as_of]
    end = times["close"] if full else min(as_of, times["close"])
    expected, t = [], times["open"]
    while t + BAR <= end:
        expected.append(t)
        t += BAR
    if full and as_of < times["close"]:
        raise ValueError("Historical replay cannot use an unfinished session")
    if [r["t"] for r in completed] != expected:
        raise ValueError("Missing, irregular or incomplete five-minute bars")
    if len(completed) < 4:
        raise ValueError("Need opening range plus a completed confirmation bar")
    return completed, times


def first_signal(
    rows: list[dict[str, Any]],
    times: dict[str, dt.datetime],
) -> dict[str, Any] | None:
    """Find the first completed-bar long breakout before the entry cutoff."""
    high, low = max(r["high"] for r in rows[:3]), min(r["low"] for r in rows[:3])
    if high <= low:
        return None
    for i in range(3, len(rows)):
        r = rows[i]
        if r["t"] + BAR > times["entry_cutoff"]:
            break
        if r["close"] > high:
            return {
                "index": i,
                "range_high": high,
                "range_low": low,
                "confirmed_at": (r["t"] + BAR).isoformat(),
                "signal_close": r["close"],
            }
    return None


def scan(
    bars: list[dict[str, Any]],
    manifest: dict[str, Any],
    as_of: str,
) -> dict[str, Any]:
    """Return rule observations or a per-symbol data block, never executable orders."""
    clock = stamp(as_of)
    results = []
    for symbol in sorted({r["symbol"] for r in bars}):
        try:
            rows, times = checked_session(
                [r for r in bars if r["symbol"] == symbol], manifest, clock.date(), clock
            )
            signal = first_signal(rows, times)
            expired = clock > times["entry_cutoff"]
            results.append(
                {
                    "symbol": symbol,
                    "status": "EXPIRED" if expired else ("MATCH" if signal else "NO_MATCH"),
                    "signal": signal,
                    "last_completed_at": (rows[-1]["t"] + BAR).isoformat(),
                    "latest_completed_close": rows[-1]["close"],
                    "source": rows[-1]["source"],
                }
            )
        except ValueError as e:
            results.append({"symbol": symbol, "status": "DATA_BLOCK", "reason": str(e)})
    return {
        "mode": "research_only",
        "as_of": clock.isoformat(),
        "currency": "INR",
        "results": results,
        "notice": "An observed rule match is not an entry ticket. Recheck a current quote, event, liquidity and risk gates.",
    }


def replay(
    bars: list[dict[str, Any]],
    manifest: dict[str, Any],
    symbol: str,
    as_of: str,
    cfg: dict[str, float],
) -> dict[str, Any]:
    """One symbol, one long ORB per session; independent account, no pooled returns."""
    clock = stamp(as_of)
    rows = [r for r in bars if r["symbol"] == symbol]
    if not rows:
        raise ValueError("Requested symbol has no bars")
    cash = finite(cfg["cash"], True)
    initial = peak = cash
    risk = finite(cfg["risk"], True)
    cap = finite(cfg["position_cap"], True)
    daily = finite(cfg["daily_loss"], True)
    target_r = finite(cfg["target_r"], True)
    slip = finite(cfg["slippage_bps"]) / 10000
    rate = finite(cfg["fee_bps"]) / 10000
    flat = finite(cfg["fee_flat"])
    drawdown_stop = finite(cfg["drawdown_stop"], True)
    if (
        slip >= 0.1
        or rate >= 0.1
        or risk > daily
        or daily > initial
        or cap > initial
        or drawdown_stop > initial
    ):
        raise ValueError("Invalid paper risk/cost limits")
    trades, rejected = [], []
    max_dd = 0
    date_min, date_max = min(r["t"].date() for r in rows), max(r["t"].date() for r in rows)
    # Include declared sessions with no bars, so a completely missing day is reported.
    dates = sorted(
        {r["t"].date() for r in rows}
        | {
            dt.date.fromisoformat(d)
            for d in manifest.get("sessions", {})
            if date_min <= dt.date.fromisoformat(d) <= date_max
        }
    )
    for date in dates:
        if max_dd >= drawdown_stop:
            rejected.append({"date": str(date), "reason": "Closed-trade drawdown stop reached"})
            continue
        try:
            day, times = checked_session(rows, manifest, date, clock, full=True)
        except ValueError as e:
            rejected.append({"date": str(date), "reason": str(e)})
            continue
        signal = first_signal(day, times)
        if not signal:
            rejected.append({"date": str(date), "reason": "No completed-bar ORB signal"})
            continue
        i = signal["index"] + 1
        if i >= len(day) or day[i]["t"] >= times["flat_by"]:
            rejected.append({"date": str(date), "reason": "No next bar before time exit"})
            continue
        stop = signal["range_low"]
        intended = signal["signal_close"] * (1 + slip)
        expected_stop = stop * (1 - slip)
        per_share_risk = intended - expected_stop + rate * (intended + expected_stop)
        if per_share_risk <= 0 or risk <= 2 * flat:
            rejected.append({"date": str(date), "reason": "No risk capacity after costs"})
            continue
        qty = math.floor(
            min(
                (min(risk, daily) - 2 * flat) / per_share_risk,
                (min(cap, cash) - flat) / (intended * (1 + rate)),
            )
        )
        if qty <= 0:
            rejected.append({"date": str(date), "reason": "Budget/risk permits zero whole shares"})
            continue
        entry_bar = day[i]
        entry = entry_bar["open"] * (1 + slip)
        entry_fee = flat + entry * qty * rate
        if entry * qty + entry_fee > min(cash, cap):
            rejected.append(
                {"date": str(date), "reason": "Next-open gap exceeds cash/position capacity"}
            )
            continue
        # The prior-bar signal fixed both stop and target before any future bars.
        target = signal["signal_close"] + target_r * (signal["signal_close"] - stop)
        if not stop < entry < target:
            rejected.append(
                {
                    "date": str(date),
                    "reason": "Next-open quote outside predeclared stop/target entry band",
                }
            )
            continue
        actual_risk = (entry - expected_stop) * qty + entry_fee + flat + expected_stop * qty * rate
        # Do not delete adverse gaps from a supposedly safe backtest: flag risk overshoot.
        exit_price, why, exit_time = None, None, None
        for bar in day[i:]:
            if bar["t"] >= times["flat_by"]:
                exit_price, why, exit_time = bar["open"] * (1 - slip), "time_exit", bar["t"]
                break
            if bar["open"] <= stop:
                exit_price, why = bar["open"] * (1 - slip), "gap_stop"
            elif bar["open"] >= target:
                exit_price, why = target, "target_limit_assumption"
            elif bar["low"] <= stop:
                exit_price, why = stop * (1 - slip), "stop_first_if_ambiguous"
            elif bar["high"] >= target:
                exit_price, why = target, "target_limit_assumption"
            if exit_price is not None:
                exit_time = bar["t"] + BAR
                break
        if exit_price is None:
            raise ValueError("Missing flatten bar; session cannot be evaluated")
        exit_fee = flat + exit_price * qty * rate
        pnl = (exit_price - entry) * qty - entry_fee - exit_fee
        cash += pnl
        peak = max(peak, cash)
        max_dd = max(max_dd, peak - cash)
        trades.append(
            {
                "date": str(date),
                "symbol": symbol,
                "confirmed_at": signal["confirmed_at"],
                "entry_at": entry_bar["t"].isoformat(),
                "exit_at": exit_time.isoformat(),
                "qty": qty,
                "entry": round(entry, 4),
                "stop": stop,
                "target": target,
                "exit": round(exit_price, 4),
                "reason": why,
                "estimated_charges": round(entry_fee + exit_fee, 2),
                "net_pnl_inr": round(pnl, 2),
                "planned_risk_overshot_by_gap": actual_risk > risk + 1e-8,
                "source": entry_bar["source"],
            }
        )
        if cash <= 0:
            break
    wins = sum(t["net_pnl_inr"] for t in trades if t["net_pnl_inr"] > 0)
    losses = -sum(t["net_pnl_inr"] for t in trades if t["net_pnl_inr"] < 0)
    return {
        "mode": "historical_replay",
        "symbol": symbol,
        "currency": "INR",
        "assumptions": cfg,
        "trades": trades,
        "rejected_sessions": rejected,
        "summary": {
            "trades": len(trades),
            "ending_virtual_cash": round(cash, 2),
            "net_pnl_inr": round(cash - initial, 2),
            "win_rate_pct": round(100 * sum(t["net_pnl_inr"] > 0 for t in trades) / len(trades), 2)
            if trades
            else None,
            "expectancy_inr": round((cash - initial) / len(trades), 2) if trades else None,
            "profit_factor": round(wins / losses, 4) if losses else None,
            "closed_trade_drawdown_inr": round(max_dd, 2),
        },
        "limitations": [
            "No exchange matching, tick-size/instrument-master, spread, volume or partial-fill model.",
            "Fees are explicit aggregate assumptions, not a statutory charge calculator.",
            "Signal from completed bar; hypothetical entry at next open inside preset entry band.",
            "Intrabar double touches count as stop first; stop gaps fill worse.",
            "A touched target is an assumed limit fill, not assured executable liquidity.",
            "Drawdown uses closed trades only; intratrade equity can fall further.",
            "No automated event/surveillance checks or evidence of future profitability.",
        ],
    }


OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


def screen(
    records: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    as_of: str,
    max_age_days: int = 200,
) -> dict[str, Any]:
    """Evaluate explicit numeric rules using only available point-in-time metrics."""
    clock = stamp(as_of)
    age = finite(max_age_days, True)
    if (
        not isinstance(rules, list)
        or not rules
        or any(
            not isinstance(r, dict)
            or r.get("op") not in OPS
            or "metric" not in r
            or "value" not in r
            for r in rules
        )
    ):
        raise ValueError("Need explicit numeric rules using >=, <=, >, < or ==")
    results = []
    seen = set()
    for row in records:
        symbol = row.get("symbol", "")
        if symbol in seen:
            raise ValueError("Duplicate metric symbol; supply one point-in-time row per company")
        seen.add(symbol)
        reasons = []
        try:
            if not re.fullmatch(r"(NSE|BSE):[A-Z0-9&.\-]+", symbol) or not row.get("source"):
                raise ValueError("Missing symbol/source")
            filed = stamp(row["published_at"])
            period = dt.date.fromisoformat(row["period_end"])
            if filed > clock or period > filed.date() or (clock.date() - period).days > age:
                raise ValueError("Future/unavailable or stale reported data")
            for rule in rules:
                metric, threshold = rule["metric"], float(rule["value"])
                if not math.isfinite(threshold):
                    raise ValueError("Nonfinite rule threshold")
                # Negative financial metrics are legitimate; missing/nonfinite are not.
                value = float(row[metric])
                if not math.isfinite(value):
                    raise ValueError("Missing/nonfinite metric: " + metric)
                if not OPS[rule["op"]](value, threshold):
                    reasons.append(f"{metric}={value:g}, needs {rule['op']} {threshold:g}")
        except (ValueError, KeyError, TypeError) as e:
            reasons.append("DATA_BLOCK: " + str(e))
        results.append(
            {
                "symbol": symbol,
                "status": "FAIL" if reasons else "PASS",
                "reasons": reasons,
                "source": row.get("source"),
                "period_end": row.get("period_end"),
                "published_at": row.get("published_at"),
            }
        )
    return {
        "mode": "research_only",
        "as_of": clock.isoformat(),
        "results": results,
        "notice": "Passing user-defined filters does not establish fair value, an edge or suitability.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("scan-orb", "replay-orb"):
        command_parser = sub.add_parser(name)
        command_parser.add_argument("--bars", required=True)
        command_parser.add_argument("--sessions", required=True)
        command_parser.add_argument("--as-of", required=True)
        if name == "replay-orb":
            command_parser.add_argument("--symbol", required=True)
            for field in (
                "cash",
                "risk",
                "daily-loss",
                "position-cap",
                "target-r",
                "fee-bps",
                "fee-flat",
                "slippage-bps",
                "drawdown-stop",
            ):
                command_parser.add_argument("--" + field, required=True, type=float)
    command_parser = sub.add_parser("screen")
    command_parser.add_argument("--metrics", required=True)
    command_parser.add_argument("--rules", required=True)
    command_parser.add_argument("--as-of", required=True)
    command_parser.add_argument("--max-age-days", type=int, default=200)
    args = parser.parse_args()
    try:
        if args.command == "screen":
            with open(args.metrics, newline="", encoding="utf-8") as handle:
                metrics = list(csv.DictReader(handle))
            result = screen(
                metrics,
                json.loads(Path(args.rules).read_text(encoding="utf-8")),
                args.as_of,
                args.max_age_days,
            )
        else:
            bars, manifest = (
                bars_from_csv(args.bars),
                json.loads(Path(args.sessions).read_text(encoding="utf-8")),
            )
            if args.command == "scan-orb":
                result = scan(bars, manifest, args.as_of)
            else:
                cfg = {
                    k: getattr(args, k)
                    for k in (
                        "cash",
                        "risk",
                        "daily_loss",
                        "position_cap",
                        "target_r",
                        "fee_bps",
                        "fee_flat",
                        "slippage_bps",
                        "drawdown_stop",
                    )
                }
                baseline = replay(bars, manifest, args.symbol, args.as_of, cfg)
                stressed = dict(
                    cfg,
                    fee_bps=cfg["fee_bps"] * 2,
                    fee_flat=cfg["fee_flat"] * 2,
                    slippage_bps=cfg["slippage_bps"] * 2,
                )
                result = {
                    "baseline": baseline,
                    "double_cost_stress": replay(bars, manifest, args.symbol, args.as_of, stressed),
                    "notice": "Hypothetical historical results, not forward paper trading or a forecast.",
                }
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, OverflowError, ZeroDivisionError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

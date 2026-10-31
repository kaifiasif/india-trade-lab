#!/usr/bin/env python3
"""Intraday long strategies, loss-avoidance filters and managed exits, as pure rules.

Every function here reads completed five-minute bars and returns a decision with
its reason. The same code drives the live coordinator, the pre-trade evidence and
the strategy tournament, so a backtested rule and a forward rule are identical.

Strategies (long only, cash equity):

- ``orb-v1``: a completed bar closes above the first 15 minutes' high. Stop at the
  opening-range low.
- ``vwap-pullback-v1``: on a day that has already broken out above the opening
  range, price pulls back to the session VWAP and a completed bar closes back
  above it, higher than the bar before. Stop just below the pullback low.

Filters (applied to every entry): the daily trend is not down, RSI(14) is below
75, and the stop is neither a hair's breadth away (noise) nor wider than one daily
ATR (too much to lose for the size).

Managed exits, from the bars since entry: the stop moves to breakeven plus costs
once price has reached +1R, then trails one R below the highest high after +1.5R.
A trade that has not reached +0.5R within an hour is closed (time stop). The
original stop, target and the session square-off still apply.

None of this predicts prices. It only decides when a setup is present, how much
can be lost if it fails, and when to leave.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

BAR = dt.timedelta(minutes=5)
ORB = "orb-v1"
VWAP = "vwap-pullback-v1"
STRATEGIES = (ORB, VWAP)
DESCRIPTIONS = {
    ORB: "close above the 15-minute opening-range high; stop at the opening-range low",
    VWAP: "after an opening-range breakout, a pullback to session VWAP that closes back "
    "above it; stop below the pullback low",
}
MIN_STOP_PCT = 0.15
RSI_CEILING = 75.0
BREAKEVEN_R = 1.0
TRAIL_START_R = 1.5
TIME_STOP_BARS = 12
TIME_STOP_PROGRESS_R = 0.5


def _orb(rows: list[dict], times: dict) -> dict | None:
    if len(rows) < 4:
        return None
    high = max(row["high"] for row in rows[:3])
    low = min(row["low"] for row in rows[:3])
    last = rows[-1]
    if high <= low or last["close"] <= high:
        return None
    # Only the first close above the range is a fresh breakout.
    if any(row["close"] > high for row in rows[3:-1]):
        return None
    return {
        "strategy": ORB,
        "stop": low,
        "range_high": high,
        "range_low": low,
        "reason": f"close {last['close']} above the opening-range high {high}",
    }


def session_vwap(rows: list[dict]) -> float | None:
    volume = sum(row["volume"] for row in rows)
    if volume <= 0:
        return None
    return sum((row["high"] + row["low"] + row["close"]) / 3 * row["volume"] for row in rows) / (
        volume
    )


def _vwap_pullback(rows: list[dict], times: dict) -> dict | None:
    if len(rows) < 7:
        return None
    high = max(row["high"] for row in rows[:3])
    if not any(row["close"] > high for row in rows[3:-2]):
        return None  # Not a trend day yet.
    vwap = session_vwap(rows)
    last, prior = rows[-1], rows[-2]
    if vwap is None:
        return None
    touched = min(last["low"], prior["low"]) <= vwap * 1.001
    if not (touched and last["close"] > vwap and last["close"] > prior["close"]):
        return None
    if last["close"] <= last["open"]:
        return None
    stop = round(min(last["low"], prior["low"]) * 0.999, 2)
    return {
        "strategy": VWAP,
        "stop": stop,
        "vwap": round(vwap, 2),
        "reason": f"pullback to session VWAP {vwap:.2f} closed back above at {last['close']}",
    }


RULES = {ORB: _orb, VWAP: _vwap_pullback}


def regime_block(context: dict | None, entry: float, stop: float) -> str | None:
    """Why an otherwise valid entry should be skipped, or None. Missing context skips a check."""
    if not stop < entry:
        return "stop is not below the entry"
    distance_pct = 100 * (entry - stop) / entry
    if distance_pct < MIN_STOP_PCT:
        return f"stop only {distance_pct:.2f}% away; noise would hit it"
    values = (context or {}).get("values") or {}
    atr = values.get("atr14")
    if atr and entry - stop > atr:
        return "stop is wider than one daily ATR; the size would be too small to matter"
    rsi = values.get("rsi14")
    if rsi is not None and rsi >= RSI_CEILING:
        return f"daily RSI {rsi} is stretched; late to chase"
    close, sma20, sma50 = values.get("close"), values.get("sma20"), values.get("sma50")
    if close is not None and sma20 is not None and sma50 is not None:
        if close < sma20 and sma20 < sma50:
            return "daily trend is down (close below the 20-day, below the 50-day average)"
    return None


def latest_signal(
    rows: list[dict],
    times: dict,
    allowed: list[str] | tuple[str, ...],
    context: dict | None = None,
) -> dict | None:
    """The first allowed strategy that fires on the latest completed bar, after filters.

    ``rows`` are the session's completed bars from the open, in order. A signal is
    only valid if that bar ended at or before the entry cutoff.
    """
    if not rows or rows[-1]["t"] + BAR > times["entry_cutoff"]:
        return None
    blocked = []
    for name in allowed:
        rule = RULES.get(name)
        signal = rule(rows, times) if rule else None
        if not signal:
            continue
        entry = rows[-1]["close"]
        reason = regime_block(context, entry, signal["stop"])
        if reason:
            blocked.append(f"{name}: {reason}")
            continue
        return {
            **signal,
            "version": name,
            "signal_close": entry,
            "confirmed_at": (rows[-1]["t"] + BAR).isoformat(),
            "filters_passed": True,
        }
    if blocked:
        return {"blocked": blocked}
    return None


def managed_stop(
    entry: float,
    initial_stop: float,
    cost_per_share: float,
    since_entry: list[dict],
) -> dict[str, Any]:
    """Current protective stop from the bars completed since entry, and why."""
    risk = entry - initial_stop
    if risk <= 0:
        return {"stop": initial_stop, "rule": "initial", "time_stop": False}
    peak = max((row["high"] for row in since_entry), default=entry)
    gained = (peak - entry) / risk
    stop, rule = initial_stop, "initial"
    if gained >= BREAKEVEN_R:
        stop, rule = max(stop, entry + cost_per_share), "breakeven"
    if gained >= TRAIL_START_R:
        trailed = peak - risk
        if trailed > stop:
            stop, rule = trailed, "trailing"
    time_stop = len(since_entry) >= TIME_STOP_BARS and gained < TIME_STOP_PROGRESS_R
    return {
        "stop": round(stop, 2),
        "rule": rule,
        "peak": peak,
        "gained_r": round(gained, 2),
        "time_stop": time_stop,
    }


def scorecard_path(root: Path) -> Path:
    return root / "strategy-scorecard.json"


def allowed_for(
    root: Path,
    settings: dict,
    symbol: str,
    session_date: str,
    reports_dir: Path | None = None,
) -> dict[str, Any]:
    """Strategies this symbol may trade today, and why: proven ones, narrowed by the judge."""
    if not settings.get("require_proven", True):
        proven = list(settings.get("enabled") or STRATEGIES)
        basis = "require_proven is off; every enabled strategy may trade (paper research)"
    else:
        try:
            card = json.loads(scorecard_path(root).read_text(encoding="utf-8"))
            built = dt.date.fromisoformat(card["as_of"][:10])
            age = (dt.date.fromisoformat(session_date) - built).days
        except (OSError, ValueError, KeyError, TypeError):
            return {"allowed": [], "basis": "no strategy scorecard; run tournament.py first"}
        if age > int(settings.get("max_scorecard_age_days", 7)):
            return {"allowed": [], "basis": f"strategy scorecard is {age} days old; rerun it"}
        proven = [
            name
            for name, result in card.get("strategies", {}).items()
            if result.get("eligible") and name in (settings.get("enabled") or STRATEGIES)
        ]
        basis = "proven in the tournament after doubled costs"
        if not proven:
            return {
                "allowed": [],
                "basis": "no strategy proved an edge after doubled costs; the desk sits out",
            }
        import regime

        proven, notes = regime.filter_allowed(root, card, proven, session_date)
        if notes:
            basis += "; " + "; ".join(notes)
        if not proven:
            return {"allowed": [], "basis": basis + "; the desk sits out in this regime"}
    if reports_dir is not None:
        try:
            report = json.loads(
                (reports_dir / f"premarket-{session_date}.json").read_text(encoding="utf-8")
            )
            picks = ((report.get("selection") or {}).get("judge") or {}).get("picks") or []
            chosen = next(
                (pick.get("strategy") for pick in picks if pick["symbol"] == symbol), None
            )
            if chosen in proven:
                return {"allowed": [chosen], "basis": f"{basis}; the judge chose {chosen}"}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return {"allowed": proven, "basis": basis}

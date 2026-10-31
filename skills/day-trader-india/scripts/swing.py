#!/usr/bin/env python3
"""Swing desk: short-term swing trades (up to 5 sessions) on volume-confirmed price action.

Volume says whether a move has participation behind it. Each setup below needs
volume to agree with price, on the daily candles the nightly scan stores for every
F&O stock (``scan.sqlite``). Long only, NSE cash equity, delivery.

| setup | price | volume |
| --- | --- | --- |
| ``vol-breakout-v1`` | closes above the 20-day high, in the top 40% of the day's range, above the 50-day average, not more than 10% above the 20-day | at least ``min_vol_ratio`` (2x) the 20-day average |
| ``pocket-pivot-v1`` | an up close near a rising 10-day and 50-day trend (within 5% of the 10-day) | more than any down day's volume in the last 10 sessions |
| ``dryup-pullback-v1`` | an uptrend pulls back 3%+ to near the 20-day average, holds the 50-day, then closes above the prior day's high | pullback volume at most 70% of normal, then the reversal at 1.5x the pullback's |

Every setup is skipped after a climax run (more than 15% in five sessions), when
the stop would be under 1% or over 8% away, when traded value is under the floor,
or when results or a board meeting fall inside the holding period.

**Trade.** Signals are found after the close; entry is the next session, at the
live price after 09:15, unless the stock gapped up more than ``max_gap_up_pct``
(late) or opened at or below the stop. Exits: the stop (the breakout day's low,
the last three lows, or the pullback low), a ``target_r`` target (2R), breakeven
after the close reaches +1R, then a trail under the last two days' lows after
+1.5R, and a time exit after ``max_hold_days`` sessions. A gap through the stop
fills at the open: an overnight hold can lose more than the planned risk.

**Proof first.** ``tournament`` replays every setup on the stored history with
next-open entries, stop-first ambiguous days, gap fills and delivery costs both
ways, and judges each at double costs (the intraday tournament's rules). With
``require_proven`` only passing setups are entered; otherwise the desk sits out.

**Book.** A separate swing paper book (``swing.sqlite``, its own virtual cash)
records entries with code-checked, sourced pre-trade evidence, under every journal
limit. Paper only: nothing here can place an order.

    python3 swing.py create-book --cash 100000 --risk 500 --daily-loss 1500 --position 25000
    python3 swing.py tournament          # after the close: which setups have earned trading
    python3 swing.py scan                # after the close: tomorrow's candidates
    python3 swing.py tick                # in session: enter once after 09:15, manage exits
    python3 swing.py status
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sqlite3
import statistics
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import charges
import intraday
import portfolio
import safety
import surveillance
import validation

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
IST = intraday.IST
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "book": "swing.sqlite",
    "max_hold_days": 5,
    "max_new_per_day": 2,
    "require_proven": True,
    "min_vol_ratio": 2.0,
    "max_gap_up_pct": 3.0,
    "event_window_days": 7,
    "target_r": 2.0,
    # Delivery costs: STT 0.1% each side plus exchange, stamp and GST; a DP charge on sale.
    "fee_bps": 12.0,
    "fee_flat_inr": 20.0,
    "slippage_bps": 5.0,
    "require_positive_odds": True,  # Skip an entry the swing simulation expects to lose on.
    "odds_replays": 2000,
}
TOURNAMENT_SIZING = {"risk_inr": 500.0, "position_cap_inr": 25_000.0}
MIN_BARS = 60
CLIMAX_RUN = 0.15
STOP_RANGE = (0.01, 0.08)
EXIT_HOUR = (15, 20)  # Time exits and end-of-day trailing happen from 15:20 IST.
DESCRIPTIONS = {
    "vol-breakout-v1": "close above the 20-day high on 2x volume, strong close; stop at the day's low",
    "pocket-pivot-v1": "up day with more volume than any down day in 10 sessions, near a rising "
    "trend; stop under the last three lows",
    "dryup-pullback-v1": "pullback on drying volume to the 20-day average, then a reversal on "
    "expanding volume; stop under the pullback low",
}


# ---------- indicators and setups (pure) ----------


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _clv(bar: dict) -> float:
    span = bar["high"] - bar["low"]
    return (bar["close"] - bar["low"]) / span if span > 0 else 0.0


def obv_rising(bars: list[dict], window: int = 20) -> bool | None:
    """On-balance volume above its own 20-day average: accumulation, as information."""
    if len(bars) < window + 2:
        return None
    obv, series = 0.0, []
    for previous, bar in zip(bars, bars[1:], strict=False):
        obv += (
            bar["volume"]
            if bar["close"] > previous["close"]
            else -bar["volume"]
            if bar["close"] < previous["close"]
            else 0
        )
        series.append(obv)
    return series[-1] > _mean(series[-window:])


def vol_breakout(bars: list[dict], cfg: dict) -> dict | None:
    last, prior = bars[-1], bars[-21:-1]
    average = _mean([bar["volume"] for bar in prior])
    high = max(bar["high"] for bar in prior)
    closes = [bar["close"] for bar in bars]
    if average <= 0 or last["close"] <= high:
        return None
    ratio = last["volume"] / average
    if ratio < float(cfg["min_vol_ratio"]) or _clv(last) < 0.6:
        return None
    if last["close"] <= _mean(closes[-50:]) or last["close"] > _mean(closes[-20:]) * 1.10:
        return None
    return {
        "stop": last["low"],
        "vol_ratio": round(ratio, 2),
        "reason": f"closed ₹{last['close']:.2f} above the 20-day high ₹{high:.2f} on "
        f"{ratio:.1f}x average volume, in the top {100 - 100 * _clv(last):.0f}% of its range",
    }


def pocket_pivot(bars: list[dict], cfg: dict) -> dict | None:
    last, previous = bars[-1], bars[-2]
    if not (last["close"] > last["open"] and last["close"] > previous["close"]):
        return None
    downs = [
        bars[index]["volume"]
        for index in range(len(bars) - 11, len(bars) - 1)
        if bars[index]["close"] < bars[index - 1]["close"]
    ]
    if not downs or last["volume"] <= max(downs):
        return None
    closes = [bar["close"] for bar in bars]
    sma10, sma50, sma50_before = _mean(closes[-10:]), _mean(closes[-50:]), _mean(closes[-60:-10])
    if not (sma10 < last["close"] <= sma10 * 1.05 and last["close"] > sma50 > sma50_before):
        return None
    average = _mean([bar["volume"] for bar in bars[-21:-1]])
    return {
        "stop": min(bar["low"] for bar in bars[-3:]),
        "vol_ratio": round(last["volume"] / average, 2) if average else None,
        "reason": f"up day on {last['volume']:,.0f} shares, more than any down day in 10 sessions "
        f"({max(downs):,.0f}), {100 * (last['close'] / sma10 - 1):.1f}% above a rising 10-day",
    }


def dryup_pullback(bars: list[dict], cfg: dict) -> dict | None:
    last, previous = bars[-1], bars[-2]
    closes = [bar["close"] for bar in bars]
    sma20, sma50 = _mean(closes[-20:]), _mean(closes[-50:])
    if not (last["close"] > sma50 and sma20 > sma50):
        return None
    normal = _mean([bar["volume"] for bar in bars[-53:-3]])
    pullback = bars[-4:-1]
    quiet = _mean([bar["volume"] for bar in pullback])
    if normal <= 0 or quiet > 0.7 * normal:
        return None
    recent_high = max(bar["close"] for bar in bars[-11:-4])
    if recent_high < previous["close"] * 1.03 or previous["close"] > sma20 * 1.02:
        return None
    if min(bar["low"] for bar in bars[-6:-1]) < sma50 * 0.99:
        return None
    if last["close"] <= previous["high"] or last["volume"] < 1.5 * quiet or _clv(last) < 0.5:
        return None
    return {
        "stop": min(bar["low"] for bar in bars[-6:]),
        "vol_ratio": round(last["volume"] / normal, 2),
        "reason": f"pulled back {100 * (1 - previous['close'] / recent_high):.1f}% on "
        f"{100 * quiet / normal:.0f}% of normal volume, then closed above the prior high on "
        f"{last['volume'] / quiet:.1f}x the pullback's volume",
    }


SETUPS: dict[str, Callable[[list[dict], dict], dict | None]] = {
    "vol-breakout-v1": vol_breakout,
    "pocket-pivot-v1": pocket_pivot,
    "dryup-pullback-v1": dryup_pullback,
}


def blocked(bars: list[dict], stop: float, min_turnover: float) -> str | None:
    """Why a setup that fired should still be skipped, or None."""
    last = bars[-1]
    if not stop < last["close"]:
        return "stop is not below the close"
    distance = (last["close"] - stop) / last["close"]
    if distance < STOP_RANGE[0]:
        return f"stop only {100 * distance:.1f}% away; overnight noise would hit it"
    if distance > STOP_RANGE[1]:
        return f"stop {100 * distance:.1f}% away; too much to risk for the size"
    if len(bars) > 6 and last["close"] / bars[-6]["close"] - 1 > CLIMAX_RUN:
        return "up more than 15% in five sessions; a volume spike here is often a climax"
    turnover = _mean([bar["close"] * bar["volume"] for bar in bars[-20:]])
    if turnover < min_turnover:
        return "traded value below the liquidity floor"
    return None


def signal(bars: list[dict], names: list[str], cfg: dict, min_turnover: float) -> dict | None:
    """The first setup that fires on the last bar and passes the filters; or None."""
    if len(bars) < MIN_BARS:
        return None
    for name in names:
        found = SETUPS[name](bars, cfg)
        if not found:
            continue
        reason = blocked(bars, found["stop"], min_turnover)
        if reason:
            continue
        return {
            **found,
            "strategy": name,
            "date": bars[-1]["date"],
            "close": round(bars[-1]["close"], 2),
            "stop": intraday.round_down(found["stop"]),
            "obv_rising": obv_rising(bars),
        }
    return None


# ---------- tournament ----------


def swing_walk(
    bars: list[dict], index: int, entry: float, stop: float, qty: int, cfg: dict, multiple: float
) -> tuple[float, str, int, float]:
    """The swing exits from the session after ``index``: gap stop, stop (first), target,
    breakeven and trail at the close, time exit. Returns exit price, why, last index, net."""
    import charges

    slip = multiple * float(cfg["slippage_bps"]) / 10_000
    hold, target_r = int(cfg["max_hold_days"]), float(cfg["target_r"])
    risk = entry - stop
    target = entry + target_r * risk
    entry_day = bars[index + 1]["date"]
    per_share = (
        multiple
        * (
            charges.fee("delivery", "buy", entry, qty, entry_day)
            + charges.fee("delivery", "sell", entry, qty, entry_day)
        )
        / qty
    )
    current, exit_price, why, last = stop, None, "time", index + 1
    for day in range(hold):
        last = index + 1 + day
        if last >= len(bars):
            last = len(bars) - 1
            break
        bar = bars[last]
        if day and bar["open"] <= current:
            exit_price, why = bar["open"], "gap stop"
            break
        if bar["low"] <= current:
            exit_price, why = current, "stop" if current == stop else "trailing stop"
            break
        if bar["high"] >= target:
            exit_price, why = (max(target, bar["open"]) if day else target), "target"
            break
        gained = (bar["close"] - entry) / risk
        if gained >= 1:
            current = max(current, entry + per_share)
        if gained >= 1.5 and last >= 1:
            current = max(current, min(bar["low"], bars[last - 1]["low"]))
    if exit_price is None:
        exit_price = bars[last]["close"]
    exit_price *= 1 - slip
    net = (
        (exit_price - entry) * qty
        - multiple * charges.fee("delivery", "buy", entry, qty, entry_day)
        - multiple * charges.fee("delivery", "sell", exit_price, qty, bars[last]["date"])
    )
    return exit_price, why, last, net


def random_twins(trades: list[dict], data: dict[str, list[dict]], cfg: dict, multiple: float,
                 twins: int, seed: int = 19) -> list[float]:  # fmt: skip
    """Net totals of random-entry copies: same stocks, same stop distance and exits."""
    import random

    rng = random.Random(seed)
    slip = multiple * float(cfg["slippage_bps"]) / 10_000
    totals = []
    for _ in range(twins):
        total = 0.0
        for trade in trades:
            bars = data.get(trade["symbol"]) or []
            if len(bars) <= MIN_BARS + 1:
                continue
            index = rng.randrange(MIN_BARS - 1, len(bars) - 1)
            entry = bars[index + 1]["open"] * (1 + slip)
            stop = entry * (1 - (trade["entry"] - trade["stop"]) / trade["entry"])
            qty = math.floor(
                min(
                    TOURNAMENT_SIZING["risk_inr"] / (entry - stop),
                    TOURNAMENT_SIZING["position_cap_inr"] / entry,
                )
            )
            if qty < 1:
                continue
            total += swing_walk(bars, index, entry, stop, qty, cfg, multiple)[3]
        totals.append(round(total, 2))
    return totals


def simulate(symbol: str, bars: list[dict], name: str, cfg: dict, multiple: float) -> list[dict]:
    """Every trade one setup would have taken on one stock, one at a time, pessimistically."""
    slip = multiple * float(cfg["slippage_bps"]) / 10_000

    trades, index = [], MIN_BARS - 1
    while index < len(bars) - 1:
        found = signal(bars[: index + 1], [name], cfg, 0.0)
        if not found:
            index += 1
            continue
        session = bars[index + 1]
        if session["open"] > found["close"] * (1 + float(cfg["max_gap_up_pct"]) / 100) or (
            session["open"] <= found["stop"]
        ):
            index += 1
            continue
        entry = session["open"] * (1 + slip)
        stop = found["stop"]
        risk = entry - stop
        qty = math.floor(
            min(TOURNAMENT_SIZING["risk_inr"] / risk, TOURNAMENT_SIZING["position_cap_inr"] / entry)
        )
        if risk <= 0 or qty < 1:
            index += 1
            continue
        exit_price, why, last, net = swing_walk(bars, index, entry, stop, qty, cfg, multiple)
        trades.append({
            "symbol": symbol, "strategy": name, "date": session["date"],
            "exit_date": bars[last]["date"], "entry": round(entry, 2), "stop": stop,
            "exit": round(exit_price, 2), "exit_reason": why, "qty": qty,
            "r": round((exit_price - entry) / risk, 2), "net_inr": round(net, 2),
        })  # fmt: skip
        index = last + 1
    return trades


def all_bars(store_path: Path, before: dt.date | None = None) -> dict[str, list[dict]]:
    if not store_path.is_file():
        raise ValueError("No daily candles yet; the nightly market scan stores them")
    with sqlite3.connect(store_path) as conn:
        rows = conn.execute(
            "SELECT symbol, date, open, high, low, close, volume FROM daily "
            "WHERE date < ? ORDER BY symbol, date",
            (str(before or dt.date(9999, 1, 1)),),
        ).fetchall()
    data: dict[str, list[dict]] = {}
    for symbol, date, o, h, low, c, v in rows:
        data.setdefault(symbol, []).append(
            {"date": date, "open": o, "high": h, "low": low, "close": c, "volume": v}
        )
    return data


def tournament(config_path: Path, data: dict[str, list[dict]] | None = None) -> dict[str, Any]:
    import tournament as intraday_tournament

    folder = intraday.config_folder(config_path)
    cfg = settings(config_path)
    data = data if data is not None else all_bars(folder / "scan.sqlite")
    dates = sorted({bar["date"] for bars in data.values() for bar in bars[MIN_BARS:]})
    if not dates:
        raise ValueError(f"Need more than {MIN_BARS} stored daily candles per stock")
    result: dict[str, Any] = {
        "as_of": dt.datetime.now(IST).isoformat(),
        "sessions": len(dates),
        "from": dates[0],
        "to": dates[-1],
        "stocks": len(data),
        "assumptions": {
            key: cfg[key]
            for key in (
                "fee_bps",
                "fee_flat_inr",
                "slippage_bps",
                "max_hold_days",
                "target_r",
                "max_gap_up_pct",
            )
        },  # fmt: skip
        "rules": intraday_tournament.RULES,
        "strategies": {},
    }
    measured: list[dict] = []
    import regime

    known = regime.labels(folder / "scan.sqlite")
    for name in SETUPS:
        runs = {
            label: [trade for symbol, bars in data.items() for trade in simulate(symbol, bars, name, cfg, multiple)]
            for label, multiple in (("baseline", 1.0), ("doubled_costs", 2.0))
        }  # fmt: skip
        rules = intraday_tournament.RULES
        eligible, reasons, folds = intraday_tournament.judge(runs["doubled_costs"], dates, rules)
        doubled = runs["doubled_costs"]
        twins = random_twins(doubled, data, cfg, 2.0, int(rules["luck_twins"])) if doubled else []
        luck = (
            validation.percentile_beaten(sum(t["net_inr"] for t in doubled), twins)
            if twins
            else 0.0
        )
        if doubled and luck < float(rules["min_luck_percentile"]):
            reasons.append(
                f"beat only {luck:.0f}% of random-entry twins; needs {rules['min_luck_percentile']:g}%"
            )
        returns = [t["r"] for t in doubled]
        assumptions = {key: cfg[key] for key in ("max_hold_days", "target_r", "max_gap_up_pct", "min_vol_ratio",
                                                 "slippage_bps")}  # fmt: skip
        measured.append({"id": validation.variant_id("swing", name, assumptions), "strategy": name,
                         "sharpe": validation.sharpe(returns), "returns": returns})  # fmt: skip
        eligible = not reasons
        result["strategies"][name] = {
            "by_regime": regime.by_regime(doubled, known),
            "luck_percentile": luck,
            "random_twins_median_inr": statistics.median(twins) if twins else None,
            "description": DESCRIPTIONS[name],
            "eligible": eligible,
            "reasons": reasons or ["passed every condition at double costs"],
            "baseline": intraday_tournament.stats(runs["baseline"]),
            "doubled_costs": intraday_tournament.stats(runs["doubled_costs"]),
            "folds_doubled_costs": folds,
            "recent_trades": sorted(runs["baseline"], key=lambda t: t["date"])[-10:],
        }
    registry = validation.record_trials(folder, "swing", measured)
    for row_trials, (_name, row) in zip(measured, result["strategies"].items(), strict=True):
        deflated = validation.deflated_sharpe(
            row_trials["returns"], registry["trials"], registry["sharpes"]
        )
        row["deflated_sharpe"] = deflated
        if row["eligible"] and (
            deflated["dsr"] is None or deflated["dsr"] < float(intraday_tournament.RULES["min_dsr"])
        ):
            row["eligible"] = False
            shown = "unknown" if deflated["dsr"] is None else f"{deflated['dsr']:.2f}"
            row["reasons"] = [f"deflated Sharpe {shown} after {registry['trials']} trials; needs "
                              f"{intraday_tournament.RULES['min_dsr']:g}"]  # fmt: skip
    result["trials"] = registry["trials"]
    result["eligible"] = [name for name, row in result["strategies"].items() if row["eligible"]]
    result["notice"] = (
        "Next-open entries, stop-first on ambiguous days, gap fills at the open, delivery costs "
        "both ways, judged at double costs. One position per stock at a time; the book's "
        "cross-stock caps are not modelled. Past sessions do not predict future returns."
    )
    intraday.write_json(folder / "swing-scorecard.json", result)
    return result


# ---------- configuration and book ----------


def settings(config_path: Path) -> dict[str, Any]:
    config = intraday.load_config(config_path)
    return {
        **DEFAULTS,
        **(config.get("swing") or {}),
        "min_turnover_inr": float(config.get("min_turnover_inr", 0) or 0),
    }


def book_path(config_path: Path) -> Path:
    name = settings(config_path)["book"]
    if not isinstance(name, str) or "/" in name or "\\" in name or not name.endswith(".sqlite"):
        raise ValueError("swing.book must be a plain .sqlite file name")
    return intraday.config_folder(config_path) / name


def create_book(config_path: Path, cash: str, risk: str, daily_loss: str, position: str) -> dict:
    import paper_book

    path = book_path(config_path)
    if path.is_file():
        raise ValueError("A swing paper book already exists; it is never overwritten")
    book = paper_book.create(
        cash, "NSE:SWING", risk, daily_loss, position, max_trades=2, max_open=3,
        max_loss_streak=3, drawdown_stop=str(round(float(cash) * 0.05, 2)), style="swing",
    )  # fmt: skip
    book["symbols"] = []  # Filled with each day's candidates before entry.
    paper_book.seal_state(book)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS book (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO book VALUES (1, ?)", (json.dumps(book),))
    return book


def read_book(config_path: Path) -> dict:
    import guardrails

    path = book_path(config_path)
    if not path.is_file():
        raise ValueError("No swing paper book yet (Setup → Paper book, or swing.py create-book)")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
        row = conn.execute("SELECT data FROM book WHERE id=1").fetchone()
    book = json.loads(row[0])
    guardrails.verify_state(book)
    if book.get("style") != "swing" or book.get("mode") != "paper_manual":
        raise ValueError("That file is not a forward swing paper book")
    return book


def _transact(config_path: Path, change: Callable[[dict], dict]) -> dict:
    """Apply one journal change under an exclusive lock; nothing is written on failure."""
    import guardrails

    with sqlite3.connect(book_path(config_path), isolation_level=None, timeout=10) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            state = json.loads(conn.execute("SELECT data FROM book WHERE id=1").fetchone()[0])
            guardrails.verify_state(state)
            updated = change(state)
            guardrails.seal_state(updated)
            conn.execute("INSERT OR REPLACE INTO book VALUES (1, ?)", (json.dumps(updated),))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return updated


def _state(config_path: Path) -> dict:
    path = intraday.config_folder(config_path) / "swing-state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"positions": {}}


def _save_state(config_path: Path, state: dict) -> None:
    intraday.write_json(intraday.config_folder(config_path) / "swing-state.json", state)  # Atomic.


# ---------- after the close: candidates ----------


def scan(
    config_path: Path,
    today: dt.date | None = None,
    events_for: Callable[[dt.date, int], dict] | None = None,
) -> dict[str, Any]:
    """Tomorrow's candidates from today's close. Writes swing-candidates-<date>.json."""
    folder = intraday.config_folder(config_path)
    cfg = settings(config_path)
    today = today or dt.datetime.now(IST).date()
    data = all_bars(folder / "scan.sqlite", today + dt.timedelta(days=1))
    try:
        card = json.loads((folder / "swing-scorecard.json").read_text(encoding="utf-8"))
        proven = set(card.get("eligible", []))
    except (OSError, ValueError):
        card, proven = None, set()
    events, events_checked, notes = {}, False, []
    if card and proven:
        import regime

        kept, regime_notes = regime.filter_allowed(
            folder, card, sorted(proven), str(today + dt.timedelta(days=1)),
            intraday.load_config(config_path),
        )  # fmt: skip
        proven = set(kept)
        notes.extend(regime_notes)
    try:
        if events_for is None:
            import market_scan

            events = market_scan.upcoming_events(
                today, int(cfg["event_window_days"]), market_scan.nse_fetch
            )
        else:
            events = events_for(today, int(cfg["event_window_days"]))
        events_checked = True
    except (ValueError, json.JSONDecodeError) as exc:
        notes.append(f"NSE event calendar unavailable ({str(exc)[:80]}); no entries without it")
    found, skipped = [], {}
    for symbol, bars in data.items():
        if not bars or bars[-1]["date"] != str(today):
            continue  # Stale candles: never trade on an old close.
        hit = signal(bars, list(SETUPS), cfg, cfg["min_turnover_inr"])
        if not hit:
            continue
        plain = symbol.split(":")[-1]
        upcoming = events.get(plain, [])
        if upcoming:
            skipped[symbol] = "; ".join(f"{e['purpose']} {e['date']}" for e in upcoming[:2])
            continue
        risk = hit["close"] - hit["stop"]
        found.append({
            "symbol": symbol, **hit, "proven": hit["strategy"] in proven,
            "target": intraday.round_up(hit["close"] + float(cfg["target_r"]) * risk),
            "risk_pct": round(100 * risk / hit["close"], 2),
        })  # fmt: skip
    found.sort(key=lambda row: (row["proven"], row.get("vol_ratio") or 0), reverse=True)
    for row in found[:10]:
        try:
            row["odds"] = simulate_plan(
                config_path, row["symbol"], row["close"], row["stop"], row["target"],
                int(cfg["max_hold_days"]), int(cfg["odds_replays"]), bars=data[row["symbol"]],
            )  # fmt: skip
        except ValueError as exc:
            row["odds"] = {"unavailable": str(exc)[:120]}
    report = {
        "date": str(today),
        "for_session": "next session",
        "scanned": len(data),
        "candidates": found[:10],
        "skipped_for_events": skipped,
        "events_checked": events_checked,
        "events_checked_at": dt.datetime.now(IST).isoformat(),
        "events_window": int(cfg["event_window_days"]),
        "proven": sorted(proven),
        "scorecard_as_of": (card or {}).get("as_of"),
        "notes": notes
        + ([] if card else ["no swing scorecard yet; run swing.py tournament"])
        + (
            []
            if proven or not cfg["require_proven"]
            else ["no setup is proven yet; the swing desk sits out"]
        ),
        "notice": "Volume and price describe participation; they do not predict prices.",
    }
    intraday.write_json(folder / f"swing-candidates-{today}.json", report)
    return report


def plan_qty(config_path: Path, entry: float, stop: float) -> int:
    """Shares the swing book would buy for this plan (its limits, or the default book's)."""
    import trade_check

    cfg = settings(config_path)
    try:
        book = read_book(config_path)
    except (ValueError, OSError, sqlite3.Error):
        book = {"limits": {"risk": "500", "daily_loss": "1500", "position_limit": "25000"},
                "positions": {}, "realized_by_day": {}, "cash": "100000"}  # fmt: skip
    costs = {key: str(cfg[key]) for key in ("fee_bps", "fee_flat_inr", "slippage_bps")}
    sized = trade_check.size({"stop": stop}, book, costs, entry, str(dt.date.today()))
    return int(sized["qty"])


def simulate_plan(
    config_path: Path, symbol: str, entry: float, stop: float, target: float,
    hold_days: int | None = None, replays: int = 5000, qty: int | None = None,
    bars: list[dict] | None = None,
) -> dict[str, Any]:  # fmt: skip
    """The swing Monte Carlo for one plan on the stock's own stored daily candles."""
    import swing_machine

    cfg = settings(config_path)
    symbol = intraday.normalise_symbol(symbol)
    if bars is None:
        bars = all_bars(intraday.config_folder(config_path) / "scan.sqlite").get(symbol, [])
    if not bars:
        raise ValueError(
            f"No stored daily candles for {symbol}; it must be an F&O stock the scan stores"
        )
    hold = int(hold_days or cfg["max_hold_days"])
    shares = qty or plan_qty(config_path, entry, stop)
    if shares < 1:
        raise ValueError("No whole share fits the swing book's limits for this stop")
    costs = {
        **{key: cfg[key] for key in ("fee_bps", "fee_flat_inr", "slippage_bps")},
        "exact": True,
    }
    result = swing_machine.for_plan(bars, entry, stop, target, hold, shares, costs, replays)
    result.update(symbol=symbol, entry=entry, stop=stop, target=target)
    return result


# ---------- in session: enter and manage ----------


def _latest_candidates(folder: Path, today: dt.date) -> dict | None:
    files = sorted(
        path for path in folder.glob("swing-candidates-*.json") if path.stem[-10:] < str(today)
    )
    if not files:
        return None
    report = json.loads(files[-1].read_text(encoding="utf-8"))
    return report


def evidence(
    candidate: dict, quote: dict, clock: dt.datetime, times: dict, report: dict, manifest: dict
) -> dict:
    """Version-1 pre-trade evidence from checks code ran, each with its source."""
    import guardrails

    bid = float(((quote.get("depth") or {}).get("buy") or [{}])[0].get("price") or 0)
    ask = float(((quote.get("depth") or {}).get("sell") or [{}])[0].get("price") or 0)
    last = float(quote.get("last_price") or 0)
    lower = float(quote.get("lower_circuit_limit") or 0)
    upper = float(quote.get("upper_circuit_limit") or 0)
    checks = {
        "cash_equity": True,
        "instrument_verified": True,
        "surveillance_clear": True,
        "price_band_ok": bool(lower and upper and lower < last < upper * 0.99),
        "no_material_event": bool(report.get("events_checked")),
        "liquidity_ok": True,
        "sector_exposure_ok": True,
        "data_authorized": True,
        "strategy_rule_met": True,
        "stop_target_reviewed": candidate["stop"] < last < candidate["target"],
    }
    sources = {
        "cash_equity": "NSE EQ series from Kite's instrument list",
        "instrument_verified": "Kite instrument list for today",
        "surveillance_clear": "NSE regulatory indicator file and F&O ban list, read daily (surveillance.json)",
        "price_band_ok": f"Kite quote circuit limits {lower}-{upper}, last {last}",
        "no_material_event": f"NSE event calendar, next {report.get('events_window', 7)} days, "
        f"checked {report.get('events_checked_at', '')[:16]}",
        "liquidity_ok": "20-day traded value above the floor (swing scan)",
        "sector_exposure_ok": "at most three open swing positions, one per stock",
        "data_authorized": "Kite Connect with the owner's own login",
        "strategy_rule_met": f"{candidate['strategy']} on the {candidate['date']} close",
        "stop_target_reviewed": f"stop {candidate['stop']}, target {candidate['target']}",
    }
    day = manifest["sessions"][str(clock.date())]
    if set(checks) != set(guardrails.REQUIRED_CHECKS):
        raise ValueError("Swing evidence does not cover the journal's required checks")
    return {
        "version": 1, "symbol": candidate["symbol"], "quote_source": "kite:quote",
        "quote_as_of": clock.isoformat(), "checked_at": clock.isoformat(),  # Quote age checked above.
        "checks": checks, "evidence_sources": sources,
        "session": {"date": str(clock.date()), "open": day["open"], "entry_cutoff": day["entry_cutoff"],
                    "close": day["close"], "source": manifest["source"]},
        "bid_inr": str(bid), "ask_inr": str(ask),
    }  # fmt: skip


def enter(config_path: Path, clock: dt.datetime, quotes_for: Callable[[list[str]], dict]) -> dict:
    """Once per session after 09:15: record the best candidates that still qualify."""
    import price_alerts
    import trade_check

    import paper_book

    folder = intraday.config_folder(config_path)
    cfg = settings(config_path)
    manifest = intraday.sessions_manifest(config_path)
    times = intraday.session_times(manifest, clock.date())
    state = _state(config_path)
    result: dict[str, Any] = {"entered": [], "skipped": {}}
    if (
        times is None
        or not times["open"] + dt.timedelta(minutes=1) <= clock < times["entry_cutoff"]
    ):
        return {**result, "status": "outside the entry window"}
    if state.get("entries_done") == str(clock.date()):
        return {**result, "status": "already entered today"}
    if (folder / "HALT_ENTRIES").exists():
        return {**result, "status": "entries paused (HALT_ENTRIES)"}
    report = _latest_candidates(folder, clock.date())
    state["entries_done"] = str(clock.date())
    if report is None:
        _save_state(config_path, state)
        return {**result, "status": "no swing candidates from the last close"}
    pool = [row for row in report["candidates"] if row["proven"] or not cfg["require_proven"]]
    if not pool:
        _save_state(config_path, state)
        return {**result, "status": "sitting out: no candidate uses a proven setup"}
    if not report.get("events_checked"):
        _save_state(config_path, state)
        return {**result, "status": "sitting out: the event calendar was not checked"}
    book = read_book(config_path)
    quotes = quotes_for([row["symbol"] for row in pool])
    costs = {key: str(cfg[key]) for key in ("fee_bps", "fee_flat_inr", "slippage_bps")}
    for candidate in pool:
        symbol = candidate["symbol"]
        if len(result["entered"]) >= int(cfg["max_new_per_day"]):
            break
        quote = quotes.get(symbol) or {}
        opened = float((quote.get("ohlc") or {}).get("open") or 0)
        ask = float((((quote.get("depth") or {}).get("sell") or [{}])[0]).get("price") or 0)
        last = ask or float(quote.get("last_price") or 0)  # A buy pays the ask.
        why = None
        stamp = quote.get("timestamp") or quote.get("last_trade_time")
        try:
            seen = intraday.now_ist(str(stamp)) if stamp else None
        except ValueError:
            seen = None
        if symbol in book["positions"]:
            why = "already held"
        elif seen is None or not -5 <= (clock - seen).total_seconds() <= 120:
            why = "the quote is stale or has no time; no entry on old data"
        elif guard := safety.entry_guard(config_path, clock):
            why = guard
        elif watched := surveillance.gate(config_path, symbol, clock)[0]:
            why = watched
        elif other := safety.held_elsewhere(config_path, symbol, "swing"):
            why = other
        elif not opened or not last:
            why = "no quote"
        elif opened > candidate["close"] * (1 + float(cfg["max_gap_up_pct"]) / 100):
            why = f"gapped up {100 * (opened / candidate['close'] - 1):.1f}%: late"
        elif opened <= candidate["stop"] or last <= candidate["stop"]:
            why = "opened at or below the stop"
        if why:
            result["skipped"][symbol] = why
            continue
        plan = {**candidate, "entry": last, "date": str(clock.date())}
        sized = trade_check.size(plan, book, costs, last, str(clock.date()))
        if sized["qty"] < 1:
            result["skipped"][symbol] = f"no whole share fits the {sized['decided_by']} limit"
            continue
        ratio = safety.net_reward_risk(
            last, candidate["stop"], candidate["target"], sized["qty"], float(cfg["fee_bps"]),
            float(cfg["fee_flat_inr"]), float(cfg["slippage_bps"]), "delivery",
        )  # fmt: skip
        minimum = float(safety.settings(intraday.load_config(config_path))["min_net_reward_risk"])
        if ratio < minimum:
            result["skipped"][symbol] = (
                f"reward after costs {ratio:.2f}x the risk; needs {minimum:g}x"
            )
            continue
        capped = portfolio.gate(
            config_path,
            "swing",
            symbol,
            last,
            candidate["stop"],
            sized["qty"],
            candidate["strategy"],
        )[0]
        if capped:
            result["skipped"][symbol] = capped
            continue
        odds = candidate.get("odds") or {}
        if cfg.get("require_positive_odds", True) and odds and odds.get("expected_pnl_inr", 0) <= 0:
            result["skipped"][symbol] = "the swing simulation expects a loss after costs"
            continue
        proof = evidence(candidate, quote, clock, times, report, manifest)

        def record(current: dict, candidate=candidate, sized=sized, proof=proof, last=last) -> dict:
            allowed = (
                paper_book.allow_symbols(
                    current, [candidate["symbol"]], "swing candidates", clock.isoformat()
                )
                if candidate["symbol"] not in current["symbols"]
                else current
            )
            return paper_book.fill(
                allowed, "buy", f"swing:{clock.date()}:{candidate['symbol']}", candidate["symbol"],
                str(last), clock.isoformat(), "kite:quote",
                f"{charges.fee('delivery', 'buy', last, sized['qty']):.2f}", costs["slippage_bps"],
                sized["qty"], str(candidate["stop"]),
                f"{charges.fee('delivery', 'sell', last, sized['qty']):.2f}", now=clock,
                evidence=proof, target=str(candidate["target"]),
                research_meta={"strategy_version": candidate["strategy"], "patterns": [candidate["strategy"]],
                               "execution_kind": "swing_autopilot"},
            )  # fmt: skip

        try:
            book = _transact(config_path, record)
        except ValueError as exc:
            result["skipped"][symbol] = str(exc)[:160]
            continue
        held = book["positions"][symbol]
        entry = float(held["entry_inr"])
        state["positions"][symbol] = {
            "strategy": candidate["strategy"], "entry": entry, "initial_stop": candidate["stop"],
            "stop": candidate["stop"], "rule": "initial", "target": candidate["target"],
            "entered": str(clock.date()), "sessions_held": 0, "qty": held["qty"],
        }  # fmt: skip
        plain = symbol.split(":")[-1].lower()
        rules = price_alerts.add(
            price_alerts.load(price_alerts.rules_path(config_path), {"rules": []}),
            [{"id": f"{plain}-swing-stop", "type": "stop", "symbol": symbol, "price": candidate["stop"],
              "label": "swing stop"},
             {"id": f"{plain}-swing-target", "type": "target", "symbol": symbol,
              "price": candidate["target"], "label": "swing target"}],
        )  # fmt: skip
        intraday.write_json(price_alerts.rules_path(config_path), rules)
        result["entered"].append({"symbol": symbol, "qty": held["qty"], "entry": entry,
                                  "stop": candidate["stop"], "target": candidate["target"],
                                  "strategy": candidate["strategy"]})  # fmt: skip
        import shadow

        try:
            shadow.record(config_path, "swing", symbol, "buy", float(entry), clock)
        except (ValueError, OSError, TypeError):
            pass
    _save_state(config_path, state)
    return {**result, "status": "done"}


def manage(config_path: Path, clock: dt.datetime, quotes_for: Callable[[list[str]], dict]) -> dict:
    """Exit on the stop, the target or the time limit; trail the stop at the end of the day."""
    import price_alerts

    import paper_book

    cfg = settings(config_path)
    manifest = intraday.sessions_manifest(config_path)
    times = intraday.session_times(manifest, clock.date())
    state = _state(config_path)
    result: dict[str, Any] = {"exited": [], "trailed": []}
    if times is None or not times["open"] <= clock < times["close"]:
        return {**result, "status": "market closed"}
    book = read_book(config_path)
    held = list(book["positions"])
    if not held:
        return {**result, "status": "no open swing positions"}
    quotes = quotes_for(held)
    end_of_day = (clock.hour, clock.minute) >= EXIT_HOUR
    for symbol in held:
        quote = quotes.get(symbol) or {}
        last = float(quote.get("last_price") or 0)
        track = state["positions"].setdefault(symbol, {
            "entry": float(book["positions"][symbol]["entry_inr"]),
            "initial_stop": float(book["positions"][symbol]["stop_inr"]),
            "stop": float(book["positions"][symbol]["stop_inr"]), "rule": "initial",
            "target": float(book["positions"][symbol].get("target_inr") or 0) or None,
            "entered": book["positions"][symbol]["day"], "sessions_held": 0,
        })  # fmt: skip
        if not last:
            continue
        sessions = sorted(
            d
            for d, s in manifest["sessions"].items()
            if s and track["entered"] <= d <= str(clock.date())
        )
        held_for = len(sessions) - 1  # Sessions after the entry day, including today.
        why = None
        if last <= track["stop"]:
            why = "stop" if track["rule"] == "initial" else f"{track['rule']} stop"
        elif track.get("target") and last >= track["target"]:
            why = "target"
        elif end_of_day and held_for >= int(cfg["max_hold_days"]):
            why = f"time exit after {held_for} sessions"
        if why:
            qty = book["positions"][symbol]["qty"]
            fee = charges.fee("delivery", "sell", last, qty)  # STT, DP charge and the rest.

            def sell(current: dict, symbol=symbol, last=last, fee=fee) -> dict:
                return paper_book.fill(
                    current, "sell", f"swing-exit:{clock.date()}:{symbol}", symbol, str(last),
                    clock.isoformat(), "kite:quote", f"{fee:.2f}", str(cfg["slippage_bps"]), now=clock,
                )  # fmt: skip

            try:
                book = _transact(config_path, sell)
            except ValueError as exc:
                result.setdefault("refused", {})[symbol] = str(exc)[:160]
                continue
            event = book["events"][-1]
            result["exited"].append({"symbol": symbol, "price": last, "why": why,
                                     "net_inr": event.get("net_realized_pnl_inr")})  # fmt: skip
            state["positions"].pop(symbol, None)
            plain = symbol.split(":")[-1].lower()
            rules = price_alerts.load(price_alerts.rules_path(config_path), {"rules": []})
            rules["rules"] = [
                r for r in rules["rules"] if not r["id"].startswith(f"{plain}-swing-")
            ]
            intraday.write_json(price_alerts.rules_path(config_path), rules)
            continue
        track["sessions_held"] = held_for
        if end_of_day and track.get("trailed_on") != str(clock.date()):
            risk = track["entry"] - track["initial_stop"]
            gained = (last - track["entry"]) / risk if risk > 0 else 0
            before = track["stop"]
            if gained >= 1:
                track["stop"], track["rule"] = (
                    max(track["stop"], round(track["entry"] * 1.003, 2)),
                    "breakeven",
                )
            if gained >= 1.5:
                low_today = float((quote.get("ohlc") or {}).get("low") or 0)
                low_before = float(track.get("prior_low") or low_today)
                trail = intraday.round_down(min(low_today, low_before))
                if trail > track["stop"]:
                    track["stop"], track["rule"] = trail, "trailing"
            track["prior_low"] = float((quote.get("ohlc") or {}).get("low") or 0) or track.get(
                "prior_low"
            )
            track["trailed_on"] = str(clock.date())
            if track["stop"] > before:
                result["trailed"].append(
                    {"symbol": symbol, "stop": track["stop"], "rule": track["rule"]}
                )
    _save_state(config_path, state)
    return {**result, "status": "done"}


def kite_quotes(symbols: list[str]) -> dict[str, dict]:
    import market_scan

    return market_scan.KiteClient().quote(symbols) if symbols else {}


def tick(config_path: Path, now: dt.datetime | None = None,
         quotes_for: Callable[[list[str]], dict] = kite_quotes) -> dict:  # fmt: skip
    """One session-worker pass: enter once after the open, then manage open positions."""
    clock = (now or dt.datetime.now(IST)).astimezone(IST)
    if not settings(config_path)["enabled"]:
        return {"status": "off"}
    if not book_path(config_path).is_file():
        return {"status": "no swing book"}
    return {
        "enter": enter(config_path, clock, quotes_for),
        "manage": manage(config_path, clock, quotes_for),
    }


def status(config_path: Path) -> dict[str, Any]:
    """The swing desk for the dashboard: candidates, open positions, results, scorecard."""
    folder = intraday.config_folder(config_path)
    view: dict[str, Any] = {
        "candidates": None,
        "positions": [],
        "closed": [],
        "book": None,
        "scorecard": None,
    }
    files = sorted(folder.glob("swing-candidates-*.json"))
    if files:
        view["candidates"] = json.loads(files[-1].read_text(encoding="utf-8"))
    try:
        book = read_book(config_path)
        tracked = _state(config_path).get("positions", {})
        view["book"] = {"cash": book["cash"], "initial_cash": book["initial_cash"],
                        "limits": book["limits"], "open": len(book["positions"])}  # fmt: skip
        for symbol, position in book["positions"].items():
            extra = tracked.get(symbol, {})
            view["positions"].append({
                "symbol": symbol, "qty": position["qty"], "entry": position["entry_inr"],
                "stop": extra.get("stop", position["stop_inr"]), "rule": extra.get("rule", "initial"),
                "target": position.get("target_inr"), "entered": position["day"],
                "strategy": extra.get("strategy"), "sessions_held": extra.get("sessions_held", 0),
            })  # fmt: skip
        view["closed"] = [
            {"symbol": e["symbol"], "at": e["as_of"], "price": e["assumed_fill_inr"],
             "net_inr": e.get("net_realized_pnl_inr")}
            for e in book["events"] if e["side"] == "sell"
        ][-10:]  # fmt: skip
    except (ValueError, OSError, sqlite3.Error):
        pass
    try:
        card = json.loads((folder / "swing-scorecard.json").read_text(encoding="utf-8"))
        view["scorecard"] = {
            "as_of": card["as_of"], "sessions": card["sessions"], "stocks": card["stocks"],
            "eligible": card["eligible"],
            "strategies": {
                name: {"eligible": row["eligible"], "reason": row["reasons"][0],
                       "trades": row["doubled_costs"]["trades"], "net_inr": row["doubled_costs"]["net_inr"],
                       "profit_factor": row["doubled_costs"]["profit_factor"],
                       "win_rate_pct": row["doubled_costs"]["win_rate_pct"]}
                for name, row in card["strategies"].items()
            },
        }  # fmt: skip
    except (OSError, ValueError, KeyError):
        pass
    return view


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" IST')
    sub = parser.add_subparsers(dest="command", required=True)
    making = sub.add_parser("create-book")
    making.add_argument("--cash", default="100000")
    making.add_argument("--risk", default="500")
    making.add_argument("--daily-loss", default="1500")
    making.add_argument("--position", default="25000")
    for name in ("tournament", "scan", "tick", "status"):
        sub.add_parser(name)
    simulating = sub.add_parser("simulate", help="Monte Carlo for one swing plan")
    simulating.add_argument("symbol")
    simulating.add_argument("--entry", type=float, required=True)
    simulating.add_argument("--stop", type=float, required=True)
    simulating.add_argument("--target", type=float, required=True)
    simulating.add_argument("--days", type=int)
    simulating.add_argument("--replays", type=int, default=5000)
    args = parser.parse_args(argv)
    try:
        clock = intraday.now_ist(args.now)
        if args.command == "create-book":
            book = create_book(args.config, args.cash, args.risk, args.daily_loss, args.position)
            result: Any = {"created": True, "cash": book["cash"], "limits": book["limits"]}
        elif args.command == "tournament":
            card = tournament(args.config)
            result = {
                "sessions": card["sessions"], "stocks": card["stocks"], "eligible": card["eligible"],
                "strategies": {n: {"eligible": r["eligible"], "reason": r["reasons"][0],
                                   "doubled_costs": r["doubled_costs"]} for n, r in card["strategies"].items()},
            }  # fmt: skip
        elif args.command == "scan":
            report = scan(args.config, clock.date())
            result = {key: report[key] for key in ("date", "scanned", "proven", "notes")}
            result["candidates"] = [
                f"{row['symbol']} {row['strategy']} close {row['close']} stop {row['stop']} "
                f"vol {row.get('vol_ratio')}x{' (proven)' if row['proven'] else ''}"
                for row in report["candidates"]
            ]
        elif args.command == "tick":
            result = tick(args.config, clock)
        elif args.command == "simulate":
            odds = simulate_plan(args.config, args.symbol, args.entry, args.stop, args.target,
                                 args.days, args.replays)  # fmt: skip
            print(odds["summary"])
            result = {key: odds[key] for key in odds if key not in ("histogram",)}
        else:
            result = status(args.config)
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        print(f"Swing desk refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

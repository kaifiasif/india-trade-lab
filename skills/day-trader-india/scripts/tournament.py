#!/usr/bin/env python3
"""Strategy tournament: which rules have earned the right to trade, on your own history.

Every strategy in strategies.py is replayed over the complete broker-export
sessions in history.sqlite, with the same signals, filters and managed exits the
live desk uses. Fills are deliberately pessimistic:

- entry at the next bar's open plus slippage, never the signal bar's close
- when a bar touches both the stop and the target, the stop is assumed first
- a gap through the stop fills at the bar's open, not at the stop
- costs are charged on both sides, and eligibility is judged at **double** costs

A strategy is eligible only if, at double costs, it made money overall, kept a
profit factor of at least ``min_profit_factor``, had at least ``min_trades``
trades, was profitable in most chronological folds and did not lose money in the
most recent fold. A strategy that fails trades nothing. If none pass, the desk
sits out, which is how it avoids paying for a rule with no edge.

Past sessions are not a forecast. Passing here means "not disproved on this
sample", nothing more. Read only: it writes a scorecard, never a journal or order.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any

import regime
import technical
import validation
from history import HistoryStore

import strategies

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
RULES = {
    "min_trades": 30,
    "min_profit_factor": 1.15,
    "folds": 3,
    "min_positive_folds": 2,
    "min_luck_percentile": 95.0,  # Beat 95% of random-entry twins at double costs.
    "luck_twins": 200,
    "min_dsr": 0.95,  # Deflated Sharpe: probability the edge beats the luckiest trial.
}
DEFAULTS = {
    "risk_inr": 250.0,
    "position_cap_inr": 15000.0,
    "target_r": 2.0,
    "fee_bps": 5.0,
    "fee_flat_inr": 10.0,
    "slippage_bps": 5.0,
}


def load(history: Path, first: dt.date | None = None) -> dict[str, list[dict]]:
    """{symbol: [{"date", "times", "bars"}]} for complete broker-export sessions."""
    with sqlite3.connect(history) as conn:
        rows = conn.execute(
            "SELECT symbol, date, payload FROM sessions WHERE kind='broker_export' ORDER BY date"
        ).fetchall()
    result: dict[str, list[dict]] = {}
    for symbol, date, payload in rows:
        if first and dt.date.fromisoformat(date) < first:
            continue
        data = json.loads(payload)
        times = {key: dt.datetime.fromisoformat(value) for key, value in data["session"].items()}
        bars = [
            {
                "t": dt.datetime.fromisoformat(bar["t"]),
                **{key: float(bar[key]) for key in ("open", "high", "low", "close", "volume")},
            }
            for bar in data["bars"]
        ]
        result.setdefault(symbol, []).append({"date": date, "times": times, "bars": bars})
    return result


def _fee(
    price: float, qty: int, cfg: dict, multiple: float, which: str = "buy", day: str | None = None
) -> float:
    """One side's charges: exact Zerodha intraday charges, or the flat model if switched off."""
    if cfg.get("exact_charges", True):
        import charges

        return multiple * charges.fee("intraday", which, price, qty, day)
    return multiple * (cfg["fee_flat_inr"] + price * qty * cfg["fee_bps"] / 10_000)


def _walk(
    rows: list[dict],
    index: int,
    entry: float,
    stop: float,
    qty: int,
    cfg: dict,
    multiple: float,
    day: dict,
) -> tuple[float, str, float]:
    """The desk's exits from the bar after ``index``: square-off, time stop, managed stop
    (stop first), target. Returns the exit price after slippage, why, and net rupees."""
    times = day["times"]
    slip = multiple * cfg["slippage_bps"] / 10_000
    target = entry + (entry - stop) * cfg["target_r"]
    entry_fee = _fee(entry, qty, cfg, multiple, "buy", day["date"])
    per_share = 2 * entry_fee / qty
    exit_price, why = None, "session end"
    for later in range(index + 1, len(rows)):
        bar = rows[later]
        if bar["t"] >= times["flat_by"]:
            exit_price, why = bar["open"], "square_off"
            break
        managed = strategies.managed_stop(entry, stop, per_share, rows[index + 1 : later])
        if managed["time_stop"]:
            exit_price, why = bar["open"], "time_stop"
            break
        if bar["low"] <= managed["stop"]:
            exit_price, why = min(managed["stop"], bar["open"]), managed["rule"] + "_stop"
            break
        if bar["high"] >= target:
            exit_price, why = target, "target"
            break
    if exit_price is None:
        exit_price = rows[-1]["close"]
    exit_price *= 1 - slip
    pnl = (
        (exit_price - entry) * qty
        - entry_fee
        - _fee(exit_price, qty, cfg, multiple, "sell", day["date"])
    )
    return exit_price, why, pnl


def random_twins(
    trades: list[dict],
    data: dict[str, list[dict]],
    cfg: dict,
    multiple: float,
    twins: int,
    seed: int = 19,
) -> list[float]:
    """Net totals of ``twins`` random-entry copies of ``trades``: same stocks, same stop
    distance and exits, entries at a random bar of a random stored session."""
    import random

    rng = random.Random(seed)
    totals = []
    for _ in range(twins):
        total = 0.0
        for trade in trades:
            days = data.get(trade["symbol"]) or []
            if not days:
                continue
            day = rng.choice(days)
            rows, times = day["bars"], day["times"]
            choices = [
                i
                for i in range(3, len(rows) - 1)
                if rows[i]["t"] + strategies.BAR <= times["entry_cutoff"]
            ]
            if not choices:
                continue
            index = rng.choice(choices)
            slip = multiple * cfg["slippage_bps"] / 10_000
            entry = rows[index + 1]["open"] * (1 + slip)
            risk_pct = (trade["entry"] - trade["stop"]) / trade["entry"]
            stop = entry * (1 - risk_pct)
            qty = math.floor(min(cfg["risk_inr"] / (entry - stop), cfg["position_cap_inr"] / entry))
            if qty < 1:
                continue
            total += _walk(rows, index, entry, stop, qty, cfg, multiple, day)[2]
        totals.append(round(total, 2))
    return totals


def simulate_day(
    symbol: str, day: dict, name: str, context: dict | None, cfg: dict, multiple: float
) -> dict | None:
    """At most one trade per symbol per day, with pessimistic fills."""
    rows, times = day["bars"], day["times"]
    slip = multiple * cfg["slippage_bps"] / 10_000
    for index in range(len(rows) - 1):
        signal = strategies.latest_signal(rows[: index + 1], times, [name], context)
        if not signal or "blocked" in signal:
            continue
        fill_bar = rows[index + 1]
        if fill_bar["t"] >= times["flat_by"]:
            return None
        entry = fill_bar["open"] * (1 + slip)
        stop = signal["stop"]
        if not stop < entry:
            continue
        qty = math.floor(min(cfg["risk_inr"] / (entry - stop), cfg["position_cap_inr"] / entry))
        if qty < 1:
            continue
        exit_price, why, pnl = _walk(rows, index, entry, stop, qty, cfg, multiple, day)
        return {
            "symbol": symbol,
            "date": day["date"],
            "strategy": name,
            "entry_at": fill_bar["t"].isoformat(),
            "entry": round(entry, 2),
            "stop": stop,
            "exit": round(exit_price, 2),
            "exit_reason": why,
            "qty": qty,
            "r": round((exit_price - entry) / (entry - stop), 2),
            "net_inr": round(pnl, 2),
        }
    return None


def stats(trades: list[dict]) -> dict[str, Any]:
    pnl = [trade["net_inr"] for trade in trades]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value <= 0]
    equity = peak = drawdown = 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    loss_total = -sum(losses)
    return {
        "trades": len(pnl),
        "net_inr": round(sum(pnl), 2),
        "win_rate_pct": round(100 * len(wins) / len(pnl), 1) if pnl else None,
        "profit_factor": round(sum(wins) / loss_total, 3) if loss_total > 0 else None,
        "expectancy_inr": round(statistics.mean(pnl), 2) if pnl else None,
        "average_r": round(statistics.mean(trade["r"] for trade in trades), 3) if trades else None,
        "max_drawdown_inr": round(drawdown, 2),
        "exits": {
            reason: sum(trade["exit_reason"] == reason for trade in trades)
            for reason in sorted({trade["exit_reason"] for trade in trades})
        },
    }


def judge(trades: list[dict], dates: list[str], rules: dict) -> tuple[bool, list[str], list]:
    """Eligibility at double costs, with the reason for every failed condition."""
    overall = stats(trades)
    size = max(1, math.ceil(len(dates) / rules["folds"]))
    folds = []
    for start in range(0, len(dates), size):
        window = set(dates[start : start + size])
        folds.append(
            {
                "from": min(window),
                "to": max(window),
                **stats([trade for trade in trades if trade["date"] in window]),
            }
        )
    reasons = []
    if overall["trades"] < rules["min_trades"]:
        reasons.append(f"only {overall['trades']} trades; need {rules['min_trades']}")
    if overall["net_inr"] <= 0:
        reasons.append(f"lost INR {-overall['net_inr']:,.0f} at double costs")
    factor = overall["profit_factor"]
    if factor is not None and factor < rules["min_profit_factor"]:
        reasons.append(f"profit factor {factor} below {rules['min_profit_factor']}")
    if factor is None and overall["trades"] and overall["net_inr"] <= 0:
        reasons.append("no winning trades")
    positive = sum(fold["net_inr"] > 0 for fold in folds)
    if positive < min(rules["min_positive_folds"], len(folds)):
        reasons.append(f"profitable in {positive} of {len(folds)} periods")
    if folds and folds[-1]["net_inr"] < 0:
        reasons.append("lost money in the most recent period")
    return not reasons, reasons, folds


def run(history: Path, cfg: dict | None = None, rules: dict | None = None) -> dict[str, Any]:
    cfg = {**DEFAULTS, **(cfg or {})}
    rules = {**RULES, **(rules or {})}
    data = load(history)
    if not data:
        raise ValueError("No complete broker-export sessions in history")
    store = HistoryStore(history)
    contexts: dict[tuple[str, str], dict | None] = {}
    for symbol, days in data.items():
        every = technical.daily_bars(store, symbol, days[-1]["times"]["close"])
        for day in days:
            # Point in time: only sessions that had closed before this one opened.
            prior = [
                row
                for row in every
                if dt.datetime.fromisoformat(row["close_at"]) <= day["times"]["open"]
            ]
            try:
                contexts[(symbol, day["date"])] = technical.snapshot(prior)
            except ValueError:
                contexts[(symbol, day["date"])] = None
    dates = sorted({day["date"] for days in data.values() for day in days})
    usable = [d for d in dates if any(contexts.get((s, d)) for s in data)]
    measured: list[dict] = []
    known = regime.labels(history.parent / "scan.sqlite")
    result: dict[str, Any] = {
        "as_of": dt.datetime.now(IST).isoformat(),
        "sessions": len(usable),
        "from": usable[0] if usable else None,
        "to": usable[-1] if usable else None,
        "symbols": sorted(data),
        "assumptions": cfg,
        "rules": rules,
        "strategies": {},
    }
    for name in strategies.STRATEGIES:
        runs = {}
        for label, multiple in (("baseline", 1.0), ("doubled_costs", 2.0)):
            trades = []
            for symbol, days in data.items():
                for day in days:
                    context = contexts.get((symbol, day["date"]))
                    if context is None:
                        continue  # Too little prior history; the live desk would refuse too.
                    trade = simulate_day(symbol, day, name, context, cfg, multiple)
                    if trade:
                        trades.append(trade)
            runs[label] = trades
        eligible, reasons, folds = judge(runs["doubled_costs"], usable, rules)
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
        variant = validation.variant_id(
            "intraday", name, {k: cfg[k] for k in sorted(cfg) if k != "exact_charges"}
        )
        measured.append({"id": variant, "strategy": name, "sharpe": validation.sharpe(returns)})
        deflation = {"returns": returns}
        eligible = not reasons
        result["strategies"][name] = {
            "by_regime": regime.by_regime(runs["doubled_costs"], known),
            "luck_percentile": luck,
            "random_twins_median_inr": statistics.median(twins) if twins else None,
            "_deflation": deflation,
            "description": strategies.DESCRIPTIONS[name],
            "eligible": eligible,
            "reasons": reasons or ["passed every condition at double costs"],
            "baseline": stats(runs["baseline"]),
            "doubled_costs": stats(runs["doubled_costs"]),
            "folds_doubled_costs": folds,
            "by_symbol": {
                symbol: stats([t for t in runs["baseline"] if t["symbol"] == symbol])
                for symbol in sorted(data)
            },
            "recent_trades": runs["baseline"][-10:],
        }
    registry = validation.record_trials(history.parent, "intraday", measured)
    for _name, row in result["strategies"].items():
        deflated = validation.deflated_sharpe(
            row.pop("_deflation")["returns"], registry["trials"], registry["sharpes"]
        )
        row["deflated_sharpe"] = deflated
        if row["eligible"] and (
            deflated["dsr"] is None or deflated["dsr"] < float(rules["min_dsr"])
        ):
            row["eligible"] = False
            shown = "unknown" if deflated["dsr"] is None else f"{deflated['dsr']:.2f}"
            row["reasons"] = [
                f"deflated Sharpe {shown} after {registry['trials']} trials; needs {rules['min_dsr']:g}"
            ]
    result["trials"] = registry["trials"]
    result["eligible"] = [n for n, r in result["strategies"].items() if r["eligible"]]
    result["notice"] = (
        "Pessimistic fills on stored history: next-bar-open entries, stop-first on ambiguous "
        "bars, gap fills at the open, costs on both sides, eligibility at double costs. "
        "Cross-symbol daily caps are not modelled. Past sessions do not predict future returns."
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
    args = parser.parse_args(argv)
    try:
        from decision_pipeline import DailyCoordinator

        coordinator = DailyCoordinator(args.config)
        config = coordinator.config
        result = run(
            coordinator.path("history_db"),
            {
                "fee_bps": float(config["fee_bps"]),
                "fee_flat_inr": float(config["fee_flat_inr"]),
                "slippage_bps": float(config["slippage_bps"]),
                "target_r": float(config["target_r"]),
            },
        )
        destination = strategies.scorecard_path(args.config.resolve().parent)
        destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "written": str(destination),
                    "sessions": result["sessions"],
                    "eligible": result["eligible"],
                    "strategies": {
                        name: {
                            "eligible": item["eligible"],
                            "reasons": item["reasons"],
                            "doubled_costs": {
                                key: item["doubled_costs"][key]
                                for key in ("trades", "net_inr", "win_rate_pct", "profit_factor")
                            },
                        }
                        for name, item in result["strategies"].items()
                    },
                },
                indent=2,
            )
        )
        return 0
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        print("DATA_BLOCK: " + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())

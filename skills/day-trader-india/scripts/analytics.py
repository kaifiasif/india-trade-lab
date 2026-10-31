#!/usr/bin/env python3
"""Performance analytics for both paper books: is the desk actually earning, and why?

Reads every closed paper trade from the intraday and swing journals and reports:

- **Results**: trades, win rate, expectancy in rupees and in R (net P&L over the
  planned loss at entry), profit factor, average win and loss, total charges paid.
- **Distribution**: an R histogram and, for swing trades, MAE and MFE (the worst and best
  price reached while held, in R, from stored daily candles).
- **Equity and drawdown**: the curve by close date and the deepest fall from a peak.
- **Attribution**: by book, strategy, market regime, weekday and entry hour.
- **Drift**: a one-sided CUSUM of each strategy's paper R against its tournament average
  at doubled costs. It alarms when paper keeps falling short of the backtest.
- **Slippage**: shadow-fill measurements against the configured assumption.
- **Tax view** (an estimate, not tax advice): intraday is speculative business income,
  taxed at your slab rate (``tax.slab_rate_pct``, default 30%); swing trades held under a
  year are short-term capital gains under section 111A at 20%. Both plus 4% cess. Per
  Indian financial year (April to March).
- **Explain**: a plain-language story of each trade.

    python3 analytics.py report                # JSON for the dashboard
    python3 analytics.py report --email --period week
    python3 analytics.py explain --last 3
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import statistics
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
IST = intraday.IST
CESS = 0.04
STCG_RATE = 0.20
SCORECARDS = {"intraday": "strategy-scorecard.json", "swing": "swing-scorecard.json"}


def _book(path: Path) -> dict | None:
    if not path.is_file():
        return None
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
        row = conn.execute("SELECT data FROM book WHERE id=1").fetchone()
    return json.loads(row[0]) if row else None


def trades(config_path: Path) -> list[dict[str, Any]]:
    """Every closed paper trade of both books, oldest first."""
    import safety

    rows = []
    for kind, path in safety.book_paths(config_path).items():
        book = _book(path)
        if not book:
            continue
        entries = {event["id"]: event for event in book.get("events", []) if event["side"] == "buy"}
        for event in book.get("events", []):
            if event["side"] != "sell" or event.get("entry_event_id") not in entries:
                continue
            entry = entries[event["entry_event_id"]]
            meta = entry.get("research_meta") or {}
            net = float(event["net_realized_pnl_inr"])
            planned = float(entry.get("planned_loss_inr") or 0)
            opened = dt.datetime.fromisoformat(entry["as_of"]).astimezone(IST)
            closed = dt.datetime.fromisoformat(event["as_of"]).astimezone(IST)
            rows.append({
                "book": kind, "symbol": event["symbol"], "qty": int(entry["qty"]),
                "strategy": meta.get("strategy_version", "manual"),
                "opened_at": opened.isoformat(), "closed_at": closed.isoformat(),
                "entry": float(entry["assumed_fill_inr"]), "exit": float(event["assumed_fill_inr"]),
                "stop": float(entry.get("stop_inr") or 0), "target": float(entry.get("target_inr") or 0),
                "charges_inr": round(float(entry.get("fee_inr") or 0) + float(event.get("fee_inr") or 0), 2),
                "net_inr": net, "planned_loss_inr": planned,
                "r": round(net / planned, 2) if planned > 0 else None,
                "exit_reason": event.get("reason") or event.get("exit_reason") or "",
                "hold_sessions": None,
            })  # fmt: skip
    return sorted(rows, key=lambda row: row["closed_at"])


def _excursions(folder: Path, trade: dict) -> tuple[float | None, float | None]:
    """Swing MAE and MFE in R from stored daily candles while held."""
    risk = trade["entry"] - trade["stop"]
    if trade["book"] != "swing" or risk <= 0:
        return None, None
    try:
        with sqlite3.connect(folder / "scan.sqlite") as conn:
            bars = conn.execute(
                "SELECT low, high FROM daily WHERE symbol=? AND date>=? AND date<=?",
                (trade["symbol"], trade["opened_at"][:10], trade["closed_at"][:10]),
            ).fetchall()
    except sqlite3.Error:
        return None, None
    if not bars:
        return None, None
    worst = min(low for low, _ in bars)
    best = max(high for _, high in bars)
    return round((worst - trade["entry"]) / risk, 2), round((best - trade["entry"]) / risk, 2)


def summary(rows: list[dict]) -> dict[str, Any]:
    pnl = [row["net_inr"] for row in rows]
    rs = [row["r"] for row in rows if row["r"] is not None]
    wins, losses = [v for v in pnl if v > 0], [v for v in pnl if v <= 0]
    return {
        "trades": len(rows),
        "net_inr": round(sum(pnl), 2),
        "win_rate_pct": round(100 * len(wins) / len(pnl), 1) if pnl else None,
        "expectancy_inr": round(statistics.fmean(pnl), 2) if pnl else None,
        "expectancy_r": round(statistics.fmean(rs), 3) if rs else None,
        "profit_factor": round(sum(wins) / -sum(losses), 3) if losses and sum(losses) < 0 else None,
        "average_win_inr": round(statistics.fmean(wins), 2) if wins else None,
        "average_loss_inr": round(statistics.fmean(losses), 2) if losses else None,
        "charges_inr": round(sum(row["charges_inr"] for row in rows), 2),
    }


def histogram(
    values: list[float], low: float = -3.0, high: float = 5.0, step: float = 0.5
) -> list[dict]:
    edges = [low + step * i for i in range(int((high - low) / step) + 1)]
    buckets = [{"from": edge, "to": edge + step, "count": 0} for edge in edges[:-1]]
    for value in values:
        index = min(max(int((value - low) // step), 0), len(buckets) - 1)
        buckets[index]["count"] += 1
    return buckets


def equity(rows: list[dict]) -> dict[str, Any]:
    curve, total, peak, deepest = [], 0.0, 0.0, 0.0
    for row in rows:
        total += row["net_inr"]
        peak = max(peak, total)
        deepest = max(deepest, peak - total)
        curve.append({"at": row["closed_at"][:10], "equity_inr": round(total, 2),
                      "drawdown_inr": round(peak - total, 2)})  # fmt: skip
    return {"curve": curve, "max_drawdown_inr": round(deepest, 2)}


def attribution(rows: list[dict], known: dict) -> dict[str, dict]:
    import regime

    groups: dict[str, dict[str, list[dict]]] = {
        "book": {},
        "strategy": {},
        "regime": {},
        "weekday": {},
        "entry_hour": {},
    }
    for row in rows:
        opened = dt.datetime.fromisoformat(row["opened_at"])
        label = regime.label_before(known, row["opened_at"][:10])
        keys = {
            "book": row["book"], "strategy": row["strategy"],
            "regime": label["label"] if label else "unknown",
            "weekday": opened.strftime("%a"), "entry_hour": f"{opened:%H}:00",
        }  # fmt: skip
        for group, key in keys.items():
            groups[group].setdefault(key, []).append(row)
    return {
        group: {key: summary(items) for key, items in sorted(values.items())}
        for group, values in groups.items()
    }


def drift(
    config_path: Path, rows: list[dict], threshold: float = 4.0, slack: float = 0.5
) -> dict[str, dict]:
    """One-sided CUSUM of paper R below the tournament's average R, per strategy.

    S = max(0, S + (expected - actual - slack)); alarm when S > threshold. With R in units
    of risk, slack 0.5 and threshold 4 follow the usual k = 0.5 sigma, h = 4 sigma for a
    per-trade spread of about 1R.
    """
    folder = intraday.config_folder(config_path)
    expected: dict[tuple[str, str], float] = {}
    for kind, name in SCORECARDS.items():
        try:
            card = json.loads((folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for strategy, row in card.get("strategies", {}).items():
            value = (row.get("doubled_costs") or {}).get("average_r")
            if value is not None:
                expected[(kind, strategy)] = float(value)
    result = {}
    for (kind, strategy), mean in expected.items():
        mine = [
            row["r"]
            for row in rows
            if row["book"] == kind and row["strategy"] == strategy and row["r"] is not None
        ]
        if not mine:
            continue
        score = peak = 0.0
        for value in mine:
            score = max(0.0, score + (mean - value - slack))
            peak = max(peak, score)
        result[f"{kind}:{strategy}"] = {
            "paper_trades": len(mine), "backtest_average_r": mean,
            "paper_average_r": round(statistics.fmean(mine), 3), "cusum": round(score, 2),
            "alarm": score > threshold,
            "verdict": ("paper is running well below the backtest: re-check costs, fills and "
                        "the regime before trusting this strategy") if score > threshold else "in line",
        }  # fmt: skip
    return result


def financial_year(when: str) -> str:
    day = dt.date.fromisoformat(when[:10])
    start = day.year if day.month >= 4 else day.year - 1
    return f"FY{start}-{str(start + 1)[2:]}"


def tax_view(rows: list[dict], slab_pct: float) -> dict[str, dict]:
    """Estimated tax per financial year. Losses here only offset gains of the same kind."""
    years: dict[str, dict[str, float]] = {}
    for row in rows:
        year = years.setdefault(financial_year(row["closed_at"]), {"speculative": 0.0, "stcg": 0.0})
        year["speculative" if row["book"] == "intraday" else "stcg"] += row["net_inr"]
    result = {}
    for year, totals in sorted(years.items()):
        spec, stcg = totals["speculative"], totals["stcg"]
        result[year] = {
            "speculative_income_inr": round(spec, 2),
            "speculative_tax_inr": round(max(spec, 0) * slab_pct / 100 * (1 + CESS), 2),
            "stcg_inr": round(stcg, 2),
            "stcg_tax_inr": round(max(stcg, 0) * STCG_RATE * (1 + CESS), 2),
            "notes": [
                f"intraday at your {slab_pct:g}% slab plus 4% cess; a speculative loss offsets only "
                "speculative income and carries forward 4 years",
                "swing gains held under 12 months: STCG at 20% plus cess (section 111A; STT paid)",
                "estimate for paper trades only; surcharge, rebate and exemption limits are ignored; "
                "not tax advice",
            ],
        }
    return result


def explain(trade: dict, known: dict | None = None) -> str:
    """One trade as a short story a beginner can follow."""
    import regime

    opened = dt.datetime.fromisoformat(trade["opened_at"])
    closed = dt.datetime.fromisoformat(trade["closed_at"])
    risk = trade["planned_loss_inr"]
    label = regime.label_before(known or {}, trade["opened_at"][:10])
    held = "the same day" if opened.date() == closed.date() else f"on {closed:%d %b}"
    outcome = "made" if trade["net_inr"] > 0 else "lost"
    text = (
        f"On {opened:%d %b} at {opened:%H:%M} the {trade['book']} desk bought {trade['qty']} "
        f"{trade['symbol'].split(':')[-1]} at ₹{trade['entry']:,.2f} using {trade['strategy']}. "
        f"The stop was ₹{trade['stop']:,.2f}"
        + (f" and the target ₹{trade['target']:,.2f}" if trade["target"] else "")
        + f", so the most it planned to lose was ₹{risk:,.0f}. "
        f"It sold {held} at ₹{trade['exit']:,.2f}"
        + (f" ({trade['exit_reason']})" if trade["exit_reason"] else "")
        + f" and {outcome} ₹{abs(trade['net_inr']):,.2f} after ₹{trade['charges_inr']:,.2f} of charges"
        + (f", which is {trade['r']:+.2f}R" if trade["r"] is not None else "")
        + "."
    )
    if label:
        text += f" The market that day was {label['label'].replace('/', ', ')}."
    return text + " Paper trade: no real money moved."


def report(config_path: Path, since: str | None = None) -> dict[str, Any]:
    import regime
    import shadow

    config = intraday.load_config(config_path)
    folder = intraday.config_folder(config_path)
    rows = [row for row in trades(config_path) if not since or row["closed_at"][:10] >= since]
    known = regime.labels(folder / "scan.sqlite")
    for row in rows:
        row["mae_r"], row["mfe_r"] = _excursions(folder, row)
    swing_rows = [row for row in rows if row["mae_r"] is not None]
    return {
        "as_of": dt.datetime.now(IST).isoformat(),
        "since": since,
        "summary": summary(rows),
        "r_histogram": histogram([row["r"] for row in rows if row["r"] is not None]),
        "excursions": {
            "trades": len(swing_rows),
            "average_mae_r": round(statistics.fmean(r["mae_r"] for r in swing_rows), 2) if swing_rows else None,
            "average_mfe_r": round(statistics.fmean(r["mfe_r"] for r in swing_rows), 2) if swing_rows else None,
            "note": "swing only, from daily candles; intraday paths are not stored",
        },
        "equity": equity(rows),
        "attribution": attribution(rows, known),
        "drift": drift(config_path, rows),
        "slippage": shadow.calibration(config_path),
        "tax": tax_view(rows, float((config.get("tax") or {}).get("slab_rate_pct", 30))),
        "recent": [{**row, "story": explain(row, known)} for row in rows[-10:]][::-1],
    }  # fmt: skip


def email_text(view: dict, period: str) -> str:
    total = view["summary"]
    lines = [
        f"India Trade Lab: your paper {period}"
        + (f" (since {view['since']})" if view["since"] else ""),
        "",
        f"Closed trades: {total['trades']}. Net ₹{total['net_inr']:,.2f} after ₹{total['charges_inr']:,.2f} charges.",
    ]
    if total["trades"]:
        lines.append(
            f"Win rate {total['win_rate_pct']}%, expectancy ₹{total['expectancy_inr']:,.2f} a trade"
            + (f" ({total['expectancy_r']:+.2f}R)" if total["expectancy_r"] is not None else "")
            + f". Deepest drawdown ₹{view['equity']['max_drawdown_inr']:,.2f}."
        )
    for key, row in view["drift"].items():
        if row["alarm"]:
            lines.append(
                f"Drift alarm: {key} paper {row['paper_average_r']}R vs backtest {row['backtest_average_r']}R."
            )
    for book, row in view["slippage"].items():
        lines.append(f"Slippage ({book}): {row['verdict']}.")
    lines += ["", "Recent trades:"] + [f"- {item['story']}" for item in view["recent"][:5]]
    lines += ["", "Paper trading only. Past paper results do not predict real results."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    reporting = sub.add_parser("report")
    reporting.add_argument("--period", choices=["all", "week", "month"], default="all",
                           help="week: the last 7 days; month: the last 30 days")  # fmt: skip
    reporting.add_argument("--email", action="store_true")
    telling = sub.add_parser("explain")
    telling.add_argument("--last", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        if args.command == "explain":
            import regime

            known = regime.labels(intraday.config_folder(args.config) / "scan.sqlite")
            for row in trades(args.config)[-args.last :]:
                print(explain(row, known), end="\n\n")
            return 0
        today = dt.datetime.now(IST).date()
        since = {
            "week": str(today - dt.timedelta(days=7)),
            "month": str(today - dt.timedelta(days=30)),
            "all": None,
        }[args.period]
        view = report(args.config, since)
        if args.period == "all":
            intraday.write_json(intraday.config_folder(args.config) / "performance.json", view)
        if args.email:
            import premarket

            message = EmailMessage()
            message["Subject"] = (
                f"India Trade Lab: paper {args.period} ₹{view['summary']['net_inr']:,.0f}"
            )
            message.set_content(email_text(view, args.period))
            sent = premarket.smtp_send(message, intraday.load_config(args.config))
            print("sent" if sent.get("sent") else f"not sent: {sent.get('reason')}")
            return 0 if sent.get("sent") else 1
        print(json.dumps(view, indent=2, default=str))
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        print(f"Analytics refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

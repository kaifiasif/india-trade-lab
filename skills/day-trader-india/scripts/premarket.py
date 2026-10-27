#!/usr/bin/env python3
"""Pre-market report: what the desk is watching today, and why, with its evidence.

For each instrument in the universe it assembles, from sources already stored or
collected: the trend and RSI from stored sessions, the sector and how that sector
index has moved, NSE's market-cap tier, traded-value liquidity, F&O eligibility
and lot size, collected headlines with their sentiment, and any broker call a
headline states. Each candidate is then ranked by a transparent score whose every
component is shown with the reason it was awarded.

This is a watchlist, not a trade list and not a forecast. A high rank means the
instrument met liquidity, size and trend conditions worth watching at the open;
it is not an entry. An entry still needs a completed-bar signal, fresh pre-trade
evidence, the review roles and every journal gate, during market hours.

Read only: no order path, no journal write. Email is off unless configured.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import smtplib
import sqlite3
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import technical
from history import HistoryStore

import sentiment
from reference import ReferenceStore

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TIER_RANK = {"large": 3, "mid": 2, "small": 1}


def trend_of(values: dict[str, Any]) -> dict[str, Any]:
    """Classify trend from stored closes and moving averages, with the reason shown."""
    close, sma20, sma50 = values.get("close"), values.get("sma20"), values.get("sma50")
    if close is None or sma20 is None:
        return {"label": "unknown", "reason": "not enough stored sessions for a 20-session average"}
    above20 = close > sma20
    if sma50 is None:
        return {
            "label": "up" if above20 else "down",
            "reason": f"close {'above' if above20 else 'below'} the 20-session average; "
            "no 50-session average yet",
        }
    stacked = sma20 > sma50
    if above20 and stacked:
        label, reason = "up", "close above the 20-session average, which is above the 50-session"
    elif not above20 and not stacked:
        label, reason = "down", "close below the 20-session average, which is below the 50-session"
    else:
        label, reason = "mixed", "the close and the two averages disagree"
    return {"label": label, "reason": reason}


def rsi_band(value: float | None) -> dict[str, Any]:
    if value is None:
        return {"band": "unknown", "note": "not enough sessions for a 14-period RSI"}
    if value >= 70:
        return {"band": "overbought", "note": "RSI at or above 70; late to chase strength"}
    if value >= 55:
        return {"band": "strong", "note": "RSI 55-70; momentum present without being stretched"}
    if value > 45:
        return {"band": "neutral", "note": "RSI 45-55; no momentum edge either way"}
    if value > 30:
        return {"band": "weak", "note": "RSI 30-45; momentum against a long"}
    return {"band": "oversold", "note": "RSI at or below 30; falling, not yet turning"}


def score(candidate: dict, settings: dict) -> dict[str, Any]:
    """Points with a stated reason for each. Transparent and deliberately simple."""
    parts: list[dict[str, Any]] = []

    def award(name: str, points: float, reason: str) -> None:
        parts.append({"factor": name, "points": round(points, 2), "reason": reason})

    tier = candidate["reference"].get("market_cap_tier")
    award(
        "market cap",
        {"large": 3.0, "mid": 1.5, "small": 0.0}.get(tier, 0.0),
        f"NSE index membership puts it in the {tier} tier"
        if tier
        else "no NSE index membership found; size unknown",
    )
    turnover = candidate["liquidity"]["turnover_inr"]
    floor = float(settings["min_turnover_inr"])
    if turnover is None:
        award("liquidity", 0.0, "no stored sessions to measure traded value")
    else:
        multiple = turnover / floor if floor else 0
        award(
            "liquidity",
            min(3.0, multiple),
            f"20-session mean traded value INR {turnover:,.0f}, {multiple:.1f}x the floor",
        )
    trend = candidate["technical"]["trend"]["label"]
    award(
        "trend",
        {"up": 2.0, "mixed": 0.5, "down": 0.0, "unknown": 0.0}[trend],
        candidate["technical"]["trend"]["reason"],
    )
    band = candidate["technical"]["rsi"]["band"]
    award(
        "momentum",
        {"strong": 1.5, "neutral": 0.5, "overbought": 0.0, "weak": 0.0, "oversold": 0.0,
         "unknown": 0.0}[band],
        candidate["technical"]["rsi"]["note"],
    )  # fmt: skip
    sector = candidate["sector"]
    if sector.get("available"):
        five = sector.get("return5_pct") or 0.0
        award(
            "sector",
            1.5 if five > 0 else 0.0,
            f"{sector['index']} is {'up' if five > 0 else 'down'} {abs(five):.2f}% over 5 sessions",
        )
    else:
        award("sector", 0.0, sector.get("reason", "sector index not stored"))
    mood = candidate["news"]
    if mood["scored"] >= int(settings.get("min_scored_headlines", 3)):
        award(
            "headline tone",
            {"bullish": 1.0, "leaning bullish": 0.5}.get(mood["band"], 0.0)
            - (
                1.0
                if mood["band"] == "bearish"
                else 0.5
                if mood["band"] == "leaning bearish"
                else 0.0
            ),
            f"{mood['scored']} scored headlines read {mood['band']}",
        )
    else:
        award("headline tone", 0.0, f"only {mood['scored']} scored headlines; too few to weigh")
    total = sum(part["points"] for part in parts)
    return {"total": round(total, 2), "parts": parts, "maximum": 12.0}


def build(config_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    """Assemble the pre-market report for every instrument in the universe."""
    from decision_pipeline import DailyCoordinator, read_json

    coordinator = DailyCoordinator(config_path)
    clock = (now or dt.datetime.now(IST)).astimezone(IST)
    settings = {
        "min_turnover_inr": coordinator.config["min_turnover_inr"],
        "min_scored_headlines": coordinator.config.get("min_scored_headlines", 3),
    }
    universe = read_json(coordinator.path("universe"))
    history = HistoryStore(coordinator.path("history_db"))
    reference = ReferenceStore(coordinator.path("reference_db"))
    try:
        news = read_json(coordinator.path("research_evidence"))
    except (OSError, ValueError):
        news = {}
    candidates, blocked = [], []
    for instrument in universe.get("instruments", [])[:20]:
        symbol = instrument.get("symbol", "")
        facts = reference.lookup(symbol, clock)
        entry: dict[str, Any] = {
            "symbol": symbol,
            "name": instrument.get("name", ""),
            "reference": facts,
            "fno": {
                "eligible": facts.get("fno_eligible", False),
                "lot_size": facts.get("lot_size"),
                "note": "F&O eligibility and lot size are shown for context. This desk trades "
                "cash equity only; no derivative position is sized or placed here.",
            },
        }
        try:
            rows = technical.daily_bars(history, symbol, clock)
            snapshot = technical.snapshot(rows)
            values = snapshot["values"]
            entry["technical"] = {
                "session": snapshot["session"],
                "sessions_used": snapshot["sessions_used"],
                "close": values["close"],
                "rsi14": values["rsi14"],
                "rsi": rsi_band(values["rsi14"]),
                "trend": trend_of(values),
                "return5_pct": values["return5_pct"],
                "return20_pct": values["return20_pct"],
                "atr14": values["atr14"],
                "high20": values["high20"],
            }
            turnover = (
                sum(row["close"] * row["volume"] for row in rows[-20:]) / min(20, len(rows))
                if rows
                else None
            )
            entry["liquidity"] = {
                "turnover_inr": turnover,
                "sessions": len(rows),
                "basis": "mean of close x volume over the last 20 stored sessions",
            }
        except (ValueError, KeyError, sqlite3.Error) as exc:
            blocked.append({"symbol": symbol, "reason": str(exc)})
            continue
        index_name = facts.get("sector_index")
        entry["sector"] = (
            reference.sector_performance(index_name, clock)
            if index_name
            else {
                "available": False,
                "reason": "no sector index mapped for "
                + (facts.get("sector") or "an unknown sector"),
            }
        )
        entry["news"] = sentiment.summarize(news.get(symbol, []), clock.isoformat())
        entry["score"] = score(entry, settings)
        candidates.append(entry)
    candidates.sort(key=lambda item: item["score"]["total"], reverse=True)
    top = int(coordinator.config["max_candidates"])
    for rank, item in enumerate(candidates, 1):
        item["rank"] = rank
        item["watch"] = rank <= top
    return {
        "as_of": clock.isoformat(),
        "session_date": str(clock.date()),
        "mode": "pre_market_research",
        "watching": [item["symbol"] for item in candidates[:top]],
        "candidates": candidates,
        "blocked": blocked,
        "universe_source": universe.get("source"),
        "reference_refreshed": next(
            (
                item["reference"].get("refreshed_at")
                for item in candidates
                if item["reference"].get("known")
            ),
            None,
        ),
        "notice": "A watchlist built before the open from stored sessions and collected "
        "headlines. It is not a trade list, not advice and not a forecast. Every entry "
        "still needs a completed-bar signal, fresh pre-trade evidence, the review roles "
        "and the journal's own gates during market hours.",
    }


def esc(value: Any) -> str:
    return html.escape("—" if value is None else str(value))


def _rupees(value: Any) -> str:
    return f"INR {float(value):,.0f}" if isinstance(value, (int, float)) else "—"


def render(report: dict) -> str:
    """One self-contained page. Every value is escaped; collected text is data."""
    rows = []
    for item in report["candidates"]:
        technicals = item["technical"]
        mood = item["news"]
        calls = "".join(
            f"<li>{esc(call['broker'])}: {esc(call['rating'] or 'no rating stated')}"
            + (f", target INR {esc(call['target_inr'])}" if call.get("target_inr") else "")
            + f'<br><span class="q">{esc(call["title"])}</span></li>'
            for call in mood["broker_calls"][:5]
        )
        headlines = "".join(
            f'<li><span class="band {esc(entry["band"]).replace(" ", "-")}">{esc(entry["band"])}</span> '
            f'{esc(entry["title"])}<br><span class="q">{esc(entry.get("published_at"))} · {esc(entry.get("source"))}</span></li>'
            for entry in mood["items"][:6]
        )
        factors = "".join(
            f"<tr><td>{esc(part['factor'])}</td><td class='n'>{esc(part['points'])}</td>"
            f"<td>{esc(part['reason'])}</td></tr>"
            for part in item["score"]["parts"]
        )
        rows.append(
            f"""<article class="card{" watch" if item["watch"] else ""}">
<h3>#{esc(item["rank"])} {esc(item["symbol"])} <small>{esc(item["name"])}</small>
<span class="score">{esc(item["score"]["total"])} / {esc(item["score"]["maximum"])}</span></h3>
<p class="meta">{esc(item["reference"].get("sector") or "sector unknown")} ·
{esc(item["reference"].get("market_cap_tier") or "tier unknown")} cap ·
{"F&amp;O eligible, lot " + esc(item["fno"]["lot_size"]) if item["fno"]["eligible"] else "not F&amp;O eligible"} ·
liquidity {_rupees(item["liquidity"]["turnover_inr"])}</p>
<p>Trend <strong>{esc(technicals["trend"]["label"])}</strong> ({esc(technicals["trend"]["reason"])}).
RSI <strong>{esc(technicals["rsi14"])}</strong> — {esc(technicals["rsi"]["note"])}.
Last close INR {esc(technicals["close"])} on {esc(technicals["session"])}; 5-session
{esc(technicals["return5_pct"])}%, 20-session {esc(technicals["return20_pct"])}%.</p>
<p>Sector: {esc(item["sector"].get("index") or "unmapped")} —
{("up/down " + esc(item["sector"].get("return5_pct")) + "% over 5 sessions") if item["sector"].get("available") else esc(item["sector"].get("reason"))}.</p>
<p>Headlines: <strong>{esc(mood["band"])}</strong> from {esc(mood["scored"])} scored of
{esc(mood["headlines"])} collected ({esc(mood["confidence"])} confidence).</p>
{f"<h4>Broker calls stated in headlines</h4><ul>{calls}</ul>" if calls else ""}
{f"<h4>Recent headlines</h4><ul>{headlines}</ul>" if headlines else ""}
<details><summary>How this rank was scored</summary>
<table><tr><th>Factor</th><th>Points</th><th>Reason</th></tr>{factors}</table></details>
</article>"""
        )
    blocked = "".join(
        f"<li>{esc(item['symbol'])}: {esc(item['reason'])}</li>" for item in report["blocked"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pre-market watchlist {esc(report["session_date"])}</title><style>
:root{{--ink:#252532;--muted:#7d7a8a;--line:#eaeaf0;--purple:#7760ce;--green:#358977;--red:#bb5a65;
font-family:Inter,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:#f6f6f9}}
body{{margin:0;padding:28px 16px;line-height:1.55}}main{{max-width:840px;margin:0 auto}}
h1{{font-size:26px;margin:0 0 4px;letter-spacing:-.5px}}h3{{margin:0 0 6px;font-size:16px}}
h4{{margin:14px 0 4px;font-size:13px;color:var(--muted)}}
small{{font-weight:400;color:var(--muted)}}
.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:14px 0}}
.card.watch{{border-color:#c5b3ea;box-shadow:0 2px 14px #7760ce1a}}
.score{{float:right;font-size:13px;color:var(--purple);font-weight:600}}
.meta{{color:var(--muted);font-size:13px;margin:2px 0 10px}}
p{{margin:8px 0;font-size:14px}}ul{{margin:4px 0;padding-left:18px;font-size:13px}}
li{{margin:5px 0}}.q{{color:var(--muted);font-size:12px}}
.band{{display:inline-block;padding:0 6px;border-radius:999px;font-size:11px;font-weight:600;
background:#f0ecfb;color:var(--purple)}}
.band.bullish,.band.leaning-bullish{{background:#e6f3ef;color:var(--green)}}
.band.bearish,.band.leaning-bearish{{background:#fae9ec;color:var(--red)}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin-top:6px}}
td,th{{text-align:left;padding:5px 7px;border-bottom:1px solid var(--line)}}td.n{{text-align:right}}
summary{{cursor:pointer;font-size:12px;color:var(--muted);margin-top:10px}}
.notice{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 20px;font-size:13px}}
footer{{margin-top:28px;font-size:12px;color:var(--muted)}}</style></head>
<body><main>
<h1>Pre-market watchlist</h1>
<p class="meta">{esc(report["as_of"])} · watching {esc(", ".join(report["watching"]) or "nothing")}</p>
<div class="notice"><strong>{esc(report["notice"])}</strong></div>
{"".join(rows) or '<div class="card">No instrument had enough stored history to assess.</div>'}
{f'<div class="card"><h4>Not assessed</h4><ul>{blocked}</ul></div>' if blocked else ""}
<footer>India Trade Lab · universe: {esc(report["universe_source"])} ·
reference refreshed {esc(report["reference_refreshed"])}</footer>
</main></body></html>
"""


def send_email(report: dict, page: str, config: dict) -> dict[str, Any]:
    """Send the report over SMTP. Off unless smtp_host and recipients are configured."""
    host, recipients = config.get("smtp_host"), config.get("email_to")
    if not host or not recipients:
        return {"sent": False, "reason": "email is not configured (smtp_host and email_to)"}
    password = os.environ.get("SMTP_PASSWORD")
    if not password:
        return {"sent": False, "reason": "SMTP_PASSWORD is not set in this environment"}
    message = EmailMessage()
    message["Subject"] = f"Pre-market watchlist {report['session_date']}: " + (
        ", ".join(report["watching"]) or "nothing today"
    )
    message["From"] = config.get("email_from") or config["smtp_user"]
    message["To"] = ", ".join(recipients) if isinstance(recipients, list) else recipients
    message.set_content(
        f"{report['notice']}\n\nWatching: {', '.join(report['watching']) or 'nothing'}\n"
        "Open the attached HTML for the full report."
    )
    message.add_alternative(page, subtype="html")
    try:
        with smtplib.SMTP(host, int(config.get("smtp_port", 587)), timeout=30) as smtp:
            smtp.starttls()
            smtp.login(config["smtp_user"], password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        # Never echo the server's reply: it can carry the account address or token state.
        return {
            "sent": False,
            "reason": "the mail server refused the message or could not be reached",
        }
    return {"sent": True, "to": message["To"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
    parser.add_argument("--as-of", help="Aware ISO timestamp; defaults to now")
    parser.add_argument("--html", type=Path, help="Write the page here as well")
    parser.add_argument("--email", action="store_true", help="Send it over configured SMTP")
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON")
    args = parser.parse_args(argv)
    try:
        clock = dt.datetime.fromisoformat(args.as_of) if args.as_of else None
        report = build(args.config, clock)
        page = render(report)
        destination = args.html
        if destination is None:
            from decision_pipeline import DailyCoordinator

            folder = DailyCoordinator(args.config).path("reports_dir")
            destination = folder / f"premarket-{report['session_date']}.html"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(page, encoding="utf-8")
        report["report_html"] = str(destination)
        if args.email:
            from decision_pipeline import DailyCoordinator

            report["email"] = send_email(report, page, DailyCoordinator(args.config).config)
        print(
            json.dumps(report, indent=2, default=str)
            if args.json
            else json.dumps(
                {
                    "session_date": report["session_date"],
                    "watching": report["watching"],
                    "report_html": report["report_html"],
                    "email": report.get("email"),
                    "blocked": report["blocked"],
                },
                indent=2,
            )
        )
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        print("DATA_BLOCK: " + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())

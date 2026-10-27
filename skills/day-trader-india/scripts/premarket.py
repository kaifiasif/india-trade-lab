#!/usr/bin/env python3
"""Pre-market report: what the desk is watching today, and why, with its evidence.

For each instrument in the universe it assembles, from sources already stored or
collected: the trend and RSI from stored sessions, the sector and how that sector
index has moved, NSE's market-cap tier, traded-value liquidity, F&O eligibility
and lot size, collected headlines with their sentiment, and any broker call a
headline states. Each candidate is then ranked by a transparent score whose every
component is shown with the reason it was awarded.

Selection runs in two stages. Hard filters come first and are code, not opinion:
enough stored history, traded value above the floor, a known NSE market-cap tier
at or above the configured minimum, and fresh reference data. The stocks that
pass form the pool. Six specialist agents (news, sentiment, technical, sector,
liquidity, brokerage) then assess the pool and the selection judge makes the
final call on what to watch (see selection_agents.py). Without a configured
model the deterministic ranking is used, and the report says which happened.

This is a watchlist, not a trade list and not a forecast. A pick means the
instrument is worth watching at the open; it is not an entry. An entry still needs a completed-bar signal, fresh pre-trade
evidence, the review roles and every journal gate, during market hours.

Read only: no order path, no journal write. Email is off unless configured.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import smtplib
import sqlite3
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import technical
from history import HistoryStore

import selection_agents
import sentiment
import strategies
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


def hard_filters(candidate: dict, settings: dict) -> list[str]:
    """Reasons a stock is kept out of the pool. Empty means it passed. Code, not opinion."""
    reasons = []
    ref = candidate["reference"]
    minimum = settings["min_market_cap_tier"]
    if not ref.get("known"):
        reasons.append(
            "not in the cached NSE index files, so its size is unknown; run reference.py refresh"
        )
    else:
        tier = ref.get("market_cap_tier")
        if TIER_RANK.get(tier, 0) < TIER_RANK[minimum]:
            reasons.append(f"{tier or 'unclassified'} cap is below the {minimum}-cap minimum")
        if ref.get("stale_days", 0) > settings["max_reference_age_days"]:
            reasons.append(
                f"reference data is {ref['stale_days']} days old (limit "
                f"{settings['max_reference_age_days']}); run reference.py refresh"
            )
    turnover = candidate["liquidity"]["turnover_inr"]
    floor = float(settings["min_turnover_inr"])
    if turnover is None or turnover < floor:
        reasons.append(
            f"traded value {_rupees(turnover)} is below the INR {floor:,.0f} liquidity floor"
        )
    return reasons


def build(
    config_path: Path, now: dt.datetime | None = None, reviewer: Any = None
) -> dict[str, Any]:
    """Assemble the pre-market report: score, filter, then let the agents and judge choose."""
    from decision_pipeline import DailyCoordinator, read_json

    coordinator = DailyCoordinator(config_path, reviewer=reviewer)
    clock = (now or dt.datetime.now(IST)).astimezone(IST)
    chooser = coordinator.config["selection"]
    settings = {
        "min_turnover_inr": coordinator.config["min_turnover_inr"],
        "min_scored_headlines": coordinator.config.get("min_scored_headlines", 3),
        "min_market_cap_tier": chooser["min_market_cap_tier"],
        "max_reference_age_days": chooser["max_reference_age_days"],
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
        try:
            rows = technical.daily_bars(history, symbol, clock)
            index_name = facts.get("sector_index")
            sector = (
                reference.sector_performance(index_name, clock)
                if index_name
                else {
                    "available": False,
                    "reason": "no sector index mapped for "
                    + (facts.get("sector") or "an unknown sector"),
                }
            )
            candidates.append(
                describe(
                    symbol,
                    instrument.get("name", ""),
                    facts,
                    rows,
                    sector,
                    news.get(symbol, []),
                    clock,
                    settings,
                )
            )
        except (ValueError, KeyError, sqlite3.Error) as exc:
            blocked.append({"symbol": symbol, "reason": str(exc)})
    session = str(clock.date())
    playbook = strategies.allowed_for(
        coordinator.config_path.parent, coordinator.config["strategy"], "", session
    )
    try:
        card = json.loads(
            strategies.scorecard_path(coordinator.config_path.parent).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        card = {}
    top = int(coordinator.config["max_candidates"])

    def run(pool: list[dict], proven: dict) -> dict:
        if not chooser["agents"]:
            return {
                "mode": "deterministic",
                "reason": "selection agents are turned off in pipeline.json; this is the "
                "deterministic ranking",
                "pool": [item["symbol"] for item in pool],
                "watching": [item["symbol"] for item in pool[:top]],
                "judge": None,
                "specialists": {},
                "model_calls": 0,
            }
        return selection_agents.run_selection(
            pool,
            session,
            coordinator.reviewer,
            top,
            reserve=lambda count: coordinator.store.reserve_model_calls(
                session, count, coordinator.config["max_model_calls_per_day"]
            ),
            min_specialists=chooser["min_specialists"],
            proven=proven,
            finalist_count=chooser["finalists"],
        )

    return assemble(
        candidates,
        blocked,
        settings,
        playbook,
        card,
        run,
        chooser["pool"],
        clock,
        universe.get("source"),
    )


def describe(
    symbol: str,
    name: str,
    facts: dict,
    rows: list[dict],
    sector: dict,
    news_items: list[dict],
    clock: dt.datetime,
    settings: dict,
) -> dict[str, Any]:
    """One stock's report entry from its reference facts, daily bars, sector and headlines."""
    snapshot = technical.snapshot(rows)
    values = snapshot["values"]
    entry: dict[str, Any] = {
        "symbol": symbol,
        "name": name,
        "reference": facts,
        "fno": {
            "eligible": facts.get("fno_eligible", False),
            "lot_size": facts.get("lot_size"),
            "note": "F&O eligibility and lot size are shown for context. This desk trades "
            "cash equity only; no derivative position is sized or placed here.",
        },
        "technical": {
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
        },
        "liquidity": {
            "turnover_inr": sum(row["close"] * row["volume"] for row in rows[-20:])
            / min(20, len(rows)),
            "sessions": len(rows),
            "basis": "mean of close x volume over the last 20 stored sessions",
        },
        "sector": sector,
        "news": sentiment.summarize(news_items, clock.isoformat()),
    }
    entry["score"] = score(entry, settings)
    entry["filters"] = hard_filters(entry, settings)
    entry["eligible"] = not entry["filters"]
    return entry


def assemble(
    candidates: list[dict],
    blocked: list[dict],
    settings: dict,
    playbook: dict,
    card: dict,
    run,
    pool_size: int,
    clock: dt.datetime,
    universe_source: str | None,
) -> dict[str, Any]:
    """Rank, pool, let the agents choose (or sit out), and shape the report."""
    candidates.sort(key=lambda item: item["score"]["total"], reverse=True)
    for rank, item in enumerate(candidates, 1):
        item["rank"] = rank
    pool = [item for item in candidates if item["eligible"]][:pool_size]
    session = str(clock.date())
    proven = {}
    for name in playbook["allowed"]:
        result = (card.get("strategies") or {}).get(name) or {}
        proven[name] = {
            "description": strategies.DESCRIPTIONS[name],
            "tournament_doubled_costs": {
                key: (result.get("doubled_costs") or {}).get(key)
                for key in ("trades", "net_inr", "win_rate_pct", "profit_factor")
            },
        }
    if not playbook["allowed"]:
        selection = {
            "mode": "sit_out",
            "reason": playbook["basis"],
            "pool": [item["symbol"] for item in pool],
            "watching": [],
            "judge": None,
            "specialists": {},
            "model_calls": 0,
        }
    else:
        selection = run(pool, proven)
    picks = {pick["symbol"]: pick for pick in (selection["judge"] or {}).get("picks", [])}
    for item in candidates:
        symbol = item["symbol"]
        item["watch"] = symbol in selection["watching"]
        item["judge_pick"] = picks.get(symbol)
        item["agent_views"] = {
            role: view["assessments"][symbol]
            for role, view in selection.get("specialists", {}).items()
            if view["status"] == "ok" and symbol in view["assessments"]
        }
    order = {symbol: index for index, symbol in enumerate(selection["watching"])}
    candidates.sort(key=lambda item: (order.get(item["symbol"], len(order)), item["rank"]))
    return {
        "as_of": clock.isoformat(),
        "session_date": session,
        "mode": "pre_market_research",
        "watching": selection["watching"],
        "selection": {
            key: selection.get(key)
            for key in ("mode", "reason", "pool", "judge", "model_calls", "finalists")
        }
        | {"strategies": proven, "strategy_basis": playbook["basis"]}
        | {
            "specialists": {
                role: {
                    "status": view["status"],
                    **({"reason": view["reason"]} if "reason" in view else {}),
                    **{key: view[key] for key in ("provider", "model") if key in view},
                }
                for role, view in selection.get("specialists", {}).items()
            },
            "filters": {
                "min_market_cap_tier": settings["min_market_cap_tier"],
                "min_turnover_inr": settings["min_turnover_inr"],
                "max_reference_age_days": settings["max_reference_age_days"],
            },
        },
        "candidates": candidates,
        "blocked": blocked,
        "universe_source": universe_source,
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


def _num(value: Any, places: int = 2) -> str:
    return f"{float(value):.{places}f}" if isinstance(value, (int, float)) else "—"


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
        pick = item.get("judge_pick")
        verdict = (
            f'<p class="pick"><strong>Judge: {esc(pick["rating"])}, {esc(pick["conviction"])} '
            f"conviction, trade with {esc(pick.get('strategy'))}.</strong> "
            f"{esc(pick['reason'])}</p>"
            if pick
            else '<p class="pick">On the watchlist by deterministic rank.</p>'
            if item["watch"]
            else ""
        )
        filtered = (
            "<p class='filtered'>Kept out of the pool: " + esc("; ".join(item["filters"])) + ".</p>"
            if item["filters"]
            else ""
        )
        views = "".join(
            f"<tr><td>{esc(role)}</td><td><span class='stance {esc(view['stance'])}'>"
            f"{esc(view['stance'])}</span></td><td>{esc(view['summary'])}</td></tr>"
            for role, view in item.get("agent_views", {}).items()
        )
        scouts = (report["selection"].get("finalists") or {}).get(item["symbol"]) or {}
        risk = scouts.get("risk-scout") or {}
        setup = scouts.get("setup-planner") or {}
        subagents = (
            "<h4>Judge's sub-agents</h4><ul>"
            + (
                f"<li>Risk scout: <strong>{esc(risk.get('risk_level'))}</strong> — "
                f"{esc(risk.get('risks'))}</li>"
                if risk.get("risk_level")
                else "<li>Risk scout: unavailable</li>"
            )
            + (
                f"<li>Setup planner: <strong>{esc(setup.get('strategy'))}</strong> — "
                f"{esc(setup.get('plan'))}</li>"
                if setup.get("strategy")
                else "<li>Setup planner: unavailable</li>"
            )
            + "</ul>"
            if scouts
            else ""
        )
        sector = item["sector"]
        sector_line = (
            f"{esc(sector.get('direction'))} {esc(sector.get('return1_pct'))}% last session, "
            f"{esc(sector.get('return5_pct'))}% over 5, {esc(sector.get('return20_pct'))}% over 20"
            if sector.get("available")
            else esc(sector.get("reason"))
        )
        rows.append(
            f"""<article class="card{" watch" if item["watch"] else ""}">
<h3>#{esc(item["rank"])} {esc(item["symbol"])} <small>{esc(item["name"])}</small>
<span class="score">{esc(item["score"]["total"])} / {esc(item["score"]["maximum"])}</span></h3>
<p class="meta">{esc(item["reference"].get("sector") or "sector unknown")} ·
{esc(item["reference"].get("market_cap_tier") or "tier unknown")} cap ·
{"F&amp;O eligible, lot " + esc(item["fno"]["lot_size"]) if item["fno"]["eligible"] else "not F&amp;O eligible"} ·
liquidity {_rupees(item["liquidity"]["turnover_inr"])}</p>
{verdict}{filtered}
<p>Trend <strong>{esc(technicals["trend"]["label"])}</strong> ({esc(technicals["trend"]["reason"])}).
RSI <strong>{_num(technicals["rsi14"], 1)}</strong> — {esc(technicals["rsi"]["note"])}.
Last close INR {_num(technicals["close"])} on {esc(technicals["session"])}; 5-session
{_num(technicals["return5_pct"])}%, 20-session {_num(technicals["return20_pct"])}%.</p>
<p>Sector: {esc(sector.get("index") or "unmapped")} — {sector_line}.</p>
<p>Headlines: <strong>{esc(mood["band"])}</strong> from {esc(mood["scored"])} scored of
{esc(mood["headlines"])} collected ({esc(mood["confidence"])} confidence).</p>
{f"<h4>Broker calls stated in headlines</h4><ul>{calls}</ul>" if calls else ""}
{f"<h4>Recent headlines</h4><ul>{headlines}</ul>" if headlines else ""}
{subagents}
{f"<h4>Specialist agents</h4><table><tr><th>Agent</th><th>Stance</th><th>Assessment</th></tr>{views}</table>" if views else ""}
<details><summary>How this rank was scored</summary>
<table><tr><th>Factor</th><th>Points</th><th>Reason</th></tr>{factors}</table></details>
</article>"""
        )
    chosen = report["selection"]
    judge = chosen.get("judge") or {}
    agents = "".join(
        f"<li>{esc(role)}: {esc(view['status'])}"
        + (f" ({esc(view['model'])})" if view.get("model") else "")
        + (f" — {esc(view['reason'])}" if view.get("reason") else "")
        + "</li>"
        for role, view in chosen.get("specialists", {}).items()
    )
    limits = chosen["filters"]
    proven = chosen.get("strategies") or {}

    def tested(stats: dict) -> str:
        if stats.get("trades") is None:
            return ""
        return (
            f" — tournament at double costs: {esc(stats['trades'])} trades, net "
            f"{_rupees(stats.get('net_inr'))}, profit factor {esc(stats.get('profit_factor'))}"
        )

    playbook = "".join(
        f"<li><strong>{esc(name)}</strong>: {esc(item['description'])}"
        f"{tested(item['tournament_doubled_costs'])}</li>"
        for name, item in proven.items()
    )
    dropped = "".join(
        f"<li>{esc(item['symbol'])}: {esc(item['dropped'])}</li>"
        for item in (judge.get("dropped") or [])
    )
    panel = f"""<div class="card judge"><h3>Final call: {esc(chosen["mode"])}</h3>
<p>{esc(chosen["reason"])}.</p>
{f"<p><strong>Judge:</strong> {esc(judge['summary'])}</p>" if judge.get("summary") else ""}
<p class="meta">Hard filters: {esc(limits["min_market_cap_tier"])} cap or bigger, traded value at least
{_rupees(limits["min_turnover_inr"])}, reference data at most {esc(limits["max_reference_age_days"])} days old.
Pool: {esc(", ".join(chosen["pool"] or []) or "empty")} · model calls {esc(chosen["model_calls"])}</p>
<h4>Strategies allowed today</h4>
{f"<ul>{playbook}</ul>" if playbook else f"<p>None. {esc(chosen.get('strategy_basis'))}.</p>"}
{f"<h4>Dropped by sub-agents</h4><ul>{dropped}</ul>" if dropped else ""}
{f"<h4>Agents</h4><ul>{agents}</ul>" if agents else ""}</div>"""
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
.pick{{background:#f0ecfb;border-radius:10px;padding:8px 12px}}
.filtered{{color:var(--red);font-size:13px}}
.stance{{display:inline-block;padding:0 6px;border-radius:999px;font-size:11px;font-weight:600;
background:#f0ecfb;color:var(--purple)}}.stance.positive{{background:#e6f3ef;color:var(--green)}}
.stance.negative{{background:#fae9ec;color:var(--red)}}
.card.judge{{border-color:#c5b3ea}}
.notice{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 20px;font-size:13px}}
footer{{margin-top:28px;font-size:12px;color:var(--muted)}}</style></head>
<body><main>
<h1>Pre-market watchlist</h1>
<p class="meta">{esc(report["as_of"])} · watching {esc(", ".join(report["watching"]) or "nothing")}</p>
<div class="notice"><strong>{esc(report["notice"])}</strong></div>
{panel}
{"".join(rows) or '<div class="card">No instrument had enough stored history to assess.</div>'}
{f'<div class="card"><h4>Not assessed</h4><ul>{blocked}</ul></div>' if blocked else ""}
<footer>India Trade Lab · universe: {esc(report["universe_source"])} ·
reference refreshed {esc(report["reference_refreshed"])}</footer>
</main></body></html>
"""


def send_email(report: dict, page: str, config: dict) -> dict[str, Any]:
    """Send the report over SMTP. Off unless smtp_host, smtp_user and recipients are set.

    The password comes from the environment or the owner-only secret store, never JSON.
    """
    import secret_store

    recipients = config.get("email_to")
    if not recipients:
        return {"sent": False, "reason": "email is not configured (email_to)"}
    if not config.get("smtp_host") or not config.get("smtp_user"):
        return {"sent": False, "reason": "set the mail server and sender in Setup → Email"}
    password = os.environ.get("SMTP_PASSWORD") or secret_store.get("SMTP_PASSWORD")
    if not password:
        return {"sent": False, "reason": "no SMTP password saved (Setup → Email)"}
    if not public_mail_host(config["smtp_host"]):
        return {"sent": False, "reason": "the mail server must be a public host name"}
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
        with smtplib.SMTP(
            config["smtp_host"], int(config.get("smtp_port", 587)), timeout=30
        ) as smtp:
            smtp.starttls()
            smtp.login(config["smtp_user"], password)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        return {"sent": False, "reason": "the mail server rejected the sender or app password"}
    except (OSError, smtplib.SMTPException):
        # Never echo the server's reply: it can carry the account address or token state.
        return {
            "sent": False,
            "reason": "the mail server refused the message or could not be reached",
        }
    return {"sent": True, "to": secret_store.mask_email(message["To"])}


def public_mail_host(host: str) -> bool:
    """Refuse IP literals and names that resolve to private, loopback or link-local
    addresses, so a settings change cannot point the mailer at internal services."""
    import ipaddress
    import socket

    if not re.fullmatch(r"(?=.{1,253}$)([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}", host or ""):
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(item).is_global for item in addresses)


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
        from decision_pipeline import DailyCoordinator

        # The paper autopilot reads today's judge picks from this file.
        picks = DailyCoordinator(args.config).path("reports_dir") / (
            f"premarket-{report['session_date']}.json"
        )
        picks.parent.mkdir(parents=True, exist_ok=True)
        picks.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
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
                    "final_call": report["selection"]["mode"],
                    "why": report["selection"]["reason"],
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

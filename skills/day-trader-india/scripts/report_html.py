"""One self-contained HTML page per research run: no scripts, no external assets.

Every value is HTML-escaped: evidence, model text and provider output are data.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

STYLE = """
:root{--ink:#252532;--muted:#7d7a8a;--line:#eaeaf0;--purple:#7760ce;--lav:#f0ecfb;
--green:#358977;--red:#bb5a65;--amber:#a87a1e;font-family:Inter,-apple-system,"Segoe UI",sans-serif;
color:var(--ink);background:#f6f6f9}
body{margin:0;padding:32px 16px;line-height:1.5}
main{max-width:920px;margin:0 auto}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.5px}
h2{font-size:18px;margin:32px 0 10px}
h3{font-size:15px;margin:18px 0 6px}
.meta{color:var(--muted);font-size:13px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:12px 0}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;
background:var(--lav);color:var(--purple)}
.Buy,.Overweight,.BUY_PAPER_PROPOSAL{background:#e6f3ef;color:var(--green)}
.Underweight,.Sell,.NO_TRADE,.DATA_BLOCK{background:#fae9ec;color:var(--red)}
.Hold,.WAIT,.WAIT_ALLOCATION{background:#fbf3e2;color:var(--amber)}
.turn{border-left:3px solid var(--line);padding:4px 0 4px 14px;margin:10px 0}
.turn.bull-researcher{border-color:var(--green)}.turn.bear-researcher{border-color:var(--red)}
.turn strong{font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px}
td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.small{font-size:12px;color:var(--muted)}
footer{margin-top:40px;font-size:12px;color:var(--muted)}
"""

ROLE_TITLES = {
    "bull-researcher": "Bull researcher",
    "bear-researcher": "Bear researcher",
    "risk-aggressive": "Aggressive risk",
    "risk-conservative": "Conservative risk",
    "risk-neutral": "Neutral risk",
}


def esc(value: Any) -> str:
    return html.escape("—" if value is None else str(value))


def badge(value: Any) -> str:
    text = esc(value)
    return f'<span class="badge {text}">{text.replace("_", " ")}</span>'


def _turns(turns: list[dict]) -> str:
    parts = []
    for turn in turns:
        title = ROLE_TITLES.get(turn.get("role"), turn.get("role"))
        rebuttal = (
            f"<p><em>Rebuttal:</em> {esc(turn['rebuttal'])}</p>" if turn.get("rebuttal") else ""
        )
        parts.append(
            f'<div class="turn {esc(turn.get("role"))}"><strong>{esc(title)} · round '
            f"{esc(turn.get('round'))}</strong><p>{esc(turn.get('argument'))}</p>{rebuttal}"
            f'<p class="small">Cites: {esc(", ".join(turn.get("evidence_ids", [])) or "none")}</p></div>'
        )
    return "".join(parts) or '<p class="small">No turns recorded.</p>'


def _call(call: dict) -> str:
    proposal = call.get("proposal") or {}
    debate = call.get("debate") or {}
    plan, decision = debate.get("plan") or {}, debate.get("decision") or {}
    rows = "".join(
        f"<tr><th>{esc(key)}</th><td>{esc(proposal.get(key))}</td></tr>"
        for key in (
            "side",
            "qty",
            "price_inr",
            "stop_inr",
            "target_inr",
            "quote_as_of",
            "quote_source",
        )
        if key in proposal
    )
    reviews = (call.get("agent_review") or {}).get("packet", {}).get("reports", [])
    review_rows = "".join(
        f"<tr><td>{esc(r.get('role'))}</td><td>{badge(r.get('decision'))}</td><td>{esc(r.get('summary'))}</td></tr>"
        for r in reviews
    )
    body = [
        f'<div class="card"><h3>{esc(call.get("symbol"))} {badge(call.get("decision"))} '
        f"{badge(call['rating']) if call.get('rating') else ''}</h3>",
        f"<p>{esc(' · '.join(call.get('reasons') or []))}</p>",
    ]
    if rows:
        body.append(f"<table>{rows}</table>")
    if review_rows:
        body.append(f"<h3>Evidence reviews</h3><table>{review_rows}</table>")
    if debate:
        body.append("<h3>Investment debate</h3>" + _turns(debate.get("research", [])))
        if plan:
            body.append(
                f"<p><strong>Research manager:</strong> {badge(plan.get('rating'))} {esc(plan.get('rationale'))}</p>"
            )
        if debate.get("risk"):
            body.append("<h3>Risk debate</h3>" + _turns(debate["risk"]))
        if decision:
            body.append(
                f"<p><strong>Portfolio manager:</strong> {badge(decision.get('rating'))} "
                f"{esc(decision.get('conviction'))} conviction. {esc(decision.get('thesis'))}</p>"
                f"<p class='small'>Invalidation: {esc(decision.get('invalidation'))}</p>"
            )
        if debate.get("failures"):
            body.append(f"<p class='small'>Failed roles: {esc(', '.join(debate['failures']))}</p>")
    body.append("</div>")
    return "".join(body)


def render(report: dict) -> str:
    memory = report.get("memory") or {}
    score_rows = "".join(
        f"<tr><td>{badge(rating)}</td><td>{esc(row['count'])}</td><td>{esc(row['hit_rate_pct'])}</td>"
        f"<td>{esc(row['mean_raw_return_pct'])}</td><td>{esc(row['mean_alpha_pp'])}</td></tr>"
        for rating, row in ((memory.get("scorecard") or {}).get("by_rating") or {}).items()
    )
    shortlist = (report.get("shortlist") or {}).get("candidates", [])
    calls = "".join(_call(call) for call in report.get("calls", [])) or (
        '<p class="small">No calls in this run.</p>'
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Research run {esc(report.get("run_id", "")[:8])}</title><style>{STYLE}</style></head>
<body><main>
<h1>Paper research run</h1>
<p class="meta">{esc(report.get("as_of"))} · {badge(report.get("status"))} · provider {esc(report.get("provider"))} · run {esc(report.get("run_id"))}</p>
<div class="card"><strong>Paper research only.</strong> No orders were placed and no paper fill was recorded by this run.
Each proposal still needs fresh validation before any manual paper fill.</div>
<h2>Shortlist</h2>
<div class="card">{esc(", ".join(item.get("symbol", "") for item in shortlist) or "No shortlist")}</div>
<h2>Calls</h2>{calls}
<h2>Blockers</h2><div class="card">{esc(" · ".join(report.get("blockers") or []) or "None")}</div>
<h2>Decision memory</h2>
<div class="card"><p class="small">Settled this run: {esc(len(memory.get("settled", [])))} · pending: {esc(memory.get("pending"))}</p>
<table><tr><th>Rating</th><th>Count</th><th>Hit rate %</th><th>Mean return %</th><th>Mean alpha pp</th></tr>{score_rows}</table>
<p class="small">{esc((memory.get("scorecard") or {}).get("notice"))}</p></div>
<footer>India Trade Lab · generated from the recorded run · <code>{esc(json.dumps(report.get("goal", {}))[:200])}</code></footer>
</main></body></html>
"""


def write(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(report), encoding="utf-8")

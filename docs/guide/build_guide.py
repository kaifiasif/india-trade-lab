"""Build "Meet the Desk", the illustrated agent guide, as HTML and PDF.

    python3 docs/guide/build_guide.py

Writes docs/guide/agents-guide.html and docs/guide/agents-guide.pdf (the PDF needs
Playwright with Chromium). Mascots come from mascots.py; text is maintained here.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mascots import MASCOTS, svg  # noqa: E402

HERE = Path(__file__).parent

# key: (team, nickname line, what it reads, what it says, what it can never do)
CARDS = {
    "scoop": (
        "The newsroom",
        "Reads every dated headline and exchange filing for each stock in the pool.",
        "Is there a real event (results, orders, guidance, a regulator, a fund raise), and is it "
        "good or bad for someone who owns the stock?",
        "Treat an old or generic market headline as news, or follow instructions hidden in one.",
    ),
    "vibe": (
        "The mood reader",
        "The same headlines, each with a word-list tone score.",
        "Is the tone real, or an artefact of wording, sarcasm, a question headline or one "
        "source? Fewer than five headlines is an anecdote.",
        "Turn a mood into a forecast.",
    ),
    "chartly": (
        "The chart reader",
        "Trend, RSI(14), 5- and 20-session returns and ATR, computed from stored prices.",
        "Up-trend with healthy momentum is positive; stretched RSI is a caution, not strength.",
        "Predict a price. Indicators describe the past only.",
    ),
    "atlas": (
        "The map keeper",
        "The stock's NSE sector and how its sector index moved over 1, 5 and 20 sessions.",
        "Is the sector helping or fighting a long position today?",
        "Call a missing sector index 'neutral'. Missing is missing.",
    ),
    "tide": (
        "The flow checker",
        "Traded value, NSE market-cap tier, F&O eligibility and lot size.",
        "Is there enough money flowing for a clean fill? F&O is shown as context only.",
        "Size or suggest a derivative trade. The desk trades cash equity only.",
    ),
    "ledger": (
        "The broker watcher",
        "Broker calls stated in headlines: who, upgrade or downgrade, target price.",
        "A downgrade or target cut is negative, an upgrade or initiation at buy is positive.",
        "Pretend it read the research note. It reads the headline only.",
    ),
    "scout": (
        "Judge's sub-agent",
        "One finalist at a time: its evidence and what the six specialists said.",
        "What could make a long lose today? Rates the risk low, medium or high.",
        "Let a high-risk pick through. If Scout says high, code drops the pick.",
    ),
    "blueprint": (
        "Judge's sub-agent",
        "One finalist, plus the strategies the tournament has proven.",
        "Which proven strategy fits this stock today, and what must happen at the open.",
        "Choose an unproven strategy or invent a price level. 'None' drops the pick.",
    ),
    "judge": (
        "The final call",
        "All six specialists, both sub-agents for every finalist, the score and the evidence.",
        "Up to three stocks to watch, each rated Buy or Overweight, with conviction, a cited "
        "reason and the proven strategy to trade it with. Picking none is allowed.",
        "Pick outside the finalists, override a filter, size a trade or place an order.",
    ),
    "bullu": (
        "Intraday debate",
        "The frozen ticket for a live setup, its evidence and past lessons.",
        "The strongest evidenced case for the trade, and what would disprove it.",
        "Change the ticket. A debate can only stop or downgrade an entry.",
    ),
    "bruno": (
        "Intraday debate",
        "The same ticket and evidence as Bullu.",
        "The strongest evidenced case against the trade. Never proposes a short sale.",
        "Change the ticket or the size.",
    ),
    "shield": (
        "Aggressive, neutral and conservative",
        "The ticket, the book, the limits and the debate so far.",
        "Three risk views argue whether the risk is worth it at this size, now.",
        "Raise a limit. Limits live in code, not in a conversation.",
    ),
    "captain": (
        "Portfolio manager",
        "The whole debate and the research manager's rating.",
        "A five-tier rating with conviction, thesis and invalidation. Only Buy or Overweight "
        "lets the entry continue.",
        "Upgrade a ticket the evidence roles vetoed.",
    ),
    "echo": (
        "The memory",
        "Each rated call once its holding window has closed on later stored prices.",
        "A short lesson (right or wrong, by how much, versus the benchmark) that later "
        "debates can read, only if it was known by then.",
        "Learn from the future.",
    ),
    "ref": (
        "Code, not AI",
        "Every strategy replayed on your stored real history, every evening.",
        "Eligible only if profitable at double costs, in most periods, including the latest. "
        "Fills are deliberately pessimistic.",
        "Be talked round. If no strategy passes, the desk sits out.",
    ),
    "pilot": (
        "Code, not AI",
        "Each minute's approved calls from the coordinator.",
        "Records the approved entry for a judge pick, and every exit: stop, breakeven, "
        "trailing, time stop, target, 15:15 square-off.",
        "Touch real money. It writes only to the virtual paper book.",
    ),
}

GLOSSARY = [
    (
        "R",
        "The money a trade risks: entry minus stop, times shares. "
        "+2R means it made twice what it risked.",
    ),
    ("Stop", "The price at which a losing trade is closed automatically."),
    (
        "Breakeven stop",
        "After +1R, the stop moves to the entry plus costs, so the trade can no longer lose.",
    ),
    ("Trailing stop", "After +1.5R, the stop follows one R below the highest price reached."),
    ("Time stop", "A trade that has not reached +0.5R within an hour is closed."),
    ("Opening range", "The high and low of the first 15 minutes (09:15-09:30)."),
    ("VWAP", "The day's volume-weighted average price: where most money changed hands."),
    ("RSI(14)", "A 0-100 momentum gauge over 14 days. Above 70-75 is stretched."),
    ("ATR", "Average true range: how far the stock typically moves in a day."),
    (
        "Profit factor",
        "Money won divided by money lost. Above 1 makes money; the desk wants "
        "1.15 or more at double costs.",
    ),
    ("Paper trading", "Trading a virtual book with real prices and no real money."),
    ("F&O lot", "The fixed contract size for futures and options. Shown, never traded."),
    (
        "Market-cap tier",
        "Large (NIFTY 100), mid (MIDCAP 150), small (SMALLCAP 250) by NSE index membership.",
    ),
]


def e(text: str) -> str:
    return html.escape(text)


def card(key: str) -> str:
    name, role, accent, _ = MASCOTS[key]
    team, reads, says, never = CARDS[key]
    return f"""<div class="card" style="--accent:{accent}">
<div class="art">{svg(key, 150)}</div>
<div class="body"><div class="name">{e(name)} <span>{e(role)}</span></div>
<div class="team">{e(team)}</div>
<p><b>Reads</b> {e(reads)}</p><p><b>Says</b> {e(says)}</p>
<p class="never"><b>Never</b> {e(never)}</p></div></div>"""


def page(content: str, number: int | None = None) -> str:
    footer = (
        f'<div class="foot">India Trade Lab · Meet the Desk<span>{number}</span></div>'
        if number
        else ""
    )
    return f'<section class="page">{content}{footer}</section>'


def build() -> str:
    lineup = "".join(
        f'<div class="mini">{svg(key, 118)}<div>{e(MASCOTS[key][0])}</div></div>' for key in MASCOTS
    )
    timeline = [
        (
            "16:10 the evening before",
            "ref",
            "Ref replays every strategy on your real history and decides which may trade tomorrow.",
        ),
        (
            "08:30",
            None,
            "You log in to Kite from your phone (2FA) and confirm the two checks a "
            "person must make: NSE surveillance lists and today's announcements.",
        ),
        (
            "08:40",
            "judge",
            "The pre-market team meets. Filters, then six specialists, then the "
            "judge and its sub-agents. The report is emailed to you.",
        ),
        (
            "09:15-14:30",
            "bullu",
            "Each minute, a live setup on a judge pick is frozen into a "
            "ticket. Evidence roles review it while Bullu, Bruno, Shield and Captain debate it.",
        ),
        (
            "All session",
            "pilot",
            "Pilot records approved entries and every protective exit in the paper book.",
        ),
        ("15:15", "pilot", "Every open position is squared off. Nothing is held overnight."),
        ("After the close", "echo", "Echo scores yesterday's calls and keeps the lesson."),
    ]
    steps = "".join(
        f'<div class="step"><div class="when">{e(when)}</div>'
        f'<div class="who">{svg(key, 70) if key else "<div class=you>You</div>"}</div>'
        f"<div class='what'>{e(what)}</div></div>"
        for when, key, what in timeline
    )
    pages = [
        page(
            f"""<div class="cover">
<div class="kicker">India Trade Lab · agent guide</div>
<h1>Meet the Desk</h1>
<p class="lede">Sixteen characters, one job: find a few good setups, keep every loss small,
and sit out when nothing has an edge. This guide explains who does what, who decides,
and what nobody is allowed to do.</p>
<div class="lineup">{lineup}</div>
<p class="small">Paper trading only. Nothing in this system can place a real order or move real
money. Past results do not predict future returns.</p></div>"""
        ),
        page(
            f"""<h2>A trading day</h2>
<p class="intro">Times are IST on NSE trading days. Holidays are skipped automatically.</p>
<div class="timeline">{steps}</div>""",
            2,
        ),
        page(
            f"""<h2>The five rules nobody can break</h2>
<ol class="rules">
<li><b>Agents can narrow, never widen.</b> An agent may veto a stock, downgrade a rating or
drop a pick. No agent can add a stock that failed a filter, raise a limit or change a ticket.</li>
<li><b>Code sizes every trade.</b> Quantity comes from the per-trade risk limit
(₹250 by default) and the stop distance. Agents never choose a size.</li>
<li><b>Only proven strategies trade.</b> Ref's tournament must pass a strategy at double costs.
If none pass, the desk sits out: no trades, no model calls.</li>
<li><b>Every loss is capped twice.</b> Each trade has a stop; each day has a loss cap
(₹750 by default), a three-trade limit and a losing-streak stop. Exits are never blocked.</li>
<li><b>Paper only.</b> There is no broker order path. Real money is a separate decision
that needs new code, a registered static IP under SEBI's 2026 rules, and your sign-off.</li>
</ol>
<div class="callout"><b>Why "no losses" is not a promise.</b> Every real strategy has losing
trades. The desk is built so that losses are small (one R, often cut earlier by breakeven and
time stops) and winners are allowed to run (two R target, trailing stop). Whether that adds up
to profit after costs is exactly what the tournament and the paper book measure.</div>
<div class="guards">
<div>{svg("shield", 150)}<b>Small losses</b><span>One R per trade, a daily cap, a streak stop</span></div>
<div>{svg("ref", 150)}<b>Proven rules only</b><span>Double-cost tournament every evening</span></div>
<div>{svg("pilot", 150)}<b>Virtual money</b><span>No broker order path exists</span></div>
</div>""",
            3,
        ),
        page(
            f"""<h2>The pre-market team</h2>
<p class="intro">Six specialists, each reading one slice of the evidence for every stock that
passed the hard filters: enough history, enough traded value, large-cap by NSE index
membership, and fresh reference data.</p>
<div class="grid">{"".join(card(k) for k in ("scoop", "vibe", "chartly", "atlas"))}</div>""",
            4,
        ),
        page(
            f"""<h2>The pre-market team, continued</h2>
<div class="grid">{"".join(card(k) for k in ("tide", "ledger"))}</div>
<h2 style="margin-top:22px">The judge and its sub-agents</h2>
<div class="flow">
<div class="node">Hard filters<br><small>code</small></div><div class="arrow">→</div>
<div class="node">6 specialists<br><small>one stance per stock</small></div><div class="arrow">→</div>
<div class="node">Top 3 finalists<br><small>support, then score</small></div><div class="arrow">→</div>
<div class="node">Scout + Blueprint<br><small>per finalist</small></div><div class="arrow">→</div>
<div class="node accent">Justice decides<br><small>stock, rating, strategy</small></div><div class="arrow">→</div>
<div class="node">Code drops high-risk<br><small>or no-setup picks</small></div>
</div>""",
            5,
        ),
        page(
            f"""<h2>The judge's team</h2>
<div class="grid">{"".join(card(k) for k in ("scout", "blueprint", "judge"))}</div>
<div class="callout">Thirteen model calls each morning (6 + 2 × 3 + 1). If no model is
configured, the budget is spent, fewer than four specialists answer, or the judge's answer
breaks a rule, the report falls back to the plain score ranking and says so.</div>""",
            6,
        ),
        page(
            f"""<h2>The intraday debate</h2>
<p class="intro">When a judge pick shows a live setup, the ticket is frozen (price, stop,
target, size) and argued over before anything is recorded.</p>
<div class="grid">{"".join(card(k) for k in ("bullu", "bruno", "shield", "captain"))}</div>""",
            7,
        ),
        page(
            f"""<h2>Memory and the two code guardians</h2>
<div class="grid">{"".join(card(k) for k in ("echo", "ref", "pilot"))}</div>""",
            8,
        ),
        page(
            """<h2>The strategies and how a trade ends</h2>
<div class="two">
<div><h3>Opening-range breakout</h3><p>The first completed five-minute close above the high of
09:15-09:30. Stop at that range's low.</p>
<h3>VWAP pullback</h3><p>On a day that has already broken out, price dips to the day's VWAP
and a bar closes back above it. Stop just under the dip.</p>
<h3>Skipped on purpose</h3><ul><li>Daily trend is down</li><li>Daily RSI is 75 or more</li>
<li>Stop under 0.15% away (noise) or wider than one daily ATR</li></ul></div>
<div><svg viewBox="0 0 360 250" width="100%" role="img" aria-label="Trade management">
<line x1="20" y1="200" x2="340" y2="200" stroke="#eaeaf0"/>
<line x1="20" y1="160" x2="340" y2="160" stroke="#bb5a65" stroke-dasharray="4 4"/>
<text x="24" y="175" font-size="10" fill="#bb5a65">initial stop (−1R)</text>
<line x1="20" y1="130" x2="340" y2="130" stroke="#9a98ab" stroke-dasharray="2 4"/>
<text x="24" y="125" font-size="10" fill="#858592">entry</text>
<line x1="20" y1="40" x2="340" y2="40" stroke="#358977" stroke-dasharray="4 4"/>
<text x="24" y="35" font-size="10" fill="#358977">target (+2R)</text>
<polyline points="40,130 80,118 120,100 150,92 180,106 210,82 250,70 280,88 310,100"
 fill="none" stroke="#7760ce" stroke-width="3" stroke-linejoin="round"/>
<polyline points="40,160 120,160 120,128 210,128 210,112 250,100 310,100" fill="none"
 stroke="#e2b84a" stroke-width="3" stroke-linejoin="round"/>
<circle cx="310" cy="100" r="5" fill="#e2b84a"/>
<text x="126" y="146" font-size="10" fill="#9b7a1e">breakeven at +1R</text>
<text x="196" y="62" font-size="10" fill="#9b7a1e">trails after +1.5R</text>
<text x="244" y="118" font-size="10" fill="#252532">exits here, in profit</text>
</svg>
<p class="small">The gold line is the protective stop. It moves up, never down. A time stop
closes a trade that goes nowhere for an hour, and 15:15 closes everything.</p></div></div>
<h3 style="margin-top:20px">Every way a trade can end</h3>
<table class="gloss">
<tr><th>Initial stop</th><td>Price falls to the stop: about one R lost, plus costs. The worst normal case.</td></tr>
<tr><th>Breakeven stop</th><td>It reached +1R, then came back: closed at entry plus costs, roughly zero.</td></tr>
<tr><th>Trailing stop</th><td>It ran past +1.5R, then turned: closed with most of the gain kept.</td></tr>
<tr><th>Time stop</th><td>No progress (+0.5R) within an hour: closed near entry to free the risk.</td></tr>
<tr><th>Target</th><td>It reached +2R: closed at the target.</td></tr>
<tr><th>Square-off</th><td>15:15 arrives: anything still open is closed. Nothing is held overnight.</td></tr>
</table>""",
            9,
        ),
        page(
            f"""<h2>Words you will see</h2>
<table class="gloss">{"".join(f"<tr><th>{e(a)}</th><td>{e(b)}</td></tr>" for a, b in GLOSSARY)}</table>
<div class="callout">Nothing here is investment advice. Indicators describe the past.
SEBI's FY23 study found over 70% of individual intraday traders lost money; that is why this
desk defaults to sitting out until a rule has earned its place on your own data.</div>""",
            10,
        ),
    ]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Meet the Desk</title><style>
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: Inter, sans-serif; color: #252532; background: #fff; }}
.page {{ width: 210mm; height: 297mm; padding: 18mm 16mm 16mm; position: relative;
  page-break-after: always; overflow: hidden; }}
.foot {{ position: absolute; left: 16mm; right: 16mm; bottom: 9mm; font-size: 9px;
  color: #858592; display: flex; justify-content: space-between; border-top: 1px solid #eaeaf0;
  padding-top: 6px; }}
h1 {{ font-family: "Inter Display", Inter; font-size: 54px; letter-spacing: -2px;
  margin: 6px 0 10px; }}
h2 {{ font-family: "Inter Display", Inter; font-size: 30px; letter-spacing: -.6px;
  margin: 0 0 6px; }}
h3 {{ font-size: 17px; margin: 12px 0 4px; color: #7760ce; }}
.kicker {{ color: #7760ce; font-weight: 700; font-size: 12px; letter-spacing: 1.4px;
  text-transform: uppercase; }}
.cover {{ background: linear-gradient(160deg, #f0ecfb, #fff 55%); position: absolute;
  inset: 0; padding: 22mm 16mm 0; }}
.lede {{ font-size: 17px; line-height: 1.55; max-width: 150mm; color: #45445a; }}
.lineup {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px 6px; margin: 22px 0; }}
.mini {{ text-align: center; font-size: 13px; font-weight: 600; color: #45445a; }}
.mini svg {{ display: block; margin: 0 auto -6px; }}
.small {{ font-size: 12px; color: #858592; line-height: 1.5; }}
.intro {{ color: #5d5c70; font-size: 14px; line-height: 1.55; margin: 0 0 12px; }}
.grid {{ display: grid; grid-template-columns: 1fr; gap: 12px; }}
.card {{ display: flex; gap: 6px; border: 1px solid #eaeaf0; border-radius: 14px;
  padding: 12px 16px 12px 6px; align-items: center; background: linear-gradient(180deg, #fff, #fbfbfd);
  border-top: 4px solid var(--accent); }}
.card .art {{ flex: 0 0 150px; }}
.card .art svg {{ width: 150px; height: 150px; }}
.card .name {{ font-weight: 800; font-size: 19px; }}
.card .name span {{ font-weight: 600; font-size: 11.5px; color: var(--accent);
  background: #f6f6f9; padding: 2px 6px; border-radius: 99px; margin-left: 4px; }}
.card .team {{ font-size: 12px; color: #858592; margin: 1px 0 4px; }}
.card p {{ font-size: 13px; line-height: 1.5; margin: 4px 0; }}
.card b {{ color: var(--accent); font-size: 10.5px; text-transform: uppercase;
  letter-spacing: .6px; margin-right: 3px; }}
.card .never b {{ color: #bb5a65; }}
.timeline {{ display: flex; flex-direction: column; gap: 10px; }}
.step {{ display: grid; grid-template-columns: 36mm 76px 1fr; align-items: center; gap: 12px;
  border: 1px solid #eaeaf0; border-radius: 14px; padding: 10px 14px; }}
.when {{ font-weight: 800; color: #7760ce; font-size: 14.5px; }}
.what {{ font-size: 14px; line-height: 1.55; }}
.you {{ width: 64px; height: 64px; border-radius: 50%; background: #f0ecfb; color: #7760ce;
  display: grid; place-items: center; font-weight: 800; font-size: 13px; }}
.rules {{ padding-left: 18px; }}
.rules li {{ font-size: 15.5px; line-height: 1.6; margin: 0 0 18px; }}
.callout {{ background: #f0ecfb; border-radius: 14px; padding: 16px 18px; font-size: 13.5px;
  line-height: 1.55; margin-top: 12px; }}
.flow {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 8px; }}
.node {{ border: 1px solid #d9d3f2; border-radius: 12px; padding: 10px 12px; font-size: 13px;
  font-weight: 700; text-align: center; background: #fff; }}
.node small {{ font-weight: 500; color: #858592; }}
.node.accent {{ background: #7760ce; color: #fff; border-color: #7760ce; }}
.node.accent small {{ color: #e6dfff; }}
.arrow {{ color: #9b84ef; font-weight: 800; }}
.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
.two p, .two li {{ font-size: 14px; line-height: 1.6; }}
.guards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 18px;
  text-align: center; }}
.guards b {{ display: block; font-size: 15px; margin-top: -6px; }}
.guards span {{ font-size: 12px; color: #5d5c70; }}
.gloss {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
.gloss th {{ text-align: left; width: 38mm; color: #7760ce; padding: 10px 8px 10px 0;
  vertical-align: top; border-bottom: 1px solid #eaeaf0; }}
.gloss td {{ padding: 10px 0; border-bottom: 1px solid #eaeaf0; line-height: 1.5; }}
</style></head><body>{"".join(pages)}</body></html>"""


def main() -> int:
    page_html = build()
    target = HERE / "agents-guide.html"
    target.write_text(page_html, encoding="utf-8")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as runner:
        browser = runner.chromium.launch()
        tab = browser.new_page()
        tab.goto(target.resolve().as_uri())
        tab.pdf(path=str(HERE / "agents-guide.pdf"), format="A4", print_background=True)
        browser.close()
    print(f"Wrote {target} and {HERE / 'agents-guide.pdf'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

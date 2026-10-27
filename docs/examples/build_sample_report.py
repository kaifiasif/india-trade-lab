"""Build the synthetic sample pre-market report shown in the README.

    python3 docs/examples/build_sample_report.py

Everything in it is made up: four fictional NSE:DEMO* stocks, generated prices,
invented headlines, and offline sample agents that follow fixed rules in place of a
model. It exists so a new reader can see what the morning email looks like before
setting up Kite. It runs the real report code (premarket.describe, assemble, render)
and the real selection-agent validation, so the layout and guards are genuine.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "day-trader-india" / "scripts"))

import premarket  # noqa: E402
import selection_agents  # noqa: E402

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
CLOCK = dt.datetime(2026, 10, 26, 8, 40, tzinfo=IST)
BANNER = (
    '<div class="notice" style="border-color:#bb5a65;background:#fff4f5"><strong>SYNTHETIC '
    "SAMPLE.</strong> Fictional stocks, generated prices, invented headlines and offline sample "
    "agents that follow fixed rules in place of a model. Nothing here is market data, a real "
    "agent's opinion or a recommendation.</div>"
)
STOCKS = [
    # symbol, name, sector, sector index, tier, lot, daily drift, base price, volume
    ("NSE:DEMOA", "Demo Alpha Software Ltd", "Information Technology", "NIFTY IT", "large", 300,
     0.0045, 1480, 2_400_000),
    ("NSE:DEMOB", "Demo Bharat Bank Ltd", "Financial Services", "NIFTY FINANCIAL SERVICES",
     "large", 750, 0.0018, 820, 5_100_000),
    ("NSE:DEMOC", "Demo Cement Ltd", "Construction Materials", None, "mid", None, 0.0030, 410,
     900_000),
    ("NSE:DEMOD", "Demo Durables Ltd", "Consumer Durables", None, "large", 125, -0.0040, 2150,
     700_000),
]  # fmt: skip
HEADLINES = {
    "NSE:DEMOA": [
        "Demo Alpha Software wins multi-year cloud contract, shares rise",
        "Demo Alpha Software reports strong order growth in Q2",
        "Demo Alpha Software expects steady margins despite currency swings",
    ],
    "NSE:DEMOB": [
        "Demo Bharat Bank loan growth beats estimates",
        "Demo Bharat Bank asset quality stable, provisions fall",
        "Demo Bharat Bank shares flat ahead of policy meeting",
    ],
    "NSE:DEMOD": [
        "Demo Durables cuts guidance as demand weakens",
        "Demo Durables shares slump after weak quarter",
    ],
}


def daily_rows(drift: float, base: float, volume: int) -> list[dict]:
    rows, price, day = [], base, CLOCK.date() - dt.timedelta(days=120)
    while day < CLOCK.date():
        if day.weekday() < 5:
            # A drift plus a wave, so indicators look like a real market, not a straight line.
            swing = 0.018 * math.sin(len(rows) / 2.2) + 0.009 * math.sin(len(rows) / 0.9)
            close = price * (1 + drift * 0.6 + swing)
            rows.append(
                {
                    "date": str(day),
                    "close_at": f"{day}T15:30:00+05:30",
                    "open": round(price, 2),
                    "high": round(max(price, close) * 1.008, 2),
                    "low": round(min(price, close) * 0.992, 2),
                    "close": round(close, 2),
                    "volume": float(volume),
                }
            )
            price = close
        day += dt.timedelta(days=1)
    return rows


class SampleAgents:
    """Offline stand-ins that follow fixed rules; labelled as such in the sample."""

    name = "offline_sample_agents"
    uses_network = True  # So the real selection path and its validation run.

    def argue(self, role: str, system: str, user: str, schema: dict) -> dict:
        payload = json.loads(user)
        base = {"role": role, "session_date": payload["session_date"]}
        if role == "risk-scout":
            symbol = payload["symbol"]
            return {
                **base,
                "symbol": symbol,
                "risk_level": "low" if symbol == "NSE:DEMOA" else "medium",
                "risks": "Sample rule: no event flagged in the headlines."
                if symbol == "NSE:DEMOA"
                else "Sample rule: a policy meeting ahead makes this medium risk.",
                "evidence_ids": [f"{symbol}#technical"],
            }
        if role == "setup-planner":
            symbol = payload["symbol"]
            return {
                **base,
                "symbol": symbol,
                "strategy": "orb-v1",
                "plan": "Sample rule: watch for a close above the first 15 minutes' high.",
                "evidence_ids": [f"{symbol}#technical"],
            }
        if role == selection_agents.JUDGE:
            finalists = [stock for stock in payload["stocks"] if stock["finalist"]]
            return {
                **base,
                "summary": "Sample rule: pick the finalist with the most positive specialists.",
                "picks": [
                    {
                        "symbol": stock["symbol"],
                        "rating": "Buy" if index == 0 else "Overweight",
                        "conviction": "medium" if index == 0 else "low",
                        "reason": "Sample rule: highest specialist support, then the highest score.",
                        "evidence_ids": [f"{stock['symbol']}#technical"],
                        "strategy": "orb-v1",
                    }
                    for index, stock in enumerate(finalists[:2])
                ],
            }
        rows = []
        for stock in payload["stocks"]:
            ids = sorted(stock["evidence"])[:1]
            rows.append(
                {
                    "symbol": stock["symbol"],
                    "stance": "positive" if ids else "insufficient",
                    "summary": f"Sample {role} rule applied to the supplied evidence.",
                    "evidence_ids": ids,
                }
            )
        return {**base, "assessments": rows}


def main() -> int:
    settings = {
        "min_turnover_inr": 20_000_000,
        "min_scored_headlines": 2,
        "min_market_cap_tier": "large",
        "max_reference_age_days": 7,
    }
    candidates = []
    for symbol, name, sector, index, tier, lot, drift, base, volume in STOCKS:
        facts = {
            "symbol": symbol,
            "known": True,
            "sector": sector,
            "market_cap_tier": tier,
            "tier_source": "SYNTHETIC",
            "fno_eligible": lot is not None,
            "lot_size": lot,
            "sector_index": index,
            "refreshed_at": CLOCK.isoformat(),
            "stale_days": 0,
        }
        sector_view = (
            {"index": index, "available": True, "direction": "up", "return1_pct": 0.42,
             "return5_pct": 1.35, "return20_pct": 3.1, "last_session": "2026-10-23"}
            if index
            else {"available": False, "reason": f"no sector index mapped for {sector}"}
        )  # fmt: skip
        news = [
            {"title": text, "published_at": "2026-10-25T19:00:00+05:30", "source": "SYNTHETIC"}
            for text in HEADLINES.get(symbol, [])
        ]
        candidates.append(
            premarket.describe(
                symbol, name, facts, daily_rows(drift, base, volume), sector_view, news, CLOCK,
                settings,
            )
        )  # fmt: skip
    playbook = {"allowed": ["orb-v1", "vwap-pullback-v1"], "basis": "sample playbook (synthetic)"}

    def run(pool: list[dict], proven: dict) -> dict:
        return selection_agents.run_selection(
            pool, CLOCK.date().isoformat(), SampleAgents(), 3, proven=proven, finalist_count=2
        )

    report = premarket.assemble(
        candidates, [], settings, playbook, {}, run, 10, CLOCK, "SYNTHETIC sample universe"
    )
    report["selection"]["reason"] = (
        "SYNTHETIC SAMPLE: offline sample agents followed fixed rules in place of a model"
    )
    page = premarket.render(report).replace("<main>", "<main>" + BANNER, 1)
    target = ROOT / "docs" / "examples" / "premarket-sample.html"
    target.write_text(page, encoding="utf-8")
    (target.with_suffix(".json")).write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"Wrote {target} · watching {report['watching']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

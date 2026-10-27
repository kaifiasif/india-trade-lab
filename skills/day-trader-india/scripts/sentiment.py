#!/usr/bin/env python3
"""Headline sentiment and brokerage-call extraction, by transparent rules.

Scores a short financial headline with a finance-specific word list, handling
negation and hedging, and separately pulls out an explicit broker call when a
headline states one ("Motilal Oswal raises Infosys to Buy, target Rs 1,800").

What this is not: a prediction, a measure of what a stock will do, or a reading
of an article. It scores the words in a headline a publisher chose. Aggregate
scores are reported with the sample size so three headlines are never mistaken
for a market mood, and the words that drove a score are returned so a reader can
disagree with it. No network and no model call; a model reading is optional and
handled by the research roles instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

POSITIVE = {
    "beat",
    "beats",
    "surge",
    "surges",
    "surged",
    "jump",
    "jumps",
    "jumped",
    "rally",
    "rallies",
    "gain",
    "gains",
    "gained",
    "rise",
    "rises",
    "rose",
    "upgrade",
    "upgrades",
    "upgraded",
    "outperform",
    "profit",
    "profits",
    "record",
    "strong",
    "robust",
    "growth",
    "expands",
    "expansion",
    "wins",
    "won",
    "bags",
    "secures",
    "approval",
    "approved",
    "boost",
    "boosts",
    "raises",
    "raised",
    "hike",
    "hikes",
    "bullish",
    "buy",
    "accumulate",
    "overweight",
    "turnaround",
    "recovery",
    "dividend",
    "bonus",
    "order",
    "orders",
    "contract",
    "deal",
}
NEGATIVE = {
    "miss",
    "misses",
    "missed",
    "fall",
    "falls",
    "fell",
    "drop",
    "drops",
    "dropped",
    "slump",
    "slumps",
    "slumped",
    "plunge",
    "plunges",
    "plunged",
    "decline",
    "declines",
    "declined",
    "loss",
    "losses",
    "weak",
    "weakness",
    "downgrade",
    "downgrades",
    "downgraded",
    "underperform",
    "cut",
    "cuts",
    "lowered",
    "lowers",
    "bearish",
    "sell",
    "reduce",
    "underweight",
    "probe",
    "investigation",
    "fraud",
    "penalty",
    "fine",
    "fined",
    "default",
    "lawsuit",
    "resign",
    "resigns",
    "resigned",
    "warns",
    "warning",
    "concern",
    "concerns",
    "risk",
    "risks",
    "slowdown",
    "layoff",
    "layoffs",
    "recall",
    "overvalued",
    "crash",
    "selloff",
    "sell-off",
    "low",
    "lows",
    "pressure",
    "halt",
    "halted",
    "ban",
    "banned",
}
NEGATIONS = {
    "not",
    "no",
    "never",
    "without",
    "fails",
    "fail",
    "failed",
    "unlikely",
    "denies",
    "denied",
}
HEDGES = {
    "may",
    "might",
    "could",
    "likely",
    "expect",
    "expects",
    "expected",
    "forecast",
    "guidance",
    "estimates",
    "outlook",
    "eyes",
    "plans",
    "seen",
}

BROKERS = (
    "Motilal Oswal",
    "ICICI Securities",
    "ICICI Direct",
    "HDFC Securities",
    "Kotak Institutional",
    "Kotak Securities",
    "Axis Securities",
    "Axis Capital",
    "JM Financial",
    "Nuvama",
    "Emkay",
    "Sharekhan",
    "Anand Rathi",
    "Prabhudas Lilladher",
    "IIFL",
    "Centrum",
    "Elara",
    "Jefferies",
    "Morgan Stanley",
    "Goldman Sachs",
    "JPMorgan",
    "J.P. Morgan",
    "Citi",
    "CLSA",
    "Macquarie",
    "Nomura",
    "UBS",
    "Bernstein",
    "BofA",
    "Bank of America",
    "HSBC",
    "Investec",
    "Antique",
    "Dolat Capital",
    "Systematix",
    "Geojit",
    "Angel One",
    "SBI Securities",
    "YES Securities",
)
CALLS = {
    "buy": "Buy",
    "accumulate": "Overweight",
    "add": "Overweight",
    "outperform": "Overweight",
    "overweight": "Overweight",
    "hold": "Hold",
    "neutral": "Hold",
    "equal-weight": "Hold",
    "reduce": "Underweight",
    "underweight": "Underweight",
    "underperform": "Underweight",
    "sell": "Sell",
}
TARGET = re.compile(
    r"(?:target|tp|price target)\s*(?:price)?\s*(?:of|at|to|:)?\s*"
    r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]{1,9}(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
WORD = re.compile(r"[a-z][a-z\-']+")
BANDS = (
    (0.35, "bullish"),
    (0.12, "leaning bullish"),
    (-0.12, "neutral"),
    (-0.35, "leaning bearish"),
)


def score_headline(text: str) -> dict[str, Any]:
    """Score one headline in [-1, 1]. A word negated within three words flips sign."""
    words = WORD.findall((text or "").lower())
    hits: list[dict[str, Any]] = []
    total = 0.0
    for index, word in enumerate(words):
        weight = 1.0 if word in POSITIVE else -1.0 if word in NEGATIVE else 0.0
        if not weight:
            continue
        window = words[max(0, index - 3) : index]
        negated = any(item in NEGATIONS for item in window)
        hedged = any(item in HEDGES for item in window)
        value = weight * (-1 if negated else 1) * (0.5 if hedged else 1)
        total += value
        hits.append({"word": word, "value": round(value, 2), "negated": negated, "hedged": hedged})
    if not hits:
        return {
            "score": 0.0,
            "band": "neutral",
            "words": [],
            "reason": "no scored word in this headline",
        }
    # Damped so one word cannot read as maximum conviction: a single hit lands near
    # the middle of its direction, and agreement across words moves the band.
    score = max(-1.0, min(1.0, total / (len(hits) ** 0.5 + 1)))
    band = next((name for threshold, name in BANDS if score >= threshold), "bearish")
    return {"score": round(score, 3), "band": band, "words": hits}


def extract_call(text: str) -> dict[str, Any] | None:
    """Pull an explicit broker call out of a headline, or return None."""
    lowered = (text or "").lower()
    broker = next((name for name in BROKERS if name.lower() in lowered), None)
    if not broker:
        return None
    rating = None
    for word, mapped in CALLS.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            rating = mapped
            break
    target = TARGET.search(text or "")
    if not rating and not target:
        return None
    return {
        "broker": broker,
        "rating": rating,
        "target_inr": target.group(1).replace(",", "") if target else None,
        "basis": "read from the headline text; the research note itself was not obtained",
    }


def summarize(items: list[dict], as_of: str | None = None) -> dict[str, Any]:
    """Aggregate scored headlines with their sample size and the broker calls found."""
    scored, calls = [], []
    for item in items:
        text = item.get("title") or item.get("facts") or ""
        result = score_headline(text)
        entry = {
            "published_at": item.get("published_at"),
            "title": text[:300],
            "source": item.get("source") or item.get("outlet"),
            **result,
        }
        call = extract_call(text)
        if call:
            entry["broker_call"] = call
            calls.append({**call, "title": text[:300], "published_at": item.get("published_at")})
        scored.append(entry)
    values = [entry["score"] for entry in scored if entry["words"]]
    mean = round(sum(values) / len(values), 3) if values else 0.0
    band = (
        next((name for threshold, name in BANDS if mean >= threshold), "bearish")
        if values
        else "no signal"
    )
    confidence = "low" if len(values) < 5 else "medium" if len(values) < 15 else "reported"
    return {
        "as_of": as_of,
        "headlines": len(scored),
        "scored": len(values),
        "mean_score": mean,
        "band": band,
        "confidence": confidence,
        "broker_calls": calls,
        "items": scored,
        "method": "finance word list with negation and hedging, applied to headline text only",
        "notice": "Headline wording, not a forecast and not a reading of the articles. "
        "Fewer than five scored headlines is an anecdote; treat the band accordingly.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", help="research-evidence.json path")
    parser.add_argument("--symbol", help="Symbol inside that file")
    parser.add_argument("--headline", help="Score a single headline instead")
    args = parser.parse_args(argv)
    try:
        if args.headline:
            result: Any = {
                **score_headline(args.headline),
                "broker_call": extract_call(args.headline),
            }
        else:
            if not args.evidence or not args.symbol:
                parser.error("give --headline, or --evidence with --symbol")
            from pathlib import Path

            payload = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
            result = summarize(payload.get(args.symbol, []))
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print("DATA_BLOCK: " + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())

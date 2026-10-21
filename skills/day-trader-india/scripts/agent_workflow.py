#!/usr/bin/env python3
"""Plan specialist handoffs and validate their reports. Never execute trades or LLM calls."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from guardrails import evidence_time

WORKFLOWS = {
    "intraday": {
        "india-data": [],
        "india-news": [],
        "india-screener": ["india-data"],
        "india-budget": ["india-screener", "india-news"],
        "india-risk": ["india-budget", "india-data", "india-news"],
        "india-reviewer": ["india-risk"],
    },
    "fundamental": {
        "india-data": [],
        "india-news": [],
        "india-analyst": [],
        "india-disclosures": [],
        "india-cost-tax": ["india-data"],
        "india-screener": ["india-data", "india-analyst"],
        "india-budget": ["india-screener", "india-disclosures", "india-cost-tax", "india-news"],
        "india-risk": ["india-budget"],
        "india-reviewer": ["india-risk"],
    },
    "portfolio": {
        "india-data": [],
        "india-news": [],
        "india-disclosures": [],
        "india-cost-tax": [],
        "india-rebalance": ["india-data", "india-disclosures", "india-cost-tax"],
        "india-budget": ["india-rebalance", "india-news"],
        "india-risk": ["india-budget"],
        "india-reviewer": ["india-risk"],
    },
    "alerts": {
        "india-data": [],
        "india-alerts": ["india-data"],
        "india-reviewer": ["india-alerts"],
    },
}


def proposal_digest(proposal: dict[str, Any]) -> str:
    """Bind reports to the exact proposed inputs; this is not a signature or approval."""
    encoded = json.dumps(proposal, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def plan(
    workflow: str,
    symbol: str,
    as_of: str,
    run_id: str,
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe dependency order; the host agent performs delegation or sequential roles."""
    valid_symbol = isinstance(symbol, str) and (
        re.fullmatch(r"(NSE|BSE):[A-Z0-9&.\-]+", symbol)
        or (workflow == "portfolio" and symbol == "PORTFOLIO")
    )
    if workflow not in WORKFLOWS or not valid_symbol:
        raise ValueError("Use a supported workflow and exchange-qualified cash-equity symbol")
    if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 128:
        raise ValueError("Run ID must be 1–128 characters")
    clock = evidence_time(as_of)
    result = {
        "schema_version": 1,
        "run_id": run_id,
        "symbol": symbol,
        "as_of": clock.isoformat(),
        "workflow": workflow,
        "mode": "research_only",
        "paper_entry_allowed": False,
        "jobs": [
            {"role": name, "depends_on": dependencies}
            for name, dependencies in WORKFLOWS[workflow].items()
        ],
        "after_review": "Show the result. Only an explicitly requested virtual record may reach the paper journal.",
        "notice": "This is a delegation plan, not a running agent service or a trade authorization.",
    }
    if proposal is not None:
        if not isinstance(proposal, dict) or proposal.get("symbol") != symbol:
            raise ValueError("Proposed inputs must name the same symbol")
        result["proposal_sha256"] = proposal_digest(proposal)
    return result


def review_packet(packet: object, now: dt.datetime | None = None) -> dict[str, Any]:
    """Apply unanimous, fresh, proposal-bound review gates without trusting majority votes."""
    if (
        not isinstance(packet, dict)
        or type(packet.get("schema_version")) is not int
        or packet.get("schema_version") != 1
    ):
        raise ValueError("Expected a version-1 specialist review packet")
    mode = packet.get("mode")
    if mode not in ("paper_research", "synthetic"):
        raise ValueError("Only paper_research and synthetic packets are supported")
    description = plan(packet["workflow"], packet["symbol"], packet["as_of"], packet["run_id"])
    clock = evidence_time(packet["as_of"])
    if mode == "paper_research":
        current = now or dt.datetime.now(dt.timezone.utc)
        if not -5 <= (current - clock).total_seconds() <= 120:
            raise ValueError("Paper-research packet is stale or future-dated")
    proposal = packet.get("proposal")
    if not isinstance(proposal, dict) or proposal.get("symbol") != packet["symbol"]:
        raise ValueError("Packet needs an exact proposed-input object for the same symbol")
    digest = proposal_digest(proposal)
    reports = packet.get("reports")
    if not isinstance(reports, list):
        raise ValueError("Packet reports must be a list")
    required = set(WORKFLOWS[packet["workflow"]])
    received, blockers = set(), []
    has_veto = False
    for report in reports:
        if not isinstance(report, dict) or report.get("role") not in required:
            raise ValueError("Unknown role or malformed specialist report")
        role = report["role"]
        if role in received:
            raise ValueError("Duplicate specialist role; one report cannot outvote another")
        received.add(role)
        if (
            type(report.get("schema_version")) is not int
            or report.get("schema_version") != 1
            or any(report.get(key) != packet[key] for key in ("run_id", "symbol"))
        ):
            blockers.append(f"{role}: report belongs to a different run or symbol")
        if evidence_time(report.get("as_of")) != clock:
            blockers.append(f"{role}: report observation time does not match the packet")
        decision = report.get("decision")
        if decision not in ("PASS", "BLOCK", "DATA_BLOCK"):
            raise ValueError("Specialist decision must be PASS, BLOCK or DATA_BLOCK")
        if not isinstance(report.get("summary"), str) or not report["summary"].strip():
            blockers.append(f"{role}: missing review summary")
        reasons = report.get("blockers")
        if not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons):
            raise ValueError("Specialist blockers must be a list of strings")
        if decision != "PASS" or reasons:
            has_veto |= decision == "BLOCK"
            blockers.append(f"{role}: {decision}; {'; '.join(reasons) or 'review did not pass'}")
            continue
        if report.get("proposal_sha256") != digest:
            blockers.append(f"{role}: PASS is not bound to the current proposal")
        evidence = report.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            blockers.append(f"{role}: PASS has no supporting evidence")
            continue
        for item in evidence:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("source"), str)
                or not item["source"].strip()
            ):
                blockers.append(f"{role}: missing evidence source")
                continue
            observed = evidence_time(item.get("observed_at"))
            published = item.get("published_at")
            if observed > clock or (published is not None and evidence_time(published) > observed):
                blockers.append(
                    f"{role}: evidence was not available at the stated observation time"
                )
    blockers.extend(f"{role}: missing required report" for role in sorted(required - received))
    status = "BLOCK" if has_veto else "DATA_BLOCK" if blockers else "REVIEW_COMPLETE"
    if not blockers and mode == "synthetic":
        status = "SYNTHETIC_REVIEW_COMPLETE"
    return {
        "schema_version": 1,
        "run_id": description["run_id"],
        "symbol": description["symbol"],
        "as_of": description["as_of"],
        "mode": mode,
        "status": status,
        "proposal_sha256": digest,
        "required_roles": sorted(required),
        "blockers": blockers,
        "paper_entry_allowed": False,
        "notice": "Report consistency only. Verify source truth and run the journal's separate pre-trade gates. No order or journal entry was sent.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    planner = subparsers.add_parser("plan")
    planner.add_argument("--workflow", choices=WORKFLOWS, default="intraday")
    planner.add_argument("--symbol", required=True)
    planner.add_argument("--as-of", required=True)
    planner.add_argument("--run-id", required=True)
    planner.add_argument(
        "--proposal", type=Path, help="Optional exact proposed inputs to fingerprint"
    )
    reviewer = subparsers.add_parser("review")
    reviewer.add_argument("--packet", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            proposal = None
            if args.proposal:
                if args.proposal.stat().st_size > 1_000_000:
                    raise ValueError("Proposed inputs exceed 1 MB")
                proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
            result = plan(args.workflow, args.symbol, args.as_of, args.run_id, proposal)
        else:
            if args.packet.stat().st_size > 1_000_000:
                raise ValueError("Review packet exceeds 1 MB")
            result = review_packet(json.loads(args.packet.read_text(encoding="utf-8")))
        print(json.dumps(result, indent=2, allow_nan=False))
        return 2 if result.get("blockers") else 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

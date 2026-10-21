"""Verify that specialist consensus cannot silently authorize paper or real orders."""

import copy
import datetime as dt
import json
import subprocess
import sys
import unittest
from pathlib import Path

from agent_workflow import WORKFLOWS, plan, proposal_digest, review_packet


def synthetic_packet() -> dict:
    proposal = {"symbol": "NSE:DEMO", "qty": 10, "price_inr": "100", "stop_inr": "98"}
    digest = proposal_digest(proposal)
    at = "2026-10-19T10:00:00+05:30"
    reports = [
        {
            "schema_version": 1,
            "run_id": "synthetic-test",
            "symbol": "NSE:DEMO",
            "as_of": at,
            "role": role,
            "decision": "PASS",
            "summary": "Synthetic test only",
            "proposal_sha256": digest,
            "blockers": [],
            "evidence": [
                {"source": "SYNTHETIC TEST ONLY", "observed_at": at, "published_at": None}
            ],
        }
        for role in WORKFLOWS["intraday"]
    ]
    return {
        "schema_version": 1,
        "run_id": "synthetic-test",
        "symbol": "NSE:DEMO",
        "workflow": "intraday",
        "as_of": at,
        "mode": "synthetic",
        "proposal": proposal,
        "reports": reports,
    }


class AgentWorkflowTests(unittest.TestCase):
    def test_all_passes_remain_research_only(self):
        result = review_packet(synthetic_packet())
        self.assertEqual(result["status"], "SYNTHETIC_REVIEW_COMPLETE")
        self.assertIs(result["paper_entry_allowed"], False)

    def test_any_veto_missing_role_or_evidence_blocks_consensus(self):
        for change in ("veto", "missing", "missing-evidence", "false-pass"):
            packet = synthetic_packet()
            if change == "veto":
                packet["reports"][-1]["decision"] = "BLOCK"
            elif change == "missing":
                packet["reports"].pop()
            elif change == "missing-evidence":
                packet["reports"][0]["evidence"] = []
            else:
                packet["reports"][0]["blockers"] = ["Unresolved problem"]
            with self.subTest(change=change):
                self.assertIn(review_packet(packet)["status"], ("BLOCK", "DATA_BLOCK"))

    def test_changed_proposal_run_or_time_invalidates_pass(self):
        for change in ("proposal", "run", "time", "future-evidence"):
            packet = synthetic_packet()
            if change == "proposal":
                packet["proposal"]["qty"] = 11
            elif change == "run":
                packet["reports"][0]["run_id"] = "another-run"
            elif change == "time":
                packet["reports"][0]["as_of"] = "2026-10-19T10:01:00+05:30"
            else:
                packet["reports"][0]["evidence"][0]["published_at"] = "2026-10-20T10:00:00+05:30"
            with self.subTest(change=change):
                self.assertEqual(review_packet(packet)["status"], "DATA_BLOCK")

    def test_duplicate_unknown_roles_and_live_modes_are_refused(self):
        for change in ("duplicate", "unknown", "live"):
            packet = synthetic_packet()
            if change == "duplicate":
                packet["reports"].append(copy.deepcopy(packet["reports"][0]))
            elif change == "unknown":
                packet["reports"][0]["role"] = "untrusted-voter"
            else:
                packet["mode"] = "live"
            with self.subTest(change=change), self.assertRaises(ValueError):
                review_packet(packet)

    def test_current_paper_review_requires_recent_packet(self):
        packet = synthetic_packet()
        packet["mode"] = "paper_research"
        current = dt.datetime.fromisoformat(packet["as_of"])
        self.assertEqual(review_packet(packet, now=current)["status"], "REVIEW_COMPLETE")
        with self.assertRaises(ValueError):
            review_packet(packet, now=current + dt.timedelta(seconds=121))

    def test_every_plan_is_a_dependency_graph_without_execution(self):
        for name in WORKFLOWS:
            output = plan(name, "NSE:DEMO", "2026-10-19T10:00:00+05:30", "test")
            available = set()
            for job in output["jobs"]:
                self.assertTrue(set(job["depends_on"]).issubset(available))
                available.add(job["role"])
            self.assertIn("india-reviewer", available)
            self.assertIs(output["paper_entry_allowed"], False)

    def test_portfolio_scope_and_proposal_fingerprint(self):
        proposal = {"symbol": "PORTFOLIO", "changes": []}
        result = plan("portfolio", "PORTFOLIO", "2026-10-19T10:00:00+05:30", "test", proposal)
        self.assertEqual(result["proposal_sha256"], proposal_digest(proposal))
        with self.assertRaises(ValueError):
            plan("intraday", "PORTFOLIO", "2026-10-19T10:00:00+05:30", "test")

    def test_bundled_refusal_packet_runs_from_the_cli(self):
        root = Path(__file__).resolve().parents[1]
        skill = root / "skills/day-trader-india"
        result = subprocess.run(
            [
                sys.executable,
                str(skill / "scripts/agent_workflow.py"),
                "review",
                "--packet",
                str(skill / "assets/review-packet.synthetic.json"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "DATA_BLOCK")
        self.assertIs(json.loads(result.stdout)["paper_entry_allowed"], False)


if __name__ == "__main__":
    unittest.main()

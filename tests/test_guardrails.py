"""Exercise forward-practice refusal gates with explicitly synthetic attestations."""

import copy
import datetime as dt
import unittest
from unittest.mock import patch

from guardrails import REQUIRED_CHECKS, seal_state, verify_state

from paper_book import IST, create, fill


def forward_evidence(at: str = "2026-10-19T10:00:00+05:30") -> dict:
    """Return made-up input for software tests, never evidence for a real symbol."""
    return {
        "version": 1,
        "symbol": "NSE:DEMO",
        "quote_source": "SYNTHETIC FIXTURE",
        "quote_as_of": at,
        "checked_at": at,
        "bid_inr": "99.95",
        "ask_inr": "100.05",
        "checks": dict.fromkeys(REQUIRED_CHECKS, True),
        "evidence_sources": dict.fromkeys(REQUIRED_CHECKS, "SYNTHETIC TEST ONLY"),
        "session": {
            "date": at[:10],
            "open": "09:15",
            "entry_cutoff": "14:30",
            "close": "15:30",
            "source": "SYNTHETIC TEST ONLY",
        },
    }


class GuardrailTests(unittest.TestCase):
    def setUp(self):
        self.book = create(100000, "NSE:DEMO,NSE:OTHER", 500, 1000, 25000)
        self.now = dt.datetime(2026, 10, 19, 10, 0, tzinfo=IST)

    def buy(self, book=None, evidence=None, at="2026-10-19T10:00:00+05:30", event="entry"):
        return fill(
            self.book if book is None else book,
            "buy",
            event,
            "NSE:DEMO",
            100,
            at,
            "SYNTHETIC FIXTURE",
            10,
            0,
            qty=10,
            stop=98,
            exit_fee=10,
            now=dt.datetime.fromisoformat(at),
            evidence=evidence,
            target=110,
        )

    def sell(self, book, at="2026-10-19T11:00:00+05:30"):
        return fill(
            book,
            "sell",
            "exit",
            "NSE:DEMO",
            99,
            at,
            "SYNTHETIC FIXTURE",
            10,
            0,
            now=dt.datetime.fromisoformat(at),
        )

    def test_forward_entry_requires_evidence_and_retains_a_snapshot(self):
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.buy()
        evidence = forward_evidence()
        evidence["unreviewed_extra"] = "This field must not enter the audit record"
        entered = self.buy(evidence=evidence)
        self.assertIn("NSE:DEMO", entered["positions"])
        snapshot = entered["events"][-1]["pretrade_evidence"]
        self.assertNotIn("unreviewed_extra", snapshot)
        evidence["checks"]["cash_equity"] = False
        self.assertIs(snapshot["checks"]["cash_equity"], True)
        verify_state(entered)
        self.assertEqual(self.book["events"], [])

    def test_every_missing_false_or_unsourced_check_blocks_entry(self):
        for name in REQUIRED_CHECKS:
            for mutation in ("missing", "false", "spoofed_boolean", "unsourced"):
                evidence = forward_evidence()
                if mutation == "missing":
                    evidence["checks"].pop(name)
                elif mutation == "false":
                    evidence["checks"][name] = False
                elif mutation == "spoofed_boolean":
                    evidence["checks"][name] = "true"
                else:
                    evidence["evidence_sources"][name] = ""
                with self.subTest(check=name, mutation=mutation), self.assertRaises(ValueError):
                    self.buy(evidence=evidence)

    def test_stale_mismatched_malformed_or_wide_market_evidence_is_blocked(self):
        changes = [
            {"checked_at": "2026-10-19T09:57:59+05:30"},
            {"checked_at": "2026-10-19T10:00:06+05:30"},
            {"quote_as_of": "2026-10-19T09:59:59+05:30"},
            {"quote_as_of": 123},
            {"version": True},
            {"version": 99},
            {"symbol": "NSE:OTHER"},
            {"quote_source": "different-source"},
            {"ask_inr": "102"},
            {"bid_inr": "101"},
            {"bid_inr": "NaN"},
            {"checks": []},
            {"session": None},
        ]
        for change in changes:
            evidence = forward_evidence()
            evidence.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.buy(evidence=evidence)

    def test_exchange_date_and_entry_window_are_required(self):
        for at in ("2026-10-19T09:14:00+05:30", "2026-10-19T14:30:00+05:30"):
            with self.subTest(at=at), self.assertRaises(ValueError):
                self.buy(evidence=forward_evidence(at), at=at)
        for change in ({"date": "2026-10-20"}, {"source": ""}, {"close": "08:00"}):
            evidence = forward_evidence()
            evidence["session"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.buy(evidence=evidence)

    def test_forward_policy_ceilings_and_live_mode_rejection(self):
        for kwargs in (
            {"risk": 501},
            {"daily_loss": 1501},
            {"position_limit": 25001},
            {"max_trades": 6},
            {"max_open": 4},
            {"max_loss_streak": 4},
            {"drawdown_stop": 5001},
        ):
            config = dict(
                cash=100000, symbols="NSE:DEMO", risk=500, daily_loss=1000, position_limit=25000
            )
            config.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                create(**config)
        modified = copy.deepcopy(self.book)
        modified["mode"] = "live"
        with self.assertRaisesRegex(ValueError, "mode"):
            self.buy(modified, forward_evidence())

    def test_kill_switch_blocks_entries_but_allows_virtual_exit(self):
        entered = self.buy(evidence=forward_evidence())
        with patch.dict("os.environ", {"INDIA_TRADE_LAB_HALT": "1"}):
            with self.assertRaisesRegex(ValueError, "halt"):
                self.buy(evidence=forward_evidence())
            replay = create(100000, "NSE:DEMO", 500, 1000, 25000, replay=True)
            with self.assertRaisesRegex(ValueError, "halt"):
                self.buy(replay)
            self.assertEqual(self.sell(entered)["positions"], {})

    def test_cooldown_after_a_loss(self):
        lost = self.sell(self.buy(evidence=forward_evidence()))
        early = "2026-10-19T11:14:59+05:30"
        with self.assertRaisesRegex(ValueError, "15 minutes"):
            self.buy(lost, forward_evidence(early), early, event="too-soon")
        allowed = "2026-10-19T11:15:00+05:30"
        self.buy(lost, forward_evidence(allowed), allowed, event="second-entry")

    def test_checksum_rejects_changed_cash_risk_and_event_history(self):
        entered = self.buy(evidence=forward_evidence())
        for key, value in (("cash", "999999"), ("events", []), ("limits", {})):
            changed = copy.deepcopy(entered)
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "checksum"):
                self.sell(changed)

    def test_legacy_books_cannot_open_new_forward_entries_but_can_close(self):
        entered = self.buy(evidence=forward_evidence())
        legacy = copy.deepcopy(entered)
        legacy["version"] = 2
        legacy.pop("state_sha256")
        self.assertEqual(self.sell(legacy)["positions"], {})
        empty = copy.deepcopy(self.book)
        empty["version"] = 2
        empty.pop("state_sha256")
        with self.assertRaisesRegex(ValueError, "version-3"):
            self.buy(empty, forward_evidence())

    def test_resealing_does_not_allow_policy_limit_bypass(self):
        changed = copy.deepcopy(self.book)
        changed["limits"]["risk"] = "1000"
        seal_state(changed)
        with self.assertRaisesRegex(ValueError, "ceiling"):
            self.buy(changed, forward_evidence())


if __name__ == "__main__":
    unittest.main()

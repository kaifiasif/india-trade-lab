"""Synthetic, offline market mechanics; none of these tests demonstrate an edge."""

import copy
import csv
import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from guardrails import seal_state

from broker_data import NoRedirect, export, make_request
from india_research import BAR, IST, bars_from_csv, replay, scan, screen, validate_bar
from paper_book import create, fill


def fixture():
    start = dt.datetime(2026, 10, 19, 9, 15, tzinfo=IST)
    rows = []
    for i in range(75):
        row = dict(
            symbol="NSE:DEMO",
            timestamp=(start + i * BAR).isoformat(),
            open=100 if i < 3 else 102,
            high=101 if i < 3 else 103,
            low=99 if i < 3 else 101,
            close=100 if i < 3 else 102,
            volume=100000,
            source="SYNTHETIC_TEST_ONLY",
        )
        if i == 3:
            row.update(open=100, low=100)
        rows.append(row)
    manifest = {
        "timezone": "Asia/Kolkata",
        "source": "SYNTHETIC_TEST_ONLY",
        "sessions": {
            "2026-10-19": {
                "open": "09:15",
                "close": "15:30",
                "entry_cutoff": "14:30",
                "flat_by": "15:15",
            }
        },
    }
    return rows, manifest


CFG = dict(
    cash=100000,
    risk=250,
    daily_loss=750,
    position_cap=15000,
    target_r=2,
    slippage_bps=0,
    fee_bps=0,
    fee_flat=0,
    drawdown_stop=2000,
)


class IndiaResearchTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.sessions = fixture()

    def bars(self):
        return [validate_bar(row) for row in self.raw]

    def test_completed_bars_and_as_of_cutoff(self):
        early = scan(self.bars(), self.sessions, "2026-10-19T09:34:59+05:30")
        self.assertEqual(early["results"][0]["status"], "DATA_BLOCK")
        ready = scan(self.bars(), self.sessions, "2026-10-19T09:35:00+05:30")
        self.assertEqual(ready["results"][0]["status"], "MATCH")
        self.assertEqual(ready["results"][0]["signal"]["confirmed_at"], "2026-10-19T09:35:00+05:30")
        # Future bars are present in the file but cannot enter the observation.
        self.raw[10]["high"] = 999999
        self.assertEqual(scan(self.bars(), self.sessions, "2026-10-19T09:35:00+05:30"), ready)

    def test_missing_unknown_and_expired_sessions(self):
        b = self.bars()
        del b[1]
        self.assertEqual(
            scan(b, self.sessions, "2026-10-19T10:00:00+05:30")["results"][0]["status"],
            "DATA_BLOCK",
        )
        self.assertEqual(
            scan(self.bars(), self.sessions, "2026-10-20T10:00:00+05:30")["results"][0]["status"],
            "DATA_BLOCK",
        )
        self.assertEqual(
            scan(self.bars(), self.sessions, "2026-10-19T14:35:00+05:30")["results"][0]["status"],
            "EXPIRED",
        )

    def test_invalid_ohlc_nonfinite_and_timezone(self):
        for changes in (
            {"high": 98},
            {"close": float("nan")},
            {"volume": -1},
            {"timestamp": "2026-10-19T09:15:00"},
            {"symbol": "TSLA"},
            {"source": ""},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_bar(dict(self.raw[0], **changes))

    def test_next_open_and_stop_first(self):
        self.raw[5].update(open=102, high=110, low=98, close=102)
        result = replay(self.bars(), self.sessions, "NSE:DEMO", "2026-10-19T16:00:00+05:30", CFG)
        trade = result["trades"][0]
        self.assertEqual(trade["entry_at"], "2026-10-19T09:35:00+05:30")
        self.assertEqual(trade["reason"], "stop_first_if_ambiguous")
        self.assertEqual(trade["exit"], 99)
        self.assertLess(trade["net_pnl_inr"], 0)

    def test_gap_can_exceed_planned_stop_loss(self):
        self.raw[5].update(open=95, high=96, low=94, close=95)
        result = replay(self.bars(), self.sessions, "NSE:DEMO", "2026-10-19T16:00:00+05:30", CFG)
        trade = result["trades"][0]
        self.assertEqual(trade["reason"], "gap_stop")
        self.assertEqual(trade["exit"], 95)
        self.assertLess(trade["net_pnl_inr"], -CFG["risk"])

    def test_entry_gap_risk_is_flagged(self):
        self.raw[4].update(open=103, high=104, low=102, close=103)
        result = replay(self.bars(), self.sessions, "NSE:DEMO", "2026-10-19T16:00:00+05:30", CFG)
        self.assertTrue(result["trades"][0]["planned_risk_overshot_by_gap"])

    def test_replay_refuses_partial_session_and_records_time_exit(self):
        out = replay(self.bars()[:-1], self.sessions, "NSE:DEMO", "2026-10-19T16:00:00+05:30", CFG)
        self.assertEqual(out["trades"], [])
        self.assertIn("Missing", out["rejected_sessions"][0]["reason"])
        out = replay(self.bars(), self.sessions, "NSE:DEMO", "2026-10-19T16:00:00+05:30", CFG)
        self.assertEqual(out["trades"][0]["exit_at"], "2026-10-19T15:15:00+05:30")
        self.assertEqual(out["trades"][0]["reason"], "time_exit")

    def test_costs_are_included(self):
        baseline = replay(self.bars(), self.sessions, "NSE:DEMO", "2026-10-19T16:00:00+05:30", CFG)
        charged = replay(
            self.bars(),
            self.sessions,
            "NSE:DEMO",
            "2026-10-19T16:00:00+05:30",
            dict(CFG, fee_bps=5, fee_flat=10, slippage_bps=5),
        )
        self.assertEqual(baseline["summary"]["net_pnl_inr"], 0)
        self.assertLess(charged["summary"]["net_pnl_inr"], 0)
        self.assertGreater(charged["trades"][0]["estimated_charges"], 20)

    def test_point_in_time_missing_and_future_financials(self):
        records = [
            dict(
                symbol="NSE:DEMO",
                source="SYNTHETIC",
                period_end="2026-09-30",
                published_at="2026-10-15T12:00:00+05:30",
                revenue_growth_yoy=-2,
            )
        ]
        rules = [dict(metric="revenue_growth_yoy", op=">=", value=-5)]
        out = screen(records, rules, "2026-10-19T10:00:00+05:30")
        self.assertEqual(out["results"][0]["status"], "PASS")
        for change in (
            {"published_at": "2026-10-20T12:00:00+05:30"},
            {"revenue_growth_yoy": ""},
            {"period_end": "2025-09-30"},
            {"source": ""},
        ):
            out = screen([dict(records[0], **change)], rules, "2026-10-19T10:00:00+05:30")
            self.assertEqual(out["results"][0]["status"], "FAIL")

    def test_read_only_requests_and_no_secret_in_url(self):
        env = dict(
            UPSTOX_ACCESS_TOKEN="test-upstox-token",
            KITE_API_KEY="test-key",
            KITE_ACCESS_TOKEN="test-kite-token",
        )
        for provider, instrument in (("upstox", "NSE_EQ|INE123456789"), ("kite", "12345")):
            request = make_request(provider, instrument, "2026-10-01", "2026-10-19", env)
            self.assertEqual(request.get_method(), "GET")
            self.assertNotIn("token", request.full_url)
            self.assertNotIn("/orders", request.full_url)
        with self.assertRaises(ValueError):
            make_request("upstox", "NSE_FO|bad", "2026-10-01", "2026-10-19", env)
        with self.assertRaises(ValueError):
            make_request("kite", "12345", "2026-10-01", "2026-10-19", {})
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")

    def test_provider_export_and_duplicate_handling(self):
        payload = {
            "status": "success",
            "data": {
                "candles": [
                    [r[k] for k in ("timestamp", "open", "high", "low", "close", "volume")]
                    for r in self.raw
                ]
            },
        }
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "bars.csv"
            self.assertEqual(export(payload, "NSE:DEMO", "SYNTHETIC", output), 75)
            self.assertEqual(len(bars_from_csv(output)), 75)
            duplicate = copy.deepcopy(payload)
            duplicate["data"]["candles"].append(duplicate["data"]["candles"][0])
            with self.assertRaises(ValueError):
                export(duplicate, "NSE:DEMO", "SYNTHETIC", Path(d) / "duplicate.csv")

    def test_cli_replay_emits_both_cost_scenarios(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            data = path / "bars.csv"
            with data.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.raw[0].keys())
                writer.writeheader()
                writer.writerows(self.raw)
            (path / "sessions.json").write_text(json.dumps(self.sessions))
            cmd = [
                sys.executable,
                str(
                    Path(__file__).resolve().parents[1]
                    / "skills/day-trader-india/scripts/india_research.py"
                ),
                "replay-orb",
                "--bars",
                str(data),
                "--sessions",
                str(path / "sessions.json"),
                "--symbol",
                "NSE:DEMO",
                "--as-of",
                "2026-10-19T16:00:00+05:30",
            ]
            for key, val in CFG.items():
                cmd.extend(["--" + key.replace("_", "-"), str(val)])
            result = json.loads(subprocess.check_output(cmd))
            self.assertIn("baseline", result)
            self.assertIn("double_cost_stress", result)


class AdditionalPaperControlsTests(unittest.TestCase):
    def buy(self, b, event="buy", at="2026-10-19T10:00:00+05:30", symbol="NSE:DEMO"):
        return fill(
            b, "buy", event, symbol, 100, at, "SYNTHETIC", 10, 0, qty=10, stop=98, exit_fee=10
        )

    def sell(self, b, event="sell", at="2026-10-19T11:00:00+05:30", price=99):
        return fill(b, "sell", event, "NSE:DEMO", price, at, "SYNTHETIC", 10, 0)

    def test_pause_blocks_entries_but_permits_exit(self):
        b = self.buy(create(100000, "NSE:DEMO,NSE:OTHER", 500, 1000, 25000, True))
        b["paused"] = True
        seal_state(b)
        with self.assertRaises(ValueError):
            self.buy(b, "another", symbol="NSE:OTHER")
        self.assertEqual(self.sell(b)["positions"], {})

    def test_daily_and_open_position_caps(self):
        b = create(100000, "NSE:DEMO,NSE:OTHER", 500, 1000, 25000, True, max_trades=1, max_open=1)
        b = self.buy(b)
        with self.assertRaises(ValueError):
            self.buy(b, "another", symbol="NSE:OTHER")
        b = self.sell(b, price=102)
        with self.assertRaises(ValueError):
            self.buy(b, "third", at="2026-10-19T12:00:00+05:30")

    def test_loss_streak_and_drawdown_stop(self):
        for kw in ({"max_loss_streak": 1}, {"drawdown_stop": 20}):
            b = create(100000, "NSE:DEMO", 500, 1000, 25000, True, **kw)
            b = self.sell(self.buy(b))
            with self.assertRaises(ValueError):
                self.buy(b, "new-day", at="2026-10-20T10:00:00+05:30")


if __name__ == "__main__":
    unittest.main()

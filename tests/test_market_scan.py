"""Market scan: the desk finds its own stocks on signals that lead the open."""

import datetime as dt
import gzip
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import market_scan
from test_market_intel import NOW, PremarketTests, SelectionFixture

import autopilot
import premarket

TODAY = NOW.date()
DUMP_HEADER = "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"


def dump_rows() -> bytes:
    lines = [
        "408065,1,INFY,INFOSYS,0,,0,0.05,1,EQ,NSE,NSE",
        "2953217,2,TCS,TATA CONSULTANCY,0,,0,0.05,1,EQ,NSE,NSE",
        "1270529,3,ICICIBANK,ICICI BANK,0,,0,0.05,1,EQ,NSE,NSE",
        "256265,4,NIFTY 50,,0,,0,0.05,0,EQ,INDICES,NSE",
        "1,5,INFY26OCTFUT,INFY,0,2026-10-27,0,0.05,400,FUT,NFO-FUT,NFO",
        "2,6,INFY26NOVFUT,INFY,0,2026-11-24,0,0.05,400,FUT,NFO-FUT,NFO",
        "3,7,TCS26OCTFUT,TCS,0,2026-10-27,0,0.05,175,FUT,NFO-FUT,NFO",
        "4,8,ICICIBANK26OCTFUT,ICICIBANK,0,2026-10-27,0,0.05,700,FUT,NFO-FUT,NFO",
        "5,9,NIFTY26OCTFUT,NIFTY,0,2026-10-27,0,0.05,75,FUT,NFO-FUT,NFO",
        "6,10,INFY26OCT1500CE,INFY,0,2026-10-27,1500,0.05,400,CE,NFO-OPT,NFO",
        "7,11,INFY26OCT1550CE,INFY,0,2026-10-27,1550,0.05,400,CE,NFO-OPT,NFO",
        "8,12,INFY26OCT1450PE,INFY,0,2026-10-27,1450,0.05,400,PE,NFO-OPT,NFO",
        "9,13,INFY26OCT1500PE,INFY,0,2026-10-27,1500,0.05,400,PE,NFO-OPT,NFO",
        "10,14,INFY26NOV1500CE,INFY,0,2026-11-24,1500,0.05,400,CE,NFO-OPT,NFO",
    ]
    return (DUMP_HEADER + "\n".join(lines) + "\n").encode()


def candles(start: float, step: float, count: int = 60) -> list[list]:
    rows, price, day = [], start, TODAY - dt.timedelta(days=count * 2)
    while len(rows) < count:
        if day.weekday() < 5:
            rows.append(
                [f"{day}T00:00:00+0530", price, price * 1.01, price * 0.99, price, 2_000_000]
            )
            # Two steps forward, one back: a trend with pullbacks, so RSI is not pinned.
            price += 2 * step if len(rows) % 2 else -step
        day += dt.timedelta(days=1)
    return rows


class FakeKite:
    def __init__(self, quotes, series):
        self.quotes, self.series, self.asked = quotes, series, []

    def quote(self, keys):
        self.asked.append(list(keys))
        return {key: self.quotes[key] for key in keys if key in self.quotes}

    def candles(self, token, interval, start, end):
        return self.series.get((str(token), interval), [])


def nse(files):
    def fetch(url):
        for name, body in files.items():
            if url.endswith(name):
                return body
        raise ValueError("NSE source unavailable: test")

    return fetch


class UniverseAndSignalTests(unittest.TestCase):
    def test_the_universe_is_every_stock_with_futures_minus_the_indices(self):
        universe = market_scan.fno_universe(market_scan.read_dump(dump_rows()), TODAY)
        self.assertEqual(sorted(universe), ["ICICIBANK", "INFY", "TCS"])
        infy = universe["INFY"]
        self.assertEqual(infy["futures"], ["NFO:INFY26OCTFUT", "NFO:INFY26NOVFUT"])
        self.assertEqual(infy["near_expiry"], "2026-10-27")
        self.assertEqual(len(infy["options"]), 4)  # Only the nearest expiry's chain.

    def test_price_against_open_interest_reads_as_positioning(self):
        cases = {
            (1.0, 5.0): "long build-up",
            (-1.0, 5.0): "short build-up",
            (1.0, -5.0): "short covering",
            (-1.0, -5.0): "long unwinding",
            (1.0, 1.0): "neutral",
            (None, 5.0): "unknown",
        }
        for (price, oi), label in cases.items():
            self.assertEqual(market_scan.buildup(price, oi), label)

    def test_option_walls_and_put_call_ratio(self):
        chain = [
            {"key": "c1", "strike": 1500, "type": "CE"},
            {"key": "c2", "strike": 1550, "type": "CE"},
            {"key": "p1", "strike": 1450, "type": "PE"},
            {"key": "p2", "strike": 1500, "type": "PE"},
        ]
        quotes = {"c1": {"oi": 100}, "c2": {"oi": 300}, "p1": {"oi": 250}, "p2": {"oi": 150}}
        walls = market_scan.option_walls(chain, quotes, 1510)
        self.assertEqual(walls, {"pcr": 1.0, "call_wall": 1550, "put_wall": 1450})

    def test_large_deals_net_out_per_symbol(self):
        bulk = b'Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price\n27-OCT-2026,INFY,Infosys,A,BUY,"1,000",1500\n27-OCT-2026,INFY,Infosys,B,SELL,400,1500\n'
        totals = market_scan.deals(nse({"bulk.csv": bulk}))
        self.assertEqual(totals["INFY"], {"net_qty": 600.0, "deals": 2})

    def test_events_in_the_window_are_kept_and_others_ignored(self):
        payload = json.dumps([
            {"symbol": "TCS", "date": "27-Oct-2026", "purpose": "Financial Results"},
            {"symbol": "INFY", "date": "20-Nov-2026", "purpose": "Dividend"},
        ]).encode()  # fmt: skip
        events = market_scan.upcoming_events(TODAY, 5, nse({"equities": payload}))
        self.assertEqual(list(events), ["TCS"])


class StageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.config = PremarketTests().project(self.directory)
        settings = json.loads(self.config.read_text())
        settings["scan"] = {"enabled": True}
        settings["min_turnover_inr"] = 1_000_000
        self.config.write_text(json.dumps(settings))
        (self.directory / f"instruments-{TODAY}.csv.gz").write_bytes(gzip.compress(dump_rows()))
        store = market_scan.ScanStore(self.directory / "scan.sqlite")
        store.save_positioning(
            str(TODAY - dt.timedelta(days=3)),
            {
                "NSE:INFY": {"prev_close": 1500, "fut_oi": 1000},
                "NSE:TCS": {"prev_close": 4000, "fut_oi": 1000},
            },
        )

    def tearDown(self):
        self.temporary.cleanup()

    def kite(self):
        def quote(close):
            return {"ohlc": {"close": close, "open": 0}}

        quotes = {
            "NSE:INFY": quote(1530),
            "NSE:TCS": quote(3900),
            "NSE:ICICIBANK": quote(1300),
            "NFO:INFY26OCTFUT": {"oi": 700},
            "NFO:INFY26NOVFUT": {"oi": 400},  # 1,100 total: +10% with price up.
            "NFO:TCS26OCTFUT": {"oi": 1200},  # +20% with price down: short build-up.
            "NFO:ICICIBANK26OCTFUT": {"oi": 500},
            "NFO:INFY26OCT1550CE": {"oi": 900},
            "NFO:INFY26OCT1500PE": {"oi": 600},
        }
        series = {
            ("408065", "day"): candles(1300, 4),  # Steady uptrend.
            ("2953217", "day"): candles(4500, -10),  # Downtrend.
            ("1270529", "day"): candles(1200, 2),
        }
        return FakeKite(quotes, series)

    def test_overnight_ranks_positioning_and_drops_downtrends_and_events(self):
        events = json.dumps(
            [{"symbol": "ICICIBANK", "date": "27-Oct-2026", "purpose": "Financial Results"}]
        ).encode()
        bhav = b"SYMBOL, SERIES, DELIV_PER\nINFY, EQ, 62.5\n"
        fetch = nse({"equities": events, "bulk.csv": b"", "block.csv": b"", "csv": bhav})
        report = market_scan.overnight(self.config, NOW, client=self.kite(), fetch=fetch)
        self.assertEqual(report["scanned"], 3)
        self.assertEqual([row["symbol"] for row in report["shortlist"]], ["NSE:INFY"])
        infy = report["shortlist"][0]["positioning"]
        self.assertEqual(infy["buildup"], "long build-up")
        self.assertEqual(infy["call_wall"], 1550)
        self.assertEqual(infy["delivery_pct"], 62.5)
        self.assertEqual(report["dropped_by"], {"daily downtrend": 1, "event today or tomorrow": 1})
        saved = market_scan.ScanStore(self.directory / "scan.sqlite").previous_positioning(
            str(TODAY + dt.timedelta(days=1))
        )
        self.assertEqual(saved["NSE:TCS"]["fut_oi"], 1200)

    def test_the_open_stage_rewards_strength_and_drops_a_hard_gap_down(self):
        rows = [
            {"symbol": s, "name": s, "sector_index": None, "events": [], "positioning": {},
             "score": {"total": 5.0, "parts": []}} for s in ("NSE:INFY", "NSE:TCS", "NSE:ICICIBANK")
        ]  # fmt: skip
        market_scan.scan_path(self.directory, TODAY).write_text(
            json.dumps(
                {
                    "stage": "overnight",
                    "session": str(TODAY),
                    "scanned": 3,
                    "passed": 3,
                    "shortlist": rows,
                }
            )  # fmt: skip
        )
        quotes = {
            "NSE:NIFTY 50": {"ohlc": {"close": 100, "open": 100.2}},
            "NSE:INFY": {"ohlc": {"close": 100, "open": 101.0}},  # +0.8 pp vs the Nifty.
            "NSE:TCS": {"ohlc": {"close": 100, "open": 98.0}},  # -2%: dropped.
            "NSE:ICICIBANK": {"ohlc": {"close": 100, "open": 104.0}},  # +4%: too late.
        }
        report = market_scan.open_stage(self.config, NOW, client=FakeKite(quotes, {}))
        self.assertEqual([row["symbol"] for row in report["ranked"]], ["NSE:INFY", "NSE:ICICIBANK"])
        self.assertEqual(report["dropped_at_open"], ["NSE:TCS"])
        self.assertEqual(report["ranked"][0]["opening"]["rs_vs_nifty_pct"], 0.8)

    def test_the_0931_check_needs_volume_vwap_and_strength(self):
        first_bars = []
        day = TODAY - dt.timedelta(days=30)
        while day < TODAY:
            if day.weekday() < 5:
                first_bars.append([f"{day}T09:15:00+0530", 1, 1, 1, 1, 100_000])
            day += dt.timedelta(days=1)
        quotes = {
            "NSE:NIFTY 50": {"last_price": 100.0, "ohlc": {"open": 100.0}},
            "NSE:INFY": {
                "last_price": 1520,
                "average_price": 1515,
                "volume": 200_000,
                "ohlc": {"open": 1500},
            },  # fmt: skip
            "NSE:TCS": {
                "last_price": 3990,
                "average_price": 4000,
                "volume": 90_000,
                "ohlc": {"open": 4000},
            },  # fmt: skip
        }
        series = {("408065", "15minute"): first_bars, ("2953217", "15minute"): first_bars}
        record = market_scan.confirm(
            self.config, ["NSE:INFY", "NSE:TCS"], NOW, client=FakeKite(quotes, series)
        )
        self.assertTrue(record["picks"]["NSE:INFY"]["confirmed"])
        self.assertEqual(record["picks"]["NSE:INFY"]["rvol"], 2.0)
        tcs = record["picks"]["NSE:TCS"]
        self.assertFalse(tcs["confirmed"])
        self.assertEqual(len(tcs["reasons"]), 3)
        coordinator = SimpleNamespace(config={"scan": {"enabled": True}}, config_path=self.config)
        self.assertEqual(autopilot.opening_gate(coordinator, "NSE:INFY", NOW), "")
        self.assertIn("failed the 09:31 check", autopilot.opening_gate(coordinator, "NSE:TCS", NOW))
        later = NOW + dt.timedelta(days=1)
        self.assertIn("waiting", autopilot.opening_gate(coordinator, "NSE:INFY", later))

    def test_the_report_uses_the_scan_and_points_the_worker_at_the_picks(self):
        store = market_scan.ScanStore(self.directory / "scan.sqlite")
        store.add_candles("NSE:INFY", candles(1300, 4), TODAY)
        signals = {"buildup": "long build-up", "oi_change_pct": 10.0, "price_change_pct": 2.0,
                   "pcr": 1.1, "call_wall": 1550, "put_wall": 1450, "delivery_pct": 62.5}  # fmt: skip
        row = {
            "symbol": "NSE:INFY", "name": "INFOSYS", "sector_index": None, "events": [],
            "positioning": signals,
            "opening": {"gap_pct": 1.0, "nifty_gap_pct": 0.2, "rs_vs_nifty_pct": 0.8},
            "score": {"total": 7.0, "parts": [
                {"factor": "trend", "points": 2.0, "reason": "up"},
                {"factor": "futures positioning", "points": 2.0, "reason": "long build-up"},
                {"factor": "pre-open strength", "points": 1.5, "reason": "+0.80 pp"},
            ]},
        }  # fmt: skip
        market_scan.scan_path(self.directory, TODAY).write_text(
            json.dumps(
                {
                    "stage": "open",
                    "session": str(TODAY),
                    "scanned": 180,
                    "passed": 40,
                    "shortlist": [row],
                    "ranked": [row],
                }
            )  # fmt: skip
        )
        (self.directory / "EQUITY_L.csv").write_text(
            "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, ISIN NUMBER\n"
            "INFY,Infosys Limited,EQ,08-FEB-1995,INE009A01021\n"
        )
        reviewer = SelectionFixture()
        report = premarket.build(self.config, NOW, reviewer=reviewer)
        self.assertEqual(report["scan"]["scanned"], 180)
        self.assertEqual(report["watching"], ["NSE:INFY"])
        factors = [part["factor"] for part in report["candidates"][0]["score"]["parts"]]
        self.assertIn("pre-open strength", factors)
        evidence = reviewer.seen["technical-analyst"]["user"]["stocks"][0]["evidence"]
        self.assertEqual(evidence["NSE:INFY#opening"]["rs_vs_nifty_pct"], 0.8)
        self.assertEqual(evidence["NSE:INFY#positioning"]["futures_buildup"], "long build-up")
        universe = json.loads((self.directory / "universe.json").read_text())
        self.assertEqual(universe["instruments"][0]["instrument_id"], "408065")
        self.assertIn("watches NSE:INFY", report["universe_written"])

    def test_without_this_mornings_scan_the_report_says_so(self):
        with self.assertRaises(ValueError) as caught:
            premarket.build(self.config, NOW, reviewer=SelectionFixture())
        self.assertIn("market scan has not run", str(caught.exception))


class LearningFromSignalsTests(unittest.TestCase):
    def test_signals_are_graded_on_daily_candles_when_no_intraday_history(self):
        import learning

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = learning.LearningStore(root / "learning.sqlite")
            report = {
                "session_date": "2026-10-23",
                "watching": ["NSE:INFY"],
                "selection": {"mode": "deterministic"},
                "candidates": [
                    {"symbol": f"NSE:S{i}",
                     "signals": {"positioning": {"buildup": "long build-up"},
                                 "opening": {"rs_vs_nifty_pct": 0.5}}}
                    for i in range(10)
                ],
            }  # fmt: skip
            store.ingest_report(report)
            scan = market_scan.ScanStore(root / "scan.sqlite")
            with sqlite3.connect(scan.path) as conn:
                for i in range(10):
                    conn.execute(
                        "INSERT INTO daily VALUES (?,?,?,?,?,?,?)",
                        (f"NSE:S{i}", "2026-10-23", 100, 103, 99, 101 + (i % 3), 1),
                    )
            when = dt.datetime(2026, 10, 23, 18, tzinfo=learning.IST)
            store.record_outcomes(root / "history.sqlite", when)
            record = {row["signal"]: row for row in store.signal_record(when)}
            self.assertEqual(record["futures: long build-up"]["count"], 10)
            self.assertEqual(record["at the open: strong vs Nifty"]["up_share"], 1.0)
            context = store.context([], [], when, {"lessons_in_prompts": True})
            self.assertEqual(len(context["signal_record"]), 2)


if __name__ == "__main__":
    unittest.main()

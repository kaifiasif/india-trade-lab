"""Backtest grid, preflight, evidence collection and pre-trade derivation, all offline."""

import csv
import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import backtest
from decision_pipeline import DEFAULT_CONFIG
from history import HistoryStore
from test_history import IST, fixtures

import engine
import evidence
import paper_book
import preflight
import pretrade

ASSETS = Path(__file__).resolve().parents[1] / "skills/day-trader-india/assets"
CALENDAR = ASSETS / "nse-sessions-2026.json"


def _session_times(date: dt.date) -> dict:
    at = lambda clock: dt.datetime.combine(date, clock, tzinfo=IST)  # noqa: E731
    return {
        "open": at(dt.time(9, 15)),
        "entry_cutoff": at(dt.time(14, 30)),
        "flat_by": at(dt.time(15, 15)),
        "close": at(dt.time(15, 30)),
    }


class EngineRegressionTests(unittest.TestCase):
    def test_the_strategy_still_sees_quotes_while_a_position_is_open(self):
        """An open position must not break the strategy's own bar-grid tracking."""
        date = dt.date(2026, 10, 26)
        session = _session_times(date)
        symbol = "NSE:DEMO"
        book = paper_book.create("100000", symbol, "250", "750", "15000", replay=True)
        broker = engine.PaperBroker(book, Decimal(5))
        config = engine.EngineConfig((symbol,), Decimal(5), Decimal(10), Decimal(5))
        strategy = engine.OpeningRangeBreakout(Decimal(250), Decimal(15000), Decimal(2))
        runner = engine.Engine(config, session, broker, strategy, notifier=lambda *_: None)
        prices = [100, 100, 100, 104, 104, 104, 97, 101, 102]
        for index, close in enumerate(prices):
            stamp = session["open"] + engine.BAR * (index + 1)
            quote = engine.Quote(
                symbol,
                stamp,
                Decimal(close),
                Decimal(close),
                "SYNTHETIC TEST ONLY",
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
            )
            runner.on_quote(quote, stamp)
        blocked = [e for e in runner.log if e["kind"] == "strategy_blocked"]
        self.assertEqual(blocked, [], "an open position must not look like missing data")
        self.assertEqual(strategy.bar_count[symbol], len(prices))
        self.assertNotIn(symbol, strategy.invalid)


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name)
        bars, sessions, self.dates = fixtures(directory, count=6)
        store = HistoryStore(directory / "history.sqlite")
        cutoff = dt.datetime.combine(self.dates[-1], dt.time(16), tzinfo=IST)
        store.ingest(bars, sessions, "NSE:TEST", "broker_export", cutoff)
        self.history = directory / "history.sqlite"
        self.cfg = {
            "cash": Decimal(100000), "risk": Decimal(250), "daily_loss": Decimal(750),
            "position_cap": Decimal(15000), "target_r": Decimal(2), "fee_bps": Decimal(5),
            "fee_flat": Decimal(10), "slippage_bps": Decimal(5), "spread_bps": Decimal(4),
            "max_trades": Decimal(3),
        }  # fmt: skip

    def test_the_grid_runs_the_real_engine_over_stored_sessions(self):
        result = backtest.backtest(
            self.history, ["NSE:TEST"], self.dates[0], self.dates[-1], self.cfg
        )
        self.assertEqual(result["mode"], "historical_backtest")
        self.assertEqual(result["sessions"], 6)
        self.assertEqual(result["baseline"]["cost_multiplier"], 1)
        self.assertEqual(result["doubled_costs"]["cost_multiplier"], 2)
        self.assertIn("NSE:TEST", result["baseline"]["by_symbol"])
        self.assertIn("halves", result["baseline"])
        self.assertEqual(result["baseline"]["sessions_with_data_blocks"], 0)

    def test_doubled_costs_never_improve_the_result(self):
        result = backtest.backtest(
            self.history, ["NSE:TEST"], self.dates[0], self.dates[-1], self.cfg
        )
        base = result["baseline"]["overall"]
        stress = result["doubled_costs"]["overall"]
        if base["trades"]:
            self.assertLessEqual(stress["net_inr"], base["net_inr"])

    def test_an_empty_range_is_refused_rather_than_scored(self):
        with self.assertRaises(ValueError):
            backtest.backtest(
                self.history, ["NSE:TEST"], dt.date(2025, 1, 1), dt.date(2025, 1, 2), self.cfg
            )

    def test_summaries_describe_an_empty_set_without_inventing_numbers(self):
        summary = backtest.summarize([], 100000.0)
        self.assertEqual(summary["trades"], 0)
        self.assertIsNone(summary["win_rate_pct"])
        self.assertIsNone(summary["expectancy_inr"])
        self.assertEqual(summary["max_closed_drawdown_inr"], 0)


class EvidenceTests(unittest.TestCase):
    RSS = (
        b'<?xml version="1.0"?><rss><channel>'
        b"<item><title>Infosys wins deal &amp; raises guidance</title>"
        b"<pubDate>Mon, 26 Oct 2026 08:30:00 GMT</pubDate><source>Reuters</source>"
        b"<link>https://example.test/1</link></item>"
        b"<item><title>Tomorrow's story</title><pubDate>Wed, 28 Oct 2026 20:00:00 GMT</pubDate>"
        b"<source>Mint</source><link>https://example.test/2</link></item>"
        b"<item><title><![CDATA[<script>bad</script>Tagged]]></title>"
        b"<pubDate>Sun, 25 Oct 2026 05:00:00 GMT</pubDate><source>ET</source>"
        b"<link>https://example.test/3</link></item>"
        b"</channel></rss>"
    )

    def test_only_items_published_by_the_cutoff_are_kept(self):
        cutoff = dt.datetime(2026, 10, 27, 10, tzinfo=IST)
        items = evidence.parse_news(self.RSS, cutoff)
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["published_at"] <= cutoff.isoformat() for item in items))
        self.assertFalse(any("Tomorrow" in item["title"] for item in items))

    def test_markup_and_entities_in_a_headline_become_plain_text(self):
        items = evidence.parse_news(self.RSS, dt.datetime(2026, 10, 27, 10, tzinfo=IST))
        titles = [item["title"] for item in items]
        self.assertIn("Infosys wins deal & raises guidance", titles)
        self.assertTrue(all("<" not in title for title in titles))

    def test_announcements_are_dated_and_point_in_time(self):
        raw = json.dumps(
            [
                {"an_dt": "26-Oct-2026 18:00:00", "desc": "Board meeting outcome"},
                {"an_dt": "28-Oct-2026 09:00:00", "desc": "Future filing"},
                {"desc": "Undated"},
            ]
        ).encode()
        items = evidence.parse_announcements(raw, dt.datetime(2026, 10, 27, 10, tzinfo=IST))
        self.assertEqual([item["title"] for item in items], ["Board meeting outcome"])

    def test_a_failing_source_is_reported_not_invented(self):
        def fetch(url, params, headers, timeout=20):
            raise ValueError("source unavailable")

        items, notes, read = evidence.collect_symbol(
            "NSE:INFY", "Infosys", dt.datetime(2026, 10, 27, tzinfo=IST), fetch
        )
        self.assertEqual(items, [])
        self.assertEqual(len(notes), 2)
        self.assertFalse(read)

    def test_malformed_feeds_are_refused(self):
        cutoff = dt.datetime(2026, 10, 27, tzinfo=IST)
        with self.assertRaises(ValueError):
            evidence.parse_news(b"not xml", cutoff)
        with self.assertRaises(ValueError):
            evidence.parse_announcements(b"{not json", cutoff)


def build_project(directory: Path, now: dt.datetime, breakout: bool = True) -> Path:
    """A complete, realistic private project: calendar, universe, history, bars, quote, book."""
    today = now.date()
    days, cursor = [], today - dt.timedelta(days=120)
    while cursor <= today:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += dt.timedelta(days=1)
    sessions = {
        "timezone": "Asia/Kolkata",
        "source": "NSE circular (offline fixture)",
        "sessions": {
            str(day): {
                "open": "09:15", "close": "15:30", "entry_cutoff": "14:30", "flat_by": "15:15",
            }
            for day in days
        },
    }  # fmt: skip
    (directory / "sessions.json").write_text(json.dumps(sessions))
    rows = []
    for day in days[:-1]:
        for index in range(75):
            stamp = dt.datetime.combine(day, dt.time(9, 15), tzinfo=IST) + dt.timedelta(
                minutes=5 * index
            )
            rows.append(
                ("NSE:INFY", stamp.isoformat(), 1500, 1505, 1495, 1500, 60000,
                 "kite:historical:5minute:408065")
            )  # fmt: skip
    with (directory / "hist.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("symbol", "timestamp", "open", "high", "low", "close", "volume", "source"))
        writer.writerows(rows)
    HistoryStore(directory / "history.sqlite").ingest(
        directory / "hist.csv", directory / "sessions.json", "NSE:INFY", "broker_export", now
    )
    closes = [(1500, 1505, 1498, 1502), (1502, 1506, 1499, 1501), (1501, 1505, 1498, 1503)]
    closes.append((1503, 1512, 1502, 1510) if breakout else (1503, 1504, 1499, 1500))
    with (directory / "current-bars.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("symbol", "timestamp", "open", "high", "low", "close", "volume", "source"))
        for index, (o, h, low, c) in enumerate(closes):
            stamp = dt.datetime.combine(today, dt.time(9, 15), tzinfo=IST) + dt.timedelta(
                minutes=5 * index
            )
            writer.writerow(
                (
                    "NSE:INFY",
                    stamp.isoformat(),
                    o,
                    h,
                    low,
                    c,
                    70000,
                    "kite:historical:5minute:408065",
                )
            )
    (directory / "universe.json").write_text(
        json.dumps(
            {
                "source": "NSE EQUITY_L.csv and Kite dump (offline fixture)",
                "as_of": now.isoformat(),
                "instruments": [
                    {
                        "symbol": "NSE:INFY", "name": "Infosys Limited", "segment": "EQ",
                        "active": True, "isin": "INE009A01021", "data_provider": "kite",
                        "instrument_id": "408065", "quote_provider": "kite", "industry": "IT",
                    }
                ],
            }
        )
    )  # fmt: skip
    (directory / "quotes.json").write_text(
        json.dumps(
            {
                "NSE:INFY": {
                    "symbol": "NSE:INFY", "bid_inr": "1510.00", "ask_inr": "1510.50",
                    "as_of": (now - dt.timedelta(seconds=20)).isoformat(),
                    "received_at": now.isoformat(), "timestamp_kind": "exchange",
                    "source": "kite:full_quote:408065",
                    "lower_circuit_inr": "1350.00", "upper_circuit_inr": "1650.00",
                }
            }
        )
    )  # fmt: skip
    book = paper_book.create("100000", "NSE:INFY", "250", "750", "15000")
    with sqlite3.connect(directory / "paper.sqlite") as conn:
        conn.execute("CREATE TABLE book (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO book VALUES (1,?)", (json.dumps(book),))
    config = directory / "pipeline.json"
    # A flat fixture series; the daily filters are tested on their own.
    settings = {**DEFAULT_CONFIG, "strategy": {**DEFAULT_CONFIG["strategy"], "filters": False}}
    config.write_text(json.dumps(settings))
    from test_decision_pipeline import prove

    prove(directory, now)
    return config


class PretradeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.now = dt.datetime(2026, 10, 26, 9, 36, tzinfo=IST)
        self.config = build_project(self.directory, self.now)

    def attested(self):
        pretrade.attest(
            self.directory / "attestations.json",
            "NSE:INFY",
            str(self.now.date()),
            {
                "surveillance_clear": "NSE ASM/GSM lists checked 09:05 IST",
                "no_material_event": "NSE announcements checked 09:05 IST",
            },
            self.now,
        )

    def test_derived_evidence_satisfies_the_journal_entry_gate(self):
        self.attested()
        result = pretrade.build(self.config, None, self.now)
        self.assertEqual(result["ready"], ["NSE:INFY"])
        payload = json.loads((self.directory / "pretrade-evidence.json").read_text())
        item = payload["NSE:INFY"]
        self.assertTrue(all(item["checks"].values()))
        self.assertEqual(len(item["evidence_sources"]), 10)
        # The journal's own gate is the real test of this evidence.
        book = paper_book.create("100000", "NSE:INFY", "250", "750", "15000")
        state = paper_book.fill(
            book, "buy", "e1", "NSE:INFY", "1510.50",
            (self.now - dt.timedelta(seconds=20)).isoformat(), "kite:full_quote:408065",
            "13.60", "5", qty=9, stop="1498", exit_fee="13.49", now=self.now, evidence=item,
        )  # fmt: skip
        self.assertEqual(state["positions"]["NSE:INFY"]["qty"], 9)

    def test_judgement_checks_need_a_dated_human_attestation(self):
        result = pretrade.build(self.config, None, self.now)
        self.assertEqual(result["ready"], [])
        self.assertIn("no attestation for today", result["refused"]["NSE:INFY"])
        yesterday = str(self.now.date() - dt.timedelta(days=1))
        pretrade.attest(
            self.directory / "attestations.json", "NSE:INFY", yesterday,
            {"surveillance_clear": "s", "no_material_event": "e"}, self.now,
        )  # fmt: skip
        self.assertEqual(pretrade.build(self.config, None, self.now)["ready"], [])
        with self.assertRaises(ValueError):
            pretrade.attest(
                self.directory / "attestations.json", "NSE:INFY", str(self.now.date()),
                {"surveillance_clear": "  ", "no_material_event": "e"}, self.now,
            )  # fmt: skip

    def test_each_unmet_machine_check_refuses_with_its_own_reason(self):
        self.attested()
        quotes = self.directory / "quotes.json"
        original = json.loads(quotes.read_text())

        def with_quote(**changes):
            quote = {**original["NSE:INFY"], **changes}
            quotes.write_text(json.dumps({"NSE:INFY": quote}))
            return pretrade.build(self.config, None, self.now)["refused"].get("NSE:INFY", "")

        cases = {
            "stale": ({"as_of": (self.now - dt.timedelta(seconds=400)).isoformat()}, "120s"),
            "last trade": ({"timestamp_kind": "last_trade"}, "exchange bid/ask timestamp"),
            "synthetic": ({"source": "SYNTHETIC_FIXTURE"}, "synthetic"),
            "outside band": ({"upper_circuit_inr": "1505.00"}, "circuit band"),
            "wide spread": ({"bid_inr": "1500.00"}, "spread"),
        }
        for name, (changes, expected) in cases.items():
            with self.subTest(case=name):
                self.assertIn(expected, with_quote(**changes))
        quotes.write_text(json.dumps(original))
        del original["NSE:INFY"]["lower_circuit_inr"]
        quotes.write_text(json.dumps(original))
        self.assertIn(
            "circuit band", pretrade.build(self.config, None, self.now)["refused"]["NSE:INFY"]
        )

    def test_no_breakout_on_the_latest_bar_is_refused(self):
        directory = Path(tempfile.mkdtemp(dir=self.temporary.name))
        config = build_project(directory, self.now, breakout=False)
        pretrade.attest(
            directory / "attestations.json", "NSE:INFY", str(self.now.date()),
            {"surveillance_clear": "s", "no_material_event": "e"}, self.now,
        )  # fmt: skip
        refused = pretrade.build(config, None, self.now)["refused"]["NSE:INFY"]
        self.assertIn("setup on the latest completed bar", refused)


class PreflightTests(unittest.TestCase):
    def test_a_fresh_config_names_every_missing_input_with_a_fix(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "pipeline.json"
            config.write_text(json.dumps(dict(DEFAULT_CONFIG)))
            result = preflight.run(config)
            self.assertEqual(result["status"], preflight.FATAL)
            named = {item["check"] for item in result["checks"]}
            self.assertTrue({"exchange calendar", "forward paper book"} <= named)
            for item in result["checks"]:
                if item["status"] in (preflight.BLOCK, preflight.FATAL):
                    self.assertTrue(item["fix"], f"{item['check']} must suggest a fix")
            self.assertIn("preflight", preflight.render(result).lower())

    def test_a_complete_project_reports_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            now = dt.datetime(2026, 10, 26, 9, 36, tzinfo=IST)
            config = build_project(directory, now)
            pretrade.attest(
                directory / "attestations.json", "NSE:INFY", str(now.date()),
                {"surveillance_clear": "s", "no_material_event": "e"}, now,
            )  # fmt: skip
            pretrade.build(config, None, now)
            (directory / "research-evidence.json").write_text(
                json.dumps({"NSE:INFY": [{"id": "n1", "source": "s", "facts": "f",
                                          "observed_at": now.isoformat()}]})
            )  # fmt: skip
            settings = json.loads(config.read_text())
            settings["model_provider"] = "local"
            settings["model"] = "qwen3:14b"
            config.write_text(json.dumps(settings))
            with patch.dict("os.environ", {"KITE_API_KEY": "k", "KITE_ACCESS_TOKEN": "t"}):
                result = preflight.run(config, now)
            blocked = [
                i for i in result["checks"] if i["status"] in (preflight.BLOCK, preflight.FATAL)
            ]
            self.assertEqual(blocked, [], result["checks"])
            self.assertEqual(result["status"], preflight.OK)

    def test_the_bundled_nse_calendar_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = directory / "pipeline.json"
            config.write_text(json.dumps(dict(DEFAULT_CONFIG)))
            (directory / "sessions.json").write_text(CALENDAR.read_text())
            checks = preflight.Checks()
            from decision_pipeline import DailyCoordinator

            manifest = preflight.check_sessions(
                DailyCoordinator(config), dt.datetime(2026, 10, 26, 10, tzinfo=IST), checks
            )
            self.assertIsNotNone(manifest)
            self.assertEqual(checks.items[0]["status"], preflight.OK)


if __name__ == "__main__":
    unittest.main()


class EvidenceRetentionTests(unittest.TestCase):
    def test_an_outage_keeps_previously_collected_items(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            now = dt.datetime(2026, 10, 26, 9, 36, tzinfo=IST)
            config = build_project(directory, now)
            working = EvidenceTests.RSS

            def fetch(url, params, headers, timeout=20):
                if "news.google" in url:
                    return working
                raise ValueError("source unavailable")

            first = evidence.collect(config, now, fetch)
            # Only the headline published before this cutoff survives the point-in-time filter.
            collected = first["symbols"]["NSE:INFY"]
            self.assertEqual(collected, 1)

            def broken(url, params, headers, timeout=20):
                raise ValueError("source unavailable")

            second = evidence.collect(config, now, broken)
            self.assertEqual(second["kept_from_previous"], ["NSE:INFY"])
            self.assertEqual(second["symbols"]["NSE:INFY"], collected)
            stored = json.loads((directory / "research-evidence.json").read_text())
            self.assertEqual(len(stored["NSE:INFY"]), collected)

    def test_a_source_that_answers_with_nothing_replaces_what_it_covers(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            now = dt.datetime(2026, 10, 26, 9, 36, tzinfo=IST)
            config = build_project(directory, now)
            evidence.collect(config, now, lambda *a, **k: EvidenceTests.RSS)
            empty = b'<?xml version="1.0"?><rss><channel></channel></rss>'
            result = evidence.collect(config, now, lambda *a, **k: empty)
            self.assertEqual(result["kept_from_previous"], [])
            self.assertNotIn("NSE:INFY", result["symbols"])

"""The itl command: setup is idempotent and the track record counts only closed paper trades."""

import contextlib
import datetime as dt
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import itl
import paper_book

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class ItlTests(unittest.TestCase):
    def test_setup_creates_the_project_once_and_keeps_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "pipeline.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(itl.main(["--config", str(config), "setup"]), 0)
                (config.parent / "sessions.json").write_text('{"kept": true}')
                self.assertEqual(itl.main(["--config", str(config), "setup"]), 0)
            self.assertTrue(json.loads(config.read_text())["version"] == 1)
            self.assertEqual(
                json.loads((config.parent / "sessions.json").read_text()), {"kept": True}
            )

    def test_track_reports_closed_trades_with_costs(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            now = dt.datetime.now(IST).replace(microsecond=0)
            book = paper_book.create("100000", "NSE:DEMO", "250", "750", "15000", replay=True)
            book = paper_book.fill(
                book, "buy", "e1", "NSE:DEMO", "100", now.isoformat(), "OFFLINE_TEST", "10",
                "0", 50, "98", "10", now=now,
            )  # fmt: skip
            later = now + dt.timedelta(minutes=30)
            book = paper_book.fill(
                book, "sell", "x1", "NSE:DEMO", "104", later.isoformat(), "OFFLINE_TEST", "10",
                "0", now=later,
            )  # fmt: skip
            with sqlite3.connect(directory / "paper.sqlite") as conn:
                conn.execute("CREATE TABLE book (id INTEGER PRIMARY KEY, data TEXT)")
                conn.execute("INSERT INTO book VALUES (1, ?)", (json.dumps(book),))
            trades = itl.closed_trades(book)
            self.assertEqual(len(trades), 1)
            self.assertEqual(str(trades[0]["net_inr"]), "180.00")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(
                    itl.main(["--config", str(directory / "pipeline.json"), "track"]), 0
                )
            self.assertIn("Closed trades: 1", out.getvalue())
            self.assertIn("Net after costs: INR 180.00", out.getvalue())


if __name__ == "__main__":
    unittest.main()

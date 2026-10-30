"""Today's desk: the dashboard reads the latest pre-market report and scorecard, read only."""

import json
import tempfile
import unittest
from pathlib import Path

from observatory import desk_state

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "docs" / "examples" / "premarket-sample.json"


class DeskTests(unittest.TestCase):
    def test_the_latest_report_and_scorecard_are_summarised(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "reports").mkdir()
            report = json.loads(SAMPLE.read_text())
            (directory / "reports" / "premarket-2026-10-20.json").write_text(
                json.dumps({**report, "session_date": "2026-10-20"})
            )
            (directory / "reports" / "premarket-2026-10-26.json").write_text(json.dumps(report))
            (directory / "strategy-scorecard.json").write_text(
                json.dumps(
                    {
                        "as_of": "2026-10-26T16:00:00+05:30",
                        "strategies": {
                            "orb-v1": {
                                "eligible": False,
                                "reasons": ["lost INR 10 at double costs"],
                                "doubled_costs": {"trades": 40},
                            }
                        },
                    }
                )
            )
            desk = desk_state(directory)
            self.assertEqual(desk["report"]["session_date"], report["session_date"])
            self.assertEqual(
                [pick["symbol"] for pick in desk["report"]["picks"]], report["watching"]
            )
            self.assertEqual(desk["report"]["picks"][0]["risk"], "low")
            self.assertFalse(desk["scorecard"]["strategies"]["orb-v1"]["eligible"])
            self.assertIn("double costs", desk["scorecard"]["strategies"]["orb-v1"]["reason"])

    def test_missing_or_broken_files_show_nothing_rather_than_failing(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertEqual(
                desk_state(directory),
                {"report": None, "scorecard": None, "trade_desk": None, "swing": None},
            )
            (directory / "reports").mkdir()
            (directory / "reports" / "premarket-2026-10-26.json").write_text("{broken")
            (directory / "strategy-scorecard.json").write_text("[]")
            self.assertEqual(
                desk_state(directory),
                {"report": None, "scorecard": None, "trade_desk": None, "swing": None},
            )


if __name__ == "__main__":
    unittest.main()

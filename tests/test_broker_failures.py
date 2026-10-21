"""Check malformed provider schemas and redacted failures without any network calls."""

import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from broker_data import export, main


class BrokerFailureTests(unittest.TestCase):
    def test_malformed_payloads_fail_before_creating_output(self):
        payloads = [
            [],
            None,
            "not an object",
            {"status": "success", "data": None},
            {"status": "success", "data": []},
            {"status": "success", "data": {"candles": "not a list"}},
            {"status": "success", "data": {"candles": [["missing OHLCV"]]}},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bars.csv"
            for payload in payloads:
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    export(payload, "NSE:DEMO", "SYNTHETIC", output)
                self.assertFalse(output.exists())

    def test_cli_redacts_provider_errors_and_refuses_malformed_json(self):
        secret = "SYNTHETIC_CREDENTIAL_MUST_NOT_APPEAR"
        cases = [
            urllib.error.HTTPError("https://api.kite.trade", 403, secret, {}, None),
            urllib.error.URLError(secret),
            b"not JSON",
            json.dumps({"status": "success", "data": None}).encode(),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bars.csv"
            argv = [
                "broker_data.py",
                "--provider",
                "kite",
                "--instrument",
                "123",
                "--symbol",
                "NSE:DEMO",
                "--from-date",
                "2026-10-19",
                "--to-date",
                "2026-10-19",
                "--output",
                str(output),
            ]
            for case in cases:
                opener = MagicMock()
                if isinstance(case, Exception):
                    opener.open.side_effect = case
                else:
                    opener.open.return_value.__enter__.return_value.read.return_value = case
                stderr = io.StringIO()
                with (
                    self.subTest(case=type(case).__name__),
                    patch("sys.argv", argv),
                    patch.dict("os.environ", {"KITE_API_KEY": secret, "KITE_ACCESS_TOKEN": secret}),
                    patch("broker_data.urllib.request.build_opener", return_value=opener),
                    contextlib.redirect_stderr(stderr),
                ):
                    self.assertEqual(main(), 2)
                self.assertNotIn(secret, stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                self.assertIn("REFUSED:", stderr.getvalue())
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

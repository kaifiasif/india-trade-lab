"""Exercise the real replay API and persisted projections using offline synthetic fixtures."""

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from observatory import Observatory, make_handler, project_state, read_run


class ObservatoryTests(unittest.TestCase):
    def test_projection_matches_persisted_fills_and_retains_prior_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Observatory(Path(directory), interval=0)
            self.assertEqual(app.state()["status"], "idle")
            first = app.start("baseline")
            app.worker.join(5)
            self.assertFalse(app.worker.is_alive())
            state = app.state()
            self.assertEqual(state["status"], "completed")
            self.assertEqual([call["side"] for call in state["calls"]], ["buy", "sell"])
            self.assertEqual(state["metrics"]["fills"], 2)
            self.assertEqual(state["metrics"]["open_positions"], 0)
            self.assertEqual(state["metrics"]["proposals"], 1)
            self.assertEqual(state["calls"][0]["stop"], "99.0")
            self.assertTrue(all(agent["status"] == "idle" for agent in state["agents"][5:]))
            book, snapshot, events = read_run(app.current)
            self.assertEqual(len(book["events"]), state["metrics"]["fills"])
            self.assertEqual(snapshot["version"], 2)
            self.assertGreater(len(events), 10)
            app.start("data-gap")
            app.worker.join(5)
            self.assertEqual(app.state()["calls"], [])
            self.assertTrue(
                any("DATA BLOCK" in event.get("reason", "") for event in app.state()["events"])
            )
            self.assertEqual(len(list(Path(directory).glob("run-*.sqlite"))), 2)
            self.assertEqual(
                project_state(Path(directory) / f"{first}.sqlite")["metrics"]["fills"], 2
            )
            reopened = Observatory(Path(directory))
            self.assertEqual(reopened.state()["status"], "interrupted")

    def test_oversized_proposal_is_rejected_by_the_actual_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Observatory(Path(directory), interval=0)
            app.start("risk-block")
            app.worker.join(5)
            state = app.state()
            self.assertEqual(state["metrics"]["fills"], 0)
            self.assertEqual(state["calls"][0]["status"], "rejected")
            self.assertEqual(state["metrics"]["blocked"], 1)

    def test_run_exclusivity_pause_halt_and_input_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Observatory(Path(directory), interval=0.005)
            with self.assertRaises(ValueError):
                app.start("live")
            with self.assertRaises(ValueError):
                app.control("resume")
            app.start("baseline")
            app.control("pause")
            self.assertEqual(app.status, "paused")
            with self.assertRaises(ValueError):
                app.start("baseline")
            app.control("halt")
            app.worker.join(5)
            state = app.state()
            self.assertEqual(state["status"], "halted")
            self.assertIn("Dashboard entry halt", state["halt_reason"])
            self.assertFalse(any(call["side"] == "buy" for call in state["calls"]))

    def test_local_api_rejects_unauthorized_and_cross_origin_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Observatory(Path(directory), interval=0)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/api/session", timeout=3) as response:
                    session = json.load(response)
                    self.assertIn(
                        "frame-ancestors 'none'", response.headers["Content-Security-Policy"]
                    )
                for headers in (
                    {},
                    {"X-Session-Token": session["token"], "Origin": "https://bad.test"},
                ):
                    request = Request(
                        base + "/api/replay",
                        data=b'{"scenario":"baseline"}',
                        headers={"Content-Type": "application/json", **headers},
                    )
                    with self.assertRaises(HTTPError) as error:
                        urlopen(request, timeout=3)
                    self.assertEqual(error.exception.code, 403)
                request = Request(
                    base + "/api/replay",
                    data=b'{"scenario":"baseline"}',
                    headers={
                        "Content-Type": "application/json",
                        "X-Session-Token": session["token"],
                    },
                )
                with urlopen(request, timeout=3) as response:
                    self.assertTrue(json.load(response)["run_id"].startswith("run-"))
                app.worker.join(5)
                with urlopen(base + "/api/state", timeout=3) as response:
                    self.assertEqual(json.load(response)["metrics"]["fills"], 2)
                web = (
                    Path(__file__).resolve().parents[1]
                    / "skills/day-trader-india/assets/observatory"
                )
                bundle = next((web / "assets").glob("index-*.js"))
                for path, filename in (
                    ("/", "index.html"),
                    ("/favicon.svg", "favicon.svg"),
                    (f"/assets/{bundle.name}", f"assets/{bundle.name}"),
                ):
                    with urlopen(base + path, timeout=3) as response:
                        self.assertEqual(response.read(), (web / filename).read_bytes())
                        self.assertIn(
                            "script-src 'self'", response.headers["Content-Security-Policy"]
                        )
                for path, headers in (
                    ("/assets/missing.js", {}),
                    ("/../README.md", {}),
                    ("/api/state", {"Host": "attacker.test"}),
                ):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base + path, headers=headers), timeout=3)
                    self.assertIn(error.exception.code, (403, 404))
            finally:
                server.shutdown()
                server.server_close()
                worker.join(3)


if __name__ == "__main__":
    unittest.main()

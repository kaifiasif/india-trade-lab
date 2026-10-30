"""Setup from the UI: secrets never come back, settings never half-save, jobs never duplicate."""

import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from observatory import Observatory, make_handler

import job_runner
import secret_store
import settings_store

SECRET = "kite-secret-VALUE-123456"


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.env = patch.dict(os.environ, {"ITL_CONFIG_DIR": str(self.root / "store")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temporary.cleanup()


class SecretStoreTests(Isolated):
    def test_values_are_private_and_only_described_never_returned(self):
        described = secret_store.set_secret("KITE_API_SECRET", SECRET)
        self.assertEqual(described, {"key": "KITE_API_SECRET", "set": True, "last4": "3456"})
        path = self.root / "store" / "secrets.env"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertNotIn(SECRET, json.dumps(secret_store.status()))
        self.assertEqual(secret_store.environment({})["KITE_API_SECRET"], SECRET)
        self.assertEqual(secret_store.scrub(f"token {SECRET} end"), "token [redacted] end")
        secret_store.set_secret("KITE_API_SECRET", "")
        self.assertFalse(secret_store.describe("KITE_API_SECRET")["set"])

    def test_unknown_keys_and_unsafe_values_are_refused(self):
        with self.assertRaises(ValueError):
            secret_store.set_secret("PATH", "x")
        for value in ("a'b", "line\nbreak"):
            with self.assertRaises(ValueError):
                secret_store.set_secret("GEMINI_API_KEY", value)


class SettingsTests(Isolated):
    def config(self):
        from decision_pipeline import DEFAULT_CONFIG

        path = self.root / "pipeline.json"
        path.write_text(json.dumps(DEFAULT_CONFIG))
        return path

    def test_valid_save_is_versioned_backed_up_and_paper_only(self):
        path = self.config()
        view = settings_store.editable_view(path)
        saved = settings_store.save(path, {"max_candidates": 10}, view["version"])
        self.assertEqual(saved["settings"]["max_candidates"], 10)
        self.assertNotEqual(saved["version"], view["version"])
        self.assertEqual(json.loads(path.read_text())["mode"], "paper_research")
        self.assertEqual(len(list(self.root.glob("pipeline.json.bak-*"))), 1)

    def test_stale_invalid_and_forbidden_saves_leave_the_file_unchanged(self):
        path = self.config()
        before = path.read_bytes()
        version = settings_store.editable_view(path)["version"]
        with self.assertRaises(PermissionError):
            settings_store.save(path, {"max_candidates": 2}, "stale")
        with self.assertRaises(ValueError):
            settings_store.save(path, {"max_candidates": 99}, version)
        with self.assertRaises(ValueError):
            settings_store.save(path, {"max_candidates": 11}, version)
        with self.assertRaises(KeyError):
            settings_store.save(path, {"mode": "live"}, version)
        self.assertEqual(path.read_bytes(), before)

    def test_no_editable_key_can_reach_orders(self):
        for key in settings_store.EDITABLE:
            for word in settings_store.FORBIDDEN_WORDS:
                self.assertNotIn(word, key)


class JobRunnerTests(Isolated):
    def test_one_job_per_kind_logs_are_scrubbed_and_finish(self):
        secret_store.set_secret("KITE_API_SECRET", SECRET)
        runner = job_runner.JobRunner(self.root, self.root / "pipeline.json")
        command = [sys.executable, "-c", f"import time; print('{SECRET}'); time.sleep(0.6)"]
        first = runner.start("preflight", command)
        second = runner.start("preflight", command)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(second["id"], first["id"])
        for _ in range(60):
            job = runner.get(first["id"])
            if job["state"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(job["state"], "succeeded")
        self.assertIn("[redacted]", job["text"])
        self.assertNotIn(SECRET, job["text"])
        with self.assertRaises(KeyError):
            runner.start("rm -rf", command)

    def test_a_job_left_running_by_a_crash_is_marked_interrupted(self):
        folder = self.root / "jobs"
        folder.mkdir()
        (folder / "x-1.json").write_text(
            json.dumps({"id": "x-1", "kind": "report", "state": "running", "started_at": "t"})
        )
        job_runner.JobRunner(self.root, self.root / "pipeline.json")
        self.assertEqual(json.loads((folder / "x-1.json").read_text())["state"], "interrupted")


class EmailTests(Isolated):
    def test_email_needs_a_server_a_sender_and_a_stored_password(self):
        import premarket

        report = {"session_date": "2026-10-27", "watching": [], "notice": "n"}
        config = {"email_to": ["me@example.com"], "smtp_host": "smtp.example.com"}
        self.assertIn("sender", premarket.send_email(report, "<p>x</p>", config)["reason"])
        config["smtp_user"] = "me@example.com"
        with patch.dict(os.environ, {"SMTP_PASSWORD": ""}):
            self.assertIn("password", premarket.send_email(report, "<p>x</p>", config)["reason"])
            secret_store.set_secret("SMTP_PASSWORD", "abcd efgh ijkl mnop")
            sent = []

            class FakeSMTP:
                def __init__(self, host, port, timeout):
                    sent.append((host, port))

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def starttls(self):
                    pass

                def login(self, user, password):
                    sent.append((user, password))

                def send_message(self, message):
                    sent.append(message["To"])

            with (
                patch("smtplib.SMTP", FakeSMTP),
                patch.object(premarket, "mail_host_problem", return_value=None),
            ):
                result = premarket.send_email(report, "<p>x</p>", config)
        self.assertTrue(result["sent"])
        self.assertEqual(result["to"], "m***@example.com")
        self.assertEqual(sent[1], ("me@example.com", "abcd efgh ijkl mnop"))


class HardeningTests(Isolated):
    def test_mail_server_cannot_point_at_internal_addresses(self):
        import premarket

        for host in ("127.0.0.1", "localhost", "10.0.0.5", "metadata.google.internal", ""):
            self.assertFalse(premarket.public_mail_host(host), host)
        with patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("169.254.169.254", 0))]):
            self.assertFalse(premarket.public_mail_host("evil.example.com"))
        with patch("socket.getaddrinfo", return_value=[(0, 0, 0, "", ("142.250.4.108", 0))]):
            self.assertTrue(premarket.public_mail_host("smtp.gmail.com"))

    def test_logs_mask_email_addresses(self):
        self.assertEqual(
            secret_store.scrub("sent to kaifi.asif@gmail.com ok"), "sent to k***@gmail.com ok"
        )

    def test_rate_limiter_blocks_then_recovers(self):
        import setup_api

        now = [0.0]
        limiter = setup_api.RateLimiter(clock=lambda: now[0])
        self.assertEqual([limiter.check("x", 2) for _ in range(2)], [0.0, 0.0])
        self.assertGreater(limiter.check("x", 2), 0)
        now[0] = 61
        self.assertEqual(limiter.check("x", 2), 0.0)


class HttpTests(Isolated):
    def setUp(self):
        super().setUp()
        self.app = Observatory(self.root / "data", interval=0)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)
        super().tearDown()

    def post(self, action, payload, token=True, content_type="application/json"):
        headers = {"Content-Type": content_type}
        if token:
            headers["X-Session-Token"] = self.app.token
        request = Request(
            f"{self.base}/api/setup/{action}", data=json.dumps(payload).encode(), headers=headers
        )
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def get(self, path):
        with urlopen(self.base + path, timeout=5) as response:
            return json.load(response)

    def status_of(self, call):
        with self.assertRaises(HTTPError) as error:
            call()
        return error.exception.code

    def test_writes_need_the_session_token_and_json(self):
        self.assertEqual(self.status_of(lambda: self.post("init_project", {}, token=False)), 403)
        self.assertEqual(
            self.status_of(lambda: self.post("init_project", {}, content_type="text/plain")), 415
        )
        self.assertEqual(self.status_of(lambda: self.post("drop_tables", {})), 400)
        big = {"csv_text": "x" * 20_000}
        self.assertEqual(self.status_of(lambda: self.post("save_secret", big)), 413)

    def test_a_full_setup_round_trip_never_exposes_a_secret(self):
        self.assertEqual(self.status_of(lambda: self.post("save_profile", {"name": "K"})), 409)
        self.post("init_project", {})
        self.post("save_profile", {"name": "Kaifi", "email_to": "me@example.com"})
        self.post("save_secret", {"key": "KITE_API_SECRET", "value": SECRET})
        self.post("save_secret", {"key": "KITE_API_KEY", "value": "kiteapikey01"})
        status = self.get("/api/setup/status")
        self.assertNotIn(SECRET, json.dumps(status))
        self.assertTrue(status["kite"]["api_key"] and status["kite"]["api_secret"])
        done = {step["id"]: step["done"] for step in status["steps"]}
        self.assertTrue(done["project"] and done["profile"] and done["kite_keys"])
        self.assertFalse(done["kite_login"])
        url = self.post("kite_login_url", {})["url"]
        self.assertIn("api_key=kiteapikey01", url)
        settings = self.get("/api/setup/settings")
        changed = self.post(
            "save_settings", {"version": settings["version"], "changes": {"poll_seconds": 120}}
        )
        self.assertEqual(changed["settings"]["poll_seconds"], 120)
        stale = {"version": settings["version"], "changes": {"poll_seconds": 90}}
        self.assertEqual(self.status_of(lambda: self.post("save_settings", stale)), 409)
        audit = (self.root / "data" / "setup-audit.jsonl").read_text()
        self.assertNotIn(SECRET, audit)
        self.assertIn('"keys_changed": ["KITE_API_SECRET"]', audit)
        self.assertTrue(self.get("/api/health")["paper_only"])

    def test_learning_summary_is_readable_before_any_grading(self):
        self.post("init_project", {})
        summary = self.get("/api/setup/learning")
        self.assertEqual(summary["sessions_graded"], 0)
        self.assertFalse(summary["routing"]["enabled"])
        status = {step["id"]: step["done"] for step in self.get("/api/setup/status")["steps"]}
        self.assertTrue(status["model"])  # Rules-only is a valid, finished choice.

    def test_routing_needs_its_provider_keys_before_the_model_step_is_done(self):
        self.post("init_project", {})
        version = self.get("/api/setup/settings")["version"]
        routing = {
            "enabled": True,
            "tiers": [{"name": "free", "provider": "gemini", "model": "flash"}],
            "simple": ["free"],
            "complex": ["free"],
            "escalate": True,
            "cache": True,
            "store_prompts": True,
            "max_escalations_per_day": 10,
        }
        self.post("save_settings", {"version": version, "changes": {"routing": routing}})
        done = lambda: {s["id"]: s["done"] for s in self.get("/api/setup/status")["steps"]}  # noqa: E731
        self.assertFalse(done()["model"])
        self.post("save_secret", {"key": "GEMINI_API_KEY", "value": "gemini-key-123456"})
        self.assertTrue(done()["model"])

    def test_openrouter_alone_finishes_the_model_step_and_the_check_never_leaks_the_key(self):
        import openrouter

        self.post("init_project", {})
        version = self.get("/api/setup/settings")["version"]
        changes = {"model_provider": "openrouter", "openrouter": {"max_usd_per_day": 0}}
        self.post("save_settings", {"version": version, "changes": changes})
        self.assertEqual(self.status_of(lambda: self.post("check_openrouter", {})), 409)
        key = "sk-or-v1-abcdef1234567890"
        self.post("save_secret", {"key": "OPENROUTER_API_KEY", "value": key})
        reported = {"is_free_tier": True, "free_requests_today": {"remaining": 40, "limit": 50}}
        with (
            patch.object(openrouter, "key_status", lambda value: dict(reported)),
            patch.object(openrouter, "catalogue", lambda folder: []),
        ):
            result = self.post("check_openrouter", {})
        self.assertEqual(result["free_requests_today"]["remaining"], 40)
        self.assertNotIn(key, json.dumps(result) + json.dumps(self.get("/api/setup/status")))
        steps = {s["id"]: s["done"] for s in self.get("/api/setup/status")["steps"]}
        self.assertTrue(steps["model"])
        self.assertEqual(self.get("/api/setup/learning")["routing"]["enabled"], True)

    def test_logins_are_rate_limited(self):
        self.post("init_project", {})
        codes = []
        for _ in range(6):
            try:
                self.post("kite_exchange", {"redirect_url": "x"})
            except HTTPError as error:
                codes.append(error.code)
        self.assertEqual(codes[-1], 429)

    def test_uploads_must_look_like_the_nse_list(self):
        for text in ("<script>alert(1)</script>", "SYMBOL,NAME\nA,B", "SYMBOL,ISIN NUMBER\x00"):
            status = self.status_of(
                lambda text=text: self.post("upload_equity_list", {"csv_text": text})
            )
            self.assertEqual(status, 422)

    def test_pages_carry_the_security_headers(self):
        with urlopen(self.base + "/api/health", timeout=5) as response:
            headers = response.headers
        self.assertIn("object-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cross-Origin-Opener-Policy"], "same-origin")

    def test_static_files_cannot_escape_the_web_folder(self):
        for path in ("/../README.md", "/%2e%2e/README.md", "/.hidden", "/notes.md"):
            self.assertIn(self.status_of(lambda path=path: self.get(path)), (403, 404))


if __name__ == "__main__":
    unittest.main()

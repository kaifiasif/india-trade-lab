"""Background jobs started from the UI: fixed commands, one per kind, logs you can follow.

Each kind maps to a fixed argument list: no user text reaches a command line.
A second start of a running kind returns the running job. Output goes to a log
file under ``<data dir>/jobs/`` with every stored secret scrubbed on read, and
each kind has a timeout that ends its whole process group.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

import secret_store

HERE = Path(__file__).resolve().parent
KINDS: dict[str, dict[str, Any]] = {
    "preflight": {"label": "Check setup", "argv": ["preflight.py"], "timeout": 120},
    "evidence": {"label": "Collect news", "argv": ["evidence.py", "collect"], "timeout": 600},
    "report": {"label": "Pre-market report", "argv": ["premarket.py"], "timeout": 900},
    "report_email": {
        "label": "Pre-market report and email",
        "argv": ["premarket.py", "--email"],
        "timeout": 900,
    },
    "tournament": {"label": "Strategy tournament", "argv": ["tournament.py"], "timeout": 900},
    "history": {
        "label": "Load 180 days of history",
        "argv": ["data_sync.py", "--days", "180", "--max-symbols", "10"],
        "timeout": 3600,
    },
    "scan_overnight": {
        "label": "Overnight scan of all F&O stocks",
        "argv": ["market_scan.py", "overnight"],
        "timeout": 900,
    },
    "scan_open": {
        "label": "Open scan (after 09:08)",
        "argv": ["market_scan.py", "open"],
        "timeout": 300,
    },
    "scan_confirm": {
        "label": "09:31 check of the picks",
        "argv": ["market_scan.py", "confirm"],
        "timeout": 300,
    },
    "learn": {
        "label": "Grade the agents and learn",
        "argv": ["learning.py", "settle"],
        "timeout": 600,
    },
    "finetune_export": {
        "label": "Export fine-tuning data",
        "argv": ["learning.py", "finetune-export", "--role", "all"],
        "timeout": 600,
    },
    "desk_tick": {
        "label": "Run the trade desk now (entry, plan, odds, check, alerts)",
        "argv": ["trade_desk.py", "--once"],
        "timeout": 300,
    },
    "insiders": {
        "label": "Insider-trading filings, last 7 days",
        "argv": ["insider_tracker.py", "recent", "--days", "7", "--insiders-only"],
        "timeout": 120,
    },
    "alerts_check": {
        "label": "Check price alerts",
        "argv": ["price_alerts.py", "check"],
        "timeout": 120,
    },
    "reference": {
        "label": "Refresh NSE reference data",
        "argv": ["reference.py", "refresh"],
        "timeout": 600,
    },
}
SUBCOMMAND_SCRIPTS = ("learning.py", "market_scan.py", "insider_tracker.py", "price_alerts.py")
STATES = ("running", "succeeded", "failed", "timed_out", "interrupted")


class JobRunner:
    def __init__(self, data_dir: Path, config: Path, python: str = sys.executable) -> None:
        self.folder = data_dir / "jobs"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.python = python
        self.lock = threading.Lock()
        self.running: dict[str, str] = {}
        for record in self.folder.glob("*.json"):
            job = self._load(record.stem)
            if job and job["state"] == "running":
                job.update(state="interrupted", finished_at=self._now())
                self._save(job)

    @staticmethod
    def _now() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat()

    def _load(self, job_id: str) -> dict | None:
        try:
            return json.loads((self.folder / f"{job_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save(self, job: dict) -> None:
        path = self.folder / f"{job['id']}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(job), encoding="utf-8")
        os.replace(temporary, path)

    def argv(self, kind: str) -> list[str]:
        spec = KINDS[kind]
        script, *rest = spec["argv"]
        if script == "reference.py":
            return [self.python, str(HERE / script), "--db",
                    str(self.config.parent / "reference.sqlite"), *rest]  # fmt: skip
        if script in SUBCOMMAND_SCRIPTS:  # Subcommands follow --config.
            return [self.python, str(HERE / script), "--config", str(self.config), *rest]
        return [self.python, str(HERE / script), *rest, "--config", str(self.config)]

    def start(self, kind: str, command: list[str] | None = None) -> dict:
        if kind not in KINDS:
            raise KeyError(kind)
        with self.lock:
            current = self.running.get(kind)
            if current:
                job = self._load(current)
                if job and job["state"] == "running":
                    return {**job, "reused": True}
            job_id = f"{kind}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
            log = self.folder / f"{job_id}.log"
            job = {
                "id": job_id,
                "kind": kind,
                "label": KINDS[kind]["label"],
                "state": "running",
                "started_at": self._now(),
                "finished_at": None,
                "exit_code": None,
            }
            handle = open(log, "wb")
            try:
                process = subprocess.Popen(
                    command or self.argv(kind),
                    cwd=str(self.config.parent),
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    env=secret_store.environment(),
                    start_new_session=True,
                )
            except OSError:
                handle.close()
                raise
            self.running[kind] = job_id
            self._save(job)
        threading.Thread(target=self._reap, args=(job, process, handle), daemon=True).start()
        return {**job, "reused": False}

    def _reap(self, job: dict, process: subprocess.Popen, handle) -> None:
        timeout = KINDS[job["kind"]]["timeout"]
        try:
            code = process.wait(timeout=timeout)
            state = "succeeded" if code == 0 else "failed"
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            code, state = process.wait(), "timed_out"
        finally:
            handle.close()
        with self.lock:
            job.update(state=state, exit_code=code, finished_at=self._now())
            self._save(job)
            if self.running.get(job["kind"]) == job["id"]:
                del self.running[job["kind"]]

    def get(self, job_id: str, offset: int = 0) -> dict:
        if not job_id.replace("-", "").replace("_", "").isalnum():
            raise KeyError(job_id)
        job = self._load(job_id)
        if job is None:
            raise KeyError(job_id)
        log = self.folder / f"{job_id}.log"
        text, end = "", offset
        if log.is_file():
            with log.open("rb") as handle:
                handle.seek(max(0, offset))
                chunk = handle.read(64_000)
            end = max(0, offset) + len(chunk)
            text = secret_store.scrub(chunk.decode("utf-8", "replace"))
        return {**job, "offset": end, "text": text}

    def recent(self, limit: int = 12) -> list[dict]:
        jobs = [self._load(path.stem) for path in self.folder.glob("*.json")]
        jobs = [job for job in jobs if job]
        return sorted(jobs, key=lambda job: job["started_at"], reverse=True)[:limit]

"""Edit pipeline.json from the UI: allowlisted keys, validated, versioned, backed up.

A save names the version it was based on (the SHA-256 of the file's bytes); a
stale version is refused rather than overwriting a change made elsewhere. The
merged candidate must pass the coordinator's own validation before it replaces
the file atomically, and the previous file is kept as a dated backup (last ten).
``mode`` stays ``paper_research``: no setting here can enable real orders.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

EDITABLE = {
    # Research model
    "model_provider", "model", "quick_model", "deep_model", "model_routes",
    "max_model_calls_per_day", "model_timeout_seconds", "max_output_tokens",
    "reasoning_effort", "local_base_url", "local_timeout_seconds",
    # Desk behaviour
    "max_candidates", "poll_seconds", "screening_mode", "review_workflow",
    "min_turnover_inr", "daily_profit_goal_inr", "target_r",
    "fee_bps", "fee_flat_inr", "slippage_bps",
    "debate", "memory", "selection", "autopilot", "strategy", "market_feeds",
    "learning", "routing", "scan",
    "min_scored_headlines",
    # Email
    "smtp_host", "smtp_port", "smtp_user", "email_from", "email_to",
}  # fmt: skip
FORBIDDEN_WORDS = ("live", "order", "broker")
_LOCK = threading.Lock()


def version_of(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(config: Path) -> tuple[dict, str]:
    raw = config.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("pipeline.json must be a JSON object")
    return data, version_of(raw)


def editable_view(config: Path) -> dict[str, Any]:
    from decision_pipeline import OPTIONAL_CONFIG

    data, version = read(config)
    merged = {**OPTIONAL_CONFIG, **data}
    return {
        "version": version,
        "settings": {key: merged.get(key) for key in sorted(EDITABLE) if key in merged},
        "mode": data.get("mode"),
    }


def validate(candidate: dict, config: Path) -> None:
    """Run the coordinator's checks on a copy, in a scratch folder, with no model."""
    from agent_runtime import OfflineReviewer
    from decision_pipeline import DailyCoordinator

    with tempfile.TemporaryDirectory() as scratch:
        probe = Path(scratch) / "pipeline.json"
        probe.write_text(json.dumps(candidate), encoding="utf-8")
        DailyCoordinator(probe, reviewer=OfflineReviewer())


def save(config: Path, changes: dict, expected_version: str) -> dict[str, Any]:
    if not isinstance(changes, dict) or not changes:
        raise ValueError("No changes supplied")
    unknown = sorted(set(changes) - EDITABLE)
    if unknown:
        raise KeyError(", ".join(unknown))
    with _LOCK:
        data, version = read(config)
        if version != expected_version:
            raise PermissionError("The settings changed elsewhere; reload and try again")
        candidate = copy.deepcopy(data)
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(candidate.get(key), dict):
                candidate[key] = {**candidate[key], **value}
            else:
                candidate[key] = value
        candidate["mode"] = "paper_research"
        validate(candidate, config)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(config, config.with_name(f"pipeline.json.bak-{stamp}"))
        backups = sorted(config.parent.glob("pipeline.json.bak-*"))
        for old in backups[:-10]:
            old.unlink(missing_ok=True)
        body = (json.dumps(candidate, indent=2) + "\n").encode()
        descriptor, temporary = tempfile.mkstemp(dir=config.parent, prefix=".pipeline-")
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, config)
    return editable_view(config)

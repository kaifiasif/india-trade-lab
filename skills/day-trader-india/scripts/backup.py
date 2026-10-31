#!/usr/bin/env python3
"""Backups: the journals, learning and settings, kept safe even if the server is lost.

Each run writes ``backups/backup-<time>.tar.gz`` with:

- both paper journals (``paper.sqlite``, ``swing.sqlite``), copied through SQLite's own
  backup so a running worker never yields a half-written file;
- ``learning.sqlite`` and ``service.sqlite``, ``pipeline.json``, ``sessions.json``,
  ``profile.json``, ``attestations.json``, the swing state and scorecards, and ``desk/``.

Secrets are never included: they live in the owner-only store outside the data folder.
Large rebuildable stores (history, the scan store, the price archive) are left out.

With ``BACKUP_PASSPHRASE`` saved in Setup, the archive is encrypted with
``openssl enc -aes-256-cbc -pbkdf2`` (``.tar.gz.enc``); without it the archive is plain
and the result says so. The newest ``backup.keep`` (14) are kept.
``backup.copy_to`` copies each one off the machine: an absolute folder (a mounted volume),
or ``remote:path`` for rclone when it is installed. Oracle Object Storage works through
rclone.

``restore-test`` opens the newest archive in a temporary folder, verifies each journal's
checksum and reports what it found. Run it monthly; the watchdog warns when no backup
has been made in 36 hours.

    python3 backup.py run
    python3 backup.py restore-test
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
DATABASES = ("paper.sqlite", "swing.sqlite", "learning.sqlite", "service.sqlite")
FILES = (
    "pipeline.json", "sessions.json", "profile.json", "attestations.json", "swing-state.json",
    "strategy-scorecard.json", "swing-scorecard.json", "trials.json", "universe.json",
)  # fmt: skip


def _settings(config_path: Path) -> dict:
    return {"keep": 14, "copy_to": "", **(intraday.load_config(config_path).get("backup") or {})}


def run(config_path: Path, clock: dt.datetime) -> dict[str, Any]:
    import secret_store

    folder = intraday.config_folder(config_path)
    cfg = _settings(config_path)
    target = folder / "backups"
    target.mkdir(exist_ok=True)
    os.chmod(target, 0o700)
    name = f"backup-{clock:%Y%m%d-%H%M%S}.tar.gz"
    included = []
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary) / "data"
        stage.mkdir()
        for database in DATABASES:
            source = folder / database
            if source.is_file():
                with sqlite3.connect(source) as src, sqlite3.connect(stage / database) as dst:
                    src.backup(dst)  # Consistent even while the worker writes.
                included.append(database)
        for file in FILES:
            if (folder / file).is_file():
                shutil.copy2(folder / file, stage / file)
                included.append(file)
        if (folder / "desk").is_dir():
            shutil.copytree(folder / "desk", stage / "desk")
            included.append("desk/")
        archive = Path(temporary) / name
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(stage, arcname="data")
        passphrase = secret_store.get("BACKUP_PASSPHRASE")
        encrypted = False
        if passphrase and shutil.which("openssl"):
            sealed = archive.with_name(name + ".enc")
            subprocess.run(
                ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in", str(archive),
                 "-out", str(sealed), "-pass", "env:ITL_BACKUP_PASS"],
                check=True, env={**os.environ, "ITL_BACKUP_PASS": passphrase}, capture_output=True,
            )  # fmt: skip
            archive, encrypted = sealed, True
        final = target / archive.name
        shutil.move(str(archive), final)
    os.chmod(final, 0o600)
    copied = _copy_off(final, cfg["copy_to"])
    removed = []
    for old in sorted(target.glob("backup-*"))[: -int(cfg["keep"])]:
        old.unlink()
        removed.append(old.name)
    return {
        "file": final.name,
        "bytes": final.stat().st_size,
        "encrypted": encrypted,
        "note": None
        if encrypted
        else "not encrypted: save BACKUP_PASSPHRASE in Setup (needs openssl)",
        "included": included,
        "copied_to": copied,
        "removed": removed,
    }


def _copy_off(path: Path, destination: str) -> str | None:
    if not destination:
        return None
    if destination.startswith("/"):
        folder = Path(destination)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, folder / path.name)
        return str(folder)
    if shutil.which("rclone"):
        subprocess.run(
            ["rclone", "copy", str(path), destination], check=True, capture_output=True, timeout=600
        )
        return destination
    return "not copied: rclone is not installed"


def restore_test(config_path: Path) -> dict[str, Any]:
    """Open the newest backup and verify every journal it holds. Changes nothing."""
    import guardrails

    import secret_store

    target = intraday.config_folder(config_path) / "backups"
    archives = sorted(target.glob("backup-*"))
    if not archives:
        raise ValueError("No backups yet; run: backup.py run")
    newest = archives[-1]
    report: dict[str, Any] = {"file": newest.name, "journals": {}}
    with tempfile.TemporaryDirectory() as temporary:
        archive = newest
        if newest.name.endswith(".enc"):
            passphrase = secret_store.get("BACKUP_PASSPHRASE")
            if not passphrase:
                raise ValueError("This backup is encrypted and no BACKUP_PASSPHRASE is saved")
            archive = Path(temporary) / "plain.tar.gz"
            subprocess.run(
                ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-in", str(newest), "-out", str(archive),
                 "-pass", "env:ITL_BACKUP_PASS"],
                check=True, env={**os.environ, "ITL_BACKUP_PASS": passphrase}, capture_output=True,
            )  # fmt: skip
        with tarfile.open(archive, "r:gz") as tar:
            safe = [
                m
                for m in tar.getmembers()
                if m.name.startswith("data")
                and ".." not in m.name
                and not m.issym()
                and not m.islnk()
            ]
            tar.extractall(temporary, members=safe)  # noqa: S202 - members filtered above.
        data = Path(temporary) / "data"
        for journal in ("paper.sqlite", "swing.sqlite"):
            path = data / journal
            if not path.is_file():
                continue
            with sqlite3.connect(path) as conn:
                state = json.loads(conn.execute("SELECT data FROM book WHERE id=1").fetchone()[0])
            try:
                guardrails.verify_state(state)
                report["journals"][journal] = {"checksum": "ok", "open": len(state["positions"]),
                                               "events": len(state["events"]), "cash": state["cash"]}  # fmt: skip
            except ValueError:
                report["journals"][journal] = {"checksum": "MISMATCH"}
        report["files"] = sorted(path.name for path in data.iterdir())
    report["ok"] = all(item.get("checksum") == "ok" for item in report["journals"].values())
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("restore-test")
    args = parser.parse_args(argv)
    try:
        result = (
            run(args.config, intraday.now_ist())
            if args.command == "run"
            else restore_test(args.config)
        )
    except (
        ValueError,
        OSError,
        sqlite3.Error,
        subprocess.SubprocessError,
        tarfile.TarError,
    ) as exc:
        print(f"Backup refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())

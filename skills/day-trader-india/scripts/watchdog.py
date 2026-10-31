#!/usr/bin/env python3
"""Watchdog: notices when something the desk needs did not happen, and tells you.

Runs every two minutes (a systemd timer on the server). Each check names a problem
in plain words; each problem is sent once a day, by Telegram when a bot is set up,
otherwise by email.

| Check | When |
| --- | --- |
| Today's Kite login is missing | trading days from 08:30 |
| The 08:40 market scan has not written today's file | trading days from 08:55 |
| The pre-market report has not been written | trading days from 09:20 |
| The session worker has not ticked in 3 minutes | trading days 09:20-15:25 |
| NSE surveillance lists have not been read today | trading days from 09:00 |
| A journal failed its checksum at the last recovery | any time |
| The disk is over 80% full | any time |
| No backup in the last 36 hours | any time (when backups are set up) |

**Telegram** (free): create a bot with @BotFather, save its token in Setup
(``TELEGRAM_BOT_TOKEN``, kept server side), and put your chat ID in
``notify.telegram_chat_id``. The bot answers only that chat:

- ``/status``: the desk's state and the last problems;
- ``/pause``: no new paper entries (creates ``HALT_ENTRIES``; exits continue);
- ``/resume``: allow entries again.

There is deliberately no "approve this trade" command. Paper only.

    python3 watchdog.py check          # run the checks and send what is new
    python3 watchdog.py telegram-test
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import intraday

DEFAULT_CONFIG = Path("data/observatory/pipeline.json")
TELEGRAM = "https://api.telegram.org"
MAX_DISK_PCT = 80.0


def _at(clock: dt.datetime, hhmm: str) -> dt.datetime:
    hours, minutes = map(int, hhmm.split(":"))
    return clock.replace(hour=hours, minute=minutes, second=0, microsecond=0)


def _mtime(path: Path) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, intraday.IST)
    except OSError:
        return None


def token_today(clock: dt.datetime) -> bool:
    import secret_store

    path = secret_store.config_dir() / secret_store.TOKENS_FILE
    saved = _mtime(path)
    if not secret_store.get("KITE_ACCESS_TOKEN") or saved is None:
        return False
    cutoff = _at(clock, "06:00")
    return saved >= (cutoff if clock >= cutoff else cutoff - dt.timedelta(days=1))


def problems(
    config_path: Path, clock: dt.datetime, login: Callable[[dt.datetime], bool] = token_today
) -> list[dict]:
    """Every problem right now, each with a stable id for once-a-day sending."""
    config = intraday.load_config(config_path)
    folder = intraday.config_folder(config_path)
    times = intraday.session_times(intraday.sessions_manifest(config_path), clock.date())
    found: list[dict] = []

    def add(key: str, text: str) -> None:
        found.append({"id": f"{key}:{clock.date()}", "text": text})

    if times is not None:
        if clock >= _at(clock, "08:30") and clock < times["close"] and not login(clock):
            add(
                "login",
                "Today's Kite login is missing. Log in from Setup → Today's Kite login, or the desk sees no prices.",
            )
        scan_on = (config.get("scan") or {}).get("enabled", False)
        if (
            scan_on
            and clock >= _at(clock, "08:55")
            and not (folder / f"scan-{clock.date()}.json").is_file()
        ):
            add(
                "scan",
                "The 08:40 market scan has not written today's file. Check the server log (run.sh premarket).",
            )
        reports = folder / config.get("reports_dir", "reports")
        if (
            scan_on
            and clock >= _at(clock, "09:20")
            and not (reports / f"premarket-{clock.date()}.json").is_file()
        ):
            add("report", "The pre-market report was not written; there are no picks today.")
        if _at(clock, "09:20") <= clock <= _at(clock, "15:25"):
            ticked = _mtime(folder / "service.sqlite")
            if ticked is None or (clock - ticked).total_seconds() > 180:
                add(
                    "worker",
                    "The session worker has not ticked for 3 minutes. Open positions are not being watched.",
                )
        if clock >= _at(clock, "09:00"):
            checked = _mtime(folder / "surveillance.json")
            if checked is None or checked.date() != clock.date():
                add(
                    "surveillance",
                    "NSE surveillance lists were not read today; new entries are blocked until they are.",
                )
    try:
        recovery = json.loads((folder / "recovery.json").read_text(encoding="utf-8"))
        for kind, book in recovery.get("books", {}).items():
            if book.get("status") == "CHECKSUM_MISMATCH":
                add(
                    f"journal-{kind}",
                    f"The {kind} journal failed its checksum. Preserve it and investigate; nothing was changed.",
                )
    except (OSError, ValueError):
        pass
    usage = shutil.disk_usage(folder)
    used = 100 * usage.used / usage.total if usage.total else 0
    if used > MAX_DISK_PCT:
        add("disk", f"The disk is {used:.0f}% full. Old logs or backups may need clearing.")
    backup_dir = folder / "backups"
    if backup_dir.is_dir():
        latest = max((_mtime(path) for path in backup_dir.glob("backup-*")), default=None)
        if latest is None or (clock - latest).total_seconds() > 36 * 3600:
            add("backup", "No backup in the last 36 hours.")
    return found


# ---------- sending ----------


def _telegram(method: str, token: str, payload: dict, opener: Any = None) -> dict:
    """One Telegram Bot API call. Fixed host, no redirects, short timeout; the token is never logged."""
    import market_scan

    request = urllib.request.Request(
        f"{TELEGRAM}/bot{token}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = opener or urllib.request.build_opener(market_scan.NoRedirect)
    try:
        with opener.open(request, timeout=15) as response:
            body = json.loads(response.read(1_000_000))
    except (urllib.error.URLError, OSError, ValueError):
        raise ValueError("Telegram did not answer") from None
    if not body.get("ok"):
        raise ValueError("Telegram refused the request")
    return body


def send(config_path: Path, text: str, opener: Any = None) -> str:
    """Send by Telegram when set up, else by email. Returns the channel used, or why not."""
    import secret_store

    config = intraday.load_config(config_path)
    chat = str((config.get("notify") or {}).get("telegram_chat_id") or "")
    token = secret_store.get("TELEGRAM_BOT_TOKEN")
    if token and chat:
        try:
            _telegram("sendMessage", token, {"chat_id": chat, "text": text[:3500]}, opener)
            return "telegram"
        except ValueError as exc:
            note = str(exc)
    else:
        note = "Telegram is not set up"
    import premarket

    message = EmailMessage()
    message["Subject"] = "India Trade Lab: " + text.split(".")[0][:120]
    message.set_content(text + "\n\nPaper trading only.")
    sent = premarket.smtp_send(message, config)
    return "email" if sent.get("sent") else f"not sent ({note}; {sent.get('reason')})"


def check(config_path: Path, clock: dt.datetime, opener: Any = None, login=token_today) -> dict:
    """Run the checks, send each new problem once, and answer Telegram commands."""
    folder = intraday.config_folder(config_path)
    state_path = folder / "watchdog-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {"sent": {}, "offset": 0}
    found = problems(config_path, clock, login)
    fresh = [item for item in found if item["id"] not in state["sent"]]
    for item in fresh:
        state["sent"][item["id"]] = {
            "at": clock.isoformat(),
            "via": send(config_path, item["text"], opener),
        }
    # Keep a week of sent ids.
    week = str(clock.date() - dt.timedelta(days=7))
    state["sent"] = {key: value for key, value in state["sent"].items() if value["at"][:10] >= week}
    state["last_check"] = clock.isoformat()
    state["open_problems"] = [item["text"] for item in found]
    answered = commands(config_path, state, clock, opener)
    intraday.write_json(state_path, state)
    return {"problems": len(found), "sent": len(fresh), "commands": answered}


def commands(config_path: Path, state: dict, clock: dt.datetime, opener: Any = None) -> list[str]:
    """Answer /status, /pause and /resume from the configured chat only."""
    import secret_store

    config = intraday.load_config(config_path)
    chat = str((config.get("notify") or {}).get("telegram_chat_id") or "")
    token = secret_store.get("TELEGRAM_BOT_TOKEN")
    if not (token and chat):
        return []
    try:
        updates = _telegram(
            "getUpdates", token, {"offset": state.get("offset", 0), "timeout": 0}, opener
        )
    except ValueError:
        return []
    folder = intraday.config_folder(config_path)
    answered = []
    for update in updates.get("result", [])[:20]:
        state["offset"] = max(state.get("offset", 0), int(update.get("update_id", 0)) + 1)
        message = update.get("message") or {}
        if str((message.get("chat") or {}).get("id")) != chat:
            continue  # Strangers get no answer at all.
        word = str(message.get("text") or "").strip().split(" ")[0].lower()
        if word == "/pause":
            (folder / "HALT_ENTRIES").write_text(f"paused from Telegram at {clock.isoformat()}\n")
            reply = "Paused: no new paper entries. Exits continue. Send /resume to allow entries."
        elif word == "/resume":
            (folder / "HALT_ENTRIES").unlink(missing_ok=True)
            reply = "Resumed: new paper entries are allowed again (every other rule still applies)."
        elif word == "/status":
            halted = (folder / "HALT_ENTRIES").exists()
            issues = state.get("open_problems") or []
            reply = f"{clock:%d %b %H:%M} IST. Entries {'PAUSED' if halted else 'allowed'}. " + (
                "Problems: " + " | ".join(issues) if issues else "No problems found."
            )
        else:
            reply = "Commands: /status, /pause, /resume. Paper trading only."
        try:
            _telegram("sendMessage", token, {"chat_id": chat, "text": reply}, opener)
        except ValueError:
            pass
        answered.append(word)
    return answered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" IST')
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("telegram-test")
    args = parser.parse_args(argv)
    clock = intraday.now_ist(args.now)
    try:
        if args.command == "telegram-test":
            print(send(args.config, "Test from India Trade Lab: alerts reach you here."))
            return 0
        print(json.dumps(check(args.config, clock), indent=2))
    except (ValueError, OSError, KeyError) as exc:
        print(f"Watchdog refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

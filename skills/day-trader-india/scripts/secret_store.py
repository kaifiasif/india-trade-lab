"""Owner-only secrets store: written from the UI, never read back by it.

Keys live in ``~/.config/india-trade-lab/secrets.env`` and the daily Kite token in
``tokens.env`` beside it (folder 0700, files 0600, override the folder with
``ITL_CONFIG_DIR``). Both are shell-safe ``export KEY='value'`` lines, so the
scheduled jobs can ``source`` them; nothing secret is ever written to
pipeline.json, the repository, a log or an API response. The API only ever learns
whether a key is set and its last four characters.
"""

from __future__ import annotations

import fcntl
import os
import re
import tempfile
from pathlib import Path

SECRET_KEYS = {
    "KITE_API_KEY": "Kite Connect API key",
    "KITE_API_SECRET": "Kite Connect API secret",
    "SMTP_PASSWORD": "Email app password (SMTP)",
    "OPENROUTER_API_KEY": "OpenRouter API key",
    "GEMINI_API_KEY": "Gemini API key",
    "ANTHROPIC_API_KEY": "Anthropic API key",
    "OPENAI_API_KEY": "OpenAI API key",
    "LOCAL_LLM_API_KEY": "Local model server key",
    "TELEGRAM_BOT_TOKEN": "Telegram bot token (alerts and /pause)",
    "BACKUP_PASSPHRASE": "Passphrase that encrypts backups",
}
TOKEN_KEYS = {"KITE_ACCESS_TOKEN": "Today's Kite access token"}
SECRETS_FILE = "secrets.env"
TOKENS_FILE = "tokens.env"
LINE = re.compile(r"^export ([A-Z][A-Z0-9_]*)='([^'\n\r\x00]*)'$")
VALUE = re.compile(r"[^'\n\r\x00]{1,4096}")


def config_dir() -> Path:
    return Path(os.environ.get("ITL_CONFIG_DIR") or Path.home() / ".config" / "india-trade-lab")


def _path(key: str) -> Path:
    if key in SECRET_KEYS:
        return config_dir() / SECRETS_FILE
    if key in TOKEN_KEYS:
        return config_dir() / TOKENS_FILE
    raise ValueError("Unknown secret name")


def _read(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return values
    for line in text.splitlines():
        match = LINE.match(line.strip())
        if match:
            values[match.group(1)] = match.group(2)
    return values


def _write(path: Path, values: dict[str, str]) -> None:
    """Atomic replace, private from creation, under an exclusive lock."""
    folder = path.parent
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    body = "# Private. Written by India Trade Lab. Never commit or share.\n" + "".join(
        f"export {key}='{value}'\n" for key, value in sorted(values.items())
    )
    descriptor, temporary = tempfile.mkstemp(dir=folder, prefix=".tmp-", text=True)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)


def set_secret(key: str, value: str) -> dict:
    """Store one value (empty string removes it). Returns only set/last4."""
    path = _path(key)
    value = value.strip()
    if value and not VALUE.fullmatch(value):
        raise ValueError("Value contains characters that cannot be stored safely")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with open(path.parent / ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        values = _read(path)
        if value:
            values[key] = value
        else:
            values.pop(key, None)
        _write(path, values)
    return describe(key)


def get(key: str) -> str:
    """For server-side use only (subprocess env, token exchange). Never return to a client."""
    return _read(_path(key)).get(key, "")


def describe(key: str) -> dict:
    value = get(key)
    return {"key": key, "set": bool(value), "last4": value[-4:] if len(value) >= 8 else None}


def status() -> dict[str, dict]:
    labels = {**SECRET_KEYS, **TOKEN_KEYS}
    return {key: {**describe(key), "label": label} for key, label in labels.items()}


def environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """A process environment with every stored value added, for job subprocesses."""
    env = dict(os.environ if base is None else base)
    for name in (SECRETS_FILE, TOKENS_FILE):
        env.update(_read(config_dir() / name))
    return env


def values_to_scrub() -> list[str]:
    stored = {**_read(config_dir() / SECRETS_FILE), **_read(config_dir() / TOKENS_FILE)}
    return [value for value in stored.values() if len(value) >= 6]


EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def mask_email(text: str) -> str:
    """me.name@gmail.com -> m***@gmail.com, so logs show which mailbox without the address."""
    return EMAIL.sub(r"\1***@\2", text)


def scrub(text: str) -> str:
    for value in values_to_scrub():
        text = text.replace(value, "[redacted]")
    return mask_email(text)

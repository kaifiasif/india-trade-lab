#!/usr/bin/env python3
"""Daily Kite Connect token exchange. You log in to Zerodha yourself, with 2FA.

This is not an automated login: it prints Zerodha's login URL, you complete the
login in your browser, and you paste back the redirect URL. The one-time
request_token is then exchanged for the day's access token through Kite's
official session endpoint. The token is written to a private env file
(created with mode 600) and is never printed or logged. No orders are placed.

    export KITE_API_KEY=...  KITE_API_SECRET=...   # keep out of Git and chat
    python3 scripts/kite_login.py
    source ~/.india-trade-lab.env
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path

from broker_data import NoRedirect

SESSION_URL = "https://api.kite.trade/session/token"
DEFAULT_ENV_FILE = Path.home() / ".india-trade-lab.env"


def login_url(api_key: str) -> str:
    return "https://kite.zerodha.com/connect/login?v=3&api_key=" + urllib.parse.quote(api_key)


def request_token_from(pasted: str) -> str:
    """Accept the full redirect URL or the bare token; reject anything else."""
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(pasted.strip()).query)
    token = (query.get("request_token") or [pasted.strip()])[0]
    if not token.isalnum() or not 8 <= len(token) <= 128:
        raise ValueError("That does not look like a Kite request_token")
    return token


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    """Kite's documented checksum: SHA-256 of api_key + request_token + api_secret."""
    return hashlib.sha256((api_key + request_token + api_secret).encode()).hexdigest()


def exchange(api_key: str, request_token: str, api_secret: str, opener=None) -> str:
    body = urllib.parse.urlencode(
        {
            "api_key": api_key,
            "request_token": request_token,
            "checksum": checksum(api_key, request_token, api_secret),
        }
    ).encode()
    request = urllib.request.Request(
        SESSION_URL, data=body, headers={"X-Kite-Version": "3"}, method="POST"
    )
    opener = opener or urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Oversized session response")
        token = json.loads(raw)["data"]["access_token"]
        if not isinstance(token, str) or not token.isalnum():
            raise ValueError("Unexpected access token shape")
        return token
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        # Never echo the provider response: it can contain account details.
        raise ValueError(
            "Token exchange failed. Request tokens expire within minutes; log in again."
        ) from None


def save_env(path: Path, api_key: str, access_token: str) -> None:
    """Write the env file private from creation; never world-readable, even briefly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"export KITE_API_KEY={api_key}\nexport KITE_ACCESS_TOKEN={access_token}\n")
    os.chmod(path, 0o600)


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    ask: Callable[[str], str] = input,
    opener=None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    api_key, api_secret = env.get("KITE_API_KEY", ""), env.get("KITE_API_SECRET", "")
    if not api_key or not api_secret:
        print("Set KITE_API_KEY and KITE_API_SECRET in this terminal first.")
        return 2
    print("1. Open this URL, log in to Zerodha and complete 2FA:")
    print("   " + login_url(api_key))
    print("2. Paste the full URL you were sent back to (it contains request_token):")
    try:
        token = exchange(api_key, request_token_from(ask("> ")), api_secret, opener)
        save_env(args.env_file, api_key, token)
    except (ValueError, OSError) as exc:
        print("REFUSED: " + str(exc))
        return 2
    print(f"Saved today's token to {args.env_file}. Load it with:  source {args.env_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

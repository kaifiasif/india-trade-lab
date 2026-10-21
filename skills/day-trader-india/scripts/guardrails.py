"""Fail-closed entry gates for manual forward paper trading; no broker/network code."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from decimal import Decimal, InvalidOperation
from typing import Any

POLICY_ID = "india-paper-v1"
REQUIRED_CHECKS = (
    "cash_equity",
    "instrument_verified",
    "surveillance_clear",
    "price_band_ok",
    "no_material_event",
    "liquidity_ok",
    "sector_exposure_ok",
    "data_authorized",
    "strategy_rule_met",
    "stop_target_reviewed",
)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def state_digest(book: dict[str, Any]) -> str:
    """Checksum the snapshot for accidental corruption detection, not authentication."""
    payload = {key: value for key, value in book.items() if key != "state_sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def seal_state(book: dict[str, Any]) -> dict[str, Any]:
    """Checksum a completed version-3 transition before persistence."""
    if book.get("version") == 3:
        book["state_sha256"] = state_digest(book)
    return book


def verify_state(book: dict[str, Any]) -> None:
    """Reject an altered version-3 snapshot; preserve the original file for review."""
    if book.get("version") == 3 and book.get("state_sha256") != state_digest(book):
        raise ValueError("Journal checksum mismatch; preserve the book and investigate")


def amount(value: object) -> Decimal:
    """Accept only finite, positive decimal evidence values."""
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid numeric guardrail input") from None
    if not result.is_finite() or result <= 0:
        raise ValueError("Guardrail amounts must be finite and positive")
    return result


def evidence_time(value: object) -> dt.datetime:
    """Require a timezone on evidence timestamps."""
    if not isinstance(value, str):
        raise ValueError("Evidence timestamp must be a string")
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Evidence timestamps must include a timezone")
    return result.astimezone(IST)


def enforce_forward_policy(book: dict[str, Any]) -> None:
    """Apply software ceilings to forward practice, including edited policy values."""
    initial = amount(book["initial_cash"])
    limits, controls = book["limits"], book["controls"]
    for name, ceiling in (("risk", ".005"), ("daily_loss", ".015"), ("position_limit", ".25")):
        if amount(limits[name]) > initial * Decimal(ceiling):
            raise ValueError(f"Forward-practice {name} exceeds the policy ceiling")
    for name, ceiling in (
        ("max_trades_per_day", 5),
        ("max_open_positions", 3),
        ("max_loss_streak", 3),
    ):
        value = controls[name]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= ceiling:
            raise ValueError(f"Forward-practice {name} exceeds the policy ceiling")
    if amount(controls["drawdown_stop_inr"]) > initial * Decimal(".05"):
        raise ValueError("Forward-practice drawdown stop exceeds 5% of initial virtual cash")


def check_entry(
    book: dict[str, Any],
    evidence: object,
    symbol: str,
    quote_time: dt.datetime,
    clock: dt.datetime,
    quote: Decimal,
    quote_source: str,
) -> dict[str, Any] | None:
    """Check halt, forward policy and dated user attestations; do not verify their truth."""
    if os.environ.get("INDIA_TRADE_LAB_HALT", "0") != "0":
        raise ValueError("Global entry halt is active; exits remain available")
    if book["mode"] == "replay_demo":
        return None
    if book.get("version") != 3 or book.get("policy_id") != POLICY_ID:
        raise ValueError("Forward entries require a version-3 book; preserve older results")
    enforce_forward_policy(book)
    if (
        not isinstance(evidence, dict)
        or type(evidence.get("version")) is not int
        or evidence.get("version") != 1
    ):
        raise ValueError("Forward entry requires version-1 pre-trade evidence")
    if evidence.get("symbol") != symbol or evidence.get("quote_source") != quote_source:
        raise ValueError("Evidence symbol/source does not match the proposed entry")
    observed = evidence_time(evidence["quote_as_of"])
    checked = evidence_time(evidence["checked_at"])
    if observed != quote_time or not -5 <= (clock - checked).total_seconds() <= 120:
        raise ValueError("Evidence must match the quote and have been checked within 120 seconds")
    checks, sources = evidence.get("checks"), evidence.get("evidence_sources")
    if not isinstance(checks, dict) or not isinstance(sources, dict):
        raise ValueError("Evidence needs explicit checks and a source for each check")
    for name in REQUIRED_CHECKS:
        if (
            checks.get(name) is not True
            or not isinstance(sources.get(name), str)
            or not sources[name].strip()
        ):
            raise ValueError(f"Missing, false or unsourced pre-trade check: {name}")
    session = evidence.get("session")
    if (
        not isinstance(session, dict)
        or not isinstance(session.get("source"), str)
        or not session["source"].strip()
    ):
        raise ValueError("A date-specific exchange session and its source are required")
    if session.get("date") != quote_time.date().isoformat():
        raise ValueError("Exchange session date does not match the quote")
    boundaries = {
        key: evidence_time(f"{session['date']}T{session[key]}:00+05:30")
        for key in ("open", "entry_cutoff", "close")
    }
    if not boundaries["open"] < boundaries["entry_cutoff"] < boundaries["close"]:
        raise ValueError("Invalid exchange-session boundaries")
    if not boundaries["open"] <= quote_time < boundaries["entry_cutoff"]:
        raise ValueError("Entry is outside the declared exchange entry window")
    bid, ask = amount(evidence["bid_inr"]), amount(evidence["ask_inr"])
    if bid > ask or not bid <= quote <= ask:
        raise ValueError("Crossed market or quote outside the supplied bid/ask")
    spread_bps = (ask - bid) / ((ask + bid) / 2) * 10000
    if spread_bps > 20:
        raise ValueError("Spread exceeds the 20 bps forward-practice ceiling")
    # A cooldown is independent of the existing consecutive-loss and drawdown stops.
    for event in reversed(book["events"]):
        if event["side"] == "sell":
            if Decimal(event["net_realized_pnl_inr"]) < 0:
                elapsed = (quote_time - evidence_time(event["as_of"])).total_seconds()
                if elapsed < 900:
                    raise ValueError("Wait at least 15 minutes after a losing close")
            break
    fields = (
        "version",
        "symbol",
        "quote_source",
        "quote_as_of",
        "checked_at",
        "checks",
        "evidence_sources",
        "session",
        "bid_inr",
        "ask_inr",
    )
    return {field: evidence[field] for field in fields}

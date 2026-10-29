#!/usr/bin/env python3
"""Market scan: the desk finds its own stocks, ranked on signals that lead the open.

The agents no longer wait for you to name one to three stocks. Plain code (no
model calls) scans every NSE stock with futures and options, then hands the
best ten to the specialists and the judge. Three stages, one per moment:

``overnight`` (08:40)
    For every F&O stock: trend, RSI and liquidity from daily candles; futures
    open-interest build-up against yesterday (fresh longs, short covering, fresh
    shorts, long unwinding); put/call open-interest ratio and the strikes with
    the most open interest; yesterday's delivery percentage and bulk/block
    deals; and results, board meetings or ex-dates in the next five days.
    Hard filters drop downtrends, RSI of 75 or more, thin stocks and anything
    with an event today or tomorrow. The best 25 make the overnight shortlist.

``open`` (09:09, after the pre-open auction sets the opening price)
    The pre-open gap of each shortlisted stock against the Nifty 50 and its
    sector index: relative strength at the open. Stocks gapping down hard are
    dropped; huge gaps up are marked too late to chase. The best ten go to the
    agents.

``confirm`` (09:31, after the first fifteen minutes)
    For the judge's picks: volume so far against the same fifteen minutes on
    the last 20 sessions, price against VWAP, and strength against the Nifty
    since the open. A pick that fails is not entered (downgrade only).

Positioning data reflects the previous session's close; the pre-open gap and
first-15-minute volume are today's. None of these predict prices: they show
how traders are positioned and whether today's move has participation. All
calls are GET requests with your own Kite login; nothing here places an order.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import gzip
import io
import json
import os
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

from broker_data import NoRedirect

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
INDEX_UNDERLYINGS = frozenset(
    {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}
)
NIFTY_KEY = "NSE:NIFTY 50"
QUOTE_BATCH = 500
QUOTE_GAP_SECONDS = 1.05  # Kite: one quote request per second.
HISTORY_GAP_SECONDS = 0.34  # Kite: three historical requests per second.
OPTION_STRIKES_EACH_SIDE = 8
OI_MOVE_PCT = 2.0  # Smaller open-interest changes are treated as no build-up.
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "shortlist": 25,
    "max_gap_up_pct": 3.0,
    "max_gap_down_pct": 1.5,
    "event_window_days": 5,
    "min_rvol": 1.5,
    "require_confirmation": True,
}
BUILDUP_POINTS = {
    "long build-up": 2.0,
    "short covering": 1.0,
    "neutral": 0.0,
    "long unwinding": -1.0,
    "short build-up": -2.0,
    "unknown": 0.0,
}
NSE_ARCHIVES = "https://nsearchives.nseindia.com"
NSE_EVENTS = "https://www.nseindia.com/api/event-calendar?index=equities"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Accept": "text/csv,application/json,text/plain,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
}
MAX_BYTES = 40_000_000


# ---------- the universe ----------


def read_dump(raw: bytes) -> list[dict[str, str]]:
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def fno_universe(rows: list[dict[str, str]], today: dt.date) -> dict[str, dict[str, Any]]:
    """Every stock with exchange futures, its cash instrument and its nearest options."""
    equities = {
        row["tradingsymbol"]: row
        for row in rows
        if row.get("exchange") == "NSE" and row.get("segment") == "NSE"
        and row.get("instrument_type") == "EQ"
    }  # fmt: skip
    futures: dict[str, list[dict[str, str]]] = {}
    options: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row.get("exchange") != "NFO" or not row.get("expiry"):
            continue
        try:
            expiry = dt.date.fromisoformat(row["expiry"])
        except ValueError:
            continue
        if expiry < today:
            continue
        kind = row.get("instrument_type")
        if kind == "FUT":
            futures.setdefault(row["name"], []).append(row)
        elif kind in ("CE", "PE"):
            options.setdefault(row["name"], []).append(row)
    universe = {}
    for name, contracts in futures.items():
        if name in INDEX_UNDERLYINGS or name not in equities:
            continue
        contracts.sort(key=lambda row: row["expiry"])
        near = contracts[0]["expiry"]
        chain = [row for row in options.get(name, []) if row["expiry"] == near]
        universe[name] = {
            "symbol": f"NSE:{name}",
            "name": equities[name].get("name") or name,
            "eq_token": equities[name]["instrument_token"],
            "futures": [f"NFO:{row['tradingsymbol']}" for row in contracts],
            "near_expiry": near,
            "lot_size": int(float(contracts[0].get("lot_size") or 0)),
            "options": [
                {
                    "key": f"NFO:{row['tradingsymbol']}",
                    "strike": float(row["strike"]),
                    "type": row["instrument_type"],
                }
                for row in chain
            ],
        }
    if not universe:
        raise ValueError("The Kite instrument list had no F&O stocks; check today's login")
    return universe


def index_keys(rows: list[dict[str, str]]) -> dict[str, str]:
    """Index name to Kite quote key, e.g. 'NIFTY IT' -> 'NSE:NIFTY IT'."""
    return {
        row["tradingsymbol"]: f"NSE:{row['tradingsymbol']}"
        for row in rows
        if row.get("segment") == "INDICES" and row.get("exchange") == "NSE"
    }


# ---------- Kite, read-only ----------


class KiteClient:
    """Quotes and candles with your own login, paced to Kite's documented rate limits."""

    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        opener: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        env = os.environ if environ is None else environ
        key, token = env.get("KITE_API_KEY", ""), env.get("KITE_ACCESS_TOKEN", "")
        if not key or not token:
            raise ValueError("Do today's Kite login first (Setup → Today's Kite login)")
        self.headers = {"Authorization": f"token {key}:{token}", "X-Kite-Version": "3"}
        self.opener = opener or urllib.request.build_opener(NoRedirect)
        self.sleep, self.clock = sleep, clock
        self.last: dict[str, float] = {}

    def _pace(self, kind: str, gap: float) -> None:
        wait = self.last.get(kind, -1e9) + gap - self.clock()
        if wait > 0:
            self.sleep(wait)
        self.last[kind] = self.clock()

    def _get(self, url: str, kind: str, gap: float) -> Any:
        for attempt in (1, 2):
            self._pace(kind, gap)
            request = urllib.request.Request(url, headers=self.headers, method="GET")
            try:
                with self.opener.open(request, timeout=30) as response:
                    raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError("Kite response too large")
                return json.loads(raw)
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt == 1:
                    self.sleep(2.0)
                    continue
                raise ValueError(f"Kite refused the {kind} request ({exc.code})") from None
            except (OSError, ValueError):
                raise ValueError(f"Kite {kind} request failed") from None
        raise ValueError(f"Kite {kind} request failed")

    def quote(self, keys: list[str]) -> dict[str, dict]:
        data: dict[str, dict] = {}
        unique = list(dict.fromkeys(keys))
        for start in range(0, len(unique), QUOTE_BATCH):
            batch = unique[start : start + QUOTE_BATCH]
            query = urllib.parse.urlencode([("i", key) for key in batch])
            payload = self._get(f"https://api.kite.trade/quote?{query}", "quote", QUOTE_GAP_SECONDS)
            if payload.get("status") != "success":
                raise ValueError("Kite quote request did not succeed")
            data.update(payload.get("data") or {})
        return data

    def candles(self, token: str, interval: str, start: dt.date, end: dt.date) -> list[list]:
        if not str(token).isdigit() or interval not in ("day", "15minute", "5minute"):
            raise ValueError("Use a numeric instrument token and a supported interval")
        query = urllib.parse.urlencode({"from": f"{start} 00:00:00", "to": f"{end} 23:59:59"})
        url = f"https://api.kite.trade/instruments/historical/{token}/{interval}?{query}"
        payload = self._get(url, "historical", HISTORY_GAP_SECONDS)
        try:
            return list(payload["data"]["candles"])
        except (KeyError, TypeError):
            raise ValueError("Kite returned no candles") from None


def load_dump(folder: Path, today: dt.date, fetch: Callable[[], bytes]) -> list[dict[str, str]]:
    """Kite's instrument list, downloaded once per day and cached beside pipeline.json."""
    path = folder / f"instruments-{today}.csv.gz"
    if not path.is_file():
        raw = fetch()
        if raw[:2] != b"\x1f\x8b":
            raw = gzip.compress(raw)
        path.write_bytes(raw)
        for old in folder.glob("instruments-*.csv.gz"):
            if old != path:
                old.unlink(missing_ok=True)
    return read_dump(path.read_bytes())


# ---------- stores ----------


class ScanStore:
    """Daily candles and positioning snapshots for the whole F&O list."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS daily (symbol TEXT, date TEXT, open REAL, high REAL,
                  low REAL, close REAL, volume REAL, PRIMARY KEY(symbol, date));
                CREATE TABLE IF NOT EXISTS positioning (day TEXT, symbol TEXT, prev_close REAL,
                  fut_oi REAL, pcr REAL, call_wall REAL, put_wall REAL, delivery_pct REAL,
                  deals TEXT, PRIMARY KEY(day, symbol));
                """
            )

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def last_date(self, symbol: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(date) FROM daily WHERE symbol=?", (symbol,)).fetchone()
        return row[0]

    def add_candles(self, symbol: str, candles: list[list], before: dt.date) -> int:
        rows = []
        for candle in candles:
            try:
                day = dt.datetime.fromisoformat(candle[0]).date()
                if day >= before:
                    continue  # Only completed sessions.
                rows.append((symbol, str(day), *(float(value) for value in candle[1:6])))
            except (ValueError, TypeError, IndexError):
                continue
        with self._connect() as conn:
            conn.executemany("INSERT OR REPLACE INTO daily VALUES (?,?,?,?,?,?,?)", rows)
        return len(rows)

    def bars(self, symbol: str, before: dt.date, limit: int = 120) -> list[dict]:
        """Completed daily bars, oldest first, in the shape technical.snapshot reads."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM daily WHERE symbol=? AND date<? ORDER BY date DESC LIMIT ?",
                (symbol, str(before), limit),
            ).fetchall()
        return [
            {
                "date": row["date"],
                "close_at": f"{row['date']}T15:30:00+05:30",
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            for row in reversed(rows)
        ]

    def save_positioning(self, day: str, rows: dict[str, dict]) -> None:
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO positioning VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        day,
                        symbol,
                        item.get("prev_close"),
                        item.get("fut_oi"),
                        item.get("pcr"),
                        item.get("call_wall"),
                        item.get("put_wall"),
                        item.get("delivery_pct"),
                        json.dumps(item.get("deals") or {}),
                    )  # fmt: skip
                    for symbol, item in rows.items()
                ],
            )

    def previous_positioning(self, day: str) -> dict[str, dict]:
        with self._connect() as conn:
            last = conn.execute("SELECT MAX(day) FROM positioning WHERE day<?", (day,)).fetchone()[
                0
            ]
            if not last:
                return {}
            return {
                row["symbol"]: dict(row)
                for row in conn.execute("SELECT * FROM positioning WHERE day=?", (last,))
            }


def refresh_daily(
    store: ScanStore, client: KiteClient, universe: dict[str, dict], today: dt.date,
    days: int = 200,
) -> dict[str, int]:  # fmt: skip
    """Fetch only the daily candles each stock is missing. About a minute for 200 stocks."""
    fetched, failed = 0, 0
    for item in universe.values():
        last = store.last_date(item["symbol"])
        start = (
            dt.date.fromisoformat(last) + dt.timedelta(days=1)
            if last
            else today - dt.timedelta(days=days)
        )
        if start >= today:
            continue
        try:
            fetched += store.add_candles(
                item["symbol"], client.candles(item["eq_token"], "day", start, today), today
            )
        except ValueError:
            failed += 1
    return {"candles": fetched, "failed": failed}


# ---------- NSE public files ----------


def nse_fetch(url: str, timeout: int = 30) -> bytes:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in (
        "nsearchives.nseindia.com",
        "www.nseindia.com",
    ):
        raise ValueError("NSE sources must be https on nseindia.com")
    request = urllib.request.Request(url, headers=BROWSER_HEADERS, method="GET")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
    except (OSError, urllib.error.URLError, ValueError):
        raise ValueError(f"NSE source unavailable: {parts.hostname}") from None
    if len(raw) > MAX_BYTES:
        raise ValueError("NSE response exceeds its size limit")
    return raw


def _csv(raw: bytes) -> list[dict[str, str]]:
    text = raw.decode("utf-8-sig", errors="replace")
    return [
        {(key or "").strip().upper(): (value or "").strip() for key, value in row.items()}
        for row in csv.DictReader(io.StringIO(text))
    ]


def delivery(session: dt.date, fetch: Callable[[str], bytes]) -> dict[str, float]:
    """Delivery % per EQ symbol from NSE's full bhavcopy for one session."""
    url = f"{NSE_ARCHIVES}/products/content/sec_bhavdata_full_{session:%d%m%Y}.csv"
    result = {}
    for row in _csv(fetch(url)):
        if row.get("SERIES") != "EQ":
            continue
        try:
            result[row["SYMBOL"]] = float(row.get("DELIV_PER") or "nan")
        except ValueError:
            continue
    return {key: value for key, value in result.items() if value == value}


def deals(fetch: Callable[[str], bytes]) -> dict[str, dict[str, float]]:
    """Net quantity bought in yesterday's bulk and block deals, per symbol."""
    totals: dict[str, dict[str, float]] = {}
    for kind in ("bulk", "block"):
        try:
            rows = _csv(fetch(f"{NSE_ARCHIVES}/content/equities/{kind}.csv"))
        except ValueError:
            continue
        for row in rows:
            symbol = row.get("SYMBOL")
            side = (row.get("BUY/SELL") or row.get("BUY / SELL") or "").upper()
            try:
                quantity = float((row.get("QUANTITY TRADED") or "0").replace(",", ""))
            except ValueError:
                continue
            if not symbol or side not in ("BUY", "SELL"):
                continue
            entry = totals.setdefault(symbol, {"net_qty": 0.0, "deals": 0})
            entry["net_qty"] += quantity if side == "BUY" else -quantity
            entry["deals"] += 1
    return totals


def upcoming_events(
    today: dt.date, window: int, fetch: Callable[[str], bytes]
) -> dict[str, list[dict[str, str]]]:
    """Results, board meetings and similar on or within ``window`` days after today."""
    payload = json.loads(fetch(NSE_EVENTS))
    if not isinstance(payload, list):
        raise ValueError("NSE event calendar returned an unexpected shape")
    events: dict[str, list[dict[str, str]]] = {}
    for item in payload:
        try:
            when = dt.datetime.strptime(str(item.get("date")), "%d-%b-%Y").date()
        except ValueError:
            continue
        if 0 <= (when - today).days <= window:
            purpose = str(item.get("purpose") or item.get("bm_desc") or "corporate event")[:120]
            events.setdefault(str(item.get("symbol")), []).append(
                {"date": str(when), "purpose": purpose}
            )
    return events


# ---------- signals ----------


def buildup(price_change_pct: float | None, oi_change_pct: float | None) -> str:
    """The classic futures reading of price change against open-interest change."""
    if price_change_pct is None or oi_change_pct is None:
        return "unknown"
    if abs(oi_change_pct) < OI_MOVE_PCT:
        return "neutral"
    if oi_change_pct > 0:
        return "long build-up" if price_change_pct > 0 else "short build-up"
    return "short covering" if price_change_pct > 0 else "long unwinding"


def option_walls(
    chain: list[dict], quotes: dict[str, dict], spot: float
) -> dict[str, float | None]:
    calls = [
        (row["strike"], (quotes.get(row["key"]) or {}).get("oi") or 0)
        for row in chain
        if row["type"] == "CE"
    ]
    puts = [
        (row["strike"], (quotes.get(row["key"]) or {}).get("oi") or 0)
        for row in chain
        if row["type"] == "PE"
    ]
    call_oi, put_oi = sum(oi for _, oi in calls), sum(oi for _, oi in puts)
    above = [item for item in calls if item[0] >= spot and item[1] > 0]
    below = [item for item in puts if item[0] <= spot and item[1] > 0]
    return {
        "pcr": round(put_oi / call_oi, 2) if call_oi else None,
        "call_wall": max(above, key=lambda item: item[1])[0] if above else None,
        "put_wall": max(below, key=lambda item: item[1])[0] if below else None,
    }


def nearby_strikes(chain: list[dict], spot: float) -> list[dict]:
    strikes = sorted({row["strike"] for row in chain}, key=lambda strike: abs(strike - spot))
    keep = set(strikes[: 2 * OPTION_STRIKES_EACH_SIDE + 1])
    return [row for row in chain if row["strike"] in keep]


def technicals(bars: list[dict]) -> dict[str, Any]:
    import technical

    import premarket

    snap = technical.snapshot(bars) if bars else {"values": {}, "session": None, "sessions_used": 0}
    values = snap.get("values") or {}
    turnover = statistics.mean(row["close"] * row["volume"] for row in bars[-20:]) if bars else None
    return {
        "sessions": len(bars),
        "close": values.get("close"),
        "rsi14": values.get("rsi14"),
        "trend": premarket.trend_of(values)["label"] if values else "unknown",
        "return5_pct": values.get("return5_pct"),
        "atr14": values.get("atr14"),
        "turnover_inr": round(turnover) if turnover else None,
    }


def overnight_filters(row: dict, settings: dict, today: dt.date) -> list[str]:
    reasons = []
    tech = row["technical"]
    if tech["sessions"] < 30:
        reasons.append(f"only {tech['sessions']} daily candles stored")
    if tech["trend"] == "down":
        reasons.append("daily downtrend")
    if tech["rsi14"] is not None and tech["rsi14"] >= 75:
        reasons.append(f"RSI {tech['rsi14']:.0f} is 75 or more (overbought)")
    if tech["turnover_inr"] is not None and tech["turnover_inr"] < settings["min_turnover_inr"]:
        reasons.append("traded value below the liquidity floor")
    tomorrow = str(today + dt.timedelta(days=1))
    for event in row["events"]:
        if event["date"] in (str(today), tomorrow):
            reasons.append(f"{event['purpose']} on {event['date']}")
            break
    return reasons


def filter_kind(reason: str) -> str:
    for needle, kind in (
        ("candles", "too little history"),
        ("downtrend", "daily downtrend"),
        ("RSI", "overbought"),
        ("liquidity", "thin trading"),
    ):
        if needle in reason:
            return kind
    return "event today or tomorrow"


def overnight_score(row: dict) -> dict[str, Any]:
    parts = []

    def award(factor: str, points: float, reason: str) -> None:
        parts.append({"factor": factor, "points": round(points, 2), "reason": reason})

    tech, pos = row["technical"], row["positioning"]
    award(
        "trend", {"up": 2.0, "mixed": 0.5}.get(tech["trend"], 0.0), f"daily trend {tech['trend']}"
    )
    rsi = tech["rsi14"]
    award("momentum", 1.5 if rsi and 55 <= rsi < 70 else 0.5 if rsi and 45 < rsi < 55 else 0.0,
          f"RSI {rsi:.0f}" if rsi else "RSI unknown")  # fmt: skip
    award("futures positioning", BUILDUP_POINTS[pos["buildup"]],
          f"{pos['buildup']} (OI {pos['oi_change_pct']:+.1f}%)" if pos.get("oi_change_pct") is not None
          else "no previous open-interest snapshot yet")  # fmt: skip
    deliv = pos.get("delivery_pct")
    change = pos.get("price_change_pct")
    if deliv is not None:
        strong = deliv >= 50 and (change or 0) > 0
        award("delivery", 1.0 if strong else 0.0, f"{deliv:.0f}% delivered yesterday")
    net = (pos.get("deals") or {}).get("net_qty")
    if net:
        award("block/bulk deals", 0.5 if net > 0 else -0.5,
              f"net {'bought' if net > 0 else 'sold'} {abs(net):,.0f} shares in large deals")  # fmt: skip
    if row["events"]:
        award(
            "upcoming event",
            -0.5,
            "; ".join(f"{e['purpose']} {e['date']}" for e in row["events"][:2]),
        )
    return {"total": round(sum(part["points"] for part in parts), 2), "parts": parts}


# ---------- stages ----------


def _session_before(sessions_file: Path, today: dt.date) -> dt.date | None:
    try:
        sessions = json.loads(sessions_file.read_text(encoding="utf-8"))["sessions"]
    except (OSError, ValueError, KeyError):
        return None
    earlier = sorted(day for day in sessions if day < str(today))
    return dt.date.fromisoformat(earlier[-1]) if earlier else None


def scan_path(folder: Path, day: dt.date) -> Path:
    return folder / f"scan-{day}.json"


def overnight(
    config_path: Path,
    now: dt.datetime | None = None,
    client: KiteClient | None = None,
    fetch: Callable[[str], bytes] = nse_fetch,
) -> dict[str, Any]:
    from decision_pipeline import DailyCoordinator

    from reference import ReferenceStore

    coordinator = DailyCoordinator(config_path)
    settings = {**DEFAULTS, **coordinator.config.get("scan", {}),
                "min_turnover_inr": float(coordinator.config["min_turnover_inr"])}  # fmt: skip
    clock = (now or dt.datetime.now(IST)).astimezone(IST)
    today = clock.date()
    folder = coordinator.config_path.parent
    client = client or KiteClient()
    import make_universe

    rows = load_dump(folder, today, lambda: make_universe.fetch_kite_dump())
    universe = fno_universe(rows, today)
    store = ScanStore(folder / "scan.sqlite")
    notes = []
    refreshed = refresh_daily(store, client, universe, today)
    if refreshed["failed"]:
        notes.append(f"daily candles failed for {refreshed['failed']} stocks")
    eq_quotes = client.quote([item["symbol"] for item in universe.values()])
    chains, keys = {}, []
    for name, item in universe.items():
        spot = (eq_quotes.get(item["symbol"]) or {}).get("ohlc", {}).get("close")
        if spot:
            chains[name] = nearby_strikes(item["options"], spot)
            keys += [row["key"] for row in chains[name]]
        keys += item["futures"]
    derivatives = client.quote(keys)
    previous = store.previous_positioning(str(today))
    yesterday = _session_before(coordinator.path("sessions"), today)
    try:
        delivered = delivery(yesterday, fetch) if yesterday else {}
    except ValueError as exc:
        delivered = {}
        notes.append(f"delivery data unavailable ({exc})")
    large_deals = deals(fetch)
    try:
        events = upcoming_events(today, int(settings["event_window_days"]), fetch)
        events_known = True
    except (ValueError, json.JSONDecodeError) as exc:
        events, events_known = {}, False
        notes.append(f"NSE event calendar unavailable ({exc}); events are not screened")
    reference = ReferenceStore(coordinator.path("reference_db"))
    snapshot: dict[str, dict] = {}
    results = []
    for name, item in universe.items():
        quote = eq_quotes.get(item["symbol"]) or {}
        prev_close = (quote.get("ohlc") or {}).get("close")
        fut_oi = sum(((derivatives.get(key) or {}).get("oi") or 0) for key in item["futures"])
        walls = option_walls(chains.get(name, []), derivatives, prev_close or 0)
        before = previous.get(item["symbol"]) or {}
        oi_change = (100 * (fut_oi / before["fut_oi"] - 1)) if before.get("fut_oi") else None
        price_change = (
            100 * (prev_close / before["prev_close"] - 1)
            if before.get("prev_close") and prev_close
            else None
        )
        position = {
            "prev_close": prev_close,
            "fut_oi": fut_oi or None,
            **walls,
            "delivery_pct": delivered.get(name),
            "deals": large_deals.get(name),
            "oi_change_pct": round(oi_change, 2) if oi_change is not None else None,
            "price_change_pct": round(price_change, 2) if price_change is not None else None,
        }
        position["buildup"] = buildup(price_change, oi_change)
        snapshot[item["symbol"]] = position
        facts = reference.lookup(item["symbol"], clock)
        row = {
            "symbol": item["symbol"],
            "name": item["name"],
            "sector": facts.get("sector"),
            "sector_index": facts.get("sector_index"),
            "market_cap_tier": facts.get("market_cap_tier"),
            "lot_size": item["lot_size"],
            "technical": technicals(store.bars(item["symbol"], today)),
            "positioning": position,
            "events": events.get(name, []),
        }
        row["filters"] = overnight_filters(row, settings, today)
        row["score"] = overnight_score(row)
        results.append(row)
    store.save_positioning(str(today), snapshot)
    passed = sorted(
        (row for row in results if not row["filters"]),
        key=lambda row: row["score"]["total"],
        reverse=True,
    )
    reasons: dict[str, int] = {}
    for row in results:
        for reason in row["filters"]:
            reasons[filter_kind(reason)] = reasons.get(filter_kind(reason), 0) + 1
    report = {
        "session": str(today),
        "stage": "overnight",
        "as_of": clock.isoformat(),
        "scanned": len(results),
        "passed": len(passed),
        "events_screened": events_known,
        "dropped_by": dict(sorted(reasons.items(), key=lambda item: -item[1])[:8]),
        "shortlist": passed[: int(settings["shortlist"])],
        "notes": notes,
        "notice": "Positioning is the previous session's close. These signals describe how "
        "traders are positioned; they do not predict prices.",
    }
    scan_path(folder, today).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def open_stage(
    config_path: Path, now: dt.datetime | None = None, client: KiteClient | None = None
) -> dict[str, Any]:
    """Rank the shortlist on the pre-open gap and its strength against the Nifty and sector."""
    from decision_pipeline import DailyCoordinator

    coordinator = DailyCoordinator(config_path)
    settings = {**DEFAULTS, **coordinator.config.get("scan", {})}
    clock = (now or dt.datetime.now(IST)).astimezone(IST)
    folder = coordinator.config_path.parent
    path = scan_path(folder, clock.date())
    report = json.loads(path.read_text(encoding="utf-8"))
    client = client or KiteClient()
    shortlist = report["shortlist"]
    sector_keys = {
        row["sector_index"]: f"NSE:{row['sector_index']}"
        for row in shortlist
        if row.get("sector_index")
    }
    quotes = client.quote(
        [row["symbol"] for row in shortlist] + [NIFTY_KEY] + list(sector_keys.values())
    )

    def gap(key: str) -> float | None:
        quote = quotes.get(key) or {}
        ohlc = quote.get("ohlc") or {}
        opened = ohlc.get("open") or quote.get("last_price")
        return (
            round(100 * (opened / ohlc["close"] - 1), 2) if opened and ohlc.get("close") else None
        )

    nifty = gap(NIFTY_KEY)
    ranked = []
    for row in shortlist:
        own = gap(row["symbol"])
        sector = (
            gap(sector_keys[row["sector_index"]])
            if row.get("sector_index") in sector_keys
            else None
        )
        rs = round(own - nifty, 2) if own is not None and nifty is not None else None
        opening = {"gap_pct": own, "nifty_gap_pct": nifty, "sector_gap_pct": sector,
                   "rs_vs_nifty_pct": rs, "rs_vs_sector_pct": round(own - sector, 2)
                   if own is not None and sector is not None else None}  # fmt: skip
        filters = []
        points, reason = 0.0, "no pre-open price"
        if own is not None:
            if own <= -float(settings["max_gap_down_pct"]):
                filters.append(f"gapped down {own:.1f}% at the open")
            if own >= float(settings["max_gap_up_pct"]):
                points, reason = -1.0, f"gapped up {own:.1f}%: late to chase"
            elif rs is not None:
                points = 1.5 if rs > 0.3 else 0.75 if rs > 0 else -1.0 if rs < -0.3 else 0.0
                reason = f"{rs:+.2f} pp against the Nifty at the open"
        total = round(row["score"]["total"] + points, 2)
        ranked.append({**row, "opening": opening, "open_filters": filters,
                       "score": {"total": total, "parts": [*row["score"]["parts"],
                       {"factor": "pre-open strength", "points": points, "reason": reason}]}})  # fmt: skip
    ranked = sorted(
        (row for row in ranked if not row["open_filters"]),
        key=lambda row: row["score"]["total"],
        reverse=True,
    )
    report.update(stage="open", opened_at=clock.isoformat(), ranked=ranked,
                  dropped_at_open=[r["symbol"] for r in shortlist if r["symbol"] not in {x["symbol"] for x in ranked}])  # fmt: skip
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def confirm(
    config_path: Path, picks: list[str] | None = None, now: dt.datetime | None = None,
    client: KiteClient | None = None,
) -> dict[str, Any]:  # fmt: skip
    """First-15-minute check of the judge's picks: volume, VWAP and strength vs the Nifty."""
    from decision_pipeline import DailyCoordinator

    coordinator = DailyCoordinator(config_path)
    settings = {**DEFAULTS, **coordinator.config.get("scan", {})}
    clock = (now or dt.datetime.now(IST)).astimezone(IST)
    today = clock.date()
    folder = coordinator.config_path.parent
    if picks is None:
        report = json.loads(
            (coordinator.path("reports_dir") / f"premarket-{today}.json").read_text("utf-8")
        )
        picks = list(report.get("watching", []))
    client = client or KiteClient()
    import make_universe

    rows = load_dump(folder, today, lambda: make_universe.fetch_kite_dump())
    tokens = {f"NSE:{row['tradingsymbol']}": row["instrument_token"] for row in rows
              if row.get("segment") == "NSE" and row.get("instrument_type") == "EQ"}  # fmt: skip
    quotes = client.quote(picks + [NIFTY_KEY])
    nifty = quotes.get(NIFTY_KEY) or {}
    nifty_move = (
        100 * (nifty["last_price"] / nifty["ohlc"]["open"] - 1)
        if nifty.get("last_price") and (nifty.get("ohlc") or {}).get("open")
        else None
    )
    results = {}
    for symbol in picks:
        quote = quotes.get(symbol) or {}
        ohlc = quote.get("ohlc") or {}
        try:
            candles = client.candles(
                tokens[symbol], "15minute", today - dt.timedelta(days=35), today
            )
        except (KeyError, ValueError):
            candles = []
        firsts = [
            float(candle[5]) for candle in candles
            if dt.datetime.fromisoformat(candle[0]).date() < today
            and dt.datetime.fromisoformat(candle[0]).strftime("%H:%M") == "09:15"
        ][-20:]  # fmt: skip
        normal = statistics.mean(firsts) if len(firsts) >= 5 else None
        rvol = round(quote["volume"] / normal, 2) if normal and quote.get("volume") else None
        move = (
            100 * (quote["last_price"] / ohlc["open"] - 1)
            if quote.get("last_price") and ohlc.get("open")
            else None
        )
        rs = round(move - nifty_move, 2) if move is not None and nifty_move is not None else None
        above_vwap = bool(quote.get("last_price") and quote.get("average_price")
                          and quote["last_price"] >= quote["average_price"])  # fmt: skip
        reasons = []
        if rvol is None or rvol < float(settings["min_rvol"]):
            reasons.append(
                f"volume {rvol if rvol is not None else 'unknown'}x normal, needs {settings['min_rvol']}x"
            )
        if not above_vwap:
            reasons.append("trading below VWAP")
        if rs is None or rs < 0:
            reasons.append("weaker than the Nifty since the open")
        results[symbol] = {
            "confirmed": not reasons,
            "rvol": rvol,
            "above_vwap": above_vwap,
            "rs_since_open_pct": rs,
            "price_at_check": quote.get("last_price"),
            "reasons": reasons,
        }
    record = {"session": str(today), "checked_at": clock.isoformat(), "picks": results}
    (folder / f"confirm-{today}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def confirmation_for(folder: Path, today: dt.date) -> dict | None:
    try:
        return json.loads((folder / f"confirm-{today}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("overnight", help="08:40: positioning, events and the overnight shortlist")
    sub.add_parser("open", help="09:09: pre-open gap and relative strength; the best ten")
    sub.add_parser("confirm", help="09:31: volume, VWAP and strength for the judge's picks")
    sub.add_parser("nightly", help="After the close: store today's daily candles")
    args = parser.parse_args(argv)
    try:
        from decision_pipeline import DailyCoordinator as _Coordinator

        if not {**DEFAULTS, **_Coordinator(args.config).config.get("scan", {})}["enabled"]:
            print(json.dumps({"scan": "off", "note": "turn on scan in Settings to use it"}))
            return 0
        if args.command == "overnight":
            result = overnight(args.config)
            summary = {
                k: result[k] for k in ("session", "scanned", "passed", "dropped_by", "notes")
            }
            summary["shortlist"] = [row["symbol"] for row in result["shortlist"]]
        elif args.command == "open":
            result = open_stage(args.config)
            summary = {"session": result["session"], "ranked": [row["symbol"] for row in result["ranked"][:10]],
                       "dropped_at_open": result["dropped_at_open"]}  # fmt: skip
        elif args.command == "confirm":
            summary = confirm(args.config)
        else:
            from decision_pipeline import DailyCoordinator

            import make_universe

            coordinator = DailyCoordinator(args.config)
            today = dt.datetime.now(IST).date()
            folder = coordinator.config_path.parent
            universe = fno_universe(
                load_dump(folder, today, lambda: make_universe.fetch_kite_dump()), today
            )
            summary = refresh_daily(ScanStore(folder / "scan.sqlite"), KiteClient(), universe,
                                    today + dt.timedelta(days=1))  # fmt: skip
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        print("SCAN_BLOCK: " + str(exc)[:300], file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

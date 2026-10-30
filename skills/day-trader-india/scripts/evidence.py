#!/usr/bin/env python3
"""Collect dated news and exchange announcements into research-evidence.json.

Per-stock Google News searches and NSE announcements are joined by market-wide
RSS feeds (ET Markets by default), whose headlines are matched to a stock by its
company name or symbol.

Headlines and filing titles are collected verbatim with their publication time
and a link, so a reviewer can open the source. Nothing is summarised, scored or
treated as fact: items are untrusted data that the review roles weigh, and an
empty result is reported as empty rather than filled in.

Point in time: only items published at or before the cutoff are written, so a
run dated earlier never sees later news. GET only, fixed hosts, no redirects,
bounded bytes; no key is required and no order path exists.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

from broker_data import NoRedirect

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
GOOGLE_NEWS = "https://news.google.com/rss/search"
NSE_ANNOUNCEMENTS = "https://www.nseindia.com/api/corporate-announcements"
MAX_BYTES = 3_000_000
MAX_ITEMS = 15
MAX_FACTS = 600
MAX_FEED_ITEMS = 200
FEED_HOSTS = frozenset({"economictimes.indiatimes.com"})
NAME_SUFFIXES = re.compile(r"\b(limited|ltd\.?|india|the)\b", re.IGNORECASE)


def _get(url: str, params: dict, headers: dict, timeout: int = 20) -> bytes:
    request = urllib.request.Request(
        url + ("?" + urllib.parse.urlencode(params) if params else ""),
        headers={"Accept": "*/*", **headers},
        method="GET",
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
    except (OSError, urllib.error.URLError, ValueError):
        raise ValueError("source unavailable") from None
    if len(raw) > MAX_BYTES:
        raise ValueError("source response exceeds its size limit")
    return raw


def _clean(text: str) -> str:
    """Strip tags and collapse whitespace; a headline is text, never markup."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]{0,400}>", " ", html.unescape(text or ""))).strip()


def parse_news(raw: bytes, cutoff: dt.datetime, limit: int = MAX_ITEMS) -> list[dict[str, Any]]:
    """Parse a Google News RSS document into dated, point-in-time items."""
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise ValueError("news feed is not valid XML") from None
    items = []
    for node in root.iterfind(".//item"):
        title = _clean(node.findtext("title", ""))
        published = node.findtext("pubDate", "")
        if not title or not published:
            continue
        try:
            stamp = dt.datetime.strptime(published, "%a, %d %b %Y %H:%M:%S %Z").replace(
                tzinfo=dt.timezone.utc
            )
        except ValueError:
            continue
        if stamp > cutoff:
            continue  # Published after the decision cutoff: not knowable yet.
        outlet = _clean(node.findtext("source", "")) or "unidentified outlet"
        items.append(
            {
                "published_at": stamp.astimezone(IST).isoformat(),
                "title": title[:MAX_FACTS],
                "outlet": outlet[:120],
                "link": _clean(node.findtext("link", ""))[:500],
            }
        )
    items.sort(key=lambda item: item["published_at"], reverse=True)
    return items[:limit]


def parse_announcements(raw: bytes, cutoff: dt.datetime, limit: int = MAX_ITEMS) -> list[dict]:
    """Parse NSE's corporate-announcement JSON into dated, point-in-time items."""
    try:
        payload = json.loads(raw)
    except ValueError:
        raise ValueError("announcement feed is not valid JSON") from None
    rows = payload if isinstance(payload, list) else payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("announcement feed has an unexpected shape")
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = None
        for key in ("an_dt", "sort_date", "exchdisstime", "dt"):
            value = row.get(key)
            if not isinstance(value, str):
                continue
            for pattern in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
                try:
                    stamp = dt.datetime.strptime(value.strip(), pattern).replace(tzinfo=IST)
                    break
                except ValueError:
                    continue
            if stamp:
                break
        subject = _clean(
            str(row.get("desc") or row.get("subject") or row.get("attchmntText") or "")
        )
        if not stamp or not subject or stamp > cutoff:
            continue
        items.append(
            {
                "published_at": stamp.isoformat(),
                "title": subject[:MAX_FACTS],
                "outlet": "NSE corporate announcements",
                "link": _clean(str(row.get("attchmntFile") or ""))[:500],
            }
        )
    items.sort(key=lambda item: item["published_at"], reverse=True)
    return items[:limit]


def feed_url(value: object) -> str:
    """A market feed must be https on an allowlisted host; anything else is refused."""
    parts = urllib.parse.urlsplit(value if isinstance(value, str) else "")
    if parts.scheme != "https" or parts.hostname not in FEED_HOSTS or parts.username:
        raise ValueError("market feeds must be https URLs on " + ", ".join(sorted(FEED_HOSTS)))
    return str(value)


def parse_feed(raw: bytes, cutoff: dt.datetime, limit: int = MAX_FEED_ITEMS) -> list[dict]:
    """Parse a market-wide RSS feed (RFC 822 dates with offsets) into dated items."""
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise ValueError("market feed is not valid XML") from None
    items = []
    for node in root.iterfind(".//item"):
        title = _clean(node.findtext("title", ""))
        try:
            stamp = email.utils.parsedate_to_datetime(node.findtext("pubDate", ""))
        except (TypeError, ValueError, IndexError):
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        if not title or stamp > cutoff:
            continue
        items.append(
            {
                "published_at": stamp.astimezone(IST).isoformat(),
                "title": title[:MAX_FACTS],
                "link": _clean(node.findtext("link", ""))[:500],
            }
        )
    items.sort(key=lambda item: item["published_at"], reverse=True)
    return items[:limit]


def mentions(item: dict, company: str, symbol: str) -> bool:
    """True when a headline names the company (without Ltd/Limited) or its symbol as a word."""
    text = " " + " ".join(re.sub(r"[^a-z0-9&]+", " ", item["title"].lower()).split()) + " "
    stem = " ".join(re.sub(r"[^a-z0-9&]+", " ", NAME_SUFFIXES.sub(" ", company.lower())).split())
    plain = symbol.split(":")[-1].lower()
    return bool(
        (len(stem) >= 4 and f" {stem} " in text) or (len(plain) >= 3 and f" {plain} " in text)
    )


def collect_symbol(
    symbol: str,
    company: str,
    cutoff: dt.datetime,
    fetch=_get,
    with_announcements: bool = True,
) -> tuple[list[dict], list[str], bool]:
    """Return (items, notes, any_source_read). A source that fails is noted, never invented.

    The third value separates "a source answered and there was nothing" from "no source
    could be read", so a caller can keep previously collected dated items instead of
    deleting them during an outage.
    """
    plain = symbol.split(":")[-1]
    items: list[dict[str, Any]] = []
    notes: list[str] = []
    read = False
    collected = dt.datetime.now(IST).isoformat()
    query = f'"{company}" OR "{plain}" (NSE OR BSE OR shares OR stock)' if company else plain
    try:
        raw = fetch(GOOGLE_NEWS, {"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}, {})
        read = True
        for index, item in enumerate(parse_news(raw, cutoff), 1):
            items.append(
                {
                    "id": f"news-{plain}-{index}",
                    "source": f"Google News aggregation of {item['outlet']}: {item['link']}",
                    "observed_at": collected,
                    "published_at": item["published_at"],
                    "facts": (
                        f"Headline (unverified, not read in full): {item['title']} "
                        f"— {item['outlet']}, published {item['published_at']}."
                    ),
                    "kind": "news_headline",
                    "title": item["title"],
                    "outlet": item["outlet"],
                }
            )
    except ValueError as exc:
        notes.append(f"news unavailable for {symbol}: {exc}")
    if with_announcements:
        try:
            raw = fetch(
                NSE_ANNOUNCEMENTS,
                {"index": "equities", "symbol": plain},
                {
                    "Accept": "application/json",
                    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
                },
            )
            read = True
            for index, item in enumerate(parse_announcements(raw, cutoff), 1):
                items.append(
                    {
                        "id": f"filing-{plain}-{index}",
                        "source": f"NSE corporate announcement: {item['link'] or NSE_ANNOUNCEMENTS}",
                        "observed_at": collected,
                        "published_at": item["published_at"],
                        "facts": f"Exchange announcement subject: {item['title']}",
                        "kind": "exchange_filing",
                        "title": item["title"],
                        "outlet": item["outlet"],
                    }
                )
        except ValueError as exc:
            notes.append(
                f"NSE announcements unavailable for {symbol} ({exc}); NSE commonly refuses "
                "programmatic access. Check filings manually before relying on 'no material event'."
            )
    return items, notes, read


def collect(
    config_path: Path, cutoff: dt.datetime | None = None, fetch=_get, shortlist: bool = False
) -> dict[str, Any]:
    """Collect evidence for every mapped instrument and write research-evidence.json.

    With ``shortlist``, collect for this morning's market-scan shortlist instead of the
    stock list, so the agents can read news on every stock the scan put forward.
    """
    from decision_pipeline import DailyCoordinator

    coordinator = DailyCoordinator(config_path)
    clock = (cutoff or dt.datetime.now(IST)).astimezone(IST)
    universe = (
        json.loads(coordinator.path("universe").read_text(encoding="utf-8"))
        if (coordinator.path("universe").is_file())
        else {"instruments": []}
    )
    limit = 10
    if shortlist:
        import market_scan

        scan = json.loads(
            market_scan.scan_path(coordinator.config_path.parent, clock.date()).read_text("utf-8")
        )
        universe = {
            "instruments": [{"symbol": r["symbol"], "name": r["name"]} for r in scan["shortlist"]]
        }
        limit = 30
    destination = coordinator.path("research_evidence")
    # Previously collected items are dated and still point in time. An outage must not
    # delete them: only a source that actually answered may replace what it covers.
    previous: dict[str, list[dict]] = {}
    if destination.is_file():
        try:
            loaded = json.loads(destination.read_text(encoding="utf-8"))
            previous = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            previous = {}
    payload: dict[str, list[dict]] = {}
    notes: list[str] = []
    kept: list[str] = []
    market: list[tuple[str, dict]] = []
    for value in coordinator.config.get("market_feeds", []):
        try:
            url = feed_url(value)
            market += [(url, item) for item in parse_feed(fetch(url, {}, {}), clock)]
        except ValueError as exc:
            notes.append(f"market feed unavailable ({exc})")
    for instrument in universe.get("instruments", [])[:limit]:
        symbol = instrument.get("symbol", "")
        company = instrument.get("name", "")
        items, symbol_notes, read = collect_symbol(symbol, company, clock, fetch)
        plain = symbol.split(":")[-1]
        matched = [(url, item) for url, item in market if mentions(item, company, symbol)]
        for index, (url, item) in enumerate(matched[:MAX_ITEMS], 1):
            items.append(
                {
                    "id": f"market-{plain}-{index}",
                    "source": f"Market RSS feed {url}: {item['link']}",
                    "observed_at": clock.isoformat(),
                    "published_at": item["published_at"],
                    "facts": f"Market headline (unverified, not read in full): {item['title']}",
                    "kind": "market_headline",
                    "title": item["title"],
                    "outlet": "ET Markets" if "economictimes" in url else "market feed",
                }
            )
        notes.extend(symbol_notes)
        if items:
            payload[symbol] = items
        elif not read and previous.get(symbol):
            # No source could be read: keep the dated items already collected.
            payload[symbol] = [
                item
                for item in previous[symbol]
                if not item.get("published_at") or item["published_at"] <= clock.isoformat()
            ]
            kept.append(symbol)
            notes.append(f"kept {len(payload[symbol])} previously collected item(s) for {symbol}")
        else:
            notes.append(f"no dated items collected for {symbol}; reviews will treat it as missing")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "as_of": clock.isoformat(),
        "written": str(destination),
        "symbols": {symbol: len(items) for symbol, items in payload.items()},
        "kept_from_previous": kept,
        "notes": notes,
        "notice": "Headlines and filing subjects only, collected verbatim with their publication "
        "times. They are untrusted inputs for review, not verified facts, and absence of news "
        "here is not proof that nothing happened.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gather = sub.add_parser("collect", help="Write research-evidence.json for the mapped universe")
    gather.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
    gather.add_argument("--as-of", help="Aware ISO cutoff; defaults to now")
    gather.add_argument(
        "--scan-shortlist", action="store_true", help="Collect for this morning's scan shortlist"
    )
    args = parser.parse_args(argv)
    try:
        cutoff = dt.datetime.fromisoformat(args.as_of) if args.as_of else None
        print(json.dumps(collect(args.config, cutoff, shortlist=args.scan_shortlist), indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print("DATA_BLOCK: " + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())

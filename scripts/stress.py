#!/usr/bin/env python3
"""Load, stress and soak checks for the paper desk. Synthetic data only; no broker or network.

    python3 scripts/stress.py engine --symbols 20 --days 60   # many symbols and days, fast
    python3 scripts/stress.py api --clients 32                # concurrent dashboard/API traffic
    python3 scripts/stress.py soak --days 250                 # a year of sessions: growth, drift
    python3 scripts/stress.py all

Every mode checks correctness as well as speed, and exits 1 on the first broken
invariant. Everything runs in a temporary folder, with secrets in a temporary
ITL_CONFIG_DIR, so your real keys and books are never read or written.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import random
import resource
import statistics
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/day-trader-india/scripts"))

import time_machine  # noqa: E402

import engine  # noqa: E402
import paper_book  # noqa: E402

IST = engine.IST
FAILURES: list[str] = []


def check(ok: bool, message: str) -> None:
    if not ok:
        FAILURES.append(message)
        print("  FAIL " + message, flush=True)


def session_for(day: dt.date) -> dict[str, dt.datetime]:
    at = lambda h, m: dt.datetime(day.year, day.month, day.day, h, m, tzinfo=IST)  # noqa: E731
    return {
        "open": at(9, 15),
        "entry_cutoff": at(14, 30),
        "flat_by": at(15, 15),
        "close": at(15, 30),
    }


def trading_days(count: int, first: dt.date = dt.date(2025, 1, 6)) -> list[dt.date]:
    days, day = [], first
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    return days


def day_quotes(symbols: list[str], day: dt.date, rng: random.Random) -> list[engine.Quote]:
    """75 completed five-minute bars per symbol, interleaved by time like a live feed."""
    open_at, quotes = session_for(day)["open"], []
    for symbol in symbols:
        price, drift = rng.uniform(100, 3000), rng.gauss(0, 0.0008)
        for index in range(75):
            start = open_at + index * engine.BAR
            close = price * (1 + drift + rng.gauss(0, 0.002))
            high = max(price, close) * (1 + abs(rng.gauss(0, 0.001)))
            low = min(price, close) * (1 - abs(rng.gauss(0, 0.001)))
            bar = {"symbol": symbol, "t": start, "source": "SYNTHETIC_STRESS",
                   "open": round(price, 2), "high": round(high, 2), "low": round(low, 2),
                   "close": round(close, 2)}  # fmt: skip
            quotes.extend(engine.bar_quotes([bar], symbol, day, Decimal(4)))
            price = close
    return sorted(quotes, key=lambda quote: (quote.as_of, quote.symbol))


def new_book(symbols: list[str]) -> dict:
    return paper_book.create(
        "10000000", ",".join(symbols), "2500", "1000000", "500000", replay=True,
        max_trades=len(symbols), max_open=len(symbols), max_loss_streak=10**6,
        drawdown_stop="10000000",
    )  # fmt: skip


def run_days(symbols: list[str], days: list[dt.date], folder: Path, seed: int) -> list[dict]:
    """One engine per session over one carried-over book, persisted after every quote."""
    rng, book, rows = random.Random(seed), new_book(symbols), []
    config = engine.EngineConfig(tuple(symbols), Decimal(5), Decimal(10), Decimal(5),
                                 heartbeat_timeout_seconds=600, max_orders_per_second=10**6)  # fmt: skip
    seen_ids: set[str] = set()
    for number, day in enumerate(days):
        session, quotes = session_for(day), day_quotes(symbols, day, rng)
        store = engine.EngineStore(folder / f"day-{number:04d}.sqlite")
        store.create(book)
        broker = engine.PaperBroker(book, Decimal(5))
        strategy = engine.OpeningRangeBreakout(Decimal(2500), Decimal(500000), Decimal(2))
        runner = engine.Engine(config, session, broker, strategy, notifier=lambda *_: None)
        started, latencies = time.perf_counter(), []
        for quote in quotes:
            tick = time.perf_counter()
            runner.on_quote(quote, quote.as_of)
            runner.tick(quote.as_of)
            store.save(runner)
            latencies.append(time.perf_counter() - tick)
        runner.tick(session["close"])
        store.save(runner)
        book = broker.book
        # Invariants: flat at the close, sealed journal, unique fills, cash reconciles.
        check(not book["positions"], f"{day}: positions left open after the close")
        check(runner.halt_reason is None, f"{day}: engine halted: {runner.halt_reason}")
        paper_book.verify_state(book)
        ids = [event["id"] for event in book["events"]]
        check(len(ids) == len(set(ids)), f"{day}: duplicate event IDs in the journal")
        new_ids = set(ids) - seen_ids
        seen_ids |= new_ids
        realized = sum((Decimal(v) for v in book["realized_by_day"].values()), Decimal(0))
        check(
            Decimal(book["cash"]) == Decimal(book["initial_cash"]) + realized,
            f"{day}: cash {book['cash']} != initial + realized {realized}",
        )
        loaded, _ = engine.EngineStore(store.path).load()
        check(loaded == book, f"{day}: persisted book differs from memory")
        rows.append({
            "day": str(day), "quotes": len(quotes), "fills": len(new_ids),
            "seconds": time.perf_counter() - started,
            "p95_ms": 1000 * sorted(latencies)[int(0.95 * (len(latencies) - 1))],
            "events": len(book["events"]), "book_kb": len(json.dumps(book)) / 1024,
        })  # fmt: skip
    return rows


def summarize(rows: list[dict]) -> dict:
    quotes = sum(row["quotes"] for row in rows)
    seconds = sum(row["seconds"] for row in rows)
    return {"days": len(rows), "quotes": quotes, "fills": sum(row["fills"] for row in rows),
            "quotes_per_second": round(quotes / seconds), "seconds": round(seconds, 2),
            "worst_p95_ms": round(max(row["p95_ms"] for row in rows), 2),
            "final_events": rows[-1]["events"], "final_book_kb": round(rows[-1]["book_kb"], 1)}  # fmt: skip


def mode_engine(args: argparse.Namespace) -> None:
    print(f"== Engine stress: {args.symbols} symbols x {args.days} sessions", flush=True)
    symbols = [f"NSE:STRESS{index}" for index in range(args.symbols)]
    with tempfile.TemporaryDirectory() as folder:
        rows = run_days(symbols, trading_days(args.days), Path(folder), args.seed)
    print("  " + json.dumps(summarize(rows)))
    print("== Time Machine stress: 50,000 replays x 20 plans", flush=True)
    rng = random.Random(args.seed)
    pool = [[(1 + rng.gauss(0, 0.001), 1 + abs(rng.gauss(0, 0.003)), 1 - abs(rng.gauss(0, 0.003)),
              1 + rng.gauss(0, 0.002)) for _ in range(75)] for _ in range(180)]  # fmt: skip
    started = time.perf_counter()
    for index in range(20):
        plan = {
            "entry": 100.0,
            "stop": 99.0 - index * 0.05,
            "target": 102.0,
            "entry_bar": 3 + index,
        }
        mc = time_machine.simulate(pool, plan, 72, replays=50_000)
        total = mc["target_first_pct"] + mc["stop_first_pct"] + mc["neither_pct"]
        check(abs(total - 100) < 0.2, f"time machine odds sum to {total}")
        check(mc == time_machine.simulate(pool, plan, 72, replays=50_000), "replays not repeatable")
    print(f"  40 runs of 50,000 replays in {time.perf_counter() - started:.2f}s")


def mode_soak(args: argparse.Namespace) -> None:
    print(f"== Soak: {args.days} sessions of {args.symbols} symbols", flush=True)
    symbols = [f"NSE:SOAK{index}" for index in range(args.symbols)]
    # Peak memory from the OS, not tracemalloc: tracing taxes every allocation and made the
    # timing itself look ~3x worse as the journal grew.
    with tempfile.TemporaryDirectory() as folder:
        rows = run_days(symbols, trading_days(args.days), Path(folder), args.seed)
        disk_mb = sum(path.stat().st_size for path in Path(folder).iterdir()) / 1e6
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak *= 1 if sys.platform == "darwin" else 1024  # Bytes on macOS, KiB on Linux.
    window = max(1, len(rows) // 10)
    early = statistics.fmean(row["seconds"] for row in rows[:window])
    late = statistics.fmean(row["seconds"] for row in rows[-window:])
    print("  " + json.dumps({**summarize(rows), "first_days_s": round(early, 3),
                             "last_days_s": round(late, 3), "slowdown": round(late / early, 2),
                             "peak_memory_mb": round(peak / 1e6, 1), "disk_mb": round(disk_mb, 1)}))  # fmt: skip
    check(late / early < 3, f"sessions got {late / early:.1f}x slower as the journal grew")


def request(base: str, path: str, token: str = "", body: dict | None = None, origin: str = ""):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if token:
        headers["X-Session-Token"] = token
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(base + path, data=data, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            status, payload = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, payload = error.code, error.read()
    except (urllib.error.URLError, ConnectionError):
        status, payload = 0, b""  # The server hung up, e.g. refusing an oversized body unread.
    return status, payload, time.perf_counter() - started


def mode_api(args: argparse.Namespace) -> None:
    print(f"== API load: {args.clients} concurrent clients", flush=True)
    with tempfile.TemporaryDirectory() as folder:
        os.environ["ITL_CONFIG_DIR"] = str(Path(folder) / "secrets")
        from http.server import ThreadingHTTPServer

        import observatory

        app = observatory.Observatory(Path(folder) / "data", interval=0.0)
        server = ThreadingHTTPServer(("127.0.0.1", 0), observatory.make_handler(app))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        pool = concurrent.futures.ThreadPoolExecutor(args.clients)
        try:
            token = json.loads(request(base, "/api/session")[1])["token"]
            check(request(base, "/api/setup/init_project", token, {})[0] == 200, "init failed")

            # 1. Read burst while a replay writes its journal.
            check(request(base, "/api/replay", token, {"scenario": "baseline"})[0] == 200,
                  "replay did not start")  # fmt: skip
            paths = ["/api/state", "/api/setup/status", "/api/health", "/", "/api/setup/jobs"]
            results = list(pool.map(lambda i: request(base, paths[i % len(paths)]),
                                    range(args.requests)))  # fmt: skip
            codes = [status for status, _, _ in results]
            latency = sorted(seconds for _, _, seconds in results)
            print("  " + json.dumps({
                "reads": len(results), "non_200": len([c for c in codes if c != 200]),
                "p50_ms": round(1000 * latency[len(latency) // 2], 1),
                "p95_ms": round(1000 * latency[int(0.95 * (len(latency) - 1))], 1),
                "max_ms": round(1000 * latency[-1], 1)}))  # fmt: skip
            check(all(code == 200 for code in codes), f"reads failed: {sorted(set(codes))}")
            for _ in range(600):
                if json.loads(request(base, "/api/state")[1])["status"] != "running":
                    break
                time.sleep(0.05)
            final = json.loads(request(base, "/api/state")[1])
            check(final["status"] in ("completed", "halted"), f"replay ended {final['status']}")

            # 2. Secret writes race: the rate limit holds and the file stays whole.
            values = [f"sk-or-stress{index:04d}abcdef" for index in range(40)]
            saved = list(pool.map(lambda v: request(base, "/api/setup/save_secret", token,
                                                    {"key": "OPENROUTER_API_KEY", "value": v}),
                                  values))  # fmt: skip
            ok = [values[i] for i, (status, _, _) in enumerate(saved) if status == 200]
            limited = [status for status, _, _ in saved if status == 429]
            check(len(ok) == 20 and len(limited) == 20,
                  f"secret saves: {len(ok)} ok, {len(limited)} limited (want 20/20)")  # fmt: skip
            import secret_store

            stored = secret_store.get("OPENROUTER_API_KEY")
            check(stored in ok, "secrets file holds a value no request saved")
            check(all(stored not in body.decode() for _, body, _ in saved), "a secret was echoed")

            # 3. Settings race on one version: exactly one save wins, the rest conflict.
            version = json.loads(request(base, "/api/setup/settings")[1])["version"]
            tries = list(pool.map(lambda n: request(base, "/api/setup/save_settings", token,
                                                    {"version": version,
                                                     "changes": {"poll_seconds": 30 + n}}),
                                  range(12)))  # fmt: skip
            codes = sorted(status for status, _, _ in tries)
            check(codes.count(200) == 1 and codes.count(409) == 11, f"settings race: {codes}")
            json.loads((Path(folder) / "data/pipeline.json").read_text())

            # 4. Hostile requests are refused, and none of them is audited as a change.
            check(request(base, "/api/setup/init_project", "", {})[0] == 403, "tokenless write")
            check(request(base, "/api/setup/init_project", token, {},
                          origin="http://evil.example")[0] == 403, "cross-origin write")  # fmt: skip
            big = {"csv_text": "x" * 4_000_000}
            huge = request(base, "/api/setup/upload_equity_list", token, big)[0]
            check(huge in (413, 0), f"huge body answered {huge}")
            check(request(base, "/../../etc/passwd")[0] == 404, "path traversal")
            audit = (Path(folder) / "data/setup-audit.jsonl").read_text().splitlines()
            check(all(json.loads(line) for line in audit), "audit log has a broken line")
            check(json.loads(request(base, "/api/health")[1])["ok"], "health not ok after load")
        finally:
            pool.shutdown()
            server.shutdown()
            os.environ.pop("ITL_CONFIG_DIR", None)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("mode", choices=("engine", "api", "soak", "all"))
    parser.add_argument("--symbols", type=int, default=20)
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--clients", type=int, default=32)
    parser.add_argument("--requests", type=int, default=600)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    for mode, days in (("engine", 60), ("api", None), ("soak", 250)):
        if args.mode in (mode, "all"):
            run = argparse.Namespace(**{**vars(args), "days": args.days or days})
            if mode == "soak" and args.mode == "all":
                run.symbols = 5
            {"engine": mode_engine, "api": mode_api, "soak": mode_soak}[mode](run)
    print("FAILED: " + "; ".join(FAILURES) if FAILURES else "All stress checks passed.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

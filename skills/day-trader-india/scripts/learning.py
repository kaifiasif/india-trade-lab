#!/usr/bin/env python3
"""Learning from mistakes: grade every agent's call against what then happened.

Each evening, after the day's bars reach history.sqlite, ``settle``:

1. reads that morning's pre-market report (every specialist's stance on every
   stock, the judge's picks and passes, each sub-agent's risk level and plan);
2. measures each stock's session from stored bars (open to close, the high and
   the low) and reads closed paper trades (R multiple, stopped or not);
3. grades each call right, wrong or missed, and writes a short lesson for every
   mistake, dated by when its outcome became known;
4. rebuilds a note per stock (how it moves, how the desk did on it) and puts a
   stock on cooldown after repeated stop-outs or wrong picks.

The next morning the agents see their own recent mistakes, their track record
and the stock notes, and finalists are weighted by which specialists have been
right. All of it can only narrow what the desk does: a cooldown removes a stock,
a lesson is advice, and nothing here changes risk limits or adds a trade.

Nothing learns from the future: a lesson is offered only after its outcome was
known. Grading is plain arithmetic, so it costs no model calls.

``finetune`` reports whether fine-tuning is worth trying per role and exports
chat-format JSONL (train and a later-dated eval split) from answers that were
graded right. It never uploads anything or starts a paid job.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import sqlite3
import statistics
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
FLAT_PCT = 0.3  # Moves smaller than this, open to close, grade nobody.
BIG_MOVE_PCT = 1.5  # A pass on a stock that ran this far counts as a missed opportunity.
DEEP_DIP_PCT = 1.5  # A "low risk" call on a stock that fell this far intraday was wrong.
COOLDOWN_DAYS = 7
FINETUNE_MIN_EXAMPLES = 300
FINETUNE_MIN_GRADED = 60
FINETUNE_WEAK_ACCURACY = 0.55
SPECIALIST_ROLES = (
    "news-analyst", "sentiment-analyst", "technical-analyst",
    "sector-analyst", "liquidity-analyst", "brokerage-analyst",
)  # fmt: skip
JUDGE = "selection-judge"
GRADED_ROLES = (*SPECIALIST_ROLES, "risk-scout", "setup-planner", JUDGE)


class LearningStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS views (session TEXT, role TEXT, symbol TEXT,
                  stance TEXT NOT NULL, detail TEXT, model TEXT,
                  PRIMARY KEY(session, role, symbol));
                CREATE TABLE IF NOT EXISTS outcomes (session TEXT, symbol TEXT, open REAL,
                  high REAL, low REAL, close REAL, ret_pct REAL, runup_pct REAL,
                  drawdown_pct REAL, known_at TEXT, PRIMARY KEY(session, symbol));
                CREATE TABLE IF NOT EXISTS trades (entry_id TEXT PRIMARY KEY, symbol TEXT,
                  session TEXT, strategy TEXT, r_multiple REAL, pnl_inr REAL, exit_kind TEXT,
                  closed_at TEXT);
                CREATE TABLE IF NOT EXISTS grades (session TEXT, role TEXT, symbol TEXT,
                  verdict TEXT NOT NULL, measure REAL, known_at TEXT NOT NULL,
                  PRIMARY KEY(session, role, symbol));
                CREATE TABLE IF NOT EXISTS lessons (id INTEGER PRIMARY KEY, scope TEXT NOT NULL,
                  subject TEXT NOT NULL, session TEXT NOT NULL, kind TEXT NOT NULL,
                  text TEXT NOT NULL, known_at TEXT NOT NULL,
                  UNIQUE(scope, subject, session, kind));
                CREATE TABLE IF NOT EXISTS stock_notes (symbol TEXT PRIMARY KEY, as_of TEXT,
                  note TEXT NOT NULL);
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

    # ---------- inputs ----------

    def ingest_report(self, report: dict) -> int:
        """Record every stance in one pre-market report. Reruns of the same day replace it."""
        session = str(report.get("session_date", ""))
        selection = report.get("selection") or {}
        if not session or selection.get("mode") != "judge":
            return 0  # Only reports where the agents actually ran carry views to grade.
        rows: list[tuple] = []
        for role, view in (selection.get("specialists") or {}).items():
            if view.get("status") != "ok" or role not in SPECIALIST_ROLES:
                continue
            for symbol, item in view.get("assessments", {}).items():
                detail = {"summary": str(item.get("summary", ""))[:240]}
                rows.append((session, role, symbol, item["stance"], detail, view.get("model")))
        judge = selection.get("judge") or {}
        picked = {pick["symbol"]: pick for pick in judge.get("picks", [])}
        picked.update({pick["symbol"]: pick for pick in judge.get("dropped", [])})
        for symbol, reports in (selection.get("finalists") or {}).items():
            scout, planner = reports.get("risk-scout") or {}, reports.get("setup-planner") or {}
            if scout.get("risk_level"):
                rows.append((session, "risk-scout", symbol, scout["risk_level"],
                             {"summary": str(scout.get("risks", ""))[:240]}, None))  # fmt: skip
            if planner.get("strategy"):
                rows.append((session, "setup-planner", symbol, planner["strategy"],
                             {"summary": str(planner.get("plan", ""))[:240]}, None))  # fmt: skip
            pick = picked.get(symbol)
            stance = "pick" if pick else "pass"
            detail = {
                key: pick.get(key)
                for key in ("rating", "conviction", "strategy", "reason", "dropped")
                if pick and pick.get(key) is not None
            }
            if "reason" in detail:
                detail["reason"] = str(detail["reason"])[:240]
            rows.append((session, JUDGE, symbol, stance, detail, None))
        with self._connect() as conn:
            conn.execute("DELETE FROM views WHERE session=?", (session,))
            conn.executemany(
                "INSERT OR REPLACE INTO views VALUES (?,?,?,?,?,?)",
                [(s, r, sym, st, json.dumps(d), m) for s, r, sym, st, d, m in rows],
            )
        return len(rows)

    def ingest_reports(self, folder: Path, as_of: dt.datetime) -> int:
        count = 0
        for path in sorted(folder.glob("premarket-*.json")):
            if path.stem.removeprefix("premarket-") > str(as_of.astimezone(IST).date()):
                continue
            try:
                count += self.ingest_report(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue  # A malformed report teaches nothing; never stop the others.
        return count

    def record_outcomes(self, history_db: Path, as_of: dt.datetime) -> int:
        """Session open, high, low and close for every viewed stock whose day is complete."""
        if not history_db.is_file():
            return 0
        with self._connect() as conn:
            wanted = conn.execute(
                "SELECT DISTINCT v.session, v.symbol FROM views v LEFT JOIN outcomes o "
                "ON o.session=v.session AND o.symbol=v.symbol WHERE o.symbol IS NULL"
            ).fetchall()
        found = []
        with contextlib.closing(sqlite3.connect(history_db, timeout=10)) as history:
            for row in wanted:
                hit = history.execute(
                    "SELECT close_at, payload FROM sessions WHERE symbol=? AND date=? "
                    "AND kind='broker_export'",
                    (row["symbol"], row["session"]),
                ).fetchone()
                if not hit or dt.datetime.fromisoformat(hit[0]) > as_of:
                    continue
                bars = json.loads(hit[1]).get("bars") or []
                if not bars:
                    continue
                first = float(bars[0]["open"])
                high = max(float(bar["high"]) for bar in bars)
                low = min(float(bar["low"]) for bar in bars)
                close = float(bars[-1]["close"])
                found.append((
                    row["session"], row["symbol"], first, high, low, close,
                    round(100 * (close / first - 1), 3), round(100 * (high / first - 1), 3),
                    round(100 * (low / first - 1), 3),
                    _stamp(dt.datetime.fromisoformat(hit[0])),
                ))  # fmt: skip
        with self._connect() as conn:
            conn.executemany("INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?,?,?,?,?,?)", found)
        return len(found)

    def record_trades(self, book: dict, as_of: dt.datetime) -> int:
        """Closed paper trades with their R multiple and how they ended."""
        events = book.get("events", [])
        entries = {event["id"]: event for event in events if event.get("side") == "buy"}
        rows = []
        for event in events:
            if event.get("side") != "sell" or event.get("entry_event_id") not in entries:
                continue
            closed = dt.datetime.fromisoformat(event["as_of"])
            if closed > as_of:
                continue
            entry = entries[event["entry_event_id"]]
            fill, exit_fill = float(entry["assumed_fill_inr"]), float(event["assumed_fill_inr"])
            stop = float(entry.get("stop_inr") or 0)
            target = float(entry.get("target_inr") or 0)
            risk = fill - stop if stop and fill > stop else None
            r_multiple = round((exit_fill - fill) / risk, 2) if risk else None
            if r_multiple is not None and r_multiple <= -0.8:
                kind = "stopped"
            elif target and exit_fill >= target * 0.999:
                kind = "target"
            else:
                kind = "closed"
            rows.append((
                entry["id"], entry["symbol"], str(closed.astimezone(IST).date()),
                (entry.get("research_meta") or {}).get("strategy_version"), r_multiple,
                float(event.get("net_realized_pnl_inr") or 0), kind, _stamp(closed),
            ))  # fmt: skip
        with self._connect() as conn:
            conn.executemany("INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    # ---------- grading ----------

    def grade(self) -> dict[str, int]:
        """Grade every view whose outcome is known and that has no grade yet."""
        with self._connect() as conn:
            pending = conn.execute(
                "SELECT v.*, o.ret_pct, o.runup_pct, o.drawdown_pct, o.known_at FROM views v "
                "JOIN outcomes o ON o.session=v.session AND o.symbol=v.symbol "
                "LEFT JOIN grades g ON g.session=v.session AND g.role=v.role AND g.symbol=v.symbol "
                "WHERE g.verdict IS NULL"
            ).fetchall()
            trades = {
                (row["session"], row["symbol"]): dict(row)
                for row in conn.execute("SELECT * FROM trades")
            }
        grades, lessons, counts = [], [], {"right": 0, "wrong": 0, "missed": 0, "flat": 0}
        for row in pending:
            trade = trades.get((row["session"], row["symbol"]))
            verdict, measure = verdict_for(dict(row), trade)
            counts[verdict] += 1
            grades.append((row["session"], row["role"], row["symbol"], verdict, measure,
                           row["known_at"]))  # fmt: skip
            if verdict in ("wrong", "missed"):
                lessons.append(("role", row["role"], row["session"], verdict,
                                lesson_text(dict(row), verdict, trade), row["known_at"]))  # fmt: skip
        with self._connect() as conn:
            conn.executemany("INSERT OR REPLACE INTO grades VALUES (?,?,?,?,?,?)", grades)
            conn.executemany(
                "INSERT OR IGNORE INTO lessons (scope, subject, session, kind, text, known_at) "
                "VALUES (?,?,?,?,?,?)",
                lessons,
            )
        return counts

    def refresh_stock_notes(self, history_db: Path, as_of: dt.datetime) -> int:
        """One note per stock: how it moves, how the desk fared, and any cooldown."""
        with self._connect() as conn:
            symbols = [row[0] for row in conn.execute("SELECT DISTINCT symbol FROM views")]
        notes = []
        for symbol in symbols:
            note = {"symbol": symbol, **self._behaviour(history_db, symbol, as_of)}
            note.update(self._desk_record(symbol, as_of))
            notes.append((symbol, _stamp(as_of), json.dumps(note)))
        with self._connect() as conn:
            conn.executemany("INSERT OR REPLACE INTO stock_notes VALUES (?,?,?)", notes)
            for symbol, _, raw in notes:
                note = json.loads(raw)
                if note.get("cooldown_until"):
                    conn.execute(
                        "INSERT OR IGNORE INTO lessons (scope, subject, session, kind, text, "
                        "known_at) VALUES ('stock', ?, ?, 'cooldown', ?, ?)",
                        (
                            symbol,
                            str(as_of.astimezone(IST).date()),
                            note["cooldown_reason"],
                            _stamp(as_of),
                        ),  # fmt: skip
                    )
        return len(notes)

    @staticmethod
    def _behaviour(history_db: Path, symbol: str, as_of: dt.datetime) -> dict:
        if not history_db.is_file():
            return {}
        with contextlib.closing(sqlite3.connect(history_db, timeout=10)) as history:
            rows = history.execute(
                "SELECT close_at, payload FROM sessions WHERE symbol=? AND kind='broker_export' "
                "ORDER BY date DESC LIMIT 60",
                (symbol,),
            ).fetchall()
        days = []
        for close_at, payload in rows:
            if dt.datetime.fromisoformat(close_at) > as_of:
                continue
            bars = json.loads(payload).get("bars") or []
            if bars:
                days.append(bars)
        if len(days) < 5:
            return {"sessions_studied": len(days)}
        days.reverse()
        ranges, gaps, moves = [], [], []
        for index, bars in enumerate(days):
            first = float(bars[0]["open"])
            high = max(float(bar["high"]) for bar in bars)
            low = min(float(bar["low"]) for bar in bars)
            ranges.append(100 * (high - low) / first)
            moves.append(100 * (float(bars[-1]["close"]) / first - 1))
            if index:
                gaps.append(100 * (first / float(days[index - 1][-1]["close"]) - 1))
        return {
            "sessions_studied": len(days),
            "avg_range_pct": round(statistics.mean(ranges), 2),
            "avg_abs_gap_pct": round(statistics.mean(abs(gap) for gap in gaps), 2),
            "up_close_share": round(sum(move > 0 for move in moves) / len(moves), 2),
        }

    def _desk_record(self, symbol: str, as_of: dt.datetime) -> dict:
        with self._connect() as conn:
            picks = conn.execute(
                "SELECT verdict, session FROM grades WHERE symbol=? AND role=? AND known_at<=? "
                "AND verdict IN ('right','wrong') ORDER BY session",
                (symbol, JUDGE, _stamp(as_of)),
            ).fetchall()
            trades = conn.execute(
                "SELECT exit_kind, r_multiple, session FROM trades WHERE symbol=? AND closed_at<=? "
                "ORDER BY closed_at",
                (symbol, _stamp(as_of)),
            ).fetchall()
        record: dict[str, Any] = {
            "judge_picks_graded": len(picks),
            "judge_picks_right": sum(row["verdict"] == "right" for row in picks),
            "paper_trades": len(trades),
            "paper_wins": sum((row["r_multiple"] or 0) > 0 for row in trades),
            "avg_r": round(
                statistics.mean(
                    row["r_multiple"] for row in trades if row["r_multiple"] is not None
                ),
                2,
            )  # fmt: skip
            if any(row["r_multiple"] is not None for row in trades)
            else None,
        }
        reason, since = None, None
        if len(trades) >= 2 and all(row["exit_kind"] == "stopped" for row in trades[-2:]):
            reason, since = "the last two paper trades were stopped out", trades[-1]["session"]
        elif len(picks) >= 3 and all(row["verdict"] == "wrong" for row in picks[-3:]):
            reason, since = "the judge's last three picks of it were wrong", picks[-1]["session"]
        if reason:
            until = dt.date.fromisoformat(since) + dt.timedelta(days=COOLDOWN_DAYS)
            if until >= as_of.astimezone(IST).date():
                record["cooldown_until"] = str(until)
                record["cooldown_reason"] = f"Cooling down until {until}: {reason}."
        return record

    def settle(self, reports_dir: Path, history_db: Path, book: dict | None,
               as_of: dt.datetime) -> dict:  # fmt: skip
        if as_of.tzinfo is None:
            raise ValueError("Settlement cutoff must be timezone-aware")
        views = self.ingest_reports(reports_dir, as_of)
        outcomes = self.record_outcomes(history_db, as_of)
        trades = self.record_trades(book, as_of) if book else 0
        counts = self.grade()
        notes = self.refresh_stock_notes(history_db, as_of)
        return {"views": views, "outcomes": outcomes, "trades": trades, "graded": counts,
                "stock_notes": notes}  # fmt: skip

    # ---------- what the agents see ----------

    def track_records(self, as_of: dt.datetime, last: int = 40) -> dict[str, dict]:
        records = {}
        with self._connect() as conn:
            for role in GRADED_ROLES:
                rows = conn.execute(
                    "SELECT verdict FROM grades WHERE role=? AND known_at<=? AND verdict!='flat' "
                    "ORDER BY session DESC LIMIT ?",
                    (role, _stamp(as_of), last),
                ).fetchall()
                verdicts = [row[0] for row in rows]
                if not verdicts:
                    continue
                right = verdicts.count("right")
                records[role] = {
                    "graded": len(verdicts),
                    "right": right,
                    "wrong": verdicts.count("wrong"),
                    "missed": verdicts.count("missed"),
                    "accuracy": round(right / len(verdicts), 2),
                }
        return records

    def context(self, roles: list[str], symbols: list[str], as_of: dt.datetime,
                options: dict) -> dict:  # fmt: skip
        """Everything the morning's agents may learn from, all known before ``as_of``."""
        known = _stamp(as_of)
        lessons: dict[str, list[str]] = {}
        notes: dict[str, str] = {}
        cooldowns: dict[str, str] = {}
        with self._connect() as conn:
            if options.get("lessons_in_prompts", True):
                for role in roles:
                    lessons[role] = [
                        row[0]
                        for row in conn.execute(
                            "SELECT text FROM lessons WHERE scope='role' AND subject=? "
                            "AND known_at<=? ORDER BY session DESC, id DESC LIMIT 5",
                            (role, known),
                        )
                    ]
            for symbol in symbols:
                row = conn.execute(
                    "SELECT note FROM stock_notes WHERE symbol=? AND as_of<=?", (symbol, known)
                ).fetchone()
                if not row:
                    continue
                note = json.loads(row[0])
                if options.get("stock_notes", True):
                    notes[symbol] = describe_stock(note)
                until = note.get("cooldown_until")
                if (
                    options.get("cooldown", True)
                    and until
                    and until >= str(as_of.astimezone(IST).date())
                ):
                    cooldowns[symbol] = note["cooldown_reason"]
        records = self.track_records(as_of)
        weights = {}
        if options.get("weight_specialists", True):
            for role in SPECIALIST_ROLES:
                record = records.get(role)
                if record and record["graded"] >= options.get("min_graded", 20):
                    # 50% accuracy keeps weight 1; the range is clamped to 0.5-1.5.
                    weights[role] = round(min(1.5, max(0.5, 2 * record["accuracy"])), 2)
        return {
            "lessons": {role: items for role, items in lessons.items() if items},
            "stock_notes": notes,
            "cooldowns": cooldowns,
            "track_records": records,
            "weights": weights,
        }

    # ---------- dashboard ----------

    def summary(self, as_of: dt.datetime) -> dict:
        with self._connect() as conn:
            recent = [
                dict(row)
                for row in conn.execute(
                    "SELECT scope, subject, session, kind, text FROM lessons "
                    "ORDER BY session DESC, id DESC LIMIT 25"
                )
            ]
            notes = [json.loads(row[0]) for row in conn.execute("SELECT note FROM stock_notes")]
            totals = dict(conn.execute("SELECT verdict, COUNT(*) FROM grades GROUP BY verdict"))
            sessions = conn.execute("SELECT COUNT(DISTINCT session) FROM grades").fetchone()[0]
        return {
            "as_of": _stamp(as_of),
            "sessions_graded": sessions,
            "totals": totals,
            "track_records": self.track_records(as_of),
            "lessons": recent,
            "stock_notes": sorted(notes, key=lambda note: note["symbol"]),
            "finetune": self.finetune_status(as_of),
        }

    # ---------- fine-tuning ----------

    def _good_examples(self, role: str, as_of: dt.datetime) -> list[dict]:
        """Stored answers from sessions where every graded call by this role was right."""
        with self._connect() as conn:
            try:
                calls = conn.execute(
                    "SELECT session, system, user, response FROM calls WHERE role=? "
                    "AND outcome='ok' AND response IS NOT NULL ORDER BY session",
                    (role,),
                ).fetchall()
            except sqlite3.OperationalError:
                return []  # The router has not logged anything yet.
            verdicts: dict[str, list[str]] = {}
            for row in conn.execute(
                "SELECT session, verdict FROM grades WHERE role=? AND known_at<=? "
                "AND verdict!='flat'",
                (role, _stamp(as_of)),
            ):
                verdicts.setdefault(row[0], []).append(row[1])
        good, seen = [], set()
        for row in calls:
            marks = verdicts.get(row["session"])
            if not marks or any(mark != "right" for mark in marks) or row["user"] in seen:
                continue
            seen.add(row["user"])
            good.append(dict(row))
        return good

    def finetune_status(self, as_of: dt.datetime) -> list[dict]:
        records = self.track_records(as_of, last=200)
        status = []
        for role in GRADED_ROLES:
            record = records.get(role, {"graded": 0, "accuracy": None})
            examples = len(self._good_examples(role, as_of))
            if (
                record["graded"] >= FINETUNE_MIN_GRADED
                and (record["accuracy"] or 0) >= FINETUNE_WEAK_ACCURACY
            ):
                advice = "Not needed: the base model is already right often enough."
            elif examples >= FINETUNE_MIN_EXAMPLES and record["graded"] >= FINETUNE_MIN_GRADED:
                advice = "Worth trying: export, tune, then route a tier to the tuned model."
            else:
                advice = (
                    f"Collecting: {examples} of {FINETUNE_MIN_EXAMPLES} right answers and "
                    f"{record['graded']} of {FINETUNE_MIN_GRADED} graded calls."
                )
            status.append({"role": role, "examples": examples, "graded": record["graded"],
                           "accuracy": record["accuracy"], "advice": advice})  # fmt: skip
        return status

    def export_finetune(self, role: str, folder: Path, as_of: dt.datetime) -> dict:
        """Write train/eval JSONL in chat format; the latest fifth of sessions is held out."""
        if role not in GRADED_ROLES:
            raise ValueError("Unknown role")
        examples = self._good_examples(role, as_of)
        if not examples:
            raise ValueError("No graded right answers stored for this role yet")
        sessions = sorted({example["session"] for example in examples})
        cut = sessions[int(len(sessions) * 0.8)] if len(sessions) >= 5 else None
        folder.mkdir(parents=True, exist_ok=True)
        counts = {"train": 0, "eval": 0}
        paths = {name: folder / f"{role}-{name}.jsonl" for name in counts}
        with (
            paths["train"].open("w", encoding="utf-8") as train,
            paths["eval"].open("w", encoding="utf-8") as held,
        ):
            for example in examples:
                line = json.dumps({
                    "messages": [
                        {"role": "system", "content": example["system"]},
                        {"role": "user", "content": example["user"]},
                        {"role": "assistant", "content": example["response"]},
                    ]
                })  # fmt: skip
                target = "eval" if cut and example["session"] >= cut else "train"
                (held if target == "eval" else train).write(line + "\n")
                counts[target] += 1
        return {"role": role, **counts, "files": {k: str(v) for k, v in paths.items()}}


def _stamp(moment: dt.datetime) -> str:
    """One timezone for every stored time, so text comparison is time comparison."""
    return moment.astimezone(IST).isoformat()


def verdict_for(view: dict, trade: dict | None) -> tuple[str, float | None]:
    """Right, wrong, missed or flat for one call, from the session and any paper trade."""
    role, stance = view["role"], view["stance"]
    ret, runup, dip = view["ret_pct"], view["runup_pct"], view["drawdown_pct"]
    traded = trade is not None and trade.get("r_multiple") is not None
    if role in SPECIALIST_ROLES:
        if stance not in ("positive", "negative") or abs(ret) < FLAT_PCT:
            return "flat", ret
        return ("right" if (ret > 0) == (stance == "positive") else "wrong"), ret
    if role == JUDGE:
        if stance == "pick":
            if traded:
                return ("right" if trade["r_multiple"] > 0 else "wrong"), trade["r_multiple"]
            if abs(ret) < FLAT_PCT:
                return "flat", ret
            return ("right" if ret > 0 else "wrong"), ret
        if runup >= BIG_MOVE_PCT and ret >= 1.0:
            return "missed", ret
        return "flat", ret
    if role == "risk-scout":
        stopped = trade is not None and trade.get("exit_kind") == "stopped"
        if stance == "low":
            return ("wrong" if stopped or dip <= -DEEP_DIP_PCT else "right"), dip
        if stance == "high":
            return ("right" if dip <= -DEEP_DIP_PCT else "flat"), dip
        return "flat", dip
    if role == "setup-planner":
        if stance == "none":
            return ("missed" if runup >= BIG_MOVE_PCT and ret >= 1.0 else "flat"), ret
        if traded:
            return ("right" if trade["r_multiple"] > 0 else "wrong"), trade["r_multiple"]
        return "flat", ret
    return "flat", ret


def lesson_text(view: dict, verdict: str, trade: dict | None) -> str:
    detail = json.loads(view.get("detail") or "{}")
    said = detail.get("summary") or detail.get("reason") or ""
    move = (
        f"it went {view['ret_pct']:+.1f}% open to close "
        f"(high {view['runup_pct']:+.1f}%, low {view['drawdown_pct']:+.1f}%)"
    )
    if trade and trade.get("r_multiple") is not None:
        ending = {
            "stopped": "was stopped out",
            "target": "hit its target",
            "closed": "was closed",
        }.get(trade["exit_kind"], "ended")
        move += f"; the paper trade {ending} at {trade['r_multiple']:+.1f}R"
    role, stance, symbol = view["role"], view["stance"], view["symbol"].replace("NSE:", "")
    if verdict == "missed":
        head = f"{view['session']} {symbol}: you passed ({stance}) but {move}."
        hint = " Ask what made the setup look weak and whether that signal held up."
    elif role == "risk-scout":
        head = f"{view['session']} {symbol}: you rated the risk {stance}, but {move}."
        hint = " Look harder for gap risk and events before calling a stock low risk."
    elif role == "setup-planner":
        head = f"{view['session']} {symbol}: you planned {stance}, but {move}."
        hint = " Check whether this setup suits how this stock usually moves."
    elif role == JUDGE:
        head = f"{view['session']} {symbol}: you picked it ({detail.get('rating', 'pick')}), but {move}."
        hint = " Weigh the specialists who were right recently more than the loud ones."
    else:
        head = f"{view['session']} {symbol}: you were {stance}, but {move}."
        hint = " Note which piece of your evidence misled you."
    if said:
        head += f' You said: "{said[:140]}".'
    return (head + hint)[:420]


def describe_stock(note: dict) -> str:
    parts = []
    if note.get("avg_range_pct") is not None:
        parts.append(
            f"over {note['sessions_studied']} sessions it moves {note['avg_range_pct']}% "
            f"high to low a day, gaps {note['avg_abs_gap_pct']}% on average and closes up "
            f"{round(100 * note['up_close_share'])}% of days"
        )
    if note.get("judge_picks_graded"):
        parts.append(
            f"judge picks right {note['judge_picks_right']} of {note['judge_picks_graded']}"
        )
    if note.get("paper_trades"):
        parts.append(
            f"paper trades won {note['paper_wins']} of {note['paper_trades']}"
            + (f" (average {note['avg_r']:+.2f}R)" if note.get("avg_r") is not None else "")
        )
    if note.get("cooldown_reason"):
        parts.append(note["cooldown_reason"])
    return ("; ".join(parts) or "no history studied yet")[:400]


def store_for(config_path: Path) -> LearningStore:
    return LearningStore(config_path.parent / "learning.sqlite")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("data/observatory/pipeline.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("settle", help="Grade the agents on completed sessions and paper trades")
    sub.add_parser("status", help="Track records, recent lessons and fine-tune readiness")
    export = sub.add_parser("finetune-export", help="Write chat JSONL from right answers")
    export.add_argument("--role", required=True, help="A role name, or 'all'")
    export.add_argument("--out", type=Path, help="Folder; defaults to <data>/finetune")
    args = parser.parse_args(argv)
    from decision_pipeline import DailyCoordinator, read_book

    coordinator = DailyCoordinator(args.config)
    store = store_for(args.config.resolve())
    now = dt.datetime.now(IST)
    try:
        if args.command == "settle":
            book = None
            try:
                book = read_book(coordinator.path("book"))
            except (OSError, ValueError, sqlite3.Error):
                book = None  # No forward book yet: grade on market moves alone.
            result = store.settle(
                coordinator.path("reports_dir"), coordinator.path("history_db"), book, now
            )
        elif args.command == "status":
            result = store.summary(now)
        else:
            folder = args.out or args.config.resolve().parent / "finetune"
            roles = GRADED_ROLES if args.role == "all" else (args.role,)
            result = {"exported": [], "skipped": []}
            for role in roles:
                try:
                    result["exported"].append(store.export_finetune(role, folder, now))
                except ValueError as exc:
                    if args.role != "all":
                        raise
                    result["skipped"].append({"role": role, "reason": str(exc)})
    except (ValueError, OSError, sqlite3.Error) as exc:
        print("LEARNING_BLOCK: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Session engine

`scripts/engine.py` is a deterministic, clock-driven loop for one exchange
session. It drives the same virtual journal as `scripts/paper_book.py`. It has
no network code, no broker order path and no live mode.

Contents: [Parts](#parts), [Exits](#exits), [Safety behaviour](#safety-behaviour),
[Replay CLI](#replay-cli), [Not yet built](#not-yet-built).

## Parts

| Part | Role |
| --- | --- |
| `Engine` | Phases `PRE_OPEN → SCANNING ⇄ IN_TRADE → SQUARING_OFF → CLOSED`; `HALTED` is sticky. |
| `RiskGate` | Fail-closed entry checks: halt flag, entry window, allowlist, spread, stop/target sanity, order rate. Exits are never blocked. |
| `PaperBroker` | Only broker implementation. Delegates fills and caps to `paper_book.fill`. |
| `Strategy` | Protocol. Returns an `EntryIntent` or `None`; it never places orders. |
| `EngineStore` | SQLite persistence: `book` (same table `paper_book.py` reads), `engine_state` snapshot and an append-only `engine_log`. |
| `OpeningRangeBreakout` | The repository's ORB test rule as a strategy. A harness, not an edge. |

The caller supplies `now` to `on_quote` and `tick`. Replay passes the bar-close
time; a forward runner would pass the wall clock. Order IDs are derived from the
session date, symbol and entry number, so a retried submission returns
`duplicate` instead of a second fill.

## Exits

Exits are checked before entries on every quote, long positions only:

1. Stop first. If an interval's low reaches the stop, it is a stop even when the
   high also reached the target. A gap below the stop fills at the open.
2. Target, when the stop was not reached.
3. Square-off at the session's `flat_by` time at the bid.

A rejected exit halts the engine for manual review.

## Safety behaviour

- Quotes that are stale, from the future, crossed, non-positive, unsourced or
  not allowlisted are logged as `quote_rejected` and never reach the strategy.
- `tick` halts entries when no valid quote has arrived within
  `heartbeat_timeout_seconds`, and raises `manual_attention` if positions are open.
- `reconcile` compares broker and engine positions; a mismatch halts entries.
- `INDIA_TRADE_LAB_HALT=1` blocks entries in both the gate and the journal.
- `EngineConfig.digest()` is stored on every order record. `restore` refuses a
  snapshot made under a different configuration or session date.
- The journal's own caps (per-trade risk, daily loss, position limit, trade
  count, loss streak, drawdown) still apply behind the gate.

## Replay CLI

```bash
python3 SKILL_DIR/scripts/engine.py replay \
  --bars SKILL_DIR/assets/synthetic-bars.csv \
  --sessions SKILL_DIR/assets/synthetic-sessions.json \
  --symbol NSE:DEMO --date 2026-10-19 --book PROJECT/engine-replay.sqlite \
  --cash 100000 --risk 250 --daily-loss 750 --position-cap 15000 \
  --target-r 2 --fee-bps 5 --fee-flat 10 --slippage-bps 5
```

Bars become quotes stamped at bar close with a symmetric `--spread-bps`
(default 4). Entries fill at the ask on the confirmation bar, which differs from
`india_research.py replay-orb`; do not compare their numbers as equivalent.
The book path must be new. `paper_book.py --book … status` reads the result.

## Not yet built

Treat these as planned, untested work:

- A live quote feed adapter and a wall-clock runner process.
- Forward paper entries need per-entry pre-trade evidence (see
  [guardrails.md](guardrails.md)); no strategy here produces it.
- Chat alerts. The default notifier writes JSON lines to stderr.
- Partial exits, trailing stops, multi-symbol replay and mark-to-market P&L.
- Any sandbox or live broker. Live execution remains a separate future project;
  see [connections.md](connections.md).

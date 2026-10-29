# Trade tools and the desk agent

Seven tools follow a trade from the scan to the square-off, for NSE cash equity,
long only, on completed five-minute bars in IST. Each one can be run by hand, and
the desk agent runs the intraday ones by itself during the session. None of them
places an order: the paper autopilot records virtual fills under the paper book's
rules, and there is no real-order path.

| Tool | Job | Reads | Writes |
| --- | --- | --- | --- |
| `entry_timer.py` | First completed bar that closes above the opening range (09:15-09:30) or your level | Kite five-minute bars | `desk/entry.json` |
| `exit_planner.py` | Stop and target before the entry; square-off time | `desk/entry.json` | `desk/plan.json` |
| `time_machine.py` | Odds of target first, stop first or neither, from replays and history | `desk/plan.json`, `history.sqlite` | `desk/timemachine.json` |
| `trade_check.py` | Budget (shares) and risk (PASS or BLOCK) against the paper book | `desk/plan.json`, the paper book | `desk/ticket.json` |
| `price_alerts.py` | Rings once on a stop, target, percent move, time or the opening bell | `desk/alerts.json`, Kite quotes | `desk/alerts-log.jsonl` |
| `results_analyst.py` | The latest filed quarter from NSE's XBRL, against the quarter before and a year earlier | NSE results filings | `desk/results-<SYMBOL>.json` |
| `insider_tracker.py` | SEBI insider-trading disclosures: who bought, sold or pledged | NSE PIT disclosures | `desk/insiders-seen.json` |

All tools take `--config` (default `data/observatory/pipeline.json`) before the
subcommand. Pin the clock with `--now "YYYY-MM-DD HH:MM"` (IST) to replay a day.

## One trade, by hand

```bash
python3 scripts/entry_timer.py check INFY --write          # TRIGGERED 09:45 IST at ₹1,612.40
python3 scripts/exit_planner.py plan --write               # stop at the range low, 2R target
python3 scripts/time_machine.py run --write                # 10,000 replays, seed 19
python3 scripts/trade_check.py --write                     # PASS: 31 shares, ₹49,980
python3 scripts/price_alerts.py add --from-plan            # stop, target, 15:15 square-off
```

## Entry Timer

The opening range is the 09:15, 09:20 and 09:25 bars (`--or-minutes`, 5-60). The
trigger is the first completed bar after it that closes above the range high, or
above `--level` with `--setup level`. A wick above is not an entry, a close
exactly at the level is not above it, and a bar still forming never counts. With
`--min-volume-x 1.5` the trigger bar also needs 1.5 times the range bars' average
volume. No trigger by the entry cutoff (14:30 on a normal day) is EXPIRED.

`watch SYMBOL` prints one line per closed bar and exits 0 on the trigger. Saved
Kite candles (`--bars file.json`) replace the network for replays and tests.

## Exit Planner

| Stop | Where |
| --- | --- |
| `or-low` (default) | The opening-range low, as `orb-v1` uses |
| `or-mid` | The range midpoint |
| `price:X` | Your price |
| `pct:X` | X% under the entry (0-20) |
| `atr:K` | K times the 14-bar ATR of today's bars up to the entry |

Stops round down and targets round up to 5 paise; check the exchange tick size
before using a price outside paper research. The target is `target_r` from
pipeline.json (2R by default), `1.5R` or `price:X`. Refused: a stop at or above the
entry, a target at or below it, a stop under 0.15% away (the desk's noise floor),
and an entry at or after the entry cutoff. Square-off is the session's `flat_by`.

## Time Machine

1. **Pool.** Every complete stored session of the stock before the plan's date
   (75 bars, 09:15-15:30) from `history.sqlite`, the same history the tournament
   uses. It needs at least 20; load history in Setup first.
2. **Replay.** From the entry bar to the square-off, each bar is a past bar from
   the same time of day (plus or minus 2 bars, `--window`), drawn at random and
   scaled to the current price. Stop first, then target; a bar touching both is
   a stop, and a gap below the stop exits at the bar's open.
3. **Odds.** Target first, stop first, neither (open at the square-off) and green
   (target first or above the entry), the price spread at the square-off, average R
   and a fan of prices bar by bar. Seed 19 by default, so a run repeats exactly.
4. **History.** The plan's own opening-range rule re-run on each past session:
   how often it fired and what really happened.
5. **Verdict.** A 2R target only has to come first in 33% of the replays that
   reach a side to break even (1 in 1 + R). Within 5 points: close to a coin flip
   (1R) or close to break-even; 5-15 points: leans; 15 or more: strongly. Costs
   (fees and slippage both ways, for the size the book would take) are then
   charged in R.

It is built from the stock's own past sessions. Results, news, circuit limits
and index events can do things those sessions never did.

## Trade check (budget and risk)

Size is the most whole shares that fit every limit the paper book enforces: loss
at the stop including slippage, the entry fee and the exit-fee reserve; largest
position; cash after open reserves; and the day's loss limit after realised losses
and open planned losses. It says which limit decided it, and sizes from a fresh
higher price (`--price`, `--price-time`) when the price has run up.

It BLOCKs on: the halt switch, a paused book, the loss-streak or drawdown stop,
the trade or open-position cap, a stock already held or a prior-day position, a
stock not on the book's list, a plan for another day, before 09:30 or after the
entry cutoff, a stop not below the entry or a target not above it, reward:risk
under `min_reward_risk` (1.0), or a learning cooldown on the stock.

## Price alerts

| Type | Rings when | Again |
| --- | --- | --- |
| `above`, `target` | Last price at or above the level | After `reset` |
| `below`, `stop` | Last price at or below the level | After `reset` |
| `pct_move` | Moved `pct`% from the previous close (`up`, `down` or `any`) | Next day |
| `time` | The IST clock passed `at` on a trading day | Next trading day |
| `opening_bell` | NSE is open | Next trading day |

A rule with a date is watched on that date only. Prices are Kite last-traded
prices; when they are unavailable, time alerts still ring. With
`"alerts": {"email": true}` rang alerts are emailed through the SMTP settings.
A price can pass a level between two checks; an alert is a fact, not an order.

## Filings

**Earnings.** `results_analyst.py SYMBOL` lists the company's quarterly filings on
NSE, takes the newest XBRL (consolidated when filed) and reads revenue, profit
before tax, net profit, EPS, finance costs, depreciation, other income and
exceptional items for the quarter, the quarter before and a year earlier. Margins
are derived and say so. It flags exceptional items and other income above a
quarter of profit before tax. Segment figures are ignored; a DOCTYPE or entity in
the XBRL is refused.

**Insiders.** `insider_tracker.py recent --days 7` reads SEBI PIT disclosures:
person and category, buy, sell or pledge, how, shares, value, trade dates and the
days to disclose. Disclosures are due within two trading days to the company and
two more to the exchange. They describe trades already made.

The 08:40 scan reads both for the candidates: net market buying by promoters,
directors or key managers in the last 30 days adds 1 point; net selling or a new
pledge subtracts 0.5. The latest quarter goes to the specialists as `#results`,
the filings as `#insiders`, and daily chart setups (20-day closing high, bull flag,
reclaimed 20-day average, oversold bounce) as `#setups`, worth up to 1 point.

## The desk agent (on the loop)

`trade_desk.py` runs inside the session worker (`market_service.py`) on every
tick, after the coordinator and the autopilot, for each of the judge's picks:

1. Entry Timer on today's bars (the worker's refreshed bars file first, else Kite).
2. On a new trigger, once per stock per day: the Exit Planner, the Time Machine
   and the trade check. The trigger is logged as an alert, with the check verdict
   and the odds line.
3. Price alerts for the day.

It writes `desk/<date>/<SYMBOL>.json` and `desk/today.json`, which the dashboard's
Desk page shows. It records nothing in the paper book.

Two hooks change what the autopilot does, both downgrade only:

- **Time Machine gate.** Before recording an entry, the autopilot replays the
  ticket's entry, stop and target (`timemachine.replays`, 5,000 by default). A
  verdict that leans or strongly leans toward the stop skips the entry. Without
  20 stored sessions the entry goes through, unless `require_history` is true.
- **Alerts on entries.** Every recorded paper entry gets a stop, target and
  square-off alert (`alerts.on_entries`).

The morning picks are also added to the paper book's stock list (logged in
`allowlist_changes`), so the book does not refuse the scan's choices.

```json
"trade_desk": {"enabled": true},
"timemachine": {"enabled": true, "replays": 5000, "require_history": false},
"alerts": {"email": false, "on_entries": true},
"scan": {"insiders": true, "results_for": 12}
```

## Data and limits

- Kite: today's five-minute candles and quotes, with your daily login, paced to
  Kite's limits. Nothing writes to Kite.
- NSE: the results and insider-disclosure endpoints on nseindia.com. NSE may
  refuse scripted requests; the tool then says the source is unavailable and does
  not evade the refusal.
- Not tested against live Kite or NSE from the development sandbox; the tests use
  saved and synthetic data.

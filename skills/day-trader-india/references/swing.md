# Swing desk: volume-confirmed swing trades

Runtime: `scripts/swing.py`. Set with `"swing"` in `pipeline.json`; on by default.

The swing desk holds a trade for up to five sessions. It runs beside the
intraday desk with its own paper book (`swing.sqlite`, ₹1 lakh by default), so
the two track records never mix. It trades only when volume agrees with price,
on the daily candles the nightly market scan stores for every F&O stock.

## Setups (long only)

| Setup | Price | Volume | Stop |
| --- | --- | --- | --- |
| `vol-breakout-v1` | Closes above the 20-day high, in the top 40% of its range, above the 50-day average and within 10% of the 20-day | At least `min_vol_ratio` (2x) the 20-day average | The breakout day's low |
| `pocket-pivot-v1` | An up close within 5% above a 10-day average, with the 50-day average rising | More than any down day's volume in the last 10 sessions | The lowest of the last three lows |
| `dryup-pullback-v1` | An uptrend pulls back 3% or more to near the 20-day average, holds the 50-day, then closes above the prior day's high | Pullback volume at most 70% of normal, then the reversal at 1.5x the pullback's | The pullback's low |

On-balance volume above its own 20-day average is shown as "OBV rising". It is
information for you, not a condition.

**Skipped** when:

- the stock is up more than 15% in five sessions (a volume spike there is often a
  climax);
- the stop is under 1% away (overnight noise) or over 8% away (too much risk);
- traded value is under the liquidity floor;
- results, a board meeting or another NSE event falls within `event_window_days`
  (7);
- the candles are not from the last session.

## A swing trade, step by step

| When (IST) | What happens |
| --- | --- |
| 16:10, after the close | `market_scan.py nightly` stores today's daily candle. `swing.py tournament` re-tests every setup on the stored history. `swing.py scan` writes the candidates for the next session |
| After 09:15, once | The session worker enters the best candidates that use a proven setup, at most `max_new_per_day` (2). It skips a stock that gapped up more than `max_gap_up_pct` (3%) or opened at or below the stop |
| Every worker tick | It exits at the stop (or the moved stop) and at the target |
| From 15:20 | After the close reaches +1R, the stop moves to breakeven plus costs. After +1.5R, it trails under the last two days' lows. A trade held `max_hold_days` (5) sessions is closed |

Entries are recorded at the ask. Each entry carries version-1 pre-trade evidence
built from checks code ran, each with its source:

- the Kite instrument list;
- F&O membership (NSE's ASM and GSM frameworks exclude F&O securities);
- Kite's circuit limits and depth;
- the NSE event calendar;
- the setup and its stop and target.

Every paper-journal limit applies at that moment. Entries also get a stop and
target alert, removed when the trade closes.

A stop is a plan, not a guarantee. An overnight gap can open below the stop and
lose more than the planned risk.

## Swing Monte Carlo and the scenario simulator

`scripts/swing_machine.py` replays the next few sessions 5,000 times (seed 19)
from the stock's own last 250 daily candles. Each day is drawn as ratios to the
previous close, so overnight gaps are as large and as frequent as the stock's
real ones. The replay applies the desk's exit rules:

- a gap through the stop exits at the open;
- otherwise the stop, then the target;
- breakeven after +1R, a two-day-low trail after +1.5R, a time exit at the end.

Every exit is valued in rupees for the shares the swing book would buy, after
fees, delivery charges and slippage on both sides.

It reports:

- the odds of target, stop (split into stop, gap stop and trailing stop) and time
  exits;
- the cumulative chance of target and of stop by session 1, 2, and so on to N;
- the rupee distribution: expected value, median, middle half, 5th and 95th
  percentiles, the average of the worst 5%, the worst outcome, and the chance of
  a profit;
- a histogram.

The scan attaches this to every candidate. With `require_positive_odds` (on by
default), a candidate whose simulation expects a loss after costs is not entered.

On the dashboard, the Swing desk card has a scenario simulator. Load a
candidate, or type any stock the scan stores, then change the entry, stop,
target or holding days and replay. The command is
`python3 scripts/swing.py simulate INFY --entry 1612 --stop 1570 --target 1696 --days 5`.

The simulation is built from the stock's history, not a forecast: results and
shocks can do what that history never did.

## Proof first

`swing.py tournament` replays each setup on every stored stock:

- entry at the next session's open, plus slippage;
- skipped if the stock gaps up too far or opens below the stop;
- on a day that touches both the stop and the target, the stop counts first;
- a gap through the stop fills at the open;
- delivery costs on both sides.

It judges each setup at **double** costs, with the intraday tournament's rules:

- at least 30 trades;
- a net profit;
- a profit factor of 1.15 or more;
- profitable in most periods, including the latest.

With `require_proven` (default true), only setups that pass are entered.
Others appear as watch-only candidates. If none pass, the swing desk sits out.
The tournament models one position per stock at a time, not the book's
cross-stock limits.

## Costs

Delivery trades pay STT of 0.1% on both the buy and the sell, plus exchange,
stamp duty and GST, and a DP charge on the sale. Defaults are 12 basis points a
side plus ₹20 an order, and 5 basis points of slippage. That is much more than
an intraday round trip, which is why the setups need larger moves.

## The swing book

Create it in Setup → Create the paper book, or with
`python3 scripts/swing.py create-book`. The defaults:

| Limit | Value |
| --- | --- |
| Virtual cash | ₹1,00,000 |
| Risk per trade | ₹500 (0.5%) |
| Open risk plus today's losses | ₹1,500 |
| Largest position | ₹25,000 |
| Open positions | 3 |
| New entries a day | 2 |
| Loss streak stop | 3 |
| Drawdown stop | ₹5,000 |

It is a forward paper book of style `swing`, the only style that may hold a
position overnight. It is never overwritten, and its journal is sealed with a
checksum like the intraday book. The stock list grows as candidates are
entered, and each addition is logged in `allowlist_changes`.

```json
"swing": {
  "enabled": true, "book": "swing.sqlite", "max_hold_days": 5, "max_new_per_day": 2,
  "require_proven": true, "min_vol_ratio": 2.0, "max_gap_up_pct": 3.0,
  "event_window_days": 7, "target_r": 2.0,
  "fee_bps": 12.0, "fee_flat_inr": 20.0, "slippage_bps": 5.0
}
```

Volume and price describe participation; they do not predict prices. Nothing
here is a recommendation, and no result here is evidence of future returns.

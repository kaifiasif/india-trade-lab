# Strategies, filters, managed exits and the tournament

No rule can guarantee a day without losses. This desk is designed to keep
losses small and rare, and to trade only rules that have shown an edge after
costs on your own history. When none has, it does not trade.

## Strategies (`scripts/strategies.py`)

Long only, cash equity, on completed five-minute bars.

| Name | Entry | Initial stop |
|---|---|---|
| `orb-v1` | First close above the high of the first 15 minutes | Opening-range low |
| `vwap-pullback-v1` | On a day that already broke out above the opening range: a pullback to the session VWAP, then a completed bar that closes back above VWAP, higher than the bar before | Just below the pullback low |

The target is `target_r` (default 2) times the risk. Entries stop at the
session's entry cutoff.

## Loss-avoidance filters

These apply to every entry, using daily values from stored sessions:

- Skip when the daily trend is down: the close is below the 20-day average, and
  that is below the 50-day average.
- Skip when daily RSI(14) is 75 or more, because the move is stretched.
- Skip when the stop is less than 0.15% away (noise) or wider than one daily ATR
  (the position would be too small to matter).

`strategy.filters: false` turns them off. Only the offline tests do that.

## Managed exits

These are worked out from the bars completed since entry:

- **Breakeven:** after +1R, the stop moves to the entry plus the round-trip cost.
  A winner that turns around can no longer become a loss.
- **Trailing:** after +1.5R, the stop trails one R below the highest high.
- **Time stop:** if the trade hasn't reached +0.5R within an hour (12 bars), it
  is closed. Money stuck in a dead trade is risk with no reward.
- The original stop, the target and the 15:15 square-off still apply.

## Tournament (`scripts/tournament.py`)

```bash
python3 scripts/tournament.py --config data/observatory/pipeline.json
```

The tournament replays every strategy over the stored broker-export sessions,
using the same signals, filters and exits. The fills are deliberately
pessimistic:
- entries fill at the next bar's open plus slippage;
- when a bar touches both the stop and the target, the stop is assumed hit first;
- a gap through the stop fills at the bar's open, not at the stop;
- costs are charged on both sides.

A strategy is **eligible** only if, at **double** costs, all of these hold:
- at least 30 trades;
- a positive net result;
- a profit factor of at least 1.15;
- a profit in at least 2 of 3 chronological periods;
- no loss in the most recent period.

The result goes to `strategy-scorecard.json`. The Oracle schedule re-runs it
every evening after the history sync, and a scorecard older than 7 days counts
as missing.

Entries use only eligible strategies. With none eligible, the pre-market report
says **sit_out**, no model calls are spent, and the coordinator refuses every
entry with the reason. Exits are never blocked.

`strategy.require_proven: false` lets every enabled strategy trade the paper
book, to collect forward evidence before the history is long enough. That is a
deliberate choice to pay for information. Never use it with real money.

## How the agents use this

1. The tournament, written in code, decides which strategies may trade.
2. Six specialists assess the filtered pool.
3. Code picks the finalists by specialist support and score (`selection.finalists`,
   up to 10). For each one the judge spawns two **sub-agents**:
   - a **risk scout**, which rates what could make a long lose today as low,
     medium or high;
   - a **setup planner**, which picks the proven strategy that fits, or none.
4. The judge picks only finalists, and names a proven strategy for each.
5. Code then drops any pick the risk scout rated high, or that the setup planner
   found no setup for. Agents can narrow the list; they can never widen it.
6. During the session, the coordinator trades each pick only with the strategy
   the judge named. The paper autopilot records the entry and every managed exit.

Model calls per morning are 6 + 2 per finalist + 1, which is 27 with ten
finalists. The judge then picks up to `max_candidates` (1–10) of them.

## Settings (`pipeline.json`)

```json
"strategy": {
  "require_proven": true,
  "enabled": ["orb-v1", "vwap-pullback-v1"],
  "max_scorecard_age_days": 7,
  "managed_exits": true,
  "filters": true
},
"selection": {"finalists": 10}
```

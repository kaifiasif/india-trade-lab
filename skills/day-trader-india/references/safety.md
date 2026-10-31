# Safety rules

Runtime: `scripts/safety.py`, the paper journal (`paper_book.py`, `guardrails.py`) and
each desk's entry path. Every rule can only stop or close a trade. Set with
`"safety"` in `pipeline.json`.

| Rule | Intraday book | Swing book |
| --- | --- | --- |
| No entries on stale or incomplete data | Quotes older than 2 minutes and missing or out-of-order five-minute bars block the call (DATA_BLOCK) | The Kite quote's own timestamp must be under 2 minutes old; candidates need the last session's candle |
| No entries in high volatility or illiquid conditions | India VIX at or above `max_india_vix` (22), or the Nifty 50 `max_index_move_pct` (2%) from its previous close, blocks new entries. So does no reading in `guard_max_age_seconds` (180). Spreads over 20 bps and thin traded value are refused | Same guard, same spread and liquidity floors |
| No duplicate positions | One position per stock per book; a stock held in the swing book cannot be entered intraday | The reverse |
| Stop and target before entry | The journal refuses a forward entry without both | Same |
| Stop first when a candle touches both | Tournament, Time Machine and replay engine | Swing tournament and swing Monte Carlo; a gap through the stop fills at the open |
| Reward after costs | The journal refuses an entry whose reward at the target, after round-trip costs, is below its loss at the stop. The desks need `min_net_reward_risk` (1.5x) | Same, with delivery costs |
| Daily loss limit | Realised loss plus open planned loss may not exceed it | Same (it caps total open risk) |
| Close intraday positions by the deadline | `auto_square_off`: every tick from `flat_by` (15:05 from 3 Aug 2026, for the closing auction; 15:15 before), the worker closes every intraday paper position, whatever the autopilot setting | Swing positions are held by design, up to 5 sessions |
| Recover after a restart | The worker timer catches up after a reboot until 15:45. On its first tick the worker verifies both journals' checksums, closes overdue intraday positions at the first valid quote and writes `recovery.json`. State files are written atomically | Swing tracking is rebuilt from the journal |

A tampered journal (checksum mismatch) is reported and left untouched.

```json
"safety": {
  "market_guard": true, "max_india_vix": 22.0, "max_index_move_pct": 2.0,
  "guard_max_age_seconds": 180, "min_net_reward_risk": 1.5, "auto_square_off": true
}
```

The 1.5x rule matters most for swing trades. With delivery costs, a 2R target on a
small position can return well under 1.5 times its risk, and those trades are
skipped.

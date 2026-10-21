# Risk process for Indian paper trading

Contents: [Losses](#loss-free-trading-is-not-achievable), [Practice limits](#initial-virtual-practice-configuration), [Entry review](#before-an-entry-go--no-trade--data-block), [Evaluation](#test-before-considering-any-live-project).

## Loss-free trading is not achievable

State this once when the user asks to avoid every loss: no model, signal,
indicator or stop-loss guarantees that. Stop fills can be worse across gaps;
some securities cannot be exited when desired. Preserve the goal of limiting
avoidable losses without implying that controls remove market risk. If the
user requires zero trading-capital loss, keep the work at virtual trading.

SEBI's dated study is useful context, not a forecast for this user:
https://www.sebi.gov.in/media-and-notifications/press-releases/jul-2024/sebi-study-finds-that-7-out-of-10-individual-intraday-traders-in-equity-cash-segment-make-losses_84948.html

Do not label that 2024 finding the latest study without checking.

## Initial virtual practice configuration

These are illustrative training limits, not a recommendation for deploying
the user's real savings or an assurance of safety.

| Setting | Initial practice value |
| --- | --- |
| Virtual starting cash | ₹100,000 |
| Planned loss per trade, including estimated costs | ₹250 |
| Daily loss budget including planned risk on open positions | ₹750 |
| Position entry cost cap | ₹15,000 |
| New entries per day / simultaneous positions | 3 / 2 |
| Stop after consecutive losing closed trades | 2 |
| Pause after closed-trade drawdown from peak | ₹2,000 |
| Instruments | Verified liquid cash equities; whole shares, long only |

The journal enforces these configured limits, cash availability, stale quotes,
unique event IDs and explicit fee/slippage assumptions. Loss-streak/drawdown
stops persist across days. It has no automatic reset or resume command.
`pause --reason TEXT` blocks buys and leaves sells available. Review results
before changing policy; never erase losses or restart a book to improve a record.
For older books without version-2 controls, preserve them as archived records
and initialize a separate, explicitly linked practice period.

Closed-trade drawdown is not current mark-to-market drawdown. An open position
may be losing more than its recorded stop risk. The journal has no streaming
quotes or automatic stop execution. Review marked prices separately; do not
describe the journal as a protective trading system.

## Before an entry: GO / NO TRADE / DATA BLOCK

Read the current quote, book state, instrument master and current exchange
information. Missing material evidence means DATA BLOCK, never assumed clear.
These checks require evidence review; not all are executable code gates.

| Check | Evidence and decision |
| --- | --- |
| Market and instrument | Verified NSE/BSE cash-equity mapping, correct segment/tick size, known trading session and available product. Index spot levels are not tradable shares. |
| Calendar and time | Date-specific exchange session/holiday source; include special sessions. Entry and time-exit policy must be explicit. |
| Surveillance/restrictions | Check ASM/GSM, trade-to-trade, illiquid call auction, suspension and price bands for the selected security. Default practice policy excludes restricted/unclear names; this is a policy, not a claim every such trade is forbidden. |
| Quote quality | Original source timestamp, current bid/ask and usable volume; reject stale, crossed, zero or incomplete data. An LTP alone is not executable liquidity. |
| Spread/participation | Set a written spread ceiling and participation assumption before testing, tailored to the instrument. Avoid sizing beyond realistic liquidity. No default percentage proves safety. |
| News/events | Current exchange/company announcements, results/board meeting/corporate action and relevant market events. Unknown event status blocks the entry. |
| Entry rule | Only completed-bar conditions; signal time and quote time are separate. A prior breakout that failed is not a fresh signal. |
| Stop/target | A written invalidation level, target and time exit; estimate reward and loss after both sides' fees/slippage. If net reward does not meet the predeclared rule, skip. |
| Portfolio | Sum risk across open positions; review sector/issuer overlap and correlated exposure. Two bank stocks are not independent diversification. Set portfolio and sector limits before a test. |
| Behaviour | No averaging down, martingale, revenge trades, moving stops away, chasing gaps or increasing size to recover losses. Respect pause/loss-streak/drawdown stops. |

Quote freshness and accounting checks are code-enforced by the paper journal.
The supplied scanner/replay does not automatically fetch or enforce current
surveillance, news, circuit, spread, sector or correlation facts. Never say
these checks have passed without obtaining and reviewing the evidence.

Official surveillance sources:

- https://www.nseindia.com/regulations/exchange-market-surveillance-actions
- https://www.nseindia.com/reports/asm
- https://www.nseindia.com/static/regulations/graded-surveillance-measure

## Test before considering any live project

1. Specify one strategy and cost assumptions in version control. The supplied
   15-minute long opening-range breakout is a test harness, not a proven strategy.
2. Use an instrument universe known at each historical date. Today's index
   members alone introduce survivorship bias. Handle splits/corporate actions
   consistently; do not combine adjusted and unadjusted OHLC.
3. Keep training, validation and unseen periods separate. Trying many settings
   and reporting only the winner is overfitting. Record every trial.
4. Run explicit fees, slippage, adverse gaps and at least the supplied doubled
   cost scenario. Missing-data and rejected-session counts belong in the report.
5. Report sample size, net expectancy, profit factor, time in market and drawdown
   alongside win rate. Closed-trade drawdown is a lower-fidelity measure than a
   full mark-to-market equity curve; disclose the difference.
6. Compare against a suitable buy-and-hold/cash baseline at comparable exposure
   with the same costs and period. This comparison is not built into the tool yet.
7. Start a separate forward paper record with real observation timestamps and
   no hindsight edits. A useful initial review might follow 30 sessions and
   50 trades; neither number establishes reliability or mandates a live switch.
8. A losing/noisy test means pause, revise transparently or abandon the strategy.
   Do not invent a guarantee by adding more indicators or a model confidence score.

Any future live execution requires separate explicit work on deterministic
risk controls, broker-supported exits, reconciliation, kill switches and
current broker/exchange requirements. This skill provides no live order path.

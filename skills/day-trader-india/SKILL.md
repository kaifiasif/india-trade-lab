---
name: day-trader-india
description: "Indian NSE/BSE cash-equity research and paper trading: read-only Kite/Upstox historical data, completed-bar scans, cost-aware historical replay, point-in-time fundamental screening, portfolio review and a virtual-INR journal with deterministic risk limits. Use for Indian stock trading practice, broker-data setup, strategy evaluation or adapting the two Jakeschincariol trading repositories. No live execution or loss-free promise."
---

# India Market Trader — paper first

Build an Indian-market workflow around verified data and explicit limits. This
is a new India-specific skill inspired by both Jakeschincariol trading projects,
with standalone Indian data/research tools. It does not route live orders.
Read [source-comparison.md](references/source-comparison.md) when comparing
the projects or explaining what was adapted and what stays US-specific.

## Coordinate specialist agents

Read [agent-workflow.md](references/agent-workflow.md) when using the specialist
pack. Generate a dependency plan with `scripts/agent_workflow.py`, delegate
independent evidence reviews when the host supports subagents, and validate
the structured handoffs. Use sequential role reviews if delegation is unavailable
and state that limitation. Keep risk and reviewer vetoes; never turn consensus
into broker permission. Native specialist profiles return findings only; the
coordinator runs tools and records only explicitly requested virtual fills.

## Set expectations and choose the task

- If the user asks for no losses, explain once: trading cannot be made loss-free.
  Stops, models and backtests do not guarantee an exit price or future returns.
  Keep the requested practice virtual; never frame a test pass as permission
  to risk real money. Say NO TRADE or DATA BLOCK when evidence is insufficient.
- Default to verified liquid cash equities on NSE/BSE, INR, Asia/Kolkata,
  whole shares and long positions. Exclude F&O, leverage, shorting, penny/SME
  strategies and averaging down from the initial practice workflow.
- Identify whether the user wants setup, intraday research, historical evaluation,
  fundamental research, a portfolio review, or a manual paper entry/exit.
- Prefer their existing broker. A skill is a workflow, a data adapter supplies
  observations, a journal records virtual fills, and a persistent runner would
  be needed to monitor continuously. Installation does not start a watcher.
- Resolve `SKILL_DIR` to this installed folder; its directory may have a generated
  ID. Keep user data and results in `PROJECT`, outside this skill repository,
  and use the host platform’s persistence features for deliverables.

## Know exactly what is implemented

| Capability | Current state |
| --- | --- |
| Kite/Upstox historical OHLCV | Read-only GET adapter; user must supply privately configured broker sessions and entitlements. |
| Indian intraday scanning | Completed five-minute bars, explicit date-specific session manifest, 15-minute long ORB observations. |
| Historical evaluation | Next-bar hypothetical entry, fees/slippage, adverse stop gaps, ambiguous-bar stop-first handling, doubled-cost stress and closed-trade drawdown. |
| Fundamental screening | User-sourced point-in-time CSV rules; future, stale and missing data fail. |
| Virtual cash and risk | Local manual journal; cash/position/planned-risk limits, daily entry/open-position caps, loss-streak/drawdown stops, pause, quote freshness and duplicate IDs. |
| Portfolio/news/disclosures | Guided evidence review; no automatic rebalancing, tax engine, news ingestion or disclosure copying. |
| Current prices/continuous paper execution | Mapped read-only quote polling is available when configured. No continuous paper-fill execution; journal stops/targets do not execute automatically. |
| Scheduled research | Explicitly started worker, mapped Kite/Paytm quotes and Kite/Upstox bars, six or ten model-role handoffs, final paper proposals and audit log; requires private configuration and refreshed evidence. |
| US/crypto | India/US dated session router with DST; Binance read-only spot observations. US decisions and crypto paper execution are not implemented. |
| Real-money orders | No implementation, connector or authorization in this skill. |

## Start with evidence and risk limits

Read [daily-service.md](references/daily-service.md) for continuous research,
Paytm quote limitations, OpenAI role reviews, crypto observations, session
routing and deployment. The ₹80,000 daily goal is reporting only and never
changes risk, sizing or frequency. No minimum return can be guaranteed.

Read [research-lab.md](references/research-lab.md) for Nifty-relative ranking,
daily technical labels, the optional bull/bear/sentiment workflow, provider
routing, checkpoint recovery and paper-performance reports. Require at least
61 aligned completed daily observations for 60-session returns; retain the
separate 50-session intraday gate. Pattern statistics never relax a veto.

Read [risk-process.md](references/risk-process.md) before planning any trade.
Read [guardrails.md](references/guardrails.md) for exact version-3 forward
entry gates, evidence schema, halt behaviour and manual/unsupported boundaries.
It separates code-enforced limits from evidence checks that still require
current source data: calendar, instrument mapping, ASM/GSM, price bands, spread,
liquidity, news/events and sector/correlation exposure. Missing evidence blocks
an entry; never present these reviews as automated checks that already passed.

Illustrative virtual defaults: ₹100,000 starting cash, ₹250 planned loss/trade,
₹750 daily loss budget, ₹15,000 entry-cost cap per position, 3 entries/day,
2 concurrent positions, stop after 2 consecutive losing closes or ₹2,000
closed-trade drawdown. These are training parameters, not real-money advice.
Do not increase them to force a rejected trade or recover a loss.

## Connect data

Read [connections.md](references/connections.md) for provider/sandbox differences
and [data-and-tools.md](references/data-and-tools.md) for actual CLI interfaces.
Use `scripts/broker_data.py` for verified Kite or Upstox cash-equity historical
candles. Credentials come only from environment variables; never request or
print passwords, tokens, API secrets or TOTP seeds in chat.

Authenticate on the broker's official flow outside chat. Verify the instrument
master and data subscription before requesting data. The adapter contains no
order endpoint, login automation, token refresh, pagination or WebSocket stream.
Use broker errors as DATA BLOCK; do not silently change data sources.
Dhan/other brokers can supply the normalized CSV or get a separately tested
read-only adapter when requested. No account is connected by installation.

## Research and evaluate a strategy

1. Freeze the instrument universe, strategy version, entry/stop/target/time exit
   and costs before evaluation. The included 15-minute long ORB is a sample
   test harness, not a demonstrated edge or a stock recommendation.
2. Verify candle source, start-time convention, currency, corporate-action
   basis and date-specific exchange sessions. Do not reuse NYSE calendars or
   relabel dollar fields. Unknown sessions and incomplete bars are blocked.
3. Run `india_research.py scan-orb` for completed-bar observations. A signal's
   confirmation time is not the quote time for an entry. Recheck current
   eligibility, liquidity and the trade rule before virtual entry.
4. Run `india_research.py replay-orb` for one symbol with explicit costs and
   risk limits. Read baseline AND doubled-cost stress, rejections and limitations.
   Separate independent single-symbol accounts; do not aggregate their returns
   as a portfolio or call historical results forward paper results.
5. Keep training/validation/unseen periods separate. Record all trials and all
   eligible/rejected signals. Explain survivorship, look-ahead and selection bias.
6. Report net expectancy, profit factor, sample size, drawdown definition, costs
   and risk overshoots alongside win rate. Gaps can exceed stop budgets.
   Target-limit fills are assumptions, not verified exchange executions.
7. Advance only to a separate virtual forward record when the user wants it.
   Thirty sessions/fifty trades can be an initial review, never proof of an
   edge or a promise of profitability. A losing/noisy test can be abandoned.

Offline examples are in `assets/synthetic-bars.csv` and
`assets/synthetic-sessions.json`. They are made-up fixtures, not market history.
Exact commands and schemas are in [data-and-tools.md](references/data-and-tools.md).

## Fundamental and portfolio research

Use `india_research.py screen` with user-sourced metrics, publication timestamp,
period end and source. Use sector-appropriate rules; do not apply nonfinancial
debt/margin heuristics blindly to banks. Never invent missing numbers.
Example rules/metrics in assets are illustrative and explicitly synthetic.

For earnings/news read NSE/BSE filings and company IR. For institutional
research use dated shareholding patterns or AMC/AMFI portfolio disclosures.
State observation and publication dates, limitations and lags; do not infer
live positions, actual trade dates or investor intent from snapshots.

For a portfolio review obtain holdings, cash, current marked prices and user
targets. Show issuer/sector concentration, aggregate planned risk, drift and
cash buffer. Rebalance proposals remain research, with costs and tax evidence
reviewed separately. No executable rebalance or correlation model is supplied.
Do not import US wash-sale/tax-lot rules or congressional trackers into India.

## Record manual paper trades

`scripts/paper_book.py` is offline and has no network/order code. Quotes, source
timestamps, fees and slippage must be explicit. It records assumed fills; its
stops are plans, not protective orders. Forward buys require a version-3 book
and dated `--evidence` JSON; start from the fail-closed template linked in
[guardrails.md](references/guardrails.md). `status` values open positions at cost,
not current market value. Closed-trade drawdown can understate open losses.

```bash
python3 SKILL_DIR/scripts/paper_book.py --book PROJECT/india-paper.sqlite init \
  --cash-inr 100000 --symbols NSE:VERIFIED_SYMBOL \
  --risk-inr 250 --daily-loss-inr 750 --position-limit-inr 15000 \
  --max-trades 3 --max-open 2 --max-loss-streak 2 --drawdown-stop-inr 2000
python3 SKILL_DIR/scripts/paper_book.py --book PROJECT/india-paper.sqlite status
```

The symbol above is a placeholder. Allowlist only verified cash equities.
The journal does not validate the instrument master or exchange calendar.
After evidence review, use `buy` with a unique event ID, symbol, whole-share
quantity, actual quoted price/time/source, selected stop, estimated entry fee,
exit-fee reserve and slippage assumption. Use `sell` to close the full virtual
position with an independently obtained quote and charges. See `--help`.
Fees must include applicable estimated charges; zero is an explicit zero-cost
assumption, not a claim that Indian trading is free.

```bash
python3 SKILL_DIR/scripts/paper_book.py --book PROJECT/india-paper.sqlite pause \
  --reason 'Review strategy or data before further entries'
```

Paused/loss-streak/drawdown-stopped books permit exits and block new entries.
Never silently reset their history. Older forward books, including version 2,
block new buys but permit valid exits. Preserve their results and start a
separate, clearly linked version-3 practice period. `init --replay` creates a
separate `replay_demo` book for historical/
synthetic examples. Never merge its performance with `paper_manual` results.

## Run the session engine

`scripts/engine.py` drives the same journal from a deterministic, clock-driven
loop: risk gate, automatic stop/target/square-off exits, stale-feed halt,
reconciliation and restart recovery. It is paper-only. Its `replay` command
runs one historical session into a new `replay_demo` book. Read
[engine.md](references/engine.md) for parts, exit rules and what is not built.

## Debate, ratings, memory and backtest

`scripts/debate.py` runs bull/bear and risk debates over the frozen ticket and
returns a five-tier rating; `scripts/memory.py` settles every rated call on later
stored prices and keeps point-in-time lessons; `scripts/backtest.py` replays the
engine across stored sessions with a doubled-cost stress run. Read
[debate.md](references/debate.md) and [backtest.md](references/backtest.md).
A rating can only stop or downgrade a ticket; code still sizes every position.

## Pre-market report and selection judge

`scripts/premarket.py` builds the morning watchlist. Hard filters (history,
liquidity, minimum NSE market-cap tier) form the pool; six specialist agents
(news, sentiment, technical, sector, liquidity, brokerage) assess it; the
selection judge makes the final call. Without a model it uses the deterministic
rank and says so. F&O lots are shown; only cash equity is traded. Read
[premarket.md](references/premarket.md).

## Strategies, exits and the tournament

`scripts/strategies.py` holds the entry rules (opening-range breakout, VWAP
pullback), the loss-avoidance filters and managed exits (breakeven, trailing and
time stops). `scripts/tournament.py` replays them on stored history with
pessimistic fills and lets a strategy trade only if it is profitable at double
costs; otherwise the desk sits out. Read [strategy.md](references/strategy.md).

## Market scan

`scripts/market_scan.py` lets the desk pick its own stocks. Code scans every F&O stock
at 08:40, using futures positioning, delivery, large deals and upcoming events. At
09:09 it adds the pre-open gap against the Nifty, and the agents judge the best ten.
At 09:31 it checks each pick's volume and VWAP before entry. Read
[market-scan.md](references/market-scan.md).

## Learning from mistakes and model routing

`scripts/learning.py settle` grades every agent's calls each evening against the
session and the paper trades. It writes lessons, stock notes and cooldowns that
the next morning's agents read, all downgrade-only. `scripts/model_router.py`
sends simple jobs to a free tier and the judge to a stronger one, with quotas, a
same-day cache and escalation. Read [learning.md](references/learning.md).

## Check the setup before trusting a run

`scripts/preflight.py` checks each prerequisite separately and names the exact
fix, instead of one DATA_BLOCK covering six possible causes.
`scripts/evidence.py` collects dated headlines and exchange filings, and
`scripts/pretrade.py` derives the eight machine-checkable pre-trade checks while
you attest the two that need judgement. The repository guide `docs/live-data.md`
covers the full live setup.

## Optional additions and boundaries

Read [resources.md](references/resources.md) for official learning/data resources
and ranked next additions. Inspect requested additions and current terms, pin
versions when installing, and test their actual capability.

OpenAlgo Analyzer is an optional later execution sandbox, not installed here.
A future adapter must verify analyzer mode and use server-side paper-only
execution restrictions; a precheck alone has a mode-switch race. Never connect
live order tools or activate a paid subscription as part of paper setup.

For an offline smoke check, run the installed copy against its bundled fixtures:

```bash
python3 SKILL_DIR/scripts/india_research.py scan-orb \
  --bars SKILL_DIR/assets/synthetic-bars.csv \
  --sessions SKILL_DIR/assets/synthetic-sessions.json \
  --as-of 2026-10-19T09:35:00+05:30
```

The full development suite lives in the source checkout, not this installed
payload. Run `python scripts/check.py` from that checkout after installing its
development requirements.

Separate test success from market performance. Never claim the software has
verified an authenticated broker connection, strategy profitability, automatic
risk protection or live operational readiness without the relevant evidence.


## Write useful research output

Lead with the result: observation, NO TRADE or DATA BLOCK. State the as-of time
in IST, source and whether data is synthetic, historical or a current quote.
Explain costs, assumptions and rejected evidence in plain language. Distinguish
code-enforced controls from manual checks; never claim a manual review ran
without its evidence. Separate a suggested next step from completed actions.
Keep answers concise and link the supporting result rather than pasting logs.

Use the host's skill invocation syntax: `/day-trader-india` in Claude Code or
`$day-trader-india` in Codex. On other hosts, select the skill or ask for it by
name. If Python, file access or current data is unavailable, explain the
missing capability and provide only the supported research guidance. Never
invent tool output, installed connectors or an active background watcher.

## Inspect recorded paper decisions

Launch `python3 SKILL_DIR/scripts/observatory.py --data-dir PROJECT/observatory`
for the local dashboard. Select a funnel stage or paper call to inspect persisted
engine evidence. Research skills shown as idle did not run. The bundled replay
has one synthetic session, not 50 days of observed market history.

Use `scripts/history.py --help` to retain complete CSV sessions and inspect
50-session coverage. Keep source kinds separate. Coverage is a research data
requirement, not a trained model or proof of profitability. Read
[history.md](references/history.md) before importing or interpreting history.

Use `scripts/watchlist.py` with a privately sourced instrument master and retained
broker history to build a dated liquidity-ranked research shortlist. Candidates
are `WAIT_FOR_SETUP`, not approved buys. It does not fetch today's market or
invoke news/reviewer skills automatically. Missing inputs yield no candidates.

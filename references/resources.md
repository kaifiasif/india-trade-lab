# Optional resources for the India profile

Contents: [Resource catalog](#resource-catalog), [Next improvements](#ranked-next-improvements),
[Evaluation additions](#additions-that-matter-more-than-extra-indicators), [Requests](#how-to-request-a-specific-addition).

Reviewed 21 October 2026. These are reference links, not installed dependencies.
Use only the additions needed for the selected workflow. Do not download entire
courses or websites into the skill; preserve focused summaries and source links.

## Resource catalog

| Priority | Resource | Why add it / where it fits |
| --- | --- | --- |
| First | [Zerodha Varsity](https://zerodha.com/varsity/) | Learn market basics, order types, technical analysis and risk before choosing rules. |
| First | [Varsity risk management](https://zerodha.com/varsity/module/risk-management/) | Position sizing, drawdown and behavioural discipline; useful for risk-review prompts. |
| First | [NSE market timings](https://www.nseindia.com/static/market-data/market-timings) | Session/calendar adapter; check segment-specific changes and special sessions. |
| First | [NSE RSS feeds](https://www.nseindia.com/static/rss-feed) | Company announcements, results and exchange circulars; replace US SEC news inputs. |
| First | [NSE corporate filings](https://www.nseindia.com/companies-listing/corporate-filings-application) | Primary-source results and announcements; record publication timestamps to avoid look-ahead bias. |
| First | [Zerodha brokerage calculator](https://zerodha.com/brokerage-calculator/) | Estimate actual charges by segment/product rather than treating gross P&L as profit. Use selected broker's calculator if different. |
| When broker chosen | [Kite Connect](https://kite.trade/docs/connect/v3/) / [Upstox API](https://upstox.com/developer/api-documentation/open-api) / [Dhan API](https://dhanhq.co/docs/v2/) | One authorized source of instrument IDs, quotes and historical bars; no need to buy all three. |
| For API tests | [Upstox sandbox](https://upstox.com/developer/api-documentation/sandbox/) / [Kite sandbox](https://kite.trade/docs/connect/v3/sandbox/) | Contract tests and order workflows; verify supported endpoints, not profitability. |
| For forward simulation | [OpenAlgo Analyzer](https://github.com/marketcalls/openalgo/blob/main/docs/userguide/15-analyzer-mode/README.md) | Optional local simulated execution and positions using authorized broker prices; requires a reviewed adapter. |
| After a written strategy | [Backtesting.py](https://kernc.github.io/backtesting.py/doc/backtesting/backtesting.html) | Historical evaluation with explicit spread and commissions. Validate strategy on unseen periods; it is not a live paper broker. Review its licence before redistribution. |
| Before future live work | [SEBI retail algo framework](https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html) and current broker implementation guidance | Verify onboarding/IP/order restrictions at implementation time. This is not an instruction to enable trading now. |

## Ranked next improvements

These are **proposed extensions**, not features claimed as installed. Choose
based on the user's broker and workflow. More indicators alone do not create
an edge or remove losses.

| Priority | Addition | What it would improve | Prerequisite |
| --- | --- | --- | --- |
| 1 | Instrument-master and session-calendar updater | Correct symbol/token/tick/segment mapping, corporate actions and special sessions | Current official exchange/broker data and authorized access |
| 1 | Current surveillance and event evidence | ASM/GSM, trade-to-trade, circuit and earnings/event exclusions | Exchange announcements/reports with dated provenance |
| 1 | Broker-specific cost model | Buy/sell asymmetry, brokerage caps, STT, GST, stamp duty and exchange charges | Selected broker/product and verified current charge schedule |
| 2 | Live quote/stream adapter and recorder | Fresh bid/ask, monotonic timestamps, reconnects and auditable forward observations | Chosen broker, valid data entitlement and a persistent runner |
| 2 | A realistic isolated paper execution service | Bid/ask fills, partial fills, participation limits, circuit/halts and automatic policy exits | Data recorder, deterministic execution/risk code, paper-only destination enforcement |
| 2 | Mark-to-market portfolio controls | Current equity/drawdown, issuer/sector/correlation exposure and aggregate open risk | Complete holdings plus fresh quotes and sector metadata |
| 3 | Walk-forward and benchmark report | Unseen-period tests, exposure-matched benchmarks, parameter stability and cost stress | Adequate clean historical data with a point-in-time universe |
| 3 | Dated Indian portfolio disclosures | Institutional holdings comparison using NSE/BSE and AMC/AMFI snapshots | Publication dates and proper instrument/issuer matching; no live-copy assumption |
| 3 | Alerts and operational monitoring | Missing-data alerts, runner health, reconciled virtual positions and a pause switch | An explicitly configured persistent runtime and destination chosen by the user |

Useful official additions to the catalog:

- [NSE surveillance actions](https://www.nseindia.com/regulations/exchange-market-surveillance-actions)
- [NSE ASM reports](https://www.nseindia.com/reports/asm)
- [NSE shareholding patterns](https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern)
- [AMFI portfolio disclosures](https://www.amfiindia.com/online-center/portfolio-disclosure)
- [Kite historical API](https://kite.trade/docs/connect/v3/historical/)
- [Upstox historical V3](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)

## Additions that matter more than extra indicators

- A selected broker's instrument-master cache, timezone-aware OHLCV store,
  corporate-action handling, holiday/session source and data-quality checks.
- Strategy definitions in version control with exact entry, invalidation, stop,
  target, time exit and no-trade rules. Freeze these during evaluation.
- A fee model for the chosen broker, product and current statutory charges.
  The bundled manual journal accepts aggregate estimates; it does not calculate
  STT, GST, stamp duty, exchange charges or tax liabilities for the user.
- A journal recording *all* eligible signals, including rejected/skipped ones,
  rather than cherry-picking winners. Separate synthetic, replay and forward data.
- Out-of-sample/walk-forward evaluation, cost stress tests, adverse gaps, missing
  quotes, stale timestamps, duplicate order IDs and interrupted connections.
- Monitoring and scheduling only after a persistent runner is configured. A
  skill installation or a chat message does not start a continuous market watcher.

## How to request a specific addition

Examples:

- “Add NSE announcement links and timestamped earnings notes to day-trader-india.”
- “Connect my existing broker's market data only and keep all fills virtual.”
- “Add a fee-aware Backtesting.py comparison using this historical CSV.”
- “Build an OpenAlgo Analyzer adapter and verify it cannot route live orders.”

For each addition, inspect current official documentation and source, identify
which capability it supplies, pin versions when installing, and run meaningful
checks. Do not equate a useful resource with evidence that a strategy works.

# Daily research service

Requires Python 3.10+, a private writable project directory and this complete
skill folder. Repository commands below run from the checkout root. In an
installed copy, replace `scripts/` with `SKILL_DIR/scripts/` and use absolute
project paths. Installation does not start a service.

## Run a useful first check

```bash
python3 scripts/decision_pipeline.py init --config data/observatory/pipeline.json
python3 scripts/market_service.py --config data/observatory/pipeline.json \
  --crypto-symbols BTCUSDT,ETHUSDT --once
python3 scripts/observatory.py --data-dir data/observatory
```

The first command creates configuration without overwriting existing settings.
The second collects public Binance spot observations and routes the markets;
India remains DATA_BLOCK until its prerequisites exist. Open
`http://127.0.0.1:8765` to inspect saved records. Remove `--once` to run until
stopped. Crypto collection is opt in, every 15 minutes per pair; failures also
consume that interval, including after a restart. The normal worker poll is
60 seconds. Nothing in this service places orders or records paper fills.

## What runs

| Market/component | Implemented | Still required |
| --- | --- | --- |
| Indian cash equities | Entitled historical batches, mapped quote/current-bar polling, 50-session shortlist, cost-aware ORB ticket, six model reviewers and final paper proposal | Your data sessions/entitlements, instrument mappings, current calendar, evidence and explicit model configuration |
| US stocks | Exchange-local session router with DST, dated holidays and early closes | US data/broker adapter, strategy evaluation, paper ledger, funding/eligibility review; no US decisions or orders run |
| Crypto spot | Public Binance metadata, 90 completed UTC daily candles, bid/ask observation, SMA20/50 and daily breakout research | Intraday strategy validation, timestamped execution feed, crypto paper accounting, charges, FX and risk integration |
| Across markets | One worker status view; execution disabled everywhere | A shared multi-currency portfolio risk ledger before cross-market execution |

Keeping the process online does not require a position at all times. WAIT,
NO_TRADE and DATA_BLOCK are valid outcomes. Crypto is independent of the two
stock-market schedules, rather than filling every gap with a trade.

## Configure Indian inputs

`pipeline.json` resolves all paths relative to its directory. Supply:

1. A **separate forward** version-3 `paper.sqlite` in `paper_manual` mode.
   Use [the journal interface](data-and-tools.md) and explicit virtual cash,
   allowed symbols and loss limits. Do not reuse replay balances or losses.
2. `sessions.json`: sourced date-by-date Asia/Kolkata sessions, including
   `open`, `close`, `entry_cutoff` and `flat_by`. The latter two must precede
   close. Unknown dates block; explicit null dates mark closures for routing.
   Apply the exchange circular and the selected instruments' applicable
   continuous-market close, including CAS changes, rather than copying the
   synthetic example. Use a homogeneous session calendar for a universe.
3. `universe.json`: the [sourced active-EQ instrument master](history.md), with
   verified `data_provider` (`kite` or `upstox`) and `instrument_id` per symbol.
   For the current feed, set `quote_provider` (`kite` or `paytm`) and
   `quote_instrument_id` (Paytm security ID). Historical and quote instrument
   identifiers can differ. Keep held symbols mapped for exit observations.
4. At least 50 complete prior non-synthetic sessions in `history.sqlite`.
   Prefer a longer evaluation sample across regimes; 50 is a data gate, not
   a statistically validated performance threshold or model training.
5. `current-bars.csv` and `quotes.json`, or opt in to the mapped collector.
   Quotes need original bid/ask timestamp, source and positive INR prices.
   Last-trade time alone is insufficient. Missing/crossed/stale quotes block.
6. `pretrade-evidence.json`, keyed by symbol, using the exact current
   [forward evidence contract](guardrails.md), including quote identity,
   surveillance, price-band, event, liquidity and portfolio checks.
7. `research-evidence.json`, keyed by symbol. Each item has a unique `id`,
   `source`, aware `observed_at`, factual `facts` and, when available,
   `published_at`. Use primary exchange/issuer material. For example:

```json
{"NSE:YOURSYMBOL": [{"id": "announcement-1", "source": "VERIFIED_EXCHANGE_URL", "observed_at": "AWARE_ISO_TIMESTAMP", "published_at": "AWARE_ISO_TIMESTAMP", "facts": "Sourced factual extract"}]}
```

These are placeholders. The models receive supplied evidence without browser
tools. They do not authenticate a source, fetch missing announcements or prove
the absence of news. Automated surveillance/news/instrument/calendar ingestion
is not implemented; keep that evidence refreshed by a separately verified
process. Missing evidence must remain blocked rather than being fabricated.

For historical collection, configure authorized credentials outside chat:
`KITE_API_KEY`/`KITE_ACCESS_TOKEN`, or `UPSTOX_ACCESS_TOKEN`. Then:

```bash
python3 scripts/data_sync.py --config data/observatory/pipeline.json --days 180 --max-symbols 3
python3 scripts/data_sync.py --config data/observatory/pipeline.json --current
```

History uses seven-calendar-day batches, GET-only routes, bounded requests,
immutable exports and existing completeness checks. The current feed supports
1–3 mapped instruments. A failed symbol is removed from the new snapshot,
not carried forward as though refreshed. No automatic login, token refresh,
retry or provider switching is performed. A refresh failure prevents that
worker tick from generating entry calls.

Paytm quotes use `PAYTM_READ_ACCESS_TOKEN` and the official FULL quote endpoint.
Its documented equity example contains depth and `last_trade_time`, but lacks
`last_update_time`. Such responses are exported as observations and **cannot
clear this forward quote gate**. Do not relabel receipt/trade time as quote
update time. The authenticated response shape has not been tested here.
Paytm historical beta is not implemented; history requires Kite/Upstox or
verified normalized exports. A Paytm account alone does not supply them.

## Configure independent role reviews

Set `model_provider` to `openai` and `model` to an explicitly chosen Responses
API model supporting structured outputs. Configure `OPENAI_API_KEY` in the
worker environment or a private environment file, never in Git or chat.
The default provider is `disabled`, which returns DATA_BLOCK.

The coordinator loads the canonical portable role instructions and runs:
data/news independently → screener → budget → risk → independent reviewer.
Every handoff binds to the same frozen ticket hash and supplied evidence.
Risk/reviewer vetoes survive all other votes. The model has no tools or broker
capability. The transport uses the official Responses endpoint, strict JSON
schema, no stored response, bounded tokens/time/bytes and redacted failures.
Instructions and market evidence are sent to the configured API provider.

Default model budget: 60 reserved calls per IST date, six per candidate,
maximum three candidates per run. Failed requests consume reserved capacity;
there are no retries. This is a call/token bound, not an exact rupee cost cap.
The service does not change model or limits to recover a failed decision.

```bash
python3 scripts/decision_pipeline.py run --config data/observatory/pipeline.json
python3 scripts/market_service.py --config data/observatory/pipeline.json \
  --refresh-india --crypto-symbols BTCUSDT,ETHUSDT
```

The worker performs scheduled research. Output is BUY_PAPER_PROPOSAL,
SELL_PAPER_PROPOSAL, HOLD_PAPER, WAIT or DATA_BLOCK. Only a breakout on the
latest completed bar is eligible. Each ticket is checked against the current
book; multiple proposals are alternatives, not reserved portfolio allocations.
Revalidate the exact current book and evidence before any manual paper fill.
Protective sell proposals do not require entry-only evidence or model approval;
they still need a valid fresh quote and session. They do not execute a stop.

`decisions.sqlite` retains runs, agent start/completion events, proposals and
vetoes. A durable lease excludes concurrent coordinators. Unchanged input
fingerprints return ARCHIVED_RESULT with current calls blocked. Interrupted
runs require refreshed evidence. The book checksum and quote freshness are
checked again after model review. Dashboard records older than 120 seconds
are visibly archived; an old approval is not a current call.

## Market schedules and continuous hosting

The router uses `Asia/Kolkata`, `America/New_York` and UTC via `zoneinfo`.
US dates are exchange dates, including after midnight in India. Supply a
source-backed US calendar with `timezone`, `source` and a `sessions` mapping;
each date is either `{"open":"09:30","close":"16:00"}`, a verified early
close, or null for a closure. There is no weekday fallback. US routing reports
`not_implemented` even during an open session.

Typical core sessions: Indian cash equities open 09:15 IST; applicable closes
and auctions require dated exchange/instrument confirmation. NYSE core hours
09:30–16:00 ET convert to 19:00–01:30 IST during US daylight time and
20:00–02:30 IST during US standard time. No extended-hours stock strategy is
enabled. Crypto public-data observation can run throughout the week, subject
to exchange/API availability. Session routing itself grants no trade approval.

Run the worker on an always-on Linux host with persistent storage and a process
supervisor. The repository includes `deploy/india-trade-lab.service` as an
operator-edited systemd template. Create the dedicated user, checkout,
configuration/data directory and private environment file before enabling it.
Keep the local dashboard bound to loopback; use an SSH tunnel to view it.
The hosted static preview does not run this Python worker or hold credentials.

Create a `HALT_ENTRIES` file alongside `pipeline.json` to pause new research
entries while retaining exit reviews. Remove it only after the cause is
resolved. Stop the service to stop collection. Back up the full private data
directory, including paper book, history, exports and audit databases. Records
have no automatic expiry. Monitor worker timestamps, disk usage and data
authorization failures; no external notification channel is configured.

## Profit goal and remaining execution work

The requested ₹80,000/day goal is reporting metadata. It never changes quantity,
risk limits, model votes or trading frequency. Net realized P&L and shortfall
come from the forward paper journal, not estimated future returns. A minimum
daily profit cannot be enforced. Actual account capital and acceptable losses
have not been supplied; illustrative defaults are not the user's finances.

Before cross-market execution, implement and validate currency-specific paper
ledgers, sourced FX conversions, shared exposure/loss/drawdown accounting,
broker reconciliation and strategy performance after all relevant costs.
Changing market or exchange must not reset accumulated losses. Review broker
eligibility and Indian resident funding rules before any US live work; do not
assume overseas margin funding is allowed. Live execution is outside this pack.

## Primary references

- [NSE market timings](https://www.nseindia.com/static/market-data/market-timings)
  and [dated circulars](https://www.nseindia.com/resources/exchange-communication-circulars).
- [NYSE hours, holidays and early closes](https://www.nyse.com/markets/hours-calendars).
- [Binance public market-data base](https://developers.binance.com/en/docs/products/spot/rest-api).
- [Paytm Money live market data](https://developer.paytmmoney.com/docs/api/live-market-data-api)
  and [official Python SDK](https://github.com/paytmmoney/pyPMClient).
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
- [RBI LRS FAQ](https://www.rbi.org.in/commonman/english/Scripts/FAQs.aspx?Id=1834).

Authenticated broker feeds and paid model requests require operator testing;
offline regression tests are not evidence of profitability.

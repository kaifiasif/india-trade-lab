# India Trade Lab

Indian cash-equity research and paper-trading tools, with an AI skill for guiding the workflow. Built for NSE/BSE, INR and Asia/Kolkata.

**Paper first. No live order execution. No promise of loss-free trading.**

## What works

- Read-only historical five-minute candle downloads from Zerodha Kite and Upstox, using privately configured broker sessions.
- Completed-bar opening-range breakout observations with explicit date-specific exchange sessions.
- Historical single-symbol replay with estimated charges, slippage, adverse stop gaps, conservative ambiguous-bar handling and doubled-cost stress.
- Point-in-time fundamental screening with source/publication dates and rejection of missing, stale or future information.
- A local virtual-INR journal with cash, position and planned-risk limits; daily entry/open-position caps; loss-streak/drawdown stops; pause; stale-quote and duplicate-event rejection.
- Synthetic examples and 23 offline checks.

The supplied opening-range rule is a test harness, not a proven trading strategy. A passing test verifies software behaviour, not investment performance.

## What is not running

There is no continuous runner, live quote stream, automatic paper stop/target execution, live broker order path, token refresh, or automatic calendar/instrument-master/news ingestion. The paper journal accepts manually supplied quotes and assumed fills. Its open positions are valued at entry cost; drawdown is based on closed trades.

The broker adapters are implemented but require an authorised account session, appropriate data entitlement and a verified symbol/instrument mapping. No account is connected by cloning this repository. Authenticated broker access has not been integration-tested in this project.

## Requirements

- Python 3.10 or newer. Tools use the Python standard library; no pip packages are required.
- For actual broker data: authorised credentials in environment variables, the required data plan and a verified cash-equity instrument master.
- A date-specific exchange session manifest. Unknown dates are blocked; the tools do not assume every weekday is a trading day.

## Quick start

```bash
git clone https://github.com/kaifiasif/india-trade-lab.git
cd india-trade-lab
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
```

### Run the made-up example

The bundled `NSE:DEMO` data is **synthetic**. It is not observed market history and must not be used as evidence of profitability.

```bash
python3 scripts/india_research.py scan-orb \
  --bars assets/synthetic-bars.csv \
  --sessions assets/synthetic-sessions.json \
  --as-of 2026-10-19T09:35:00+05:30

python3 scripts/india_research.py replay-orb \
  --bars assets/synthetic-bars.csv \
  --sessions assets/synthetic-sessions.json \
  --symbol NSE:DEMO --as-of 2026-10-19T15:30:00+05:30 \
  --cash 100000 --risk 250 --daily-loss 750 --position-cap 15000 \
  --target-r 2 --fee-bps 5 --fee-flat 10 --slippage-bps 5 \
  --drawdown-stop 2000
```

The replay prints a baseline and a doubled-cost scenario. Fees are explicit assumptions, not a complete Indian statutory-charge calculator. It does not model tick sizes, partial fills, spreads, market depth or exchange matching. Stop gaps can exceed the planned loss budget.

### Create a separate virtual book

This example uses a synthetic symbol and `--replay`, so every entry is labelled `replay_demo`.

```bash
python3 scripts/paper_book.py --book data/demo.sqlite init \
  --cash-inr 100000 --symbols NSE:DEMO \
  --risk-inr 250 --daily-loss-inr 750 --position-limit-inr 15000 \
  --max-trades 3 --max-open 2 --max-loss-streak 2 --drawdown-stop-inr 2000 \
  --replay

python3 scripts/paper_book.py --book data/demo.sqlite status
```

For forward manual paper practice, use a **different** book without `--replay`, allowlist verified cash-equity symbols, and supply recent authorised quotes with their original timestamps. Never merge synthetic/replay results with forward paper results. Keep personal books and broker exports out of Git.

Use command help for entries, full-position exits and pausing:

```bash
python3 scripts/paper_book.py --book data/demo.sqlite buy --help
python3 scripts/paper_book.py --book data/demo.sqlite sell --help
python3 scripts/paper_book.py --book data/demo.sqlite pause --help
```

### Download broker history

Read [data and tool interfaces](references/data-and-tools.md) first. The adapter issues GET requests only and does not place orders.

```bash
# Set KITE_API_KEY and KITE_ACCESS_TOKEN privately outside chat and Git.
# Replace the instrument token and symbol using a verified instrument master.
python3 scripts/broker_data.py --provider kite \
  --instrument VERIFIED_NUMERIC_TOKEN --symbol NSE:VERIFIED_SYMBOL \
  --from-date YYYY-MM-DD --to-date YYYY-MM-DD \
  --output data/bars.csv
```

For Upstox use `UPSTOX_ACCESS_TOKEN`, `--provider upstox`, and a verified cash-equity instrument key. Quote keys containing a pipe in your shell, for example `'NSE_EQ|VERIFIED_ISIN'`. These are placeholders, not working credentials or identifiers. Existing output files are not overwritten.

## Use the AI skill

The root [SKILL.md](SKILL.md) supplies the workflow. Load it in a skill-capable assistant, or install this repository into that client's supported skill directory under the name `day-trader-india`.

Example request:

> Use $day-trader-india to walk me through Indian stock paper trading with ₹1,00,000 virtual capital. Keep all execution virtual and show costs, missing evidence and risk limits.

A skill file provides instructions; it does not start a background service. Client installation and tool-execution support vary.

## Automation roadmap

These additions are planned, **not implemented**:

1. Persistent market-hours runner with session-aware start/stop and duplicate-signal handling.
2. Broker current-price/stream adapter, reconnect logic and fresh bid/ask recording.
3. Isolated paper execution service with simulated stops, targets, time exits and restarts.
4. Current instrument/calendar, surveillance/event and broker-specific cost updates.
5. Mark-to-market portfolio controls, operational monitoring and end-of-session reports.

GitHub stores and versions the code. Continuous intraday monitoring requires a running process with persistent storage and broker authorisation. AI can explain results; deterministic code should apply risk limits and virtual execution rules.

## References

- [Risk process and limitations](references/risk-process.md)
- [Data and CLI schemas](references/data-and-tools.md)
- [Broker connections and sandbox distinctions](references/connections.md)
- [Optional resources and ranked improvements](references/resources.md)
- [Comparison with the source projects](references/source-comparison.md)

Design influences: [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) and [Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill). This repository contains the India-specific implementation; it does not bundle the separately installed US skill collection. US tax, SEC and congressional-disclosure logic is not treated as Indian-market functionality.

## Licence

MIT. See [LICENSE](LICENSE).

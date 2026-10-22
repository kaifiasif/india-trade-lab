# India Trade Lab

Indian cash-equity research and paper-trading tools, with a coordinator and twelve specialist AI roles. Built for NSE/BSE, INR and Asia/Kolkata.

**Paper first. No live order execution. No promise of loss-free trading.**

Start with [skill installation](docs/installation.md) for Claude, Codex and other agents,
or use the Python CLI below.

## What works

- Read-only historical five-minute candle downloads from Zerodha Kite and Upstox, using privately configured broker sessions.
- Completed-bar opening-range breakout observations with explicit date-specific exchange sessions.
- Historical single-symbol replay with estimated charges, slippage, adverse stop gaps, conservative ambiguous-bar handling and doubled-cost stress.
- Point-in-time fundamental screening with source/publication dates and rejection of missing, stale or future information.
- A local virtual-INR journal with cash, position and planned-risk limits; daily entry/open-position caps; loss-streak/drawdown stops; pause; stale-quote and duplicate-event rejection.
- A deterministic paper session engine with a risk gate, automatic stop/target/square-off exits, stale-feed halt, reconciliation and restart recovery. See [engine reference](skills/day-trader-india/references/engine.md).
- A local browser dashboard with a 3D decision funnel, mascot, recorded calls, replay controls and persistent history coverage.
- Dated research shortlists from a sourced active-EQ universe, complete history and prior traded-value checks; current setups still need confirmation.
- Fifty-session historical coverage checks for forward engine entries; synthetic history never satisfies that gate.
- Fourteen portable skills, optional native Claude/Codex specialist profiles, synthetic examples and offline regression tests.

The supplied opening-range rule is a test harness, not a proven trading strategy. A passing test verifies software behaviour, not investment performance.

## What is not running

There is no continuous wall-clock runner, live quote stream, live broker order path, token refresh, or automatic calendar/instrument-master/news ingestion. The paper journal accepts manually supplied quotes and assumed fills. Its open positions are valued at entry cost; drawdown is based on closed trades.

The broker adapters are implemented but require an authorised account session, appropriate data entitlement and a verified symbol/instrument mapping. No account is connected by cloning this repository. Authenticated broker access has not been integration-tested in this project.

## Requirements

- Python 3.10 or newer. Tools use the Python standard library; no pip packages are required.
- For actual broker data: authorised credentials in environment variables, the required data plan and a verified cash-equity instrument master.
- A date-specific exchange session manifest. Unknown dates are blocked; the tools do not assume every weekday is a trading day.

## Quick start

```bash
git clone https://github.com/kaifiasif/india-trade-lab.git
cd india-trade-lab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/check.py
```

### Open the paper observatory

From the repository root, run:

```bash
python3 scripts/observatory.py
```

Open `http://127.0.0.1:8765`. Choose **Run paper replay** to watch the engine
process the bundled synthetic session. Select a funnel stage or call to inspect
its recorded inputs, result and explanation. The UI polls the local API every
second. Pause controls replay time; a sticky entry halt still permits paper exits.

The dashboard has no exchange connection or live-order controls. Its five active
stages are deterministic Python rules. Research skills that were not invoked are
shown as idle. An exported hosted preview displays archived synthetic events;
run the local backend for working replay controls.

Books and event logs live under `data/observatory/` and are retained between runs.
Historical coverage and import instructions are in [the observatory guide](docs/observatory.md).

### Run the made-up example

The bundled `NSE:DEMO` data is **synthetic**. It is not observed market history and must not be used as evidence of profitability.

```bash
python3 scripts/india_research.py scan-orb \
  --bars skills/day-trader-india/assets/synthetic-bars.csv \
  --sessions skills/day-trader-india/assets/synthetic-sessions.json \
  --as-of 2026-10-19T09:35:00+05:30

python3 scripts/india_research.py replay-orb \
  --bars skills/day-trader-india/assets/synthetic-bars.csv \
  --sessions skills/day-trader-india/assets/synthetic-sessions.json \
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

### Replay a session through the engine

The engine applies stops, targets and the session square-off itself, through the same journal.

```bash
python3 scripts/engine.py replay \
  --bars skills/day-trader-india/assets/synthetic-bars.csv \
  --sessions skills/day-trader-india/assets/synthetic-sessions.json \
  --symbol NSE:DEMO --date 2026-10-19 --book data/engine-demo.sqlite \
  --cash 100000 --risk 250 --daily-loss 750 --position-cap 15000 \
  --target-r 2 --fee-bps 5 --fee-flat 10 --slippage-bps 5
```

### Download broker history

Read [data and tool interfaces](skills/day-trader-india/references/data-and-tools.md) first. The adapter issues GET requests only and does not place orders.

```bash
# Set KITE_API_KEY and KITE_ACCESS_TOKEN privately outside chat and Git.
# Replace the instrument token and symbol using a verified instrument master.
python3 scripts/broker_data.py --provider kite \
  --instrument VERIFIED_NUMERIC_TOKEN --symbol NSE:VERIFIED_SYMBOL \
  --from-date YYYY-MM-DD --to-date YYYY-MM-DD \
  --output data/bars.csv
```

For Upstox use `UPSTOX_ACCESS_TOKEN`, `--provider upstox`, and a verified cash-equity instrument key. Quote keys containing a pipe in your shell, for example `'NSE_EQ|VERIFIED_ISIN'`. These are placeholders, not working credentials or identifiers. Existing output files are not overwritten.

## Install the skills

The installable skills are now in [`skills/`](skills/), not the repository root.
Each folder includes its own instructions and resources.

| Skill | Use it for |
| --- | --- |
| [day-trader-india](skills/day-trader-india/SKILL.md) | Indian market research, historical evaluation and manual paper trading |
| [india-trade-dev](skills/india-trade-dev/SKILL.md) | Code reviews, tests, portable packaging and clear technical documentation |

From this checkout, choose your client:

```bash
python3 scripts/install_skills.py --platform claude --scope user --with-agents
python3 scripts/install_skills.py --platform codex --scope user --with-agents
```

These are alternatives; run the one for your client, or both if you use both.
The default installs all fourteen skills. `--with-agents` also installs twelve native specialist profiles for that client. Existing files are never replaced.
Use `/day-trader-india` in Claude Code or `$day-trader-india` in Codex.

For **Claude web / Desktop**, run `python3 scripts/package_skills.py` and upload
the core ZIP and any role ZIPs you need from `dist/` in **Customize > Skills**. Full instructions for Claude,
Codex, Cursor, Copilot and other hosts are in [installation](docs/installation.md).
A skill does not start a background service or connect your broker.

## Specialist agents and guardrails

The pack includes data, news, earnings analysis, screening, disclosures, budget,
risk, paper-broker, alerts, costs/tax, rebalancing and independent reviewer roles.
See the [role map and handoff contract](skills/day-trader-india/references/agent-workflow.md).
Native Claude/Codex profiles are in [agent_profiles/](agent_profiles/). They
return research findings; the coordinator runs tools. On other hosts, invoke
role skills or follow their procedures sequentially and label that limitation.

Use this request after installation:

> Use day-trader-india to coordinate the Indian research agents. Review the data,
> news, setup, budget and risks, then have the independent reviewer challenge the
> proposal. Return DATA BLOCK for missing evidence. Keep everything virtual.

The offline workflow CLI prints dependency plans and validates handoff packets:

```bash
python3 skills/day-trader-india/scripts/agent_workflow.py plan \
  --workflow intraday --symbol NSE:DEMO \
  --as-of 2026-10-19T10:00:00+05:30 --run-id synthetic-demo
```

This plans delegation; it does not launch models or start a service. The
coordinator uses the host's subagent feature. Any veto, missing report or
changed proposal blocks review completion. A completed review never authorizes
an order or replaces the journal's gates.

Forward manual entries now require a **version-3 journal** and sourced
`--evidence` JSON. Added controls include fixed practice ceilings, supplied
session/quote/spread checks, a loss cooldown, entry halt and state checksums.
Existing accounting, duplicate, loss-streak and drawdown controls remain.
Read [guardrails and limitations](skills/day-trader-india/references/guardrails.md)
for the exact enforced/manual boundary and migration from older books. No
collection of guardrails guarantees loss-free trading or truthful input data.

## Code and writing standards

The runtime implementation lives in `skills/day-trader-india/scripts/`. The
original `scripts/broker_data.py`, `scripts/india_research.py` and
`scripts/paper_book.py` remain compatible CLI entry points. Offline regression
tests live in `tests/`; install/package/validation tools live in `scripts/`.
References and synthetic assets moved inside the trading skill so copied
installations work without this checkout.

[AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md) give coding assistants the repo
rules. [CONTRIBUTING.md](CONTRIBUTING.md) documents the development workflow and
[engineering standards](skills/india-trade-dev/references/engineering.md) define
code and writing expectations. `python scripts/check.py` runs Ruff lint,
format checks, skill metadata and local-link validation, generated-agent drift checks, and offline tests.
GitHub Actions uses the same command on Python 3.10 and 3.12 and uploads skill
ZIPs as a workflow artifact. Public function annotations support readability;
full static type checking is not enforced yet.

## Automation roadmap

These additions are planned, **not implemented**:

1. Persistent market-hours runner with session-aware start/stop and duplicate-signal handling.
2. Broker current-price/stream adapter, reconnect logic and fresh bid/ask recording.
3. Isolated paper execution service with simulated stops, targets, time exits and restarts.
4. Current instrument/calendar, surveillance/event and broker-specific cost updates.
5. Mark-to-market portfolio controls, operational monitoring and end-of-session reports.

GitHub stores and versions the code. Continuous intraday monitoring requires a running process with persistent storage and broker authorisation. AI can explain results; deterministic code should apply risk limits and virtual execution rules.

## References

- [Risk process and limitations](skills/day-trader-india/references/risk-process.md)
- [Data and CLI schemas](skills/day-trader-india/references/data-and-tools.md)
- [Broker connections and sandbox distinctions](skills/day-trader-india/references/connections.md)
- [Optional resources and ranked improvements](skills/day-trader-india/references/resources.md)
- [Comparison with the source projects](skills/day-trader-india/references/source-comparison.md)

Design influences: [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) and [Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill). This repository contains the India-specific implementation; it does not bundle the separately installed US skill collection. US tax, SEC and congressional-disclosure logic is not treated as Indian-market functionality.

## Licence

MIT. See [LICENSE](LICENSE).

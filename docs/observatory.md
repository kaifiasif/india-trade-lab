# Paper observatory

Requires Python 3.10+. From the repository root:

```bash
python3 scripts/observatory.py
```

Open `http://127.0.0.1:8765`. No npm install or broker credentials are needed
to run it: the React app is prebuilt into `assets/observatory/`, and the UI and
Python backend ship together in the portable `day-trader-india` skill.

## Pages

| Page | What it shows or does |
| --- | --- |
| Today | Greeting, setup progress, the paper book, today's picks, the IST session timeline and the strategy tournament |
| Pre-market desk | The judge's picks and drops, each specialist's one-line view, today's scan (how many F&O stocks were scanned and why they were dropped, positioning, pre-open strength and the 09:31 check for each ranked stock), and buttons to run every stage |
| Paper replay | A synthetic NSE:DEMO session through the real engine: five pipeline stages, the price with fills, stop and target, paper calls and engine events, with pause and halt |
| Research | Recorded research reviews, how past ratings settled, history coverage and the screened watchlist |
| Agents | The sixteen-member desk and what each one is allowed to do |
| Learning | Each agent's report card, recent lessons from mistakes, what the desk knows about each stock, model use per tier against your limits, and fine-tuning readiness |
| Setup | Eleven steps from an empty server to a working desk (below) |
| Settings | Every editable `pipeline.json` setting, in tabs, saved atomically with a backup |

Light and dark themes follow the system and can be switched from the header.
The mascots are SVG moved with GSAP; their moods follow recorded events (asleep
when the desk sits out, a hop on a new pick or fill, an alarm on a block). With
reduced motion they hold still and every value is still shown.

## Setup from the browser

Setup walks through: the private project, your name and report address, Kite
Connect keys, today's Kite login (open Zerodha, paste the address it returns
to), email, the research model, choosing one to ten stocks from NSE's
`EQUITY_L.csv`, loading history, the tournament, the paper book and today's
surveillance and announcement checks. Long tasks run as server jobs with a live
log; one job per kind runs at a time and a restart marks unfinished jobs as
interrupted.

Email goes out over SMTP from your own mailbox (for Gmail, `smtp.gmail.com`
with a 16-character app password). There is no Google sign-in.

Secrets (Kite key and secret, today's token, the SMTP password, model keys) are
written to `~/.config/india-trade-lab/secrets.env` and `tokens.env`, folder mode
0700 and files 0600, or under `ITL_CONFIG_DIR` if set. They are never written to
`pipeline.json`, never returned by the API (only "saved, ends 1234"), and are
scrubbed from job logs. Every setup action is recorded in `setup-audit.jsonl`
without values.

Run a normal replay, a missing-bar scenario or an oversized-proposal scenario.
All use made-up `NSE:DEMO` data. Replays run automatically through the actual
engine/journal. Each new run uses a separate database; prior results are retained.
Pause freezes replay time. Halt entries is sticky for that run; remaining
observations still drive protective exits. A replay interrupted by process
shutdown is displayed as interrupted after restart; it is not silently resumed.

## Keep historical context

The bundled data contains **one synthetic session**. It is never counted as
observed broker history. Import your verified five-minute broker CSV and complete,
source-backed exchange session manifest:

```bash
python3 scripts/history.py --db data/observatory/history.sqlite import \
  --bars data/broker-bars.csv --sessions data/exchange-sessions.json \
  --symbol NSE:TCS --kind broker_export --as-of 2026-10-21T15:30:00+05:30

python3 scripts/history.py --db data/observatory/history.sqlite coverage \
  --symbol NSE:TCS --as-of 2026-10-21T15:30:00+05:30 --minimum-sessions 50
```

The `data/` files in this example are user inputs, not bundled files. Select the
imported symbol in the dashboard's history panel. The backend reads updates on
its next poll. Imports do not train a model or change the strategy's rules.
See the [history policy](../skills/day-trader-india/references/history.md) for
provenance, cutoff and revision behaviour. All history is retained until explicitly
archived. Two days is insufficient for this project's configured research gate;
50 sessions is still not a promise of profitable or loss-free trading.

## API and access

- `GET /api/state`: persisted snapshot, recorded calls/stages and coverage.
- `GET /api/session`: process-local replay-control token.
- `POST /api/replay`: `{"scenario":"baseline"}`; also `data-gap` or `risk-block`.
- `POST /api/control`: `{"action":"pause"}`, `resume` or `halt`.
- `GET /api/health`, `GET /api/setup/status`, `GET /api/setup/settings`,
  `GET /api/setup/jobs[/<id>?offset=N]`.
- `POST /api/setup/<action>`: `init_project`, `save_profile`, `save_secret`,
  `kite_login_url`, `kite_exchange`, `send_test_email`, `save_settings`,
  `upload_equity_list`, `search_symbols`, `build_universe`, `create_book`,
  `attest`, `run_job`.

POST requires `Content-Type: application/json` and the `X-Session-Token` returned
by `/api/session`. Requests must use the expected loopback host and same origin.
The server provides no arbitrary-file or exchange-order endpoints, and no endpoint returns a stored secret.
It is a local application server, not an authenticated internet deployment.

Use `--data-dir` to select private persistent storage and `--port` for another
local port. Back up the history database and each run database.
`--export-preview FILE` writes the latest synthetic state as JSON (used by the
recap video).
The daily research desk reads saved coordinator handoffs, final proposals,
worker routes and read-only crypto snapshots when present. See
[daily service setup](../skills/day-trader-india/references/daily-service.md).
Model reviews and authenticated broker access require private configuration.

## How a stock reaches the shortlist

The `india-screener` skill describes research. The dashboard also includes an
executable daily research selector. It reads `data/observatory/universe.json`
and your retained broker-export history. Nothing is selected when those inputs
are absent. The instrument master must be sourced, dated within 30 days, and
contain distinct exchange-qualified active EQ instruments with ISINs:

```json
{
  "source": "YOUR_VERIFIED_INSTRUMENT_MASTER_SOURCE",
  "as_of": "2026-10-22T08:30:00+05:30",
  "instruments": [
    {"symbol": "NSE:YOURSYMBOL", "isin": "REPLACE_WITH_VERIFIED_ISIN", "segment": "EQ", "active": true}
  ]
}
```

These are placeholders; replace them with your provider's verified fields.
The selector requires 50 complete non-synthetic sessions per symbol, no missing
declared sessions in that window, and the latest session within seven calendar
days. It ranks by prior 20-session average traded-value proxy, calculated as
`sum(five-minute close × volume)`. The dashboard's example threshold is ₹2 crore
per session and its maximum shortlist is ten. These are configurable research
settings, not calibrated trading recommendations or measured bid/ask liquidity.

Run a dated selection explicitly:

```bash
python3 scripts/watchlist.py --db data/observatory/history.sqlite \
  --universe data/observatory/universe.json --as-of 2026-10-22T09:00:00+05:30 \
  --top 10 --min-turnover-inr 20000000
```

The dashboard rebuilds when its input files/history change or the date changes,
and persists each resulting selection in `selection.sqlite`. It labels each
candidate `WAIT_FOR_SETUP`. It does not automatically subscribe those stocks to
an intraday feed or launch a trading session. A scheduled ingestion/feed runner
is still needed for that. No actual stocks are selected by the synthetic demo.

For a running allowlisted paper session, the current strategy proposes a long
entry after a complete opening range and a later completed close above its high.
Stops, targets and square-off rules generate sell exits. Risk and journal checks
can refuse entries. News, disclosures and surveillance evidence are still required
for forward paper practice. The separately configured daily service can call six
research roles on supplied evidence and retain their vetoes and proposals.
The system has no short-selling or real-exchange execution path.

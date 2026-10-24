# Paper observatory

Requires Python 3.10+. From the repository root:

```bash
python3 scripts/observatory.py
```

Open `http://127.0.0.1:8765`. No npm install or broker credentials are needed.
The UI and Python backend ship together in the portable `day-trader-india` skill.

## What the dashboard shows

| View | Source |
| --- | --- |
| 3D/flat funnel | Persisted data, strategy, gate, paper executor and journal events. In 3D, each newly recorded event travels as a particle between the stages it reached; blocked events turn red and drop at the stage that stopped them |
| Session tape | The replay's recorded bids as a 3D ribbon, with each paper fill and the planned stop and target while the position was open |
| Decision inspector | Recorded explanations and event payloads, not private model reasoning |
| Trade calls | Assumed entry/exit fills, rejected orders, quantity, stop and target |
| Activity stream | Filterable decisions, observations, blocks and alerts |
| History coverage | Retained complete sessions, source kind and a 50-session research baseline |
| Specialist bench | Idle portable research skills; no LLM providers are connected |

The 3D views use Three.js 0.170.0, bundled under
`assets/observatory/vendor/` with its licence and checksum, so the page still
loads nothing from outside your computer. Drag a scene to turn it and
double-click to reset. Without WebGL, the page uses the flat funnel and the
tables; with reduced motion, nothing animates but every value is still shown.
The 3D views only draw recorded events and prices.

To turn a recorded session into a shareable video, see the
[recap video](../recap-video/README.md).

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

POST requires `Content-Type: application/json` and the `X-Session-Token` returned
by `/api/session`. Requests must use the expected loopback host and same origin.
The server provides no arbitrary-file, exchange-order or credential endpoints.
It is a local application server, not an authenticated internet deployment.

Use `--data-dir` to select private persistent storage and `--port` for another
local port. Back up the history database and each run database. A hosted static
preview can be exported with `--export-preview FILE`; it contains synthetic
replay events, has no connected backend, and its run controls point to local setup.
The daily research desk reads saved coordinator handoffs, final proposals,
worker routes and read-only crypto snapshots when present. See
[daily service setup](../skills/day-trader-india/references/daily-service.md).
Model reviews and authenticated broker access require private configuration.
The static preview does not run the service.

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

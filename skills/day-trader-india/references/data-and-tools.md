# Data and tool interfaces

Contents: [Paths](#resolve-paths), [Broker data](#read-only-broker-data), [Schemas](#candle-csv-and-sessions), [Scanner](#completed-bar-scanner), [Replay](#historical-replay-and-doubled-cost-stress), [Screen](#point-in-time-fundamental-screen), [Examples](#offline-examples).

## Resolve paths

`SKILL_DIR` means the directory containing this installed SKILL.md. The saved
directory may have a generated ID. Never assume a sibling source folder exists.
`PROJECT` means a user project folder for market data/results, outside the skill.
All synthetic assets are software examples, not observed Indian prices.

## Read-only broker data

The supplied `scripts/broker_data.py` implements historical **GET** requests
only for Kite and Upstox. It has no orders, token generation, password/TOTP
automation or live-mode switch. Tokens remain in environment variables and
are not printed. Redirects are refused so an authorization header is not
forwarded to another host. Existing output files are not overwritten.

The user must already have a broker account, a correctly issued session, the
required data entitlement, and a verified instrument-master mapping. No account
is connected just because this script is installed. API tests use synthetic
responses; successful authenticated access has not been established here.

```bash
python3 SKILL_DIR/scripts/broker_data.py --provider kite \
  --instrument VERIFIED_NUMERIC_TOKEN --symbol NSE:VERIFIED_SYMBOL \
  --from-date YYYY-MM-DD --to-date YYYY-MM-DD --output PROJECT/bars.csv
```

Kite requires `KITE_API_KEY` and `KITE_ACCESS_TOKEN`, privately set outside chat.
For Upstox use `--provider upstox`, an instrument key such as
`NSE_EQ|VERIFIED_ISIN`, and `UPSTOX_ACCESS_TOKEN`. Quote that key in a shell:
the pipe character is otherwise shell syntax. Do not use the illustrative
placeholders as if they were actual tokens or ISINs.

- Kite historical API: https://kite.trade/docs/connect/v3/historical/
- Upstox historical V3: https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/
- Upstox OAuth: https://upstox.com/developer/api-documentation/authentication/

Respect current range/rate limits. A provider error or an expired token is a
data block. Do not silently scrape a different source or print account secrets.
The script retrieves one instrument/window; it does not automatically paginate,
resample, refresh tokens, stream live data, fetch an instrument master or fetch
exchange calendars. Dhan and other brokers can supply the normalized CSV or
receive a separately implemented and tested read-only adapter when requested.

## Candle CSV and sessions

Required CSV columns:

`symbol,timestamp,open,high,low,close,volume,source`

Timestamps are candle **start** times with timezone offsets. Values are INR and
share volumes for verified cash-equity symbols such as `NSE:RELIANCE` or the
verified BSE identifier. The parser rejects duplicate timestamps, nonfinite
values, invalid OHLC and missing sources. It does not verify the instrument
master, corporate actions, adjustment basis or tradeability.

Required session manifest shape:

```json
{
  "timezone": "Asia/Kolkata",
  "source": "URL of the exchange session/calendar verified for this date and segment",
  "sessions": {
    "YYYY-MM-DD": {
      "open": "09:15",
      "close": "15:30",
      "entry_cutoff": "14:30",
      "flat_by": "15:15"
    }
  }
}
```

The times are an example for an ordinary session and a chosen practice policy,
not an automatically maintained market calendar. Verify actual dates/segment
times and special sessions. Unknown dates are blocked, including weekdays.
This engine supports five-minute grids and 15-minute opening ranges; other
session/bar structures need a code change and tests.

## Completed-bar scanner

```bash
python3 SKILL_DIR/scripts/india_research.py scan-orb --bars PROJECT/bars.csv \
  --sessions PROJECT/sessions.json --as-of ISO_TIMESTAMP_WITH_OFFSET
```

The first three five-minute bars define the opening high/low. A subsequent
completed bar closing above that high is a match. It requires every completed
bar from the opening through the observation time, reports missing data as
DATA_BLOCK, and reports expired entry windows. Future/in-progress bars do not
enter the scan. The first signal is an observation, not a new executable ticket
at every later check. Revalidate the plan and current quote before any paper entry.

## Historical replay and doubled-cost stress

Use one verified symbol at a time. Each replay has an independent virtual
account; never sum these accounts' returns as a combined strategy portfolio.

```bash
python3 SKILL_DIR/scripts/india_research.py replay-orb \
  --bars PROJECT/bars.csv --sessions PROJECT/sessions.json \
  --symbol NSE:VERIFIED_SYMBOL --as-of ISO_TIMESTAMP_AFTER_TEST_PERIOD \
  --cash 100000 --risk 250 --daily-loss 750 --position-cap 15000 \
  --target-r 2 --fee-bps ESTIMATED_AGGREGATE_BPS_PER_SIDE \
  --fee-flat ESTIMATED_FLAT_CHARGE_PER_SIDE --slippage-bps ASSUMED_BPS \
  --drawdown-stop 2000
```

Fees are a user-supplied approximation; Indian buy/sell charges can be asymmetric
and product-specific. This is not a statutory charge calculator. The baseline
and doubled-cost scenario use the same input bars; sizing can differ because
costs consume the risk budget.

Rule: one long entry per session, signal on a completed 15-minute-ORB breakout,
quantity sized from the signal close, hypothetical fill at the next open plus
slippage, stop at the opening-range low, target fixed from the signal close and
selected R, flatten at the declared policy time. Entry is skipped if that next
quote lies outside the predeclared stop/target band or exceeds cash/cost cap.
This assumes the runner can check that quote before entry; it does not model
an already-submitted unprotected market order.

Adverse entry gaps that increase planned stop risk are flagged. Stop gaps can
lose more than the budget. When both stop and target lie inside one bar, stop
is checked first. A touched target is an assumed limit fill, with no liquidity
guarantee. There is no tick-grid, volume, spread, partial-fill or exchange
matching model. Full session data is required; rejected sessions are reported.
Drawdown is on closed trades only; the configured drawdown stop skips later
sessions after it is reached. Replay daily loss is a sizing ceiling because
there is at most one entry per session; it is not a guarantee on gap losses.

## Point-in-time fundamental screen

```bash
python3 SKILL_DIR/scripts/india_research.py screen \
  --metrics PROJECT/metrics.csv --rules PROJECT/rules.json \
  --as-of ISO_TIMESTAMP_WITH_OFFSET --max-age-days 200
```

Metrics need `symbol,source,period_end,published_at` plus the user-selected
numeric columns. Rules are a JSON list of `{metric,op,value}` using `>=`, `<=`,
`>`, `<` or `==`. Percentages are percentage points, e.g. 10 means 10% growth,
not 0.10. Ratios such as debt/equity use plain ratios. Supply only one row
known at the decision time per company. Future publications, stale periods,
missing metrics and nonfinite inputs fail. Values are not fetched automatically.
Do not impose a nonfinancial-sector debt rule on banks without an appropriate
sector model. A passing company is a research candidate, not a buy instruction.

## Offline examples

The `assets/synthetic-*` files and `metrics.synthetic.csv` are deliberately
made-up software fixtures. Use them only for a walkthrough, not as evidence
that the strategy works. The `screen-rules.example.json` file illustrates
user-defined rules; it is not a universal Indian stock selection policy.

Run checks with:

```bash
python3 -B -m unittest discover -s SKILL_DIR/scripts -p 'test_*.py'
```

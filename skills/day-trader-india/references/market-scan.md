# Market scan: the desk picks its own stocks

Runtime: `scripts/market_scan.py`. It is on by default for projects created with
`decision_pipeline.py init` or the dashboard, and set with `"scan"` in
`pipeline.json`.

Without the scan, the agents only judge the 1–3 stocks you list. With it, plain
code scans every NSE stock that has futures and options (about 180–220). It
hands the best ten to the specialists and the judge, ranked on signals that
show how traders are positioned going into the open, not only on news the
market has already priced.

## Three stages

| Time (IST) | Stage | What it uses |
| --- | --- | --- |
| 08:40 | `overnight` | Daily candles: trend, RSI, liquidity. Futures open-interest change against price change. Put/call open-interest ratio and the strikes with the most open interest. Yesterday's delivery % and bulk/block deals. Results, board meetings and ex-dates in the next five days. Keeps the best 25 |
| 09:09 | `open` | The pre-open auction's opening price for those 25: the gap, and the gap against the Nifty 50 and the sector index. Then `premarket.py` runs the agents and the judge on the best ten and emails the picks |
| 09:31 | `confirm` | For each pick: volume so far against the same 15 minutes on the last 20 sessions, price against VWAP, and strength against the Nifty since the open |

How to read futures open interest (OI) against price, using the previous
session's close:

| Price | OI | Reading | Score |
| --- | --- | --- | --- |
| Up | Up | Long build-up: fresh buying | +2 |
| Up | Down | Short covering | +1 |
| Down | Down | Long unwinding | −1 |
| Down | Up | Short build-up: fresh selling | −2 |

OI moves under 2% read as neutral. OI is summed across all expiries, so
rollover near expiry does not distort it. The first day after setup has no
previous snapshot, so positioning reads "unknown" until the second day.

## Filters and gates (downgrade only)

- **Overnight:** a stock is dropped when it:
  - has fewer than 30 daily candles;
  - is in a daily downtrend;
  - has RSI(14) of 75 or more;
  - trades below the liquidity floor;
  - has an event today or tomorrow.
- **At the open:** a gap down of 1.5% or more drops the stock. A gap up of 3%
  or more counts against it (late to chase).
- **Before entry:** a pick is entered only if all three hold at 09:31:
  - volume at least 1.5 times normal;
  - price above VWAP;
  - stronger than the Nifty since the open.

  A pick that fails is not entered. Until the check has run, entries wait. To
  turn the gate off, set `"require_confirmation": false`.

All thresholds are in `"scan"`. The scan only removes or ranks stocks; risk
limits and position sizing are unchanged.

## What the agents see

Each candidate's evidence gains three items:

- `#positioning`, read by the liquidity and technical analysts;
- `#opening`, read by the technical and sector analysts;
- `#events`, read by the news analyst.

The judge is told to weigh what leads the open above news that is already
priced. Once enough sessions are graded, it also sees how stocks with each
signal (for example "long build-up" or "strong vs Nifty at the open") actually
did from open to close.

## Data and limits

- **Kite (your login, read-only):**
  - the instrument list, once a day;
  - quotes in batches of 500, one request a second;
  - daily and 15-minute candles, three requests a second.

  The first scan fetches about 200 days of daily candles for every stock, which
  takes about a minute. After that, only missing days are fetched, nightly at
  16:10.
- **NSE public files:**
  - the full bhavcopy (delivery %);
  - `bulk.csv` and `block.csv`;
  - the event calendar.

  If NSE refuses a request, that signal is reported as unavailable. The scan
  does not evade the refusal.
- **Stock list for the worker:** after the judge picks, `universe.json` is
  rewritten with the picks, so the session worker watches them. This needs
  NSE's `EQUITY_L.csv`, uploaded in Setup. History sync then grows the 5-minute
  history behind the strategy tournament one pick at a time.

These signals describe positioning and participation. They do not predict
prices, and no result here is evidence of future returns.

# Paper trading on live Kite data

Requires Python 3.10+ (macOS's built-in `python3` may be 3.9; see
[installation](installation.md)), a Zerodha account and the paid Kite Connect
data plan. Run every command from the repository root inside your virtual
environment. Everything stays virtual: no command here places an order.

## What live data does today

| Works | Not yet |
| --- | --- |
| Real five-minute candles and bid/ask quotes during market hours | Entry proposals: they also need a configured review model and pre-trade evidence re-checked within 120 seconds of each quote, which nothing generates automatically |
| A daily shortlist from 50+ complete real sessions per stock | Live orders of any kind |
| Stop, target and square-off exit proposals for open paper positions | |

## One-time setup

1. At [developers.kite.trade](https://developers.kite.trade), create an app with
   redirect URL `http://127.0.0.1`, subscribe to the Kite Connect plan (check the
   current price there), and note the API key and secret.
2. Create the private project folder, configuration and NSE session calendar.
   The bundled calendar follows NSE circulars NSE/CMTR/71775 and NSE/CMTR/72260
   for April to December 2026; add any special session NSE announces later.

```bash
mkdir -p data/observatory
python3 scripts/decision_pipeline.py init --config data/observatory/pipeline.json
cp skills/day-trader-india/assets/nse-sessions-2026.json data/observatory/sessions.json
```

## Every trading morning, before 09:15

Kite access tokens expire daily. Log in yourself; the helper exchanges the
one-time request token and saves the access token to `~/.india-trade-lab.env`
with owner-only permissions. It never prints the token.

```bash
export KITE_API_KEY=your_key KITE_API_SECRET=your_secret
python3 scripts/kite_login.py
source ~/.india-trade-lab.env
```

## Choose 1-10 stocks (monthly)

Download NSE's equity list in a browser from
`https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv`, then:

```bash
python3 scripts/make_universe.py --equity-list ~/Downloads/EQUITY_L.csv \
  --symbols INFY,TCS,RELIANCE --output data/observatory/universe.json
```

The symbols are examples, not recommendations. The universe expires after
30 days.

## Load history (weekly)

```bash
python3 scripts/data_sync.py --config data/observatory/pipeline.json --days 180 --max-symbols 3
```

Each stock needs at least 50 complete sessions; 180 days gives about 120.

## Create the forward paper book (once)

Use the same symbols. These limits sit inside the forward-practice ceilings.

```bash
python3 scripts/paper_book.py --book data/observatory/paper.sqlite init \
  --cash-inr 100000 --symbols NSE:INFY,NSE:TCS,NSE:RELIANCE \
  --risk-inr 250 --daily-loss-inr 750 --position-limit-inr 15000 \
  --max-trades 3 --max-open 2 --max-loss-streak 2 --drawdown-stop-inr 2000
```

## During market hours

Run the morning login first in each terminal, then:

```bash
python3 scripts/market_service.py --config data/observatory/pipeline.json --refresh-india
```

```bash
python3 scripts/observatory.py --data-dir data/observatory
```

Open `http://127.0.0.1:8765`. Live results appear in the **Daily research desk**
panel; the 3D funnel and session tape show synthetic replays.

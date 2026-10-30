# Pre-market report, specialist agents and the selection judge

`scripts/premarket.py` builds the morning watchlist before the open. It is
research only: it never writes the journal and never places an order. A pick
means "worth watching at the open"; an entry still needs a completed-bar signal,
fresh pre-trade evidence, the review roles and every journal gate.

## What each stock shows

| Item | Source |
|---|---|
| Trend, RSI(14), 5/20-session returns, ATR | Stored broker-export sessions (`technical.py`) |
| Sector and sector-index moves (1/5/20 sessions) | NSE index files; index closes you sync |
| Market-cap tier (large/mid/small) | NSE index membership: NIFTY 100 / MIDCAP 150 / SMALLCAP 250 |
| Liquidity | Mean close × volume over the last 20 stored sessions |
| F&O eligibility and lot size | NSE `fo_mktlots.csv`, shown for context only |
| Headlines and their tone | Google News, NSE announcements, ET Markets RSS (`sentiment.py`) |
| Broker calls (broker, rating, target) | Stated in headlines; the note itself is not obtained |

The desk trades **cash equity only**. F&O eligibility is marked so you can see
it, but no derivative position is sized or placed.

## How stocks are chosen

1. **Hard filters (code).** A stock enters the pool only with enough stored
   history, traded value at or above `min_turnover_inr`, a known NSE tier at or
   above `selection.min_market_cap_tier` (default `large`) and reference data no
   older than `selection.max_reference_age_days`. A stock that fails shows the
   reason on the page.
2. **Six specialist agents.** Each reads one slice of the evidence for every
   pooled stock and returns a stance (positive, neutral, negative, insufficient)
   citing evidence IDs from that slice only:
   `news-analyst`, `sentiment-analyst`, `technical-analyst`, `sector-analyst`,
   `liquidity-analyst`, `brokerage-analyst`.
3. **Sub-agents.** For each finalist (up to 10, set by `selection.finalists`), the judge spawns a risk scout
   (low, medium or high risk today) and a setup planner (which proven strategy
   fits, or none). Code drops any pick rated high risk or with no setup. See
   [strategy.md](strategy.md).
4. **Selection judge (final call).** Reads every assessment, the deterministic
   score and the evidence, then picks at most `max_candidates` stocks rated Buy
   or Overweight, with conviction, a cited reason and the proven strategy to
   trade it with. Picking none is allowed. When the tournament has proven no
   strategy, the report says `sit_out` and no model calls are made.

Guards around the judge: it can pick only from the filtered pool, at most the
configured number, citing each stock's own evidence. It cannot add a stock,
override a filter or size a trade. Headlines are passed as data under a rule to
ignore instructions inside them.

The report falls back to the deterministic ranking, and says why, when no model
is configured, the daily model-call budget cannot cover the seven calls, fewer
than `selection.min_specialists` specialists return valid output, or the
judge's answer is refused.

Model routing uses the existing settings: specialists use `quick_model`, the
judge uses `deep_model`, and `model_routes` can override any role. Raise
`max_output_tokens` to about 2500 for a pool of ten.

## Settings (`pipeline.json`)

```json
"selection": {
  "agents": true,
  "pool": 20,
  "min_specialists": 4,
  "min_market_cap_tier": "large",
  "max_reference_age_days": 7
},
"market_feeds": ["https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"],
"reference_db": "reference.sqlite",
"smtp_host": "smtp.gmail.com", "smtp_port": 587,
"smtp_user": "you@gmail.com", "email_to": "you@gmail.com"
```

Market feeds must be https on an allowlisted host (currently
`economictimes.indiatimes.com`). Feed headlines are matched to a stock by its
whole company name (without Ltd/Limited) or its symbol as a word.

## Morning routine

```bash
python3 scripts/reference.py --db data/observatory/reference.sqlite refresh
python3 scripts/reference.py --db data/observatory/reference.sqlite \
  sync-sector --index "NIFTY IT" --kite-token <index token from the Kite instrument dump>
python3 scripts/evidence.py collect --config data/observatory/pipeline.json
SMTP_PASSWORD=<Gmail app password> \
  python3 scripts/premarket.py --config data/observatory/pipeline.json --email
```

`sync-sector` also accepts `--csv` with Date and Close columns. Only completed
sessions are stored. For Gmail, use an app password (Google Account → Security →
App passwords) in the `SMTP_PASSWORD` environment variable. Never put it in
`pipeline.json` or Git.

## Limits

Sentiment is a finance word list applied to headline text, not a reading of the
articles; fewer than five scored headlines is an anecdote. Broker calls are what
a headline states. Market-cap tier is index membership, not a live
capitalisation. None of this is a forecast.

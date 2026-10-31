# Robustness: exchange reality, honest testing, operations and analytics

These tools make the paper results harder to fool yourself with and keep the desk
running unattended. Every rule here can only stop, shrink or measure a trade. None
can add a trade, raise risk or place an order.

## Exchange reality

| Tool | What it does |
| --- | --- |
| `charges.py` | Exact Zerodha charges for NSE cash equity, versioned by date (intraday: brokerage 0.03% or ₹20, STT 0.025% on the sell, stamp 0.003% on the buy; delivery: STT 0.1% both sides, stamp 0.015%, DP ₹15.34 a sale; both: NSE transaction charge, SEBI fee, IPFT, 18% GST). Used by both tournaments, sizing, the reward-after-costs rule and exits. Add a version when rates change; never edit an old one. |
| `surveillance.py` | Reads NSE's regulatory indicator file and the F&O ban list each morning. GSM, long-term ASM, ESM, suspension, insolvency and BZ/SZ block new entries; short-term ASM, add-on price band, pledge and F&O ban are shown as caution. Unread lists block entries (`surveillance.unknown_blocks`). |
| Calendar | Since 3 August 2026 F&O stocks leave continuous trading at 15:15 for the closing auction, so the desk squares off by 15:05. Muhurat (8 Nov 2026) is listed as no session. `intraday.py sync-calendar` (run each evening) brings an old `sessions.json` up to date and keeps a backup. |

## Honest testing

| Test | Rule |
| --- | --- |
| Better than luck | Each strategy's net result at doubled costs is compared with 200 random-entry twins on the same stocks with the same stop distance and exits. It must beat 95% of them (`validation.py`). |
| Deflated Sharpe | Every variant ever tested is recorded in `trials.json`. The per-trade Sharpe is deflated for that number of trials, skew and fat tails (Bailey and López de Prado, 2014); it must be at least 0.95. |
| Regime | `regime.py` labels each session `trend/volatility` (Nifty against its 50-day average; India VIX under 13, 13-20, above 20). Both tournaments record results per label. A strategy that lost on average in today's label over at least 20 trades sits out today. |
| Drift | `analytics.py` runs a one-sided CUSUM of paper R against the tournament's average R (k = 0.5R, h = 4R) and alarms when paper keeps falling short. |
| Slippage | `shadow.py` re-quotes each paper fill a minute later (the ask for a buy, the bid for a sell) and compares the measured 75th percentile with `slippage_bps`. |

## Portfolio caps (`portfolio.py`)

Across both books: total open risk at most 5% of combined starting capital (a
swing position counts at least one daily ATR a share, since a gap can open
through the stop), at most 2 positions per NSE sector, no new stock whose daily
returns correlate above 0.7 with a held one over 60 sessions, and, once a
strategy has 100 tournament trades, risk no larger than a quarter of its Kelly
fraction (win rate x (1 - 1 / profit factor)) of the book. Unknown sector or
history is noted, not blocked.

## Operations

| Tool | Schedule | What it does |
| --- | --- | --- |
| `watchdog.py check` | every 2 minutes | Missed login, scan or report, a stalled worker, unread surveillance lists, a journal checksum failure, a disk over 80% and no backup in 36 hours. Each problem is sent once a day, by Telegram when set up, else by email. From your own chat only: `/status`, `/pause` (creates `HALT_ENTRIES`; both desks stop entering, exits continue) and `/resume`. |
| `backup.py run` | 23:30 daily | Consistent SQLite copies of both journals, learning and service state, plus settings and scorecards. Encrypted with `openssl` AES-256 when `BACKUP_PASSPHRASE` is saved; 14 kept; copied off the machine with `backup.copy_to` (a folder or an rclone `remote:path`). Secrets are never included. `restore-test` runs on the 1st and verifies every journal checksum. |
| `bhavcopy.py sync` | 08:40 | NSE's full bhavcopy for recent sessions into `bhavcopy.sqlite`; `gaps`, `cross-check` against Kite closes, `breadth`. |
| `market_context.py build` | 08:40 | FII/DII flows, breadth and regime, shown to the sector and technical analysts as `#market` evidence. |

## Analytics (`analytics.py`)

Results of both books (expectancy in rupees and R, profit factor, charges), an R
histogram, swing MAE/MFE from daily candles, the equity curve and drawdown,
attribution by book, strategy, regime, weekday and entry hour, drift, slippage, a
plain-language story of each trade, and an estimated tax view per financial year
(intraday as speculative income at `tax.slab_rate_pct`; swing as STCG at 20%; both
plus 4% cess; not tax advice). Written to `performance.json` each evening and shown
on the dashboard's Performance page; emailed weekly on Fridays and monthly on the 1st.

The OpenRouter judge also has a monthly dollar cap (`openrouter.max_usd_per_month`,
default $10) next to the daily one; the dashboard shows spend by role.

## Deferred

- **A second live data source.** Kite is the only intraday feed. The bhavcopy
  archive is an official end-of-day second copy, which covers the daily data the
  scan, swing desk and regime use. A paid second intraday feed is not worth it for
  paper research.
- **Event study** (how stocks moved around results and similar events). It needs a
  few months of stored filings and the bhavcopy archive first; the archive now
  collects that data.

## Caveats

NSE may refuse scripted requests. Surveillance then blocks entries (by design),
and breadth or FII/DII flows are left out and said so. The FII/DII feed address is
NSE's own web API and may change. All thresholds are starting defaults, editable in
Settings. None of this has been tested against a live market session yet.

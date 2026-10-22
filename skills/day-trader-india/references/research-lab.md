# Expanded Indian research lab

Run these commands from the repository root with Python 3.10+. In an installed
copy, replace `scripts/` with `CORE_DIR/scripts/`. Keep all inputs, credentials,
books and results in your private project directory.

## Rank a daily watchlist without model calls

```bash
python3 scripts/research_lab.py universe --csv PROJECT/nifty500.csv \
  --source VERIFIED_MEMBERSHIP_SOURCE --as-of AWARE_ISO_TIMESTAMP \
  --output PROJECT/universe.json
python3 scripts/research_lab.py screen --daily-bars PROJECT/daily-bars.csv \
  --universe PROJECT/universe.json --benchmark NSE:NIFTY50 \
  --as-of AWARE_ISO_TIMESTAMP --top 10
```

Replace the uppercase placeholders with actual paths, sources and timestamps.
The membership importer accepts an NSE-format CSV with `Symbol`, `Series`,
`ISIN Code` and `Industry`; it keeps active EQ rows and sector names. Optional
`universe --download` uses one fixed NSE URL, bounded bytes and timeout, without
redirects or a fallback symbol list. A current membership snapshot is not a
historical membership database. Verify its publication time before evaluating
past dates. Add verified broker mappings separately for the current collector.

Supply a daily CSV with these columns:

```text
symbol,date,open,high,low,close,volume,source,close_at,available_at,price_basis,adjustment
```

Use aware timestamps for session close and the time that bar became available.
Availability cannot precede close. The loader excludes observations unavailable
at the requested cutoff. Source the session close from the applicable exchange
calendar; a declared timestamp is not independent proof of market closure.
`price_basis` is `price_return` or `total_return`; `adjustment` is
`split_adjusted` or `index_level`. Supply normalized split-adjusted equity prices
and a compatible benchmark. The tool does not fetch or verify corporate-action
adjustments. OHLCV must be finite, internally consistent and duplicate-free.

Ranking requires at least 61 completed, aligned stock/benchmark observations
for 20- and 60-session returns. It computes stock-minus-index return percentage
points, weights them 40/60, assigns a percentile among eligible instruments and
adds bounded pattern points. Low traded-value proxies and misaligned/mixed
price bases are rejected. Universe publication must be within 30 days of the
cutoff; the latest benchmark session must be within seven calendar days.
Those age checks do not prove exchange-session completeness.

Features include SMA20/50, Wilder RSI14, seeded EMA12/26 MACD with EMA9 signal,
14-observation **simple mean** true range, Bollinger width and volume ratio.
Labels cover closing-high breakout, RSI reclaim, near-high squeeze, trend
pullback, approximate ascending triangle and approximate cup/handle. These
are transparent heuristics, without calibrated probabilities or entry approval.
The screen emits WAIT_FOR_SETUP. It does not train a predictor.

In `pipeline.json`, set `screening_mode` to `relative_strength` and point
`daily_bars` and `benchmark_symbol` at those inputs. The default remains the
existing liquidity shortlist. Either mode still requires the separate 50-session
intraday history gate, a new completed-bar ORB signal and all entry evidence.
Daily screening does not provide an automatic daily-data subscription or expand
the mapped collector beyond its existing one-to-three-symbol limit.

## Use opposing reviews and explicit model routing

Set `review_workflow` to `intraday_debate` for ten separately prompted roles:
data, news, analyst, sentiment, screener, bull, bear, budget, risk and reviewer.
Both research sides reach budget/risk/final review. One bounded round avoids
unlimited debate costs. Every required veto survives; there is no majority
permission to trade. The six-role `intraday` workflow remains the default.

Set `model_provider` to `openai`, `anthropic` or `gemini`, then set `model` to an
explicit supported structured-output model ID. API keys belong only in the
worker environment: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`.
Optional `quick_model` covers data/news/screener/sentiment; `deep_model` covers
the other roles. Blank values inherit `model`. Override a role with:

```json
{"model_routes":{"india-bear":{"provider":"anthropic","model":"YOUR_SUPPORTED_MODEL_ID"}}}
```

Requests use fixed official HTTPS hosts, no model tools, no credential-bearing
redirects, no automatic retry or provider fallback. Model access is lazy: an
unused override does not require its key. Missing keys block the affected role.
`model_timeout_seconds` bounds each request to 1–30 seconds;
`max_output_tokens` bounds output to 400–8000 (default 1200). Optional
`reasoning_effort` applies to OpenAI only. Choose a model supporting those API
fields. Usage counters, provider, model and response receipts are retained when
supplied. The daily call budget reserves six or ten calls per candidate,
including failed requests. It is not an exact currency spending cap.

Official contracts: [OpenAI](https://developers.openai.com/api/docs/guides/structured-outputs),
[Anthropic](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
[Gemini](https://ai.google.dev/api/generate-content).
Adapters are covered by mocked transport tests; authenticated model calls have
not been exercised. Market evidence is sent to your selected provider.

## Recover an interrupted review

```bash
python3 scripts/decision_pipeline.py run --config PROJECT/pipeline.json --resume
```

SQLite checkpoints retain normalized handoffs and their proposal binding. Resume
requires unchanged input fingerprints, matching dependency/run/symbol/time/hash,
and the original 120-second freshness window. Saved blocks remain blocks.
An expired quote or changed book still prevents a proposal. Reserved calls are
conservatively charged again on resume. Completed runs return archived results;
resume does not reroll a failed completed review until it agrees.

The next review receives up to 20 resolved paper outcomes, clearly labelled
untrusted observations. This is outcome context, not model training, autonomous
strategy rewriting or permission to loosen risk. At most one ranked passing
entry is selected per book snapshot; other passing entries wait for allocation.
Selection neither reserves cash nor records a fill.

## Measure paper outcomes against matching benchmark windows

```bash
python3 scripts/paper_analytics.py --book PROJECT/paper.sqlite \
  --quotes PROJECT/quotes.json --benchmark PROJECT/benchmark-quotes.json \
  --as-of AWARE_ISO_TIMESTAMP --operating-cost-inr 0 \
  --save PROJECT/performance.sqlite
```

`--quotes`, `--benchmark` and `--save` are optional. Missing fresh open-position
quotes leave total equity/unrealized/net results unknown. Closed P&L remains
available. Marks use bid, assumed exit slippage and fees. Recorded fees are
shown separately and are not deducted twice. Operating cost is an explicit
cumulative assumption, not an automatic bill import or income-tax calculation.
The coordinator also includes a read-only performance report in each run; the
local research desk opens its details separately from synthetic replay results.

Benchmark JSON contains `symbol`, `price_basis: price_return`, and
`observations: [{as_of,price_inr,source}]`. Each closed trade needs observations
at or before both fill times, no more than 120 seconds old. Missing windows
leave alpha unscored; a daily close cannot substitute for an intraday mark.
Alpha is net trade return minus the matched price-index return in percentage
points, not a cash-matched portfolio benchmark or risk-adjusted alpha.

Reports show daily closed P&L, win rate, expectancy, profit factor, closed-trade
drawdown and overlapping pattern groups. Use manual buy flags `--target-inr`,
`--patterns ORB,PULLBACK_IN_UPTREND` and `--strategy-version MY_VERSION` to retain
reviewed attribution. Unlabelled history stays unlabelled. Targets are retained
and can produce protective exit proposals; the manual journal does not execute
them. Neither small samples nor a high win rate demonstrate profitability.

New books have a stable ID. Saved performance snapshots reject mixed books,
conflicting timestamps and backward insertion; observed drawdown starts at
initial cash. Sampled equity drawdown cannot reveal unsampled intraday moves.
Legacy books can be reported without changing history; saving requires an
existing book ID. Preserve their reports separately rather than rewriting the
journal or erasing losses. No records expire automatically.

## Upstream comparison and boundaries

Reviewed 2026-10-22. These are relevant public projects, not a verified ranking
of today's GitHub Trending page. This release uses original standard-library
implementations of selected ideas; it installs none of these frameworks and
copies no upstream source code.

| Project | Relevant idea | India Trade Lab result |
| --- | --- | --- |
| [Gathin23/TradingAgents](https://github.com/Gathin23/TradingAgents/tree/73471745c7900e0a47e04abbb8181d8bc6a78fd3) (Apache-2.0) | Relative-strength funnel, patterns, analyst teams, opposing researchers, quick/deep models, recovery and memory | Daily screen, three new portable roles, ten-role workflow, explicit provider routing, fresh checkpoints and resolved-outcome context |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) (MIT) | Separate research and paper records, portfolio review and benchmark results | Separate existing forward/replay journals, one selected entry per snapshot, added paper performance and benchmark windows; no autonomous allocation optimizer |
| [microsoft/qlib](https://github.com/microsoft/qlib) (MIT) | Point-in-time research and reproducible experiment workflows | Explicit availability/price basis, fixed rule version and existing input/config fingerprints; Qlib training, factor mining and rolling optimization are not implemented |
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) (GPL-3.0) | Dry runs, cost-aware evaluation and lookahead checks | Existing paper replay and doubled-cost stress retained; added future-availability regression checks. This is not Freqtrade's strategy-wide lookahead-analysis or exchange execution engine |

No arbitrary provider host, local-model loader, social scraping, automatic
strategy promotion, US strategy, crypto fill engine, leveraged product or live
exchange order route is added. The existing Binance adapter remains read-only.
A ₹80,000 daily goal stays reporting metadata; no profit floor is enforceable.

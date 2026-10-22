# Historical memory

Persist five-minute candles, source labels, complete session boundaries, import
times and content digests in a separate SQLite history database. Importing the
same session twice is idempotent. Conflicting revisions are refused; retain
revisions in separate databases and investigate the source before comparing them.

## Research policy

The default minimum is **50 completed exchange sessions per symbol**, not
50 calendar days and not two days. This is a configurable engineering baseline
for research coverage. It does not prove that a strategy has an edge. Consider
longer history across different volatility/trend regimes and a separate unseen
validation period before interpreting a pattern. The 252-session context target
is informational; this code does not automatically fetch that history.

The coverage tool reports prior complete broker-export sessions, separately
counted synthetic sessions, first/last market dates, missing declared sessions
and 20/50-session moving averages when enough observations exist. It uses only
sessions closed by the explicit cutoff. These averages describe prices; the ORB
strategy does not learn or retrain from them.

`broker_export` is a user-declared provenance label, not authenticated provider
verification. A renamed CSV is not proof of a real market source. Verify the
instrument master, exchange calendar, price-adjustment basis and source before
using imports. The source manifest must explicitly declare every expected
session in the research window, including sessions missing entirely from the CSV.
A coverage report cannot detect exchange sessions omitted from that manifest.

## CLI

Resolve `SKILL_DIR` to this installed skill folder and `PROJECT` to private data.
First exercise the synthetic import:

```bash
python3 SKILL_DIR/scripts/history.py --db PROJECT/history.sqlite import \
  --bars SKILL_DIR/assets/synthetic-bars.csv \
  --sessions SKILL_DIR/assets/synthetic-sessions.json \
  --symbol NSE:DEMO --kind synthetic --as-of 2026-10-19T15:30:00+05:30

python3 SKILL_DIR/scripts/history.py --db PROJECT/history.sqlite coverage \
  --symbol NSE:DEMO --as-of 2026-10-19T15:30:00+05:30 --minimum-sessions 50
```

For verified broker CSV exports, change paths/symbol and declare
`--kind broker_export`. Use the existing five-minute CSV schema and a sourced,
complete session manifest. Do not put either data or broker credentials in Git.
There is no automatic deletion: archive/back up the history database explicitly.
Run decisions, rejections and assumed fills remain in each run's journal/log.

Forward engine entries require this coverage through `history_provider`; no
current bundled strategy generates the other required forward evidence. Missing
coverage is a data block. Replay is allowed for software tests and is labelled
synthetic. Crypto calendars and exchange adapters are separate future work.

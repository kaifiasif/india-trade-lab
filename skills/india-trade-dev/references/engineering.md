# Engineering and writing standards

## Code structure

Use Python 3.10+ and the standard library for runtime tools. Keep optional
development dependencies pinned in `requirements-dev.txt`. Separate input
validation, domain calculations, persistence and CLI orchestration. Use type
annotations at public function boundaries; represent provider JSON explicitly
and validate it before treating values as domain data. This project does not
currently enforce full static type checking.

Use descriptive names, four-space indentation and Ruff's 100-column formatter.
Avoid compressed statements, unrelated changes and broad catch-all exceptions.
Document units, timezone assumptions and failure behaviour. Use UTF-8 for text
files and timezone-aware timestamps. Do not change a CLI flag or output field
without documenting the migration and updating its tests.

## Financial and data boundaries

Keep Decimal arithmetic for persisted cash and journal charges. The historical
research engine uses floating-point arithmetic; preserve its stated precision
limits and rounding assumptions. Never imply these are exact exchange fills.
Require explicit fees, slippage, sources and quote times. Treat missing, stale
or contradictory evidence as a blocked action rather than a default approval.

Validate date ranges, instruments and provider response shapes. Use GET-only
broker adapters with finite timeouts and response limits. Reject redirects so
credentials cannot be forwarded to another host. Never log headers, tokens,
response bodies containing account data, passwords or TOTP seeds.

Keep journal state transitions pure until validation passes; persist under one
SQLite transaction. Reject duplicate IDs. Preserve existing books, loss records
and risk stops. No live-order endpoint, automated login or live-mode toggle
belongs in the paper workflow.

## Verification

Run `python scripts/check.py` from the checkout root. It checks Ruff lint and
formatting, all skill manifests, local documentation links generated-agent drift and offline unit
tests. Add tests for changed behaviour, including rejection and boundary
cases. Mock external calls. Test invalid provider responses without exposing
raw responses. Never add a test that silently calls a real broker.

Build the ZIPs and run a copied skill from a temporary directory. Check that it
does not require sibling repository files. Do not report remote CI or an
authenticated broker integration as passing unless its result was observed.
Passing tests says nothing about a strategy's future performance.

## Technical writing

Start setup instructions with prerequisites and the working directory. Show a
small working example before optional detail. Label placeholders clearly and
keep secret values out of commands. Prefer a capability table to vague claims.
Separate instructions for Claude web, Claude Code and local coding assistants;
their filesystems, permissions and persistence differ.

For research reports, state the observation time, timezone, source and data
quality. Present net results after explicit cost assumptions. Explain what the
code enforced, what a person checked and what remains missing. Use NO TRADE or
DATA BLOCK when appropriate. Avoid invented data, unqualified return claims,
empty adjectives and repeated warnings that obscure the next useful step.

For change reports, describe the resulting behaviour, how it was checked and
material limits. Use concise commit subjects describing the change. Keep PRs
reviewable and distinguish local checks from GitHub Actions results.

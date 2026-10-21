# Repository instructions

Read [engineering standards](skills/india-trade-dev/references/engineering.md)
before changing code or documentation. These instructions apply to the repo.

- Keep runtime tools in `skills/day-trader-india/scripts/`; root CLI files are
  compatibility wrappers. Do not maintain two copies of the trading engine.
- Keep skills portable and declare core dependencies. Install complete folders, not only `SKILL.md`.
- Keep native profiles generated from role skills; run `python scripts/generate_agents.py` after role edits.
- Keep broker adapters read-only and paper books separate from source control.
- Preserve documented CLI flags, Decimal journal accounting and refusal paths.
- Use clear function names, annotations at public boundaries and concise docstrings.
- Run `python scripts/check.py` and package skills after editing their resources.
- Explain changed behaviour and actual checks. Mark planned or untested work plainly.

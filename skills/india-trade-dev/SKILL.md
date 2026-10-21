---
name: india-trade-dev
description: "Maintain India Trade Lab code, portable AI skills and technical documentation. Use when adding or reviewing broker-data adapters, changing paper-journal risk rules, fixing tests, packaging skills, improving coding standards or rewriting project instructions. Preserve paper-only execution and distinguish implemented behaviour from planned work."
---

# Maintain India Trade Lab

Read [engineering.md](references/engineering.md) for code, test and writing standards.
Apply this skill when working on an India Trade Lab checkout; it contains no trading engine.

## Inspect before changing

1. Read the checkout's `AGENTS.md`, `CONTRIBUTING.md` and `pyproject.toml`.
2. Find the implementation and tests. Resolve `REPO` to that checkout;
   resolve `SKILL_DIR` to this installed skill folder. Do not assume they coincide.
3. State the concrete behaviour to improve and preserve documented CLI compatibility.
4. Keep domain changes in `skills/day-trader-india/scripts/`; keep distribution
   and validation tooling in `scripts/`, tests in `tests/` and user setup in `docs/`.

## Implement and verify

- Use small named functions, descriptive names, public function annotations and
  docstrings that explain assumptions. Let Ruff enforce formatting and imports.
- Keep broker access read-only. Validate input and provider schemas, set timeouts,
  reject credential-bearing redirects and redact failures. Do not add order routes.
- Preserve Decimal accounting in the paper journal, atomic persistence and unique
  event IDs. Do not reset history or loosen limits to make an entry pass.
- Add regression tests for changed behaviour, boundary cases and refused actions.
  Use synthetic fixtures and mocked transports; never rely on broker credentials.
- Run `python scripts/check.py` from `REPO` after installing development requirements.
  If something cannot run, name that check and its blocker. Never label it passed.
- Regenerate native profiles with `python scripts/generate_agents.py` after role edits.
  Run `python scripts/package_skills.py` after changing skill contents. Exercise
  an installed copy outside the repository to catch missing relative resources.
- Keep skill instructions self-contained and declare role dependencies with standard `name` and `description` frontmatter.
  Avoid client-specific dynamic commands or assumed tools in shared instructions.

## Write and report clearly

- Lead with what works and the command to use it. Use short sentences,
  concrete verbs, consistent names and tables only for useful comparisons.
- Separate shipped, manually reviewed and planned capabilities. Call replay data
  synthetic when appropriate. Do not describe test success as profitable trading.
- Resolve relative paths from the documented working directory. Run examples
  against fixtures before publishing them; keep credentials out of all examples.
- Report the resulting behaviour, relevant checks and remaining limitations.
  Link changed repository files and commits. Avoid unsupported "production-ready",
  "safe", "guaranteed" and "loss-free" claims.

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

## Security baseline (every change)

Before calling work done, run the backend-design security-discipline audit and
confirm each item that applies. Mark items that do not apply and say why.

- XSS: strict CSP (no inline script or style injection), escaped output, no
  `dangerouslySetInnerHTML` with data from outside the repo.
- CSRF: same-origin check plus the per-process session token on every write.
- Uploads: validate type, size and content on the server.
- Authorization: every route checked on the server (loopback host, token);
  object IDs validated before use. Rate-limit writes.
- Secrets and API keys stay server side in the owner-only store; never in the
  web bundle, JSON config, logs, PR text or chat.
- If user accounts are ever added: a vetted password hash (argon2id or scrypt)
  and MFA. If Postgres or Supabase is added: row-level security.
- Webhooks: verify signatures. Outbound URLs: allowlisted hosts, no redirects,
  timeouts, no private or link-local addresses.
- No source maps in production builds, no default credentials, no secrets or
  personal data (emails are masked) in logs.
- `npm audit` in `web/` must report 0 vulnerabilities; pin exact versions at
  least two weeks old.

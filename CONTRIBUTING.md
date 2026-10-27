# Contributing

Use Python 3.10 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/check.py
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell. Runtime
commands require no pip dependencies. Development checks require the pinned
tools above.

Follow [engineering and writing standards](skills/india-trade-dev/references/engineering.md).
Format code with `python -m ruff format .`; apply reviewed lint fixes with
`python -m ruff check --fix .`. Add behaviour-focused tests for code changes.
Tests must use synthetic data and mocked broker responses, never real accounts.

Regenerate native profiles with `python scripts/generate_agents.py` after role edits.
The checker rejects drift between role instructions and checked-in profiles.

Build portable packages with `python scripts/package_skills.py`. Run the copied
skill outside this checkout before submitting packaging changes. The automated
tests cover copied resources, overwrite refusal and reproducible ZIP contents.

Keep commits focused. Describe the problem, resulting behaviour, relevant checks
and limitations in the PR. Never commit tokens, exports, journal databases or
logs. GitHub Actions runs offline checks on Python 3.10 and 3.12 and uploads the
skill packages; see the workflow for the exact commands. Passing CI does not
demonstrate profitable trading or verified broker access.

The observatory is a React 18 + Vite + Tailwind app in `web/`. Its build is
committed to `skills/day-trader-india/assets/observatory/` so the skill runs with
Python alone. After changing anything in `web/`:

```bash
cd web
npm ci
npm run build   # type-checks, then writes the bundle into the skill
```

Commit `web/` and the rebuilt `assets/observatory/` together. The page runs under
a strict Content-Security-Policy (`script-src 'self'; style-src 'self'`): no
inline scripts, no injected `<style>` tags, no CDNs. GSAP and React set styles
through the DOM, which the policy allows. The optional `recap-video/` folder is
a separate Node project; check it with `npm run lint` there.

Browser checks should cover every page in light and dark themes, the setup steps
with a fresh data folder, empty and server-offline states, keyboard access,
reduced motion and a 390px-wide viewport.
The Python API tests exercise actual synthetic replays and reject unauthorized
control requests. Keep archived previews clearly distinct from a connected engine.

# Install the skills

This repository contains seventeen portable Agent Skills: a coordinator/runtime,
fifteen specialist roles and a developer skill. Start with the coordinator;
see the [complete role map](../skills/day-trader-india/references/agent-workflow.md).

| Skill | Purpose | Source |
| --- | --- | --- |
| `day-trader-india` | Indian cash-equity research, historical replay and manual paper trading | [Skill folder](../skills/day-trader-india/) |
| `india-trade-dev` | Maintain this project with consistent code, tests and documentation | [Skill folder](../skills/india-trade-dev/) |

Copy complete folders, including bundled scripts and references. Specialist
roles depend on `day-trader-india`; the installer includes that dependency. A lone
`SKILL.md` cannot run the tools. Installation does not connect a broker or
start a trading service.

## Download once

Install Python 3.10+ and Git. In your terminal:

```bash
git clone https://github.com/kaifiasif/india-trade-lab.git
cd india-trade-lab
```

All commands below run from that checkout root. On Windows, use `python`
instead of `python3` if that is your Python 3 command. The installer uses only
the standard library; development dependencies are optional.

## Claude Code

Install the complete skill pack and native specialist agents for your local projects:

```bash
python3 scripts/install_skills.py --platform claude --scope user --with-agents
```

This creates seventeen skill folders under `~/.claude/skills/` and fifteen
restricted agent profiles under `~/.claude/agents/`. Omit `--with-agents` to
install only skills. Open Claude Code's skill selector or start
a new session, then use:

```text
/day-trader-india Help me run the bundled synthetic example. Keep every trade virtual.
/india-trade-dev Review this checkout's code and documentation, then run its checks.
```

For one project instead, use `--scope project --project /path/to/project`.
This installs under that project's `.claude/skills/` and, with `--with-agents`,
`.claude/agents/`. These instructions follow
the [official Claude Code skill documentation](https://code.claude.com/docs/en/skills).

## Codex

```bash
python3 scripts/install_skills.py --platform codex --scope user --with-agents
```

This creates seventeen skill folders under `~/.agents/skills/` and fifteen
native profiles under `~/.codex/agents/`. For a repository install,
use `--scope project --project /path/to/project`, which targets `.agents/skills/` and `.codex/agents/`.
Reopen the skill selector or session and ask:

```text
Use $day-trader-india to explain Indian stock paper trading with ₹1,00,000 virtual capital.
Use $india-trade-dev to improve this checkout and verify its code and documentation.
```

These are the local discovery paths in the
[official OpenAI documentation](https://learn.chatgpt.com/docs/build-skills).
Hosted products can use a separate skill-management interface; local installs
do not automatically upload a skill to another account or cloud workspace.

## Delegate to the native agents

After a Claude/Codex install with `--with-agents`, start a new session and ask:

```text
Use day-trader-india as coordinator. Delegate data, news, screening, budget and
risk reviews to the India specialists, then ask india-reviewer for an independent
challenge. Use only supplied verified evidence; block missing inputs. Keep every
trade virtual and show the review before recording anything.
```

Claude Code profiles have a `Read, Grep, Glob` allowlist. Codex profiles disable
shell, app, plugin, memory and permission-request capabilities supported by its
custom-agent format. Other permissions/MCP servers come from the parent, so
keep order-capable connectors out of that session. These profiles are research
workers: even `india-paper-broker` returns a proposal; the coordinator runs
the journal for a separately requested virtual record. Agent launch/UI and
capability support depend on the installed host version.

`--agent-destination /path/to/agents` overrides the native profile destination;
`--destination` overrides only the skill destination. Native profiles are
available only for Claude/Codex in this installer. Existing skill/profile files
are refused before mutation. Selecting one role with `--skill india-risk`
includes its core dependency; existing dependencies are not overwritten or
silently reused. Use an empty destination or back up the prior pack to update.

Read [the workflow contract](../skills/day-trader-india/references/agent-workflow.md)
for plans, proposal digests and handoff validation. See the official
[Claude subagent documentation](https://code.claude.com/docs/en/sub-agents) and
[Codex subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents)
for native discovery and inherited permissions.

### Claude Code plugin alternative

Instead of copying folders, add this repository's marketplace:

```text
/plugin marketplace add kaifiasif/india-trade-lab
/plugin install india-trade-lab@india-trade-lab
```

The plugin manifest includes all skills and the fifteen Claude agent profiles.
Plugin skills use names such as `/india-trade-lab:day-trader-india`. Choose one
installation method to avoid duplicate skills. The manifest/path checks run
offline; native plugin loading has not been exercised in this environment.

## Claude web and Desktop / Cowork

Build one ZIP per skill:

```bash
python3 scripts/package_skills.py
```

The output is `dist/day-trader-india.zip`, `dist/india-trade-dev.zip` and a
SHA-256 checksum manifest, plus one ZIP for each of the fifteen specialist skills. Each archive contains a single named skill folder
with `SKILL.md` and all its resources.

Enable **Code execution and file creation**, then open **Customize > Skills**.
Choose **+ > Create skill > Upload a skill**, upload the core ZIP and any role ZIPs you need, and enable them. The developer
skill is optional for trading research. Uploading role skills does not install
native Claude Code subagents; those use the local installer.
Ask Claude to use `day-trader-india` by name. See
[Claude's official instructions](https://support.claude.com/en/articles/12512180-use-skills-in-claude)
for account and organization requirements.

Claude web's execution environment is separate from your laptop. Local broker
environment variables and SQLite books are not transferred by uploading a
skill. Start with synthetic fixtures there; use authorized local data exports
only when the host supports them. Check where that host saves results before
using a continuing practice journal.

## Cursor and GitHub Copilot

Choose your client:

```bash
python3 scripts/install_skills.py --platform cursor --scope user
python3 scripts/install_skills.py --platform copilot --scope user
```

| Client | Project location | Personal location | Usage |
| --- | --- | --- | --- |
| Cursor | `.cursor/skills/` | `~/.cursor/skills/` | Type `/` in Agent chat and select the skill |
| Copilot | `.github/skills/` | `~/.copilot/skills/` | Ask the agent to use the named skill; support depends on the Copilot surface |

Use `--scope project --project /path/to/project` to share skills with a repo.
See [Cursor skills](https://cursor.com/docs/skills) and
[Copilot CLI skills](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills)
for discovery rules. Local personal installs do not automatically reach cloud
agents. Follow the client's documented sync or repository installation path.

## Other agents

If the host supports the Agent Skills standard, copy either complete folder
from `skills/` into its documented skill directory. You can also extract a
generated ZIP there. Use `--destination /path/to/skills` to override the
installer's destination; it still requires a platform selection as a label.
Do not assume every chat app can discover skills or run Python.

If a host only supports instruction files, attach `SKILL.md` and the relevant
references for guidance. It cannot run this project's tools without Python
and access to the bundled resources. Prompt-only use is not a broker connector.

## Verify, update or remove

1. Confirm the client's selector lists the skill by name.
2. Ask it to locate the installed folder and run the synthetic scan documented
   in `day-trader-india/SKILL.md`.
3. Confirm it labels the output synthetic and research-only.

The installer prints the exact paths and refuses to overwrite existing skills.
To update, run `git pull`, back up the named installed folders outside the
client's discovery directory, remove those old installed folders and rerun the
installer. Rebuild and re-upload ZIPs for Claude web. To uninstall, remove only
only this pack's named skill folders and, if installed, its fifteen native
profile files, or disable/remove uploaded skills in the host UI.
Never delete a parent skill directory containing other skills.

The developer skill runs against an India Trade Lab source checkout. Its
references travel with it, but development tools and tests remain in that
checkout. No skill grants new tool permissions or guarantees model
compliance; deterministic checks and the journal enforce only their stated rules.

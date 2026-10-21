#!/usr/bin/env python3
"""Generate deterministic, read-only Claude and Codex specialist profiles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from skill_tools import AGENT_PLATFORMS, ROLE_SKILLS, ROOT

HANDOFF_RULES = """## Specialist execution boundary

You are a read-only specialist working for the India Trade Lab coordinator.
Review evidence and return findings, assumptions, missing data, and a proposed
next step to the parent. Do not delegate further or start a background service.
Return NO TRADE or DATA BLOCK when required evidence is missing or contradictory.

Do not use shell, write or edit files, change configuration, or mutate any journal.
Do not call brokerage, account, order, execution, or other side-effecting MCP tools,
even if inherited from the parent. Never place, amend, cancel, or route orders.
The parent must not expose order-capable MCP tools to this specialist. Platform
feature flags are a tool restriction, not a separate sandbox or a guarantee that
inherited MCP permissions are removed. Keep the parent's permissions restrictive.

Even india-paper-broker returns a proposal only. The coordinator alone may run
the offline paper journal after all required evidence, risk checks, and user
instructions have been satisfied. Never report a proposed action as completed.

The coordinator must supply the installed role skill and day-trader-india core
resource paths. Resolve references in the role instructions relative to that
installed role skill, not this agent file. Ask the parent for required resources
that are unavailable; never invent their contents or claim a check was run.

## Role instructions (generated from the portable skill)
"""


def read_role(name: str, root: Path = ROOT) -> tuple[str, str]:
    """Read the two-field portable frontmatter without a YAML runtime dependency."""
    if name not in ROLE_SKILLS:
        raise ValueError(f"Unknown specialist role: {name}")
    source = root / "skills" / name / "SKILL.md"
    text = source.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"Missing portable frontmatter: {name}")
    header, body = text[4:].split("\n---\n", 1)
    metadata: dict[str, str] = {}
    for line in header.splitlines():
        key, separator, raw = line.partition(":")
        if not separator or key not in {"name", "description"} or key in metadata:
            raise ValueError(f"Invalid portable frontmatter: {name}")
        value = raw.strip()
        if value.startswith('"'):
            value = json.loads(value)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Invalid {key}: {name}")
        metadata[key] = value
    if set(metadata) != {"name", "description"} or metadata["name"] != name:
        raise ValueError(f"Invalid portable frontmatter: {name}")
    return metadata["description"], body.strip()


def profile_payloads(
    platform: str, names: list[str] | tuple[str, ...] = ROLE_SKILLS, root: Path = ROOT
) -> dict[str, str]:
    """Render profiles from role sources; no model override or order tool access."""
    if platform not in AGENT_PLATFORMS:
        raise ValueError("Native agents are supported only for Claude and Codex")
    payloads = {}
    for name in dict.fromkeys(names):
        if name not in ROLE_SKILLS:
            continue
        description, body = read_role(name, root)
        instructions = HANDOFF_RULES + "\n" + body + "\n"
        if platform == "claude":
            payloads[f"{name}.md"] = (
                f"---\nname: {name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n"
                "tools: Read, Grep, Glob\nmodel: inherit\n---\n\n" + instructions
            )
        else:
            # Preserve Unicode scalars: JSON surrogate-pair escapes are invalid TOML.
            payloads[f"{name}.toml"] = (
                f"name = {json.dumps(name)}\n"
                f"description = {json.dumps(description, ensure_ascii=False)}\n"
                f"developer_instructions = {json.dumps(instructions, ensure_ascii=False)}\n\n"
                "[features]\n"
                "shell_tool = false\napps = false\nplugins = false\nmemories = false\n"
                "request_permissions_tool = false\n"
            )
    return payloads


def generate_profiles(root: Path = ROOT, *, check: bool = False) -> list[Path]:
    """Write checked-in profiles, or reject missing, stale, and unexpected files."""
    expected = {
        root / "agent_profiles" / platform / filename: content
        for platform in AGENT_PLATFORMS
        for filename, content in profile_payloads(platform, root=root).items()
    }
    if check:
        actual = {path for path in (root / "agent_profiles").rglob("*") if path.is_file()}
        if actual != set(expected):
            raise ValueError("Native profile file list differs; run scripts/generate_agents.py")
        for path, content in expected.items():
            if path.read_bytes() != content.encode("utf-8"):
                raise ValueError(f"Stale native profile: {path.relative_to(root)}")
    else:
        for path, content in expected.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    return list(expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Refuse stale generated profiles")
    args = parser.parse_args()
    try:
        profiles = generate_profiles(check=args.check)
    except (ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"{'Checked' if args.check else 'Generated'} {len(profiles)} native agent profiles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

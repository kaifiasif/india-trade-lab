#!/usr/bin/env python3
"""Install complete skills for a supported client. Never replace existing files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from skill_tools import AGENT_PLATFORMS, PLATFORMS, SKILLS, install_skills


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=PLATFORMS, required=True)
    parser.add_argument("--scope", choices=("project", "user"), default="project")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--skill", choices=(*SKILLS, "all"), default="all")
    parser.add_argument("--destination", type=Path, help="Override the client skill directory")
    parser.add_argument(
        "--with-agents", action="store_true", help="Also install read-only Claude/Codex specialists"
    )
    parser.add_argument(
        "--agent-destination", type=Path, help="Override native agent directory (not skills)"
    )
    args = parser.parse_args()
    if args.with_agents and args.platform not in AGENT_PLATFORMS:
        parser.error("--with-agents supports only Claude and Codex")
    if args.agent_destination and not args.with_agents:
        parser.error("--agent-destination requires --with-agents")
    locations = PLATFORMS[args.platform]
    destination = args.destination or (
        args.project / locations[0] if args.scope == "project" else Path.home() / locations[1]
    )
    names = list(SKILLS) if args.skill == "all" else [args.skill]
    agent_destination = None
    if args.with_agents:
        agent_location = AGENT_PLATFORMS[args.platform]
        agent_destination = args.agent_destination or (
            args.project / agent_location
            if args.scope == "project"
            else Path.home() / agent_location
        )
    try:
        for path in install_skills(
            names,
            destination,
            agent_platform=args.platform if args.with_agents else None,
            agent_destination=agent_destination,
        ):
            print(f"Installed {path.name}: {path}")
    except (ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if agent_destination is not None:
        print(f"Installed read-only specialist profiles: {agent_destination}")
    print("Reopen your client's skill selector. Installation starts no trading service.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

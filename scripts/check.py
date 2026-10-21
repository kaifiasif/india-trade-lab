#!/usr/bin/env python3
"""Run the same lint, format, skill/document validation and tests as CI."""

from __future__ import annotations

import os
import subprocess
import sys

from skill_tools import ROOT


def main() -> int:
    environment = dict(os.environ)
    imports = [str(ROOT / "skills/day-trader-india/scripts"), str(ROOT / "scripts")]
    if environment.get("PYTHONPATH"):
        imports.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(imports)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    commands = [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "scripts/validate_skills.py"],
        [sys.executable, "scripts/generate_agents.py", "--check"],
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
    ]
    for command in commands:
        print("+ " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

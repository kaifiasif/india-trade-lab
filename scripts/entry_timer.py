#!/usr/bin/env python3
"""Run the portable entry_timer tool from the repository root."""

import runpy
import sys
from pathlib import Path

# A named floor: these wrappers are the entry point, so a reader on an older
# interpreter gets this message instead of a SyntaxError from the skill module.
MINIMUM_PYTHON = (3, 10)

if sys.version_info[:2] < MINIMUM_PYTHON:
    sys.exit(
        "India Trade Lab needs Python {}.{} or newer; this is {} ({}).\n".format(
            *MINIMUM_PYTHON, sys.version.split()[0], sys.executable
        )
        + "macOS ships an older python3. Install a newer one, for example:\n"
        "  brew install python@3.12 && python3.12 -m venv .venv && source .venv/bin/activate\n"
        "  (or: curl -LsSf https://astral.sh/uv/install.sh | sh && uv venv --python 3.12 .venv)"
    )

if __name__ == "__main__":
    skill_scripts = Path(__file__).resolve().parents[1] / "skills/day-trader-india/scripts"
    sys.path.insert(0, str(skill_scripts))
    runpy.run_path(str(skill_scripts / "entry_timer.py"), run_name="__main__")

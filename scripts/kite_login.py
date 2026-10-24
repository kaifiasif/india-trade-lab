#!/usr/bin/env python3
"""Run the portable kite_login tool from the repository root."""

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    skill_scripts = Path(__file__).resolve().parents[1] / "skills/day-trader-india/scripts"
    sys.path.insert(0, str(skill_scripts))
    runpy.run_path(str(skill_scripts / "kite_login.py"), run_name="__main__")

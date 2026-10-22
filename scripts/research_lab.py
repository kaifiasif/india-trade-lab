#!/usr/bin/env python3
"""Launch portable daily relative-strength research."""

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    scripts = Path(__file__).resolve().parents[1] / "skills/day-trader-india/scripts"
    sys.path.insert(0, str(scripts))
    runpy.run_path(str(scripts / "research_lab.py"), run_name="__main__")

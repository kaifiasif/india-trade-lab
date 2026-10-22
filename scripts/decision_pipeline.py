#!/usr/bin/env python3
"""Launch the portable daily research coordinator."""

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    scripts = Path(__file__).resolve().parents[1] / "skills/day-trader-india/scripts"
    sys.path.insert(0, str(scripts))
    runpy.run_path(str(scripts / "decision_pipeline.py"), run_name="__main__")

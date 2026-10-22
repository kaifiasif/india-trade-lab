#!/usr/bin/env python3
"""Run the portable historical-coverage tool from the checkout root."""

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    scripts = Path(__file__).resolve().parents[1] / "skills/day-trader-india/scripts"
    sys.path.insert(0, str(scripts))
    runpy.run_path(str(scripts / "history.py"), run_name="__main__")

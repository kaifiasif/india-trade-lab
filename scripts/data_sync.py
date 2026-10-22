#!/usr/bin/env python3
"""Collect entitled Indian historical candles using portable data tools."""

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    scripts = Path(__file__).resolve().parents[1] / "skills/day-trader-india/scripts"
    sys.path.insert(0, str(scripts))
    runpy.run_path(str(scripts / "data_sync.py"), run_name="__main__")

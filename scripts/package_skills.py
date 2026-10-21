#!/usr/bin/env python3
"""Build self-contained skill ZIPs and SHA-256 checksums; exclude user state."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from skill_tools import ROOT, SKILLS, build_archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    checksums = {}
    for name in SKILLS:
        archive = build_archive(name, args.output)
        checksums[archive.name] = hashlib.sha256(archive.read_bytes()).hexdigest()
        print(f"Built {archive}")
    (args.output / "SHA256SUMS.json").write_text(
        json.dumps(checksums, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

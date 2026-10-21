#!/usr/bin/env python3
"""Validate portable frontmatter, metadata, resources and local Markdown links."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from skill_tools import ROOT, SKILLS, skill_files


def validate(root: Path = ROOT) -> None:
    for name in SKILLS:
        files = skill_files(name, root)
        source = root / "skills" / name
        document = (source / "SKILL.md").read_text(encoding="utf-8")
        metadata = yaml.safe_load(document.split("---\n", 2)[1])
        if set(metadata) != {"name", "description"} or metadata["name"] != name:
            raise ValueError(f"Invalid portable frontmatter: {name}")
        if not isinstance(metadata["description"], str) or not metadata["description"].strip():
            raise ValueError(f"Missing description: {name}")
        if len(document.splitlines()) > 500:
            raise ValueError(f"Move detailed instructions to references: {name}")
        interface = yaml.safe_load((source / "agents/openai.yaml").read_text(encoding="utf-8"))[
            "interface"
        ]
        if f"${name}" not in interface["default_prompt"]:
            raise ValueError(f"Metadata prompt names a different skill: {name}")
        for key in ("display_name", "short_description"):
            if not isinstance(interface[key], str) or not interface[key].strip():
                raise ValueError(f"Missing {key}: {name}")
        if not 25 <= len(interface["short_description"]) <= 64:
            raise ValueError(f"Short description must be 25–64 characters: {name}")
        if not files:
            raise ValueError(f"Empty payload: {name}")
    documents = [*root.glob("*.md"), *root.glob("docs/*.md")]
    documents += [path for name in SKILLS for path in (root / "skills" / name).rglob("*.md")]
    for document in documents:
        text = document.read_text(encoding="utf-8")
        if "[TODO:" in text:
            raise ValueError(f"Unfinished template: {document.relative_to(root)}")
        for link in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", text):
            url = urlsplit(link.strip("<>"))
            if url.scheme or url.netloc or not url.path:
                continue
            target = document.parent / unquote(url.path)
            if not target.exists():
                raise ValueError(f"Broken link in {document.relative_to(root)}: {link}")
            if document.is_relative_to(root / "skills"):
                skill_root = root / "skills" / document.relative_to(root / "skills").parts[0]
                if not target.resolve().is_relative_to(skill_root.resolve()):
                    raise ValueError(f"Skill link escapes its portable folder: {link}")


if __name__ == "__main__":
    validate()
    print("Skill metadata, portable resources and local documentation links passed.")

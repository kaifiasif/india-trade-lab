"""Validate, install and package the repository's portable skill folders."""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE_SKILLS = (
    "india-data",
    "india-news",
    "india-analyst",
    "india-screener",
    "india-disclosures",
    "india-budget",
    "india-risk",
    "india-paper-broker",
    "india-alerts",
    "india-cost-tax",
    "india-rebalance",
    "india-reviewer",
)
SKILLS = ("day-trader-india", "india-trade-dev", *ROLE_SKILLS)
AGENT_PLATFORMS = {
    "claude": ".claude/agents",
    "codex": ".codex/agents",
}
PLATFORMS = {
    "claude": (".claude/skills", ".claude/skills"),
    "codex": (".agents/skills", ".agents/skills"),
    "cursor": (".cursor/skills", ".cursor/skills"),
    "copilot": (".github/skills", ".copilot/skills"),
}


def skill_files(name: str, root: Path = ROOT) -> list[Path]:
    """Return a reviewed payload; refuse symlinks and unexpected file types."""
    if name not in SKILLS:
        raise ValueError(f"Unknown skill: {name}")
    source = root / "skills" / name
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"Missing or symlinked skill folder: {name}")
    header = (source / "SKILL.md").read_text(encoding="utf-8")
    if not header.startswith("---\n"):
        raise ValueError(f"Missing skill frontmatter: {name}")
    frontmatter = header.split("---\n", 2)[1]
    if not re.search(rf"^name: {re.escape(name)}$", frontmatter, re.MULTILINE):
        raise ValueError(f"Skill name must match its folder: {name}")
    if not re.search(r"^description: .+", frontmatter, re.MULTILINE):
        raise ValueError(f"Missing skill description: {name}")
    files = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not portable skill resources: {path.name}")
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_dir():
            continue
        if relative.parts[0] not in {"SKILL.md", "scripts", "references", "assets", "agents"}:
            raise ValueError(f"Unexpected skill resource: {relative}")
        if path.suffix not in {".md", ".py", ".yaml", ".svg", ".csv", ".json"}:
            raise ValueError(f"Unexpected resource type: {relative}")
        files.append(path)
    return files


def selected_skills(names: list[str]) -> list[str]:
    """Include the core dependency for role skills; preserve stable, unique order."""
    names = list(dict.fromkeys(names))
    for name in names:
        if name not in SKILLS:
            raise ValueError(f"Unknown skill: {name}")
    if any(name in ROLE_SKILLS for name in names) and "day-trader-india" not in names:
        names.insert(0, "day-trader-india")
    return names


def install_skills(
    names: list[str],
    destination: Path,
    root: Path = ROOT,
    *,
    agent_platform: str | None = None,
    agent_destination: Path | None = None,
) -> list[Path]:
    """Install complete skills and optional profiles, refusing all existing targets.

    Role selections include day-trader-india. Existing dependencies are never reused
    or replaced: select an empty destination or back up the prior installation.
    All profiles are preflighted before copying; failure removes only this call's
    newly created skills and profile files.
    """
    destination = destination.expanduser().absolute()
    names = selected_skills(names)
    payloads = {name: skill_files(name, root) for name in names}
    profiles: dict[Path, str] = {}
    if agent_platform is not None:
        if agent_platform not in AGENT_PLATFORMS:
            raise ValueError("Native agents are supported only for Claude and Codex")
        if agent_destination is None:
            raise ValueError("An agent destination is required for native agents")
        from generate_agents import profile_payloads

        agents = agent_destination.expanduser().absolute()
        profiles = {
            agents / filename: content
            for filename, content in profile_payloads(agent_platform, names, root).items()
        }
    elif agent_destination is not None:
        raise ValueError("An agent destination requires native agents")
    for name in names:
        target = destination / name
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Already exists: {target}. Back it up before reinstalling.")
        if destination.resolve().is_relative_to((root / "skills" / name).resolve()):
            raise ValueError("Install outside the source skill folder")
    for target in profiles:
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Already exists: {target}. Back it up before reinstalling.")
    destination.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    created_profiles: list[Path] = []
    with tempfile.TemporaryDirectory(prefix=".india-skills-", dir=destination) as staging:
        staged = Path(staging)
        for name, files in payloads.items():
            for source in files:
                target = staged / name / source.relative_to(root / "skills" / name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        try:
            for name in names:
                target = destination / name
                target.mkdir()  # Exclusive creation also rejects a concurrent install.
                installed.append(target)
                shutil.copytree(staged / name, target, dirs_exist_ok=True)
            for target, content in profiles.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("x", encoding="utf-8", newline="\n") as stream:
                    created_profiles.append(target)
                    stream.write(content)
        except Exception:
            for target in created_profiles:
                target.unlink()
            for target in installed:
                shutil.rmtree(target)
            raise
    return installed


def build_archive(name: str, output: Path, root: Path = ROOT) -> Path:
    """Build a reproducible ZIP with a single skill folder at its root."""
    files = skill_files(name, root)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{name}.zip"
    with tempfile.TemporaryDirectory(prefix=".india-package-", dir=output) as staging:
        temporary = Path(staging) / target.name
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                relative = path.relative_to(root / "skills")
                info = zipfile.ZipInfo(relative.as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
        temporary.replace(target)
    return target

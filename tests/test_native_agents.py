"""Verify native specialists, dependency installs, and no-overwrite transactions."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from generate_agents import HANDOFF_RULES, generate_profiles, profile_payloads, read_role

from skill_tools import AGENT_PLATFORMS, ROLE_SKILLS, ROOT, install_skills, selected_skills

try:
    import tomllib
except ImportError:  # Python 3.10 runtime tools do not require a TOML parser.
    tomllib = None


class NativeAgentTests(unittest.TestCase):
    def test_generated_files_are_current_and_exact(self):
        paths = generate_profiles(check=True)
        self.assertEqual(len(paths), len(ROLE_SKILLS) * 2)
        for platform in AGENT_PLATFORMS:
            extension = ".md" if platform == "claude" else ".toml"
            self.assertEqual(
                {path.name for path in paths if path.parent.name == platform},
                {name + extension for name in ROLE_SKILLS},
            )

    def test_profiles_embed_role_and_restrict_tools(self):
        for name in ROLE_SKILLS:
            description, body = read_role(name)
            claude = profile_payloads("claude", [name])[name + ".md"]
            self.assertIn(f"description: {json.dumps(description, ensure_ascii=False)}\n", claude)
            self.assertIn("tools: Read, Grep, Glob\nmodel: inherit\n", claude)
            self.assertIn(body, claude)
            codex = profile_payloads("codex", [name])[name + ".toml"]
            if tomllib is not None:
                parsed = tomllib.loads(codex)
            else:
                # Strings use JSON-compatible TOML syntax; this still checks escaping.
                parsed = {
                    key: json.loads(value)
                    for line in codex.split("\n\n", 1)[0].splitlines()
                    for key, value in [line.split(" = ", 1)]
                }
                parsed["features"] = {
                    key: value == "true"
                    for line in codex.split("[features]\n", 1)[1].splitlines()
                    for key, value in [line.split(" = ", 1)]
                }
            self.assertEqual(parsed["name"], name)
            self.assertEqual(parsed["description"], description)
            self.assertEqual(parsed["developer_instructions"], HANDOFF_RULES + "\n" + body + "\n")
            self.assertEqual(
                parsed["features"],
                dict.fromkeys(
                    ("shell_tool", "apps", "plugins", "memories", "request_permissions_tool"),
                    False,
                ),
            )
            self.assertNotIn("model", parsed)
            self.assertNotIn("mcp_servers", parsed)
            for phrase in (
                "Do not call brokerage",
                "parent must not expose order-capable MCP tools",
                "coordinator alone may run",
                "india-paper-broker returns a proposal only",
            ):
                self.assertIn(phrase, claude)
                self.assertIn(phrase, parsed["developer_instructions"])

    def test_profile_escaping_preserves_unicode_and_literal_role_text(self):
        description = 'Read "evidence" \U0001f4c8'
        body = 'Quoted "text", backslash \\, tab\t, and line break\nnext line \U0001f4c8'
        with patch("generate_agents.read_role", return_value=(description, body)):
            profile = profile_payloads("codex", ["india-risk"])["india-risk.toml"]
        if tomllib is not None:
            parsed = tomllib.loads(profile)
        else:
            parsed = {
                key: json.loads(value)
                for line in profile.split("\n\n", 1)[0].splitlines()
                for key, value in [line.split(" = ", 1)]
            }
        self.assertEqual(parsed["description"], description)
        self.assertEqual(parsed["developer_instructions"], HANDOFF_RULES + "\n" + body + "\n")

    def test_cli_user_defaults_install_under_user_agent_directory(self):
        for platform, relative in AGENT_PLATFORMS.items():
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                command = [
                    sys.executable,
                    str(ROOT / "scripts/install_skills.py"),
                    "--platform",
                    platform,
                    "--scope",
                    "user",
                    "--skill",
                    "india-risk",
                    "--destination",
                    str(directory / "custom-skills"),
                    "--with-agents",
                ]
                subprocess.run(
                    command, env={**os.environ, "HOME": temporary}, capture_output=True, check=True
                )
                self.assertEqual(len(list((directory / relative).iterdir())), 1)

    def test_role_dependency_and_existing_core_refusal(self):
        self.assertEqual(selected_skills(["india-risk"]), ["day-trader-india", "india-risk"])
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills"
            paths = install_skills(["india-risk"], destination)
            self.assertEqual([path.name for path in paths], ["day-trader-india", "india-risk"])
            with self.assertRaises(FileExistsError):
                install_skills(["india-news"], destination)
            self.assertFalse((destination / "india-news").exists())

    def test_existing_profile_preflight_does_not_install_skills(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            agents = directory / "agents"
            agents.mkdir()
            profile = agents / "india-risk.toml"
            profile.write_text("local edits", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                install_skills(
                    ["india-risk"],
                    directory / "skills",
                    agent_platform="codex",
                    agent_destination=agents,
                )
            self.assertFalse((directory / "skills").exists())
            self.assertEqual(profile.read_text(encoding="utf-8"), "local edits")

    def test_failure_rolls_back_only_created_profiles_and_skills(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            agents = directory / "agents"
            agents.mkdir()
            keep = agents / "unrelated.md"
            keep.write_text("keep", encoding="utf-8")
            real_open = Path.open

            def fail_second_profile(path, *args, **kwargs):
                if path == agents / "india-risk.md" and args and args[0] == "x":
                    raise OSError("simulated disk failure")
                return real_open(path, *args, **kwargs)

            with patch.object(Path, "open", fail_second_profile):
                with self.assertRaisesRegex(OSError, "simulated disk failure"):
                    install_skills(
                        ["india-news", "india-risk"],
                        directory / "skills",
                        agent_platform="claude",
                        agent_destination=agents,
                    )
            self.assertEqual(list((directory / "skills").iterdir()), [])
            self.assertEqual(list(agents.iterdir()), [keep])
            self.assertEqual(keep.read_text(encoding="utf-8"), "keep")

    def test_concurrent_profile_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            agents = directory / "agents"
            real_open = Path.open

            def concurrent_create(path, *args, **kwargs):
                if path == agents / "india-risk.toml" and args and args[0] == "x":
                    path.write_text("concurrent install", encoding="utf-8")
                return real_open(path, *args, **kwargs)

            with patch.object(Path, "open", concurrent_create):
                with self.assertRaises(FileExistsError):
                    install_skills(
                        ["india-risk"],
                        directory / "skills",
                        agent_platform="codex",
                        agent_destination=agents,
                    )
            self.assertEqual(list((directory / "skills").iterdir()), [])
            self.assertEqual(
                (agents / "india-risk.toml").read_text(encoding="utf-8"), "concurrent install"
            )

    def test_cli_platform_defaults_and_separate_destinations(self):
        for platform, relative in AGENT_PLATFORMS.items():
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                command = [
                    sys.executable,
                    str(ROOT / "scripts/install_skills.py"),
                    "--platform",
                    platform,
                    "--project",
                    str(directory),
                    "--skill",
                    "india-risk",
                    "--destination",
                    str(directory / "custom-skills"),
                    "--with-agents",
                ]
                subprocess.run(command, capture_output=True, check=True)
                self.assertTrue((directory / "custom-skills/day-trader-india/SKILL.md").exists())
                self.assertEqual(len(list((directory / relative).iterdir())), 1)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            command = [
                sys.executable,
                str(ROOT / "scripts/install_skills.py"),
                "--platform",
                "codex",
                "--scope",
                "user",
                "--skill",
                "india-risk",
                "--destination",
                str(directory / "skills"),
                "--agent-destination",
                str(directory / "custom-agents"),
                "--with-agents",
            ]
            subprocess.run(command, capture_output=True, check=True)
            self.assertTrue((directory / "custom-agents/india-risk.toml").exists())

    def test_cli_refuses_native_agents_for_other_platforms(self):
        for platform in ("cursor", "copilot"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temporary:
                command = [
                    sys.executable,
                    str(ROOT / "scripts/install_skills.py"),
                    "--platform",
                    platform,
                    "--project",
                    temporary,
                    "--with-agents",
                ]
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(list(Path(temporary).iterdir()), [])
                subprocess.run(command[:-1], capture_output=True, check=True)

    def test_check_rejects_stale_or_extra_generated_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            profiles = {name: ("description", "role instructions") for name in ROLE_SKILLS}
            with patch("generate_agents.read_role", side_effect=lambda name, root: profiles[name]):
                generated = generate_profiles(directory)
                generate_profiles(directory, check=True)
                generated[0].write_text("stale", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Stale native profile"):
                    generate_profiles(directory, check=True)
                generate_profiles(directory)
                (directory / "agent_profiles/extra.md").write_text("extra", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "file list differs"):
                    generate_profiles(directory, check=True)


if __name__ == "__main__":
    unittest.main()

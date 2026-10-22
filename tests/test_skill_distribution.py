"""Exercise copied skill payloads without relying on the source checkout's resources."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from skill_tools import PLATFORMS, ROOT, SKILLS, build_archive, install_skills, skill_files


class SkillDistributionTests(unittest.TestCase):
    def test_each_platform_installs_complete_skills_and_blocks_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            for platform, locations in PLATFORMS.items():
                with self.subTest(platform=platform):
                    destination = Path(temporary) / platform / locations[0]
                    installed = install_skills(list(SKILLS), destination)
                    self.assertEqual(len(installed), len(SKILLS))
                    for name in SKILLS:
                        for source in skill_files(name):
                            copied = destination / name / source.relative_to(ROOT / "skills" / name)
                            self.assertEqual(copied.read_bytes(), source.read_bytes())
                    existing = destination / SKILLS[0] / "SKILL.md"
                    existing.write_text("my local edits", encoding="utf-8")
                    with self.assertRaises(FileExistsError):
                        install_skills(list(SKILLS), destination)
                    self.assertEqual(existing.read_text(encoding="utf-8"), "my local edits")

    def test_installed_trading_skill_runs_without_checkout_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills"
            install_skills(["day-trader-india"], destination)
            skill = destination / "day-trader-india"
            command = [
                sys.executable,
                "-I",  # Isolate imports from PYTHONPATH and the checkout.
                "-c",
                "import runpy,sys; from pathlib import Path; "
                "sys.path.insert(0,str(Path(sys.argv[1]).parent)); "
                "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')",
                str(skill / "scripts/india_research.py"),
                "scan-orb",
                "--bars",
                str(skill / "assets/synthetic-bars.csv"),
                "--sessions",
                str(skill / "assets/synthetic-sessions.json"),
                "--as-of",
                "2026-10-19T09:35:00+05:30",
            ]
            output = subprocess.check_output(command, cwd=temporary, text=True)
            result = json.loads(output)
            self.assertEqual(result["mode"], "research_only")
            self.assertEqual(result["results"][0]["status"], "MATCH")
            book = Path(temporary) / "demo.sqlite"
            base = [sys.executable, str(skill / "scripts/paper_book.py"), "--book", str(book)]
            subprocess.run(
                base
                + [
                    "init",
                    "--cash-inr",
                    "100000",
                    "--symbols",
                    "NSE:DEMO",
                    "--risk-inr",
                    "250",
                    "--daily-loss-inr",
                    "750",
                    "--position-limit-inr",
                    "15000",
                    "--replay",
                ],
                cwd=temporary,
                capture_output=True,
                check=True,
            )
            state = json.loads(subprocess.check_output(base + ["status"], cwd=temporary))
            self.assertEqual(state["mode"], "replay_demo")
            for script in ("broker_data.py", "paper_book.py", "india_research.py", "engine.py"):
                subprocess.run(
                    [sys.executable, str(skill / "scripts" / script), "--help"],
                    cwd=temporary,
                    capture_output=True,
                    check=True,
                )

    def test_archives_are_reproducible_complete_and_private_state_free(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in SKILLS:
                with self.subTest(name=name):
                    first = build_archive(name, Path(temporary))
                    digest = hashlib.sha256(first.read_bytes()).hexdigest()
                    second = build_archive(name, Path(temporary))
                    self.assertEqual(digest, hashlib.sha256(second.read_bytes()).hexdigest())
                    with zipfile.ZipFile(second) as archive:
                        expected = {
                            path.relative_to(ROOT / "skills").as_posix()
                            for path in skill_files(name)
                        }
                        self.assertEqual(set(archive.namelist()), expected)
                        self.assertIn(f"{name}/SKILL.md", expected)
                        self.assertFalse(any(".." in Path(path).parts for path in expected))
                        self.assertFalse(
                            any(path.endswith((".sqlite", ".env", ".pyc")) for path in expected)
                        )

    def test_install_refuses_unknown_skill_and_existing_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            with self.assertRaises(ValueError):
                install_skills(["../secrets"], destination)
            outside = destination / "outside"
            outside.mkdir()
            (destination / "day-trader-india").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(FileExistsError):
                install_skills(["day-trader-india"], destination)
            self.assertEqual(list(outside.iterdir()), [])

    def test_original_cli_paths_still_work(self):
        for name in ("broker_data.py", "paper_book.py", "india_research.py", "engine.py"):
            with self.subTest(script=name):
                subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / name), "--help"],
                    capture_output=True,
                    check=True,
                )


if __name__ == "__main__":
    unittest.main()

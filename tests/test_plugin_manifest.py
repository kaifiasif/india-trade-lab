"""Check the plugin packages the intended resources without hooks or MCP servers."""

import json
import unittest

from skill_tools import ROLE_SKILLS, ROOT, SKILLS


class PluginManifestTests(unittest.TestCase):
    def test_marketplace_and_manifest_resolve_the_complete_pack(self):
        folder = ROOT / ".claude-plugin"
        plugin = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads((folder / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "india-trade-lab")
        self.assertEqual(marketplace["plugins"][0]["name"], plugin["name"])
        self.assertEqual(marketplace["plugins"][0]["source"], "./")
        self.assertNotIn("mcpServers", plugin)
        self.assertNotIn("hooks", plugin)
        self.assertEqual({path.name for path in (ROOT / plugin["skills"]).iterdir()}, set(SKILLS))
        self.assertEqual(
            {path for path in plugin["agents"]},
            {f"./agent_profiles/claude/{name}.md" for name in ROLE_SKILLS},
        )
        for path in plugin["agents"]:
            self.assertTrue((ROOT / path).is_file())


if __name__ == "__main__":
    unittest.main()

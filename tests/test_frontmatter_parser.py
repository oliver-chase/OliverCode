"""OC-10: smoke tests for scripts/olivercode's _parse_skill_frontmatter().

Run: python3 -m unittest discover tests

scripts/olivercode has no .py suffix (it's the `olivercode` CLI entrypoint), so it's
loaded via importlib.machinery.SourceFileLoader rather than a normal import.
"""

import importlib.util
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_PATH = REPO_ROOT / "scripts" / "olivercode"


def _load_launcher():
    loader = SourceFileLoader("olivercode_launcher", str(LAUNCHER_PATH))
    spec = importlib.util.spec_from_loader("olivercode_launcher", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


launcher = _load_launcher()


class TestFrontmatterParser(unittest.TestCase):
    def _write_skill(self, tmpdir, content):
        skill_dir = Path(tmpdir) / "some-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(content, encoding="utf-8")
        return skill_md

    def test_plain_description(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = self._write_skill(
                tmpdir,
                "---\nname: some-skill\ndescription: A plain one-line description.\n---\n\n# Some Skill\n",
            )
            name, description = launcher._parse_skill_frontmatter(skill_md)
            self.assertEqual(name, "some-skill")
            self.assertEqual(description, "A plain one-line description.")

    def test_folded_block_scalar_description(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = self._write_skill(
                tmpdir,
                "---\nname: some-skill\ndescription: >\n  Line one of the description.\n  Line two continues it.\n---\n\n# Some Skill\n",
            )
            name, description = launcher._parse_skill_frontmatter(skill_md)
            self.assertEqual(name, "some-skill")
            self.assertEqual(description, "Line one of the description. Line two continues it.")

    def test_missing_frontmatter_falls_back_to_dirname(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_md = self._write_skill(tmpdir, "# Some Skill\n\nNo frontmatter here.\n")
            name, description = launcher._parse_skill_frontmatter(skill_md)
            self.assertEqual(name, "some-skill")  # falls back to the parent dir name
            self.assertEqual(description, "")


if __name__ == "__main__":
    unittest.main()

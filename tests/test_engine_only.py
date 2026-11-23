"""An OliverCode clone is engine only: personal files are refused at commit and flagged by conform (#819). The Engine-only check section of docs/GATES.md describes it."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import conform, engine_only  # noqa: E402

FLEET_NAME = "alpha-repo"


def make_repo(case, files):
    """A scratch engine checkout whose untracked registry names one fleet repo, with FILES staged."""
    repo = scratch_repo(temp_dir(case) / "repo")
    (repo / "scripts" / "lib").mkdir(parents=True)
    (repo / "scripts" / "lib" / "engine_only.py").write_text("")
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    (repo / "shared").mkdir(exist_ok=True)
    (repo / "shared" / "repo-profiles.json").write_text(json.dumps({"profiles": {FLEET_NAME: {}}}))
    (repo / ".git" / "info" / "exclude").write_text("shared/repo-profiles.json\n")
    return repo


def gate(repo, *paths):
    return subprocess.run([sys.executable, "-m", "lib.engine_only", *paths], cwd=repo, capture_output=True, text=True,
                          env={"PYTHONPATH": str(REPO_ROOT / "scripts"), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


class StagedGate(unittest.TestCase):
    def test_a_staged_personal_story_is_refused_with_a_pointer_to_the_fleet_repo(self):
        repo = make_repo(self, {"docs/stories/one.md": "A story.\n", "docs/note.md": f"Work on {FLEET_NAME} next.\n"})
        done = gate(repo)
        self.assertEqual(done.returncode, 1)
        self.assertIn("docs/stories/one.md", done.stdout)
        self.assertIn(f"docs/note.md is names the fleet repo {FLEET_NAME}", done.stdout)
        self.assertIn("olivercode-fleet", done.stdout)

    def test_a_staged_config_and_a_filled_registry_are_refused(self):
        repo = make_repo(self, {"olivercode.local.json": "{}\n", "shared/repo-profiles.json": json.dumps({"profiles": {"x": {}}})})
        done = gate(repo)
        self.assertEqual(done.returncode, 1)
        self.assertIn("olivercode.local.json", done.stdout)
        self.assertIn("a filled-in fleet registry", done.stdout)

    def test_generic_files_pass(self):
        repo = make_repo(self, {"scripts/tool.py": "print(1)\n", "docs/guide.md": "Generic guide.\n",
                                "olivercode.local.example.json": "{}\n", "shared/repo-profiles.json": json.dumps({"profiles": {}})})
        done = gate(repo)
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_the_commit_gate_lists_the_check(self):
        checks = json.loads((REPO_ROOT / "docs" / "SUITE-CHECKS.json").read_text())["checks"]
        self.assertIn("lib.engine_only", " ".join(c["command"] for c in checks if "*" in c["files"]))


class ConformRow(unittest.TestCase):
    def test_a_personal_file_in_the_checkout_fails_conform_with_the_fix(self):
        repo = make_repo(self, {"queue/item.md": "x\n"})
        row = conform.engine_only(repo)
        self.assertEqual(row.status, "fail")
        self.assertIn("queue/item.md", row.detail)
        self.assertIn("olivercode-fleet", row.fix)

    def test_an_untracked_unignored_personal_file_also_fails(self):
        repo = make_repo(self, {"docs/guide.md": "ok\n"})
        (repo / "stories").mkdir()
        (repo / "stories" / "a.md").write_text("x\n")
        self.assertEqual(conform.engine_only(repo).status, "fail")

    def test_a_clean_engine_passes_and_a_fleet_repo_is_skipped(self):
        self.assertEqual(conform.engine_only(make_repo(self, {"docs/guide.md": "ok\n"})).status, "pass")
        other = scratch_repo(temp_dir(self) / "other")
        self.assertEqual(conform.engine_only(other).status, "skip")


if __name__ == "__main__":
    unittest.main()

"""An OliverCode clone is engine only: personal files are refused at commit (#819). The Engine-only check section of docs/GATES.md describes it."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import engine_only  # noqa: E402

FLEET_NAME = "alpha-repo"


def make_repo(case, files):
    """A scratch engine checkout with FILES staged. Its machine config names one private repo, FLEET_NAME."""
    base = temp_dir(case)
    repo = scratch_repo(base / "repo")
    (repo / "scripts" / "lib").mkdir(parents=True)
    (repo / "scripts" / "lib" / "engine_only.py").write_text("")
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    config = base / "local.json"
    config.write_text(json.dumps({"privateRepos": {FLEET_NAME: str(base / FLEET_NAME)}}))
    case.config = config
    return repo


def gate(repo, config, *paths):
    return subprocess.run([sys.executable, "-m", "lib.engine_only", *paths], cwd=repo, capture_output=True, text=True,
                          env={"PYTHONPATH": str(REPO_ROOT / "scripts"), "OLIVERCODE_LOCAL_CONFIG": str(config),
                               "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


class StagedGate(unittest.TestCase):
    def test_a_staged_personal_story_is_refused_with_a_pointer_to_the_fleet_repo(self):
        repo = make_repo(self, {"docs/stories/one.md": "A story.\n", "docs/note.md": f"Work on {FLEET_NAME} next.\n"})
        done = gate(repo, self.config)
        self.assertEqual(done.returncode, 1)
        self.assertIn("docs/stories/one.md", done.stdout)
        self.assertIn("docs/note.md is names a fleet repo", done.stdout)
        self.assertIn("olivercode-fleet", done.stdout)

    def test_a_staged_config_is_refused(self):
        repo = make_repo(self, {"olivercode.local.json": "{}\n"})
        done = gate(repo, self.config)
        self.assertEqual(done.returncode, 1)
        self.assertIn("olivercode.local.json", done.stdout)

    def test_generic_files_pass(self):
        repo = make_repo(self, {"scripts/tool.py": "print(1)\n", "docs/guide.md": "Generic guide.\n",
                                "olivercode.local.example.json": "{}\n"})
        done = gate(repo, self.config)
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_the_commit_gate_lists_the_check(self):
        checks = json.loads((REPO_ROOT / "docs" / "SUITE-CHECKS.json").read_text())["checks"]
        self.assertIn("lib.engine_only", " ".join(c["command"] for c in checks if "*" in c["files"]))


if __name__ == "__main__":
    unittest.main()

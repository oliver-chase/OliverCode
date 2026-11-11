"""What `olivercode bootstrap` leaves in a new repo works: the files it names exist, the
validation passes, the board config is a placeholder, and every shipped workflow is manual.

Each test bootstraps into a scratch repo with HOME and git config isolated, and reaches no network.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from _support import REPO_ROOT, git_env, scratch_repo, temp_dir

LAUNCHER = REPO_ROOT / "scripts" / "olivercode"
BACKLOG_CHECK = REPO_ROOT / "skills" / "backlog" / "scripts" / "check_board_hygiene.py"
WORKFLOWS = REPO_ROOT / "core" / "templates" / "project" / ".github" / "workflows"


def workflow_triggers(text):
    """The keys under the top-level `on:` block of a workflow file."""
    keys, inside = [], False
    for line in text.splitlines():
        if re.match(r"on:\s*$", line):
            inside = True
        elif inside and re.match(r"\S", line) and not line.startswith("#"):
            break
        elif inside:
            m = re.match(r"  ([A-Za-z_]+):", line)
            if m:
                keys.append(m.group(1))
    return keys


class BootstrapOutput(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir(self, "olivercode-bootout-")
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.repo = scratch_repo(self.tmp / "repo")
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin", "https://github.com/jane-doe/shop.git"],
                       check=True)
        self.env = git_env(HOME=str(self.home))
        done = subprocess.run([sys.executable, str(LAUNCHER), "bootstrap", str(self.repo)],
                              env=self.env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_every_file_claude_md_names_exists(self):
        claude = (self.repo / "CLAUDE.md").read_text()
        for rel in ("scripts/validate.sh", "docs/backlog-config.json"):
            self.assertIn(rel, claude)
        named = set(re.findall(r"`(?:bash )?((?:scripts|docs)/[A-Za-z0-9_./-]+\.(?:sh|json))`", claude))
        self.assertTrue({"scripts/validate.sh", "docs/backlog-config.json"} <= named)
        for rel in named:
            self.assertTrue((self.repo / rel).is_file(), rel)
        # The owner and the orchestration repo are filled in, and no template names an npm script.
        self.assertIn("* @jane-doe", (self.repo / ".github/CODEOWNERS").read_text())
        self.assertNotIn("<Repo>", (self.repo / "CLAUDE.md").read_text())
        workflow = (self.repo / ".github/workflows/olivercode-governance.yml").read_text()
        own = subprocess.run(["git", "-C", str(REPO_ROOT), "remote", "get-url", "origin"],
                             capture_output=True, text=True).stdout.strip()
        if own:  # a checkout with no origin has no orchestration repo to name
            self.assertNotIn("your-org/your-orchestration", workflow)
            self.assertIn("repository: " + re.sub(r"^.*[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", r"\1", own), workflow)
        for rel in ("docs/repo-structure-contract.md",):
            self.assertNotIn("npm run -s qa", (self.repo / rel).read_text())
            self.assertNotIn("npm run qa:", (self.repo / rel).read_text())

    def test_validate_sh_exits_zero_on_the_new_repo(self):
        done = subprocess.run(["bash", "scripts/validate.sh"], cwd=self.repo, env=self.env,
                              capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)

    def test_validate_sh_fails_when_the_repo_check_fails(self):
        (self.repo / "package.json").write_text(
            json.dumps({"scripts": {"validate": "exit 1"}}))
        if not shutil.which("npm"):
            self.skipTest("npm is not installed")
        done = subprocess.run(["bash", "scripts/validate.sh"], cwd=self.repo, env=self.env,
                              capture_output=True, text=True)
        self.assertNotEqual(0, done.returncode)

    def test_the_backlog_config_is_the_placeholder_and_the_skill_rejects_it(self):
        shipped = (self.repo / "docs" / "backlog-config.json").read_text()
        self.assertEqual((REPO_ROOT / "shared" / "backlog-config.example.json").read_text(), shipped)
        done = subprocess.run([sys.executable, str(BACKLOG_CHECK), "--config",
                               str(self.repo / "docs" / "backlog-config.json"), "--verify-config"],
                              env=self.env, capture_output=True, text=True)
        self.assertNotEqual(0, done.returncode, done.stdout)

    def test_files_in_presence_mode_survive_a_second_bootstrap(self):
        mine = {"CLAUDE.md": "MY REPO RULES\n", "docs/backlog-config.json": '{"mine": true}\n', "docs/SIZE-BASELINE.json": '{"lines": 777}\n'}
        for rel, text in mine.items():
            (self.repo / rel).write_text(text)
        subprocess.run([sys.executable, str(LAUNCHER), "bootstrap", str(self.repo)], env=self.env, check=True, capture_output=True)
        for rel, text in mine.items():
            self.assertEqual(text, (self.repo / rel).read_text(), rel)


class ShippedWorkflows(unittest.TestCase):
    def test_every_workflow_triggers_on_workflow_dispatch_only(self):
        files = sorted(WORKFLOWS.glob("*.yml"))
        for path in files:
            self.assertEqual(["workflow_dispatch"], workflow_triggers(path.read_text()), path.name)

    def test_the_manifest_ships_each_workflow_and_keeps_no_unread_policy_key(self):
        manifest = json.loads((REPO_ROOT / "shared" / "project-bootstrap-manifest.json").read_text())
        shipped = {Path(e["source"]).name for e in manifest["templatedFiles"]
                   if e["source"].startswith("core/templates/project/.github/workflows/")}
        self.assertEqual({p.name for p in WORKFLOWS.glob("*.yml")}, shipped)

if __name__ == "__main__":
    unittest.main()


class TestOfferedFiles(unittest.TestCase):
    """CODEOWNERS and the workflow are offered once, and a repo that dropped them is not told to add them back."""

    def setUp(self):
        self.repo = temp_dir(self, "olivercode-offered-")
        scratch_repo(self.repo)

    def bootstrap(self):
        return subprocess.run([sys.executable, str(LAUNCHER), "bootstrap", str(self.repo)], env=git_env(), capture_output=True, text=True)

    def test_the_first_run_offers_them_and_a_later_run_does_not_restore_a_deleted_one(self):
        self.bootstrap()
        self.assertTrue((self.repo / ".github" / "CODEOWNERS").exists())
        shutil.rmtree(self.repo / ".github")
        self.bootstrap()
        self.assertFalse((self.repo / ".github").exists())

    def test_the_structure_contract_script_passes_in_a_repo_without_github(self):
        self.bootstrap()
        shutil.rmtree(self.repo / ".github")
        ran = subprocess.run(["node", "scripts/check-structure-contract.mjs"], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)

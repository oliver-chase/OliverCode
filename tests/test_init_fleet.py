"""`olivercode init-fleet` scaffolds a private fleet repo from a generic template (#820). No test reaches GitHub."""

import os
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _support import REPO_ROOT, temp_dir, quiet  # noqa: E402
from lib import cmd_initfleet  # noqa: E402


def fake(private="true", collaborators='["me"]', calls=None, github="none"):
    def runner(args):
        calls.append(args)
        text = " ".join(args)
        if args[2:3] == ["repos/me/olivercode-fleet"] and ".name" in args:
            return (1, "gh: Not Found (HTTP 404)") if github == "none" else (0, "olivercode-fleet")
        if "contents/repo-profiles.json" in text:
            return (0, "repo-profiles.json") if github == "fleet" else (1, "gh: Not Found (HTTP 404)")
        if "collaborators" in text:
            return 0, collaborators
        if args[:2] == ["gh", "api"] and "--jq" in args and ".private" in args:
            return 0, private
        return 0, "me" if "user" in args and "--jq" in args else ""
    return runner


class InitFleet(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(temp_dir(self))})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_template_is_generic(self):
        names = {p.name for p in cmd_initfleet.TEMPLATE.iterdir()}
        self.assertEqual(names, {"repo-profiles.json", "owner-rules.json", "owner-queue.jsonl", "review-config.json", "CLAUDE.md"})
        text = " ".join(p.read_text() for p in cmd_initfleet.TEMPLATE.iterdir()).lower()
        import subprocess
        who = subprocess.run(["git", "-C", str(REPO_ROOT), "remote", "get-url", "origin"], capture_output=True, text=True).stdout
        owner = who.strip().rstrip("/").split("/")[-2].split(":")[-1].lower() if "/" in who else ""
        if owner:
            self.assertNotIn(owner, text)

    def run_cmd(self, runner, *extra):
        dest = temp_dir(self) / "fleet"
        rc, out = quiet(cmd_initfleet.command_init_fleet, ["--dir", str(dest), *extra], runner)
        return rc, out, dest

    def test_a_private_repo_is_confirmed_before_the_push(self):
        calls = []
        rc, out, dest = self.run_cmd(fake(calls=calls))
        self.assertEqual(rc, 0, out)
        flat = [" ".join(c) for c in calls]
        create = next(i for i, c in enumerate(flat) if "-X POST user/repos" in c and "private=true" in c)
        push = next(i for i, c in enumerate(flat) if " push " in c)
        check = next(i for i, c in enumerate(flat) if "collaborators" in c)
        self.assertLess(create, check)
        self.assertLess(check, push)
        self.assertFalse((dest / "backlog-config.json").exists())
        self.assertFalse(any("graphql" in c for c in flat))

    def test_a_public_repo_is_never_pushed(self):
        calls = []
        rc, out, _ = self.run_cmd(fake(private="false", calls=calls))
        self.assertEqual(rc, 1)
        self.assertFalse(any(" push " in " ".join(c) for c in calls))

    def test_a_collaborator_blocks_the_push(self):
        calls = []
        rc, out, _ = self.run_cmd(fake(collaborators='["me","friend"]', calls=calls))
        self.assertEqual(rc, 1)
        self.assertFalse(any(" push " in " ".join(c) for c in calls))

    def test_an_existing_fleet_is_left_alone(self):
        calls = []
        rc, _, dest = self.run_cmd(fake(calls=calls))
        rc2, out = quiet(cmd_initfleet.command_init_fleet, ["--dir", str(dest)], fake(calls=calls))
        self.assertEqual(rc2, 1)

    def test_a_name_taken_by_a_repo_that_is_not_a_fleet_stops_before_any_write(self):
        calls = []
        rc, out, dest = self.run_cmd(fake(calls=calls, github="other"))
        self.assertEqual(rc, 1)
        self.assertIn("not a fleet repo", out)
        self.assertFalse(any("POST" in " ".join(c) or " push " in " ".join(c) for c in calls))
        self.assertFalse(dest.exists())

    def test_a_fleet_repo_already_on_github_is_cloned_and_nothing_is_created(self):
        calls = []
        rc, out, dest = self.run_cmd(fake(calls=calls, github="fleet"))
        self.assertEqual(rc, 0, out)
        flat = [" ".join(c) for c in calls]
        self.assertTrue(any(c.startswith("git clone") and "me/olivercode-fleet.git" in c for c in flat))
        self.assertFalse(any("POST" in c for c in flat))

    def test_adoption_and_setup_run_it(self):
        for doc in ("docs/SETUP.md", "skills/olivercode-adoption/SKILL.md"):
            self.assertIn("olivercode init-fleet", (REPO_ROOT / doc).read_text())


if __name__ == "__main__":
    unittest.main()

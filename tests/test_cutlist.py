"""cutlist names each guard's origin story, last block and size, flags what has not triggered, and lists uncovered owner rules (#562)."""

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, git, scratch_repo, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import cmd_cutlist, hook_fires  # noqa: E402


class TestCutlist(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        self.fleet = self.home / "fleet"
        self.fleet.mkdir()
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home), "OLIVERCODE_FAILURE_LOG": str(self.home / "failures.log"),
                                               "OLIVERCODE_FLEET_REGISTRY": str(self.fleet / "repo-profiles.json")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def repo(self):
        root = temp_dir(self) / "oc"
        scratch_repo(root)
        (root / "core/hooks/gates").mkdir(parents=True)
        (root / "scripts/hooks").mkdir(parents=True)
        (root / "shared").mkdir()
        (root / "core/hooks/gates/secrets.sh").write_text("a\nb\nc\n")
        (root / "core/hooks/gates/pii.sh").write_text("a\n")
        (root / "scripts/hooks/wip_save.py").write_text("x\ny\n")
        (root / "docs").mkdir()
        (root / "docs/RULES.md").write_text("# Rules\n")
        (self.fleet / "owner-rule-gates.json").write_text(json.dumps([{"match": "push straight to main", "check": "core/hooks/pre-push.sh"}]))
        git(root, "add", "-A")
        git(root, "commit", "-qm", "Add the gates (#38)")
        return root

    def test_each_guard_carries_its_story_last_block_lines_and_flag(self):
        root = self.repo()
        (self.home / "failures.log").write_text("2026-11-20T10:00:00Z\tr\tSecrets\tBLOCKED\n2026-08-01T10:00:00Z\tr\tPII\tBLOCKED\n")
        memory = root / "USER.md"
        memory.write_text("## Standing Rules\n\n- Commit and push straight to main always\n- Never delete a photo\n\n## Projects\n\n- Not a rule\n")
        text = cmd_cutlist.report(root, 60, memory, now=1795300000)  # 2026-11-21
        secrets = next(l for l in text.splitlines() if "secrets.sh" in l)
        self.assertIn("#38", secrets)
        self.assertIn("2026-11-20", secrets)
        self.assertTrue(secrets.rstrip().endswith("3"), secrets)
        self.assertIn("no trigger", next(l for l in text.splitlines() if "pii.sh" in l))
        self.assertNotIn("not logged", next(l for l in text.splitlines() if "wip_save.py" in l))
        self.assertIn("2 in the memory file, 1 with no gate", text)
        self.assertIn("covered by core/hooks/pre-push.sh: Commit and push", text)
        self.assertIn("no gate: Never delete a photo", text)
        self.assertNotIn("Not a rule", text)
        self.assertIn("docs/RULES.md", text)

    def test_a_registered_hook_shows_its_last_action_and_is_flagged_only_after_a_full_window_without_one(self):
        root = self.repo()
        (root / "scripts/hooks/error_paste.py").write_text("x\n")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "Add the error paste hook (#38)")
        folder = self.home / "hook-fires"
        folder.mkdir()
        (folder / "error_paste.json").write_text(json.dumps({"since": "2026-06-01T00:00:00Z", "ran": "2026-11-20T10:00:00Z"}))
        (folder / "wip_save.json").write_text(json.dumps({"since": "2026-06-01T00:00:00Z", "ran": "2026-11-20T10:00:00Z"}))
        text = cmd_cutlist.report(root, 60, root / "USER.md", now=1795300000)  # 2026-11-21
        context = next(l for l in text.splitlines() if "error_paste.py" in l)
        self.assertIn("no trigger", context)  # it ran, but never acted, across a log older than 60 days
        wip = next(l for l in text.splitlines() if "wip_save.py" in l)
        self.assertIn("2026-11-20", wip)  # a silent hook counts its last run
        self.assertNotIn("no trigger", wip)

    def test_a_hook_logged_for_less_than_the_window_is_not_flagged_yet(self):
        root = self.repo()
        (self.home / "hook-fires").mkdir()
        (self.home / "hook-fires" / "wip_save.json").write_text(json.dumps({"since": "2026-11-20T00:00:00Z"}))
        text = cmd_cutlist.report(root, 60, root / "USER.md", now=1795300000)
        self.assertNotIn("no trigger", next(l for l in text.splitlines() if "wip_save.py" in l))

    def test_the_command_log_counts_use_and_flags_nothing_while_it_is_young(self):
        root = self.repo()
        cmd_cutlist.record_command("health")
        cmd_cutlist.record_command("--help")
        log = (self.home / "commands.log").read_text().splitlines()
        self.assertEqual(1, len(log))
        self.assertTrue(log[0].endswith("\thealth"))
        rows, began = cmd_cutlist.commands(root, "2026-09-22")
        self.assertEqual("", next(r for r in rows if r["item"] == "health")["flag"])
        self.assertTrue(began)
        (self.home / "commands.log").write_text("2026-08-01T00:00:00Z\tland\n")
        rows, _ = cmd_cutlist.commands(root, "2026-09-22")
        self.assertEqual("no trigger", next(r for r in rows if r["item"] == "land")["flag"])
        self.assertEqual(1, cmd_cutlist.command_cutlist(["--bogus"]))

    def test_dupes_lists_each_pair_of_same_body_helpers_and_the_count(self):
        root = temp_dir(self)
        (root / "scripts").mkdir()
        body = 'def f(x):\n    y = x + 1\n    return y * 2\n'
        (root / "scripts/a.py").write_text(body)
        (root / "scripts/b.py").write_text(body.replace("def f", "def g"))
        (root / "scripts/c.py").write_text("def f(x):\n    return x\n")
        text = cmd_cutlist.dupes_report(root)
        self.assertIn("1 duplicate helper pairs in 1 groups", text)
        self.assertIn("scripts/a.py:1 f, scripts/b.py:1 g", text)


    def test_a_document_that_something_still_links_is_flagged_so_it_is_not_cut(self):
        root = self.repo()
        (root / "docs/OTHER.md").write_text("# Other\n")
        (root / "README.md").write_text("See docs/RULES.md\n")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "Link the rules (#39)")
        rows = cmd_cutlist.documents(root, {}, {})
        self.assertEqual("linked from 1", next(r for r in rows if r["item"] == "docs/RULES.md")["flag"])
        self.assertEqual("", next(r for r in rows if r["item"] == "docs/OTHER.md")["flag"])


if __name__ == "__main__":
    unittest.main()


class TestHookFires(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_output_that_changes_the_session_counts_as_an_action(self):
        self.assertTrue(hook_fires.acted('{"decision": "block", "reason": "x"}'))
        self.assertTrue(hook_fires.acted('{"hookSpecificOutput": {"permissionDecision": "deny"}}'))
        self.assertTrue(hook_fires.acted('{"systemMessage": "note"}'))
        self.assertTrue(hook_fires.acted('{"hookSpecificOutput": {"additionalContext": "note"}}'))
        self.assertFalse(hook_fires.acted("{}"))
        self.assertFalse(hook_fires.acted(""))
        self.assertFalse(hook_fires.acted('{"hookSpecificOutput": {"permissionDecision": "allow"}}'))

    def test_run_passes_output_through_and_records_a_run_and_an_action(self):
        def block():
            print('{"decision": "block"}')
            return 0

        def quiet():
            print("{}")
            return 0

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(0, hook_fires.run("blocker", block))
            hook_fires.run("sleeper", quiet)
        self.assertEqual('{"decision": "block"}\n{}\n', buffer.getvalue())
        seen = hook_fires.last_fires()
        self.assertEqual({"since", "ran", "acted"}, set(seen["blocker"]))
        self.assertEqual({"since", "ran"}, set(seen["sleeper"]))

    def test_an_exception_keeps_the_output_and_a_damaged_file_is_ignored(self):
        def boom():
            print("partial")
            raise RuntimeError("x")

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), self.assertRaises(RuntimeError):
            hook_fires.run("boom", boom)
        self.assertEqual("partial\n", buffer.getvalue())
        (self.home / "hook-fires").mkdir(exist_ok=True)
        (self.home / "hook-fires" / "bad.json").write_text("not json")
        self.assertNotIn("bad", hook_fires.last_fires())
        hook_fires.record("bad", False)
        self.assertEqual({"since", "ran"}, set(hook_fires.last_fires()["bad"]))


class TestJudgmentAndRepoCarriers(unittest.TestCase):
    """A rule only a person can judge is carried when a skill in the repo states it; a repo carries one in its owner-rules.json (#679)."""

    def setUp(self):
        self.root = temp_dir(self) / "oc"
        self.fleet = temp_dir(self) / "fleet"
        self.fleet.mkdir()
        patcher = mock.patch.dict(os.environ, {"OLIVERCODE_FLEET_REGISTRY": str(self.fleet / "repo-profiles.json")})
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.root / "shared").mkdir(parents=True)
        (self.root / "skills" / "plan").mkdir(parents=True)
        (self.root / "skills" / "plan" / "SKILL.md").write_text("# Plan\nThe user approves, then every step runs.\n")
        self.memory = self.root / "USER.md"
        self.memory.write_text("## Standing Rules\n\n- Approved plans run to the end\n")

    def gates(self, *entries):
        (self.fleet / "owner-rule-gates.json").write_text(json.dumps(list(entries)))
        return cmd_cutlist.owner_rules(self.memory, self.root)

    def test_a_judgment_entry_counts_when_the_skill_exists_and_states_the_rule(self):
        got = self.gates({"match": "Approved plans", "check": "judgment: plan", "stated": "the user approves"})
        self.assertEqual([("Approved plans run to the end", "judgment: plan")], got)

    def test_a_missing_skill_or_an_unstated_rule_leaves_the_rule_uncarried(self):
        for entry in ({"check": "judgment: nothing", "stated": "the user approves"}, {"check": "judgment: plan", "stated": "never said"},
                      {"check": "judgment: plan"}):
            got = self.gates({"match": "Approved plans", **entry})
            self.assertEqual([("Approved plans run to the end", "")], got, entry)

    def test_a_repo_entry_counts_only_when_that_repos_owner_rules_hold_the_id(self):
        entry = {"match": "Approved plans", "check": "repo: fleet-app", "id": "plans-run"}
        self.assertEqual("", self.gates(entry)[0][1])
        (self.root.parent / "fleet-app").mkdir()
        (self.root.parent / "fleet-app" / "owner-rules.json").write_text(json.dumps([{"id": "plans-run"}]))
        self.assertEqual("repo: fleet-app", self.gates(entry)[0][1])

    def test_the_engine_ships_no_owner_rule_gates(self):
        self.assertFalse((REPO_ROOT / "shared" / "owner-rule-gates.json").exists())

    def test_a_fleet_with_no_gates_file_lists_no_rules(self):
        self.assertEqual([], cmd_cutlist.owner_rules(self.memory, self.root))

"""The daily version cut, the version-files commit gate and the docs check (story #638)."""

import contextlib
import io
import os
import plistlib
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import REPO_ROOT, git, scratch_repo, temp_dir
from test_precommit_gates import GateHarness, setUpModule, tearDownModule  # noqa: F401
__all__ = ["setUpModule", "tearDownModule"]  # unittest runs them from this module

sys.path.insert(0, str(REPO_ROOT / "scripts"))
SCRIPTS = REPO_ROOT / "core" / "templates" / "project" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import docs_check  # noqa: E402
import version_cut  # noqa: E402
from lib import cmd_version, launchd  # noqa: E402


def commit(repo, day, subject, files=None, remove=(), body=""):
    for rel, text in (files or {"f.txt": subject}).items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for rel in remove:
        (repo / rel).unlink()
    git(repo, "add", "-A")
    stamp = f"{day}T12:00:00+0000"
    env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp, "OLIVERCODE_VERSION_CUT": "1"}
    subprocess.run(["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", subject + ("\n\n" + body if body else "")],
                   check=True, capture_output=True, env=env)


class CutCase(unittest.TestCase):
    def setUp(self):
        self.repo = scratch_repo(temp_dir(self) / "repo", branch="main")
        (self.repo / "docs").mkdir()
        shutil.copy2(REPO_ROOT / "docs" / "VERSIONING.md", self.repo / "docs" / "VERSIONING.md")
        commit(self.repo, "2026-11-01", "Seed the repo (#1)", {"docs/VERSIONING.md": (self.repo / "docs" / "VERSIONING.md").read_text()})

    def cut(self, day):
        out = io.StringIO()
        state, version = version_cut.cut(self.repo, day, "main", out=lambda s: out.write(s + "\n"))
        if version:
            version_cut.commit_cut(self.repo, version, "#850")
        return state, version, out.getvalue()

    def version(self):
        return (self.repo / "VERSION").read_text().strip() if (self.repo / "VERSION").exists() else None


class TestBumpAndLevel(unittest.TestCase):
    rules = version_cut.load_rules(REPO_ROOT)

    def test_numbers_count_up_and_never_roll_over(self):
        self.assertEqual((1, 10, 0), version_cut.bump((1, 9, 0), "MINOR"))
        self.assertEqual((2, 0, 0), version_cut.bump((1, 9, 4), "MAJOR"))
        self.assertEqual((1, 9, 11), version_cut.bump((1, 9, 10), "PATCH"))
        self.assertEqual((1, 0, 0), version_cut.bump(None, "PATCH"))

    def level(self, subject, files=()):
        return version_cut.level_of({"subject": subject, "body": "", "files": list(files)}, self.rules)

    def test_each_level_is_picked_from_the_rules(self):
        self.assertEqual("PATCH", self.level("Fix the retry in land (#9)"))
        self.assertEqual("MINOR", self.level("Add olivercode drain (#9)"))
        self.assertEqual("MINOR", self.level("Land the thing (#9)", [("A", "skills/x/SKILL.md", "skills/x/SKILL.md")]))
        self.assertEqual("PATCH", self.level("Retire the ledger command, cut and remove it (#9)"))
        self.assertEqual("MAJOR", self.level("Tidy (#9)", [("D", "core/hooks/gates/pii.sh", "core/hooks/gates/pii.sh")]))
        self.assertEqual("PATCH", self.level("Tidy (#9)", [("M", "core/hooks/gates/pii.sh", "core/hooks/gates/pii.sh")]))

    def test_the_highest_level_of_the_day_wins(self):
        commits = [{"subject": s, "body": "", "files": []} for s in ("Fix a typo (#1)", "Add a command (#2)")]
        self.assertEqual("MINOR", version_cut.pick_level(commits, self.rules)[0])
        commits.append({"subject": "Tidy (#3)", "body": "", "files": [("D", "core/hooks/gates/pii.sh", "core/hooks/gates/pii.sh")]})
        level, majors = version_cut.pick_level(commits, self.rules)
        self.assertEqual("MAJOR", level)
        self.assertEqual(1, len(majors))


class TestCut(CutCase):
    def test_the_first_cut_sets_1_0_0_and_groups_the_section_by_story(self):
        commit(self.repo, "2026-11-02", "Add a thing (#5)")
        commit(self.repo, "2026-11-02", "Fix the thing (#5)", {"g.txt": "g"})
        commit(self.repo, "2026-11-02", "Tweak without a story", {"h.txt": "h"})
        state, version, _ = self.cut("2026-11-02")
        self.assertEqual(("cut", (1, 0, 0)), (state, version))
        self.assertEqual("1.0.0", self.version())
        log = (self.repo / "CHANGELOG.md").read_text()
        self.assertIn("## 1.0.0 - 2026-11-02", log)
        self.assertEqual(1, log.count("### #5"))
        self.assertLess(log.index("### #5"), log.index("### No story"))

    def test_commits_that_land_after_the_days_cut_get_their_own_version(self):
        commit(self.repo, "2026-11-02", "Add a thing (#5)")
        self.cut("2026-11-02")
        commit(self.repo, "2026-11-02", "Fix another (#6)", {"g.txt": "g"})
        state, version, _ = self.cut("2026-11-02")
        self.assertEqual(("cut", (1, 0, 1)), (state, version))
        log = (self.repo / "CHANGELOG.md").read_text()
        self.assertEqual(1, log.count("Fix another"))
        self.assertEqual(1, log.count("Add a thing"))

    def test_an_empty_day_makes_no_version(self):
        commit(self.repo, "2026-11-02", "Add a thing (#5)")
        self.cut("2026-11-02")
        state, version, out = self.cut("2026-11-03")
        self.assertEqual(("empty", None), (state, version))
        self.assertIn("no new version", out)
        self.assertEqual("1.0.0", self.version())

    def test_a_cut_commit_does_not_count_as_activity(self):
        commit(self.repo, "2026-11-02", "Add a thing (#5)")
        self.cut("2026-11-02")
        self.assertEqual("empty", self.cut("2026-11-03")[0])

    def test_later_days_pick_patch_minor_and_major(self):
        commit(self.repo, "2026-11-02", "Add a thing (#5)")
        self.cut("2026-11-02")
        commit(self.repo, "2026-11-03", "Fix a typo (#6)", {"a.txt": "a"})
        self.assertEqual("1.0.1", ".".join(map(str, self.cut("2026-11-03")[1])))
        commit(self.repo, "2026-11-04", "Add olivercode wonder (#7)", {"b.txt": "b", "skills/old/SKILL.md": "old"})
        self.assertEqual((1, 1, 0), self.cut("2026-11-04")[1])
        commit(self.repo, "2026-11-05", "Fix again (#8)", {"c.txt": "c"})
        commit(self.repo, "2026-11-05", "Remove the old skill (#9)", {"d.txt": "d"}, remove=["skills/old/SKILL.md"], body="Upgrade: use olivercode wonder instead.")
        state, version, _ = self.cut("2026-11-05")
        self.assertEqual((2, 0, 0), version)
        log = (self.repo / "CHANGELOG.md").read_text()
        self.assertIn("Breaking: 1 change", log)
        self.assertIn("#9: use olivercode wonder instead.", log)
        self.assertLess(log.index("## 2.0.0"), log.index("## 1.1.0"))

    def test_a_minor_never_rolls_into_the_next_major(self):
        (self.repo / "VERSION").write_text("1.9.0\n")
        (self.repo / "CHANGELOG.md").write_text("# Changelog\n\n## 1.9.0 - 2026-10-01\n\n### #1\n- x\n")
        commit(self.repo, "2026-11-06", "Add a command (#10)", {"e.txt": "e"})
        self.assertEqual((1, 10, 0), self.cut("2026-11-06")[1])

    def test_a_malformed_version_file_fails_instead_of_being_overwritten(self):
        (self.repo / "VERSION").write_text("one point oh\n")
        commit(self.repo, "2026-11-06", "Add a command (#10)", {"e.txt": "e"})
        with self.assertRaises(ValueError):
            self.cut("2026-11-06")

    def test_commit_cut_commits_both_files_past_the_gate_env(self):
        commit(self.repo, "2026-11-02", "Add a thing (#5)")
        self.cut("2026-11-02")
        self.assertIn("Cut version 1.0.0 (#850)", git(self.repo, "log", "-1", "--format=%s").stdout)
        self.assertEqual("", git(self.repo, "status", "--porcelain").stdout)
        self.assertIn("No test:", git(self.repo, "log", "-1", "--format=%B").stdout)


class TestVersionFilesGate(GateHarness):
    def test_an_ordinary_commit_that_edits_version_is_refused(self):
        self.stage("VERSION", "1.0.1\n")
        result = self.run_hook()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("daily version cut", result.stdout)

    def test_an_ordinary_commit_that_edits_the_changelog_is_refused(self):
        self.stage("CHANGELOG.md", "# Changelog\n")
        self.assertNotEqual(0, self.run_hook().returncode)

    def test_the_cut_may_stage_both_and_other_files_pass(self):
        self.stage("VERSION", "1.0.1\n")
        self.stage("CHANGELOG.md", "# Changelog\n")
        self.assertEqual(0, self.run_hook(OLIVERCODE_VERSION_CUT="1").returncode)
        git(self.tmp, "reset", "-q")
        self.stage("notes.txt", "hello\n")
        self.assertEqual(0, self.run_hook().returncode)


class TestDocsCheck(unittest.TestCase):
    def tree(self):
        root = temp_dir(self)
        files = {
            "scripts/lib/cli.py": 'COMMANDS = [\n    ("olivercode alpha DIR", "x"),\n    ("olivercode beta", "y"),\n]\n',
            "README.md": "# R\n\n`olivercode alpha`, `olivercode beta`\n\n| [`docs/GATES.md`](docs/GATES.md) | g |\n",
            "docs/GATES.md": "# G\n\n## Commit gates\n\n| Gate | Blocks |\n|---|---|\n| Secrets | k |\n\nAfter.\n",
            "scripts/build-hooks.py": 'TITLES = {\n    "secrets": "Secrets",\n}\n',
            "core/hooks/gates/secrets.sh": "true\n",
            "skills/INDEX.md": "| Skill | Domain |\n|---|---|\n| `one` | d |\n",
            "skills/one/SKILL.md": "---\nname: one\n---\n",
        }
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        return root

    def test_a_consistent_tree_passes(self):
        self.assertEqual([], docs_check.run(self.tree()))

    def test_an_undocumented_command_fails(self):
        root = self.tree()
        (root / "README.md").write_text((root / "README.md").read_text().replace(", `olivercode beta`", ""))
        problems = docs_check.run(root)
        self.assertEqual(1, len(problems))
        self.assertIn("beta", problems[0])

    def test_a_gate_with_no_row_and_a_row_with_no_gate_fail(self):
        root = self.tree()
        (root / "core/hooks/gates/extra.sh").write_text("true\n")
        (root / "docs/GATES.md").write_text((root / "docs/GATES.md").read_text().replace("| Secrets | k |", "| Secrets | k |\n| Ghost | z |"))
        text = "\n".join(docs_check.run(root))
        self.assertIn("extra", text)
        self.assertIn("\"Ghost\"", text)

    def test_a_skill_missing_from_the_index_and_an_index_row_with_no_skill_fail(self):
        root = self.tree()
        (root / "skills/two").mkdir()
        (root / "skills/two/SKILL.md").write_text("---\nname: two\n---\n")
        (root / "skills/INDEX.md").write_text((root / "skills/INDEX.md").read_text() + "| `gone` | d |\n")
        text = "\n".join(docs_check.run(root))
        self.assertIn("`two`", text)
        self.assertIn("`gone`", text)

    def test_a_doc_not_linked_from_the_readme_and_a_dead_link_fail(self):
        root = self.tree()
        (root / "docs/EXTRA.md").write_text("# e\n")
        (root / "README.md").write_text((root / "README.md").read_text() + "[x](docs/NOPE.md)\n")
        text = "\n".join(docs_check.run(root))
        self.assertIn("docs/EXTRA.md is not linked", text)
        self.assertIn("docs/NOPE.md", text)

    def test_a_listed_gate_script_that_nothing_runs_fails_and_one_a_script_runs_passes(self):
        root = self.tree()
        (root / "docs/GATES.md").write_text((root / "docs/GATES.md").read_text() + "\nThe smoke gate (`scripts/lib/smoke_runner.py`) fails a bypass.\n")
        text = "\n".join(docs_check.run(root))
        self.assertIn("scripts/lib/smoke_runner.py and the file does not exist", text)
        (root / "scripts/lib/smoke_runner.py").write_text("print('ok')\n")
        (root / "scripts/validate.sh").write_text("# python3 scripts/lib/smoke_runner.py, a comment runs nothing\nexit 0\n")
        problems = docs_check.run(root)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("no script or hook runs it", problems[0])
        (root / "scripts/validate.sh").write_text('python3 "$DIR/lib/smoke_runner.py" .\n')
        self.assertEqual([], docs_check.run(root))

    def test_the_main_exit_code_is_one_on_a_miss_and_zero_on_a_pass(self):
        root = self.tree()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, docs_check.main([str(root)]))
            (root / "skills/INDEX.md").write_text("| Skill | Domain |\n")
            self.assertEqual(1, docs_check.main([str(root)]))

    def test_this_checkout_passes_its_own_docs_check(self):
        self.assertEqual([], docs_check.run(REPO_ROOT))


class TestWiring(unittest.TestCase):
    def test_the_managed_files_ship_both_scripts(self):
        import json
        entries = json.loads((REPO_ROOT / "shared" / "project-bootstrap-manifest.json").read_text())["templatedFiles"]
        targets = {e["target"]: e["mode"] for e in entries}
        self.assertEqual("strict", targets["scripts/version_cut.py"])
        self.assertEqual("strict", targets["scripts/docs_check.py"])

    def test_a_bad_argument_prints_the_usage_and_cuts_nothing(self):
        with mock.patch.object(cmd_version, "load", side_effect=AssertionError("ran")) as load, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(1, cmd_version.command_version_cut(["--day", "2026-11-01", "--now"]))
            self.assertEqual(1, cmd_version.command_version_cut(["--commit", "--schedule"]))
            self.assertEqual(1, cmd_version.command_version_cut(["--day", "--story", "638"]))
        self.assertIn("Usage", out.getvalue())

    def test_schedule_writes_a_nightly_launchd_job(self):
        home = temp_dir(self)
        # launchd is mocked, so the plist is built and checked on Linux too; supported() is forced true so the launchd path runs there.
        with mock.patch.dict(os.environ, {"HOME": str(home), "OLIVERCODE_HOME": str(home / "oc")}), \
                mock.patch.object(launchd, "supported", return_value=True), \
                mock.patch.object(launchd.subprocess, "run", return_value=mock.Mock(returncode=0, stderr="")), \
                mock.patch.object(launchd, "newer_python", return_value="/usr/bin/python3"), \
                mock.patch.object(Path, "home", return_value=home), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, cmd_version.command_version_cut(["--schedule", "--story", "850"]))
            plist = plistlib.loads((home / "Library" / "LaunchAgents" / f"{cmd_version.LABEL}.plist").read_bytes())
            self.assertEqual({"Hour": 23, "Minute": 50}, plist["StartCalendarInterval"])
            self.assertEqual(["version-cut", "--commit", "--story", "850"], plist["ProgramArguments"][-4:])
            self.assertEqual(0, cmd_version.command_version_cut(["--unschedule"]))
            self.assertFalse((home / "Library" / "LaunchAgents" / f"{cmd_version.LABEL}.plist").exists())


class CutAndLand(unittest.TestCase):
    """The daily cut is committed in a worktree of origin/main and landed, so the installed checkout only fast-forwards (#785)."""

    def setUp(self):
        base = temp_dir(self) / "Repos"
        origin = scratch_repo(base / "origin.git", bare=True, branch="main")
        self.oc = scratch_repo(base / "oc", branch="main")
        git(self.oc, "remote", "add", "origin", str(origin))
        (self.oc / "docs").mkdir()
        shutil.copy2(REPO_ROOT / "docs" / "VERSIONING.md", self.oc / "docs" / "VERSIONING.md")
        commit(self.oc, "2026-11-01", "Seed the repo (#1)", {"docs/VERSIONING.md": (self.oc / "docs" / "VERSIONING.md").read_text(encoding="utf-8")})
        git(self.oc, "push", "-q", "origin", "main")
        git(self.oc, "fetch", "-q", "origin")
        self.landed = []
        for patcher in (mock.patch.object(cmd_version, "OC_ROOT", self.oc),
                        mock.patch.object(cmd_version.cmd_land, "command_land", side_effect=lambda argv: self.landed.append(argv) or 0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_cut_is_committed_in_a_worktree_and_handed_to_land_and_the_installed_checkout_is_untouched(self):
        head = git(self.oc, "rev-parse", "HEAD").stdout.strip()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, cmd_version.command_version_cut(["--day", "2026-11-01", "--commit", "--story", "638"]))
        wt = self.oc.parent / "_worktrees" / "oc-cut-2026-11-01"
        self.assertEqual(head, git(self.oc, "rev-parse", "HEAD").stdout.strip())
        self.assertFalse((self.oc / "VERSION").exists())
        self.assertEqual([[str(wt), "638"]], self.landed)
        self.assertTrue((wt / "VERSION").is_file())
        self.assertTrue(git(wt, "log", "-1", "--format=%s").stdout.startswith("Cut version 1.0.0"))

    def test_a_cut_with_no_story_refuses_and_names_the_flag(self):
        out = io.StringIO()
        with mock.patch.object(cmd_version, "cut_and_land") as cut, contextlib.redirect_stdout(out):
            self.assertEqual(1, cmd_version.command_version_cut([]))
        self.assertIn("--story", out.getvalue())
        cut.assert_not_called()

    def test_a_day_with_no_commit_leaves_no_worktree_branch_or_landing(self):
        commit(self.oc, "2026-11-01", "Cut version 1.0.0 (#638)", {"VERSION": "1.0.0\n"})
        git(self.oc, "push", "-q", "origin", "main")
        git(self.oc, "fetch", "-q", "origin")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, cmd_version.command_version_cut(["--day", "2026-11-02", "--commit", "--story", "638"]))
        self.assertEqual([], self.landed)
        self.assertFalse((self.oc.parent / "_worktrees" / "oc-cut-2026-11-02").exists())
        self.assertEqual("", git(self.oc, "branch", "--list", "version-cut-2026-11-02").stdout.strip())

    def test_the_cut_holds_the_lock_while_it_lands_and_releases_it_after(self):
        logs = self.oc.parent / "logs"
        seen = []
        with mock.patch.object(cmd_version.cmd_land, "LOG_DIR", logs), \
                mock.patch.object(cmd_version.cmd_land, "command_land", side_effect=lambda argv: seen.append((logs / "version-cut.lock").is_file()) or 0), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, cmd_version.command_version_cut(["--day", "2026-11-01", "--commit", "--story", "638"]))
        self.assertEqual([True], seen)
        self.assertFalse((logs / "version-cut.lock").exists())

    def test_version_cut_is_the_same_command_as_version_cut_commit(self):
        with mock.patch.object(cmd_version, "cut_and_land", return_value=0) as cut, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, cmd_version.command_version_cut(["--commit", "--day", "2026-11-01", "--story", "638"]))
        self.assertEqual("2026-11-01", cut.call_args.args[1])

    def test_a_second_cut_while_one_runs_refuses(self):
        logs = self.oc.parent / "logs"
        logs.mkdir()
        (logs / "version-cut.lock").write_text(str(os.getppid()))
        out = io.StringIO()
        with mock.patch.object(cmd_version.cmd_land, "LOG_DIR", logs), contextlib.redirect_stdout(out):
            self.assertEqual(1, cmd_version.command_version_cut(["--day", "2026-11-01", "--commit", "--story", "638"]))
        self.assertIn("already running", out.getvalue())
        self.assertEqual([], self.landed)

    def test_a_denied_push_reaches_the_owner_queue_once_with_the_exact_command(self):
        from lib import cmd_owner
        home = temp_dir(self)
        logs = home / "logs"
        logs.mkdir()
        def land(argv):
            (logs / f"land-oc-{argv[1]}.log").write_text("remote: Permission to push denied by the classifier\nRESULT main-kept-moving\n")
            return 1
        with mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home)}), mock.patch.object(cmd_version.cmd_land, "LOG_DIR", logs), \
                mock.patch.object(cmd_version.cmd_land, "command_land", side_effect=land), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, cmd_version.command_version_cut(["--day", "2026-11-01", "--commit", "--story", "638"]))
            wt = self.oc.parent / "_worktrees" / "oc-cut-2026-11-01"
            cmd_version._queue_denial(wt, "638")
            open_lines = [i for i in cmd_owner.items() if i["status"] == "open"]
        self.assertEqual(1, len(open_lines))
        self.assertEqual("git push origin HEAD:main", open_lines[0]["command"])


if __name__ == "__main__":
    unittest.main()

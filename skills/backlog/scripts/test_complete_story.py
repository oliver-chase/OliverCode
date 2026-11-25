"""Test complete_story.py against fixtures and a fake gh runner. No network and no gh.
Run: python3 -m unittest discover -p "test_*.py"   (from this folder)
"""
import io
import json
import os
import shutil
import tempfile
import subprocess
import unittest
import unittest.mock
from pathlib import Path

import complete_story as cs

FIX = Path(__file__).parent / "fixtures"
BODY = str(FIX / "story-scenarios.body")


class CompleteStory(unittest.TestCase):
    """complete_story.py closes a story on its builder entry and pushed commits, through a fake gh runner."""

    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.enterContext(unittest.mock.patch.dict(os.environ, {"OLIVERCODE_HOME": home.name}))
        self.copy = Path(home.name) / "board-o-1.json"

    def test_a_completed_story_drops_the_shared_board_copy(self):
        self.copy.write_text("[]")
        self.run_it("builder-only.json")
        self.assertFalse(self.copy.exists())
        self.copy.write_text("[]")
        self.run_it("no-builder.json")  # nothing was written, so the copy stays
        self.assertTrue(self.copy.exists())

    def run_it(self, comments, items="PVTI_1", extra=None, fail=None, failtext="HTTP 422: Validation Failed", pushed=lambda commit, root=None: None, live=None, root_marker=False):
        calls = []

        def runner(args):
            calls.append(args)
            if fail and any(fail in a for a in args):
                return subprocess.CompletedProcess([], 1, "", failtext)
            text = ""
            if "--slurp" in args:
                text = json.dumps([json.loads((FIX / comments).read_text())])
            elif ".body" in args:
                text = Path(BODY).read_text()
            elif any("projectsV2" in a for a in args):
                text = "\n".join(json.dumps(r) for r in (
                    [{"number": 99, "id": "PVTI_other", "repo": ""}, {"number": 54, "id": items, "repo": "https://api.github.com/repos/o/r"}]
                    if items else []))
            return subprocess.CompletedProcess([], 0, text, "")
        # A real text stream, as sys.stdout is from the command line.
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        cfg.write(json.dumps({"repoOwner": "o", "repoName": "r", "projectId": "PVT_x", "projectNumber": 1, "projectOwner": "o",
                              "fields": {"status": {"id": "F1", "options": {"Complete": "OPT_DONE"}}}, **(extra or {})}))
        cfg.close()
        self.addCleanup(os.unlink, cfg.name)
        self.err = io.StringIO()
        code = cs.main(["--story", "54", "--config", cfg.name, "--evidence", "3 files, validate.sh exits 0"],
                       runner=runner, out=out, err=self.err, pushed=pushed, **({'live': live} if live else {}))
        out.flush()
        return code, out.buffer.getvalue().decode(), [" ".join(c) for c in calls]

    def test_a_held_graphql_share_still_comments_and_closes_and_queues_the_status(self):
        import gh_budget
        gh_budget.note_limit(resources=("graphql",), fetch=lambda: {})
        code, text, calls = self.run_it("builder-only.json")
        self.assertEqual(code, 0)
        joined = "\n".join(calls)
        self.assertIn("state=closed", joined)
        self.assertIn("-f body=3 files", joined)
        self.assertNotIn("graphql", joined)  # no GraphQL call is made while it is held
        self.assertIn("queued for the GraphQL reset", text)
        queued = (Path(os.environ["OLIVERCODE_HOME"]) / gh_budget.QUEUE).read_text()
        self.assertIn("updateProjectV2ItemFieldValue", queued)
        self.assertIn("OPT_DONE", queued)

    def test_closing_a_story_marks_linked_lessons_implemented_by_its_builder_commit(self):
        with unittest.mock.patch.object(cs.lessons, "mark_implemented", return_value=2) as mark:
            code, text, _ = self.run_it("builder-only.json")
        self.assertEqual(0, code)
        mark.assert_called_once_with("#54", "abc1234", unittest.mock.ANY)
        self.assertIn("Marked 2 linked lesson(s) implemented", text)

    def test_the_evidence_comment_ends_with_the_close_mark_the_sweep_reads(self):
        code, _, calls = self.run_it("builder-only.json")
        self.assertEqual(code, 0)
        self.assertIn("3 files, validate.sh exits 0\n\nClosed by complete_story.py.", "\n".join(calls).replace("-f body=", ""))

    def test_a_gated_story_with_no_run_output_is_refused_and_one_with_it_closes(self):
        code, text, calls = self.run_it("builder-only.json", extra={"closeGateFromIssue": 50})
        self.assertEqual(code, 1)
        self.assertIn("no run output", text)
        self.assertFalse([c for c in calls if "state=closed" in c])
        code, _, calls = self.run_it("builder-only.json", extra={"closeGateFromIssue": 60})  # story 54 is below the gate
        self.assertEqual(code, 0)

    def test_a_graphql_limit_hit_on_the_status_write_queues_it_after_the_close(self):
        import gh_budget
        code, text, calls = self.run_it("builder-only.json", fail="graphql", failtext="GraphQL: API rate limit exceeded")
        self.assertEqual(code, 0)
        self.assertTrue(any("state=closed" in c for c in calls))
        self.assertIn("queued for the GraphQL reset", text)
        self.assertTrue((Path(os.environ["OLIVERCODE_HOME"]) / gh_budget.QUEUE).read_text().strip())

    def test_a_story_whose_commit_is_not_on_origin_main_is_refused_and_nothing_is_written(self):
        code, text, calls = self.run_it("builder-only.json", pushed=lambda commit, root=None: f"commit {commit} is not on origin/main; push it first: git push origin HEAD:main")
        self.assertEqual(code, 1)
        self.assertIn("not on origin/main", text)
        self.assertEqual([], [c for c in calls if "PATCH" in c or "mutation" in c or "-f body" in c])

    def test_commit_pushed_reads_the_remote_branches_that_contain_the_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t" + chr(64) + "t.test",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t" + chr(64) + "t.test"}
            def git(*a, cwd=tmp):
                return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, env=env, check=True).stdout.strip()
            remote = os.path.join(tmp, "remote"); work = os.path.join(tmp, "work")
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", remote], check=True)
            subprocess.run(["git", "clone", "-q", remote, work], check=True, capture_output=True, env=env)
            git("commit", "-q", "--allow-empty", "-m", "one", cwd=work)
            git("push", "-q", "origin", "HEAD:main", cwd=work)
            pushed = git("rev-parse", "HEAD", cwd=work)
            git("commit", "-q", "--allow-empty", "-m", "two", cwd=work)
            local = git("rev-parse", "HEAD", cwd=work)
            git("fetch", "-q", "origin", cwd=work)
            self.assertIsNone(cs.commit_pushed(pushed, work))
            self.assertIn("push it first", cs.commit_pushed(local, work))
            self.assertIn("not in this checkout", cs.commit_pushed("0" * 40, work))

    def test_a_commit_on_a_master_default_branch_counts_as_pushed(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t" + chr(64) + "t.test",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t" + chr(64) + "t.test"}
            def git(*a, cwd=tmp):
                return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, env=env, check=True).stdout.strip()
            remote = os.path.join(tmp, "remote"); work = os.path.join(tmp, "work")
            subprocess.run(["git", "init", "-q", "--bare", "-b", "master", remote], check=True)
            subprocess.run(["git", "clone", "-q", remote, work], check=True, capture_output=True, env=env)
            git("commit", "-q", "--allow-empty", "-m", "one", cwd=work)
            git("push", "-q", "origin", "HEAD:master", cwd=work)
            git("fetch", "-q", "origin", cwd=work)
            git("remote", "set-head", "origin", "master", cwd=work)
            self.assertIsNone(cs.commit_pushed(git("rev-parse", "HEAD", cwd=work), work))

    def test_a_board_whose_finished_lane_is_named_done_closes_to_done(self):
        code, _, calls = self.run_it("builder-only.json", extra={"fields": {"status": {"id": "F1", "options": {"Done": "OPT_FINISHED"}}}})
        self.assertEqual(code, 0)
        self.assertIn("-f v=OPT_FINISHED", "\n".join(calls))

    def test_complete_writes_only_after_the_builder_check_passes_and_the_item_is_found(self):
        # A failed close names the write that already landed, so a rerun finishes the rest.
        code, _, _ = self.run_it("builder-only.json", fail="state=closed")
        self.assertEqual(code, 1)
        self.assertIn("already done: evidence comment posted", self.err.getvalue())
        code, _, calls = self.run_it("builder-only.json")
        self.assertEqual(code, 0)
        joined = "\n".join(calls)
        for wanted in ("-f i=PVTI_1","-f v=OPT_DONE", "-f body=3 files, validate.sh exits 0", "state=closed"):
            self.assertIn(wanted, joined)
        self.assertEqual(1, joined.count("graphql"))  # one GraphQL call completes a story; the item lookup is REST
        writes = lambda cs: [c for c in cs if "PATCH" in c or "mutation" in c or "-f body" in c]
        code, text, calls = self.run_it("builder-only.json")  # a builder entry closes the story, and no QA comment is asked for
        self.assertEqual(code, 0)
        self.assertIn("state=closed", "\n".join(calls))
        self.assertNotIn("QA", text)
        code, text, calls = self.run_it("no-builder.json")  # no builder entry
        self.assertEqual(code, 1)
        self.assertIn("not completed", text)
        self.assertEqual([], writes(calls))
        code, text, calls = self.run_it("builder-only.json", items=None)
        self.assertEqual(code, 1)
        self.assertIn("not on the project board", text)
        self.assertEqual([], writes(calls))

    def test_an_olivercode_story_closes_only_when_it_is_live_and_the_evidence_names_the_proof(self):
        with unittest.mock.patch.object(cs, "is_olivercode", lambda root: True):
            code, text, calls = self.run_it("builder-only.json", live=lambda c, oc, root: ("the installed checkout lacks abc", None))
            self.assertEqual(code, 1)
            self.assertIn("not completed: the installed checkout lacks abc", text)
            self.assertEqual([], [c for c in calls if "PATCH" in c or "-f body" in c])
            code, _, calls = self.run_it("builder-only.json", live=lambda c, oc, root: (None, "Live: hook entry Stop wip_save.py is in settings.json."))
            self.assertEqual(code, 0)
            self.assertTrue(any("Live: hook entry Stop wip_save.py" in c for c in calls))


class LiveCheck(unittest.TestCase):
    """live_check: the installed checkout holds the commits, after one update when it is behind (#713)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t" + chr(64) + "t.test", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t" + chr(64) + "t.test"}
        self.oc = self.tmp / "oc"
        self.oc.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.oc / "scripts" / "hooks").mkdir(parents=True); (self.oc / "docs").mkdir()
        (self.oc / "scripts" / "olivercode").write_text(""); (self.oc / "docs" / "RULES.md").write_text("")
        self.git("add", "."); self.git("commit", "-q", "-m", "base")
        self.settings = self.tmp / "settings.json"

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.oc), *a], capture_output=True, text=True, env=self.env, check=True).stdout.strip()

    def commit(self, rel, text):
        f = self.oc / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(text)
        self.git("add", "."); self.git("commit", "-q", "-m", rel)
        return self.git("rev-parse", "HEAD")

    def test_a_commit_the_installed_checkout_holds_passes_and_is_named(self):
        c = self.commit("docs/a.md", "x")
        reason, proof = cs.live_check([c], self.oc, self.oc, update=lambda oc: self.fail("no update needed"))
        self.assertIsNone(reason)
        self.assertIn(c[:10], proof)

    def test_a_checkout_that_is_behind_is_updated_first_and_then_passes(self):
        c = self.commit("docs/a.md", "x")
        self.git("reset", "-q", "--hard", "HEAD~1")
        updated = []
        reason, proof = cs.live_check([c], self.oc, self.oc, update=lambda oc: (updated.append(oc), self.git("reset", "-q", "--hard", c)))
        self.assertEqual(updated, [self.oc])
        self.assertIsNone(reason)

    def test_a_checkout_that_stays_behind_after_the_update_refuses_the_close(self):
        c = self.commit("docs/a.md", "x")
        self.git("reset", "-q", "--hard", "HEAD~1")
        reason, proof = cs.live_check([c], self.oc, self.oc, update=lambda oc: None)
        self.assertIn("even after `olivercode update`", reason)
        self.assertIsNone(proof)

    def test_an_installed_checkout_ahead_of_origin_refuses_the_close_with_the_fix_and_changes_nothing(self):
        """An ahead checkout is refused before any update runs, and the refusal names its commits and the one fix (#785)."""
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
        c = self.commit("docs/a.md", "x")
        reason, proof = cs.live_check([c], self.oc, self.oc, update=lambda oc: self.fail("an ahead checkout is not updated"))
        self.assertIn("origin/main lacks", reason)
        self.assertIn("t: docs/a.md", reason)  # the author name and subject of the commit it holds
        self.assertIn("branch olivercode-local", reason)
        self.assertIsNone(proof)

    def test_a_missing_installed_checkout_refuses_the_close(self):
        reason, _ = cs.live_check(["a" * 40], None, self.oc)
        self.assertIn("$OC", reason)

    def test_a_hook_story_needs_its_entry_in_settings_and_names_it(self):
        c = self.commit("scripts/hooks/wip_save.py", "x")
        reason, _ = cs.live_check([c], self.oc, self.oc, settings=self.settings)
        self.assertIn("wip_save.py is not in", reason)
        cs.claude_settings.install(self.settings, self.oc / "scripts" / "hooks")
        reason, proof = cs.live_check([c], self.oc, self.oc, settings=self.settings)
        self.assertIsNone(reason)
        self.assertIn("hook entry Stop wip_save.py", proof)

    def test_a_job_story_needs_the_job_loaded_and_names_its_label(self):
        c = self.commit("scripts/lib/cmd_job.py", 'LABEL = "com.olivercode.demo-job"\n'
                        'def schedule(on):\n    return launchd.schedule(on, LABEL, lambda: launchd.job(LABEL, ["x"], "x.out"), "a", "b")\n')
        reason, _ = cs.live_check([c], self.oc, self.oc, loaded=lambda label: False)
        self.assertIn("com.olivercode.demo-job is not loaded", reason)
        reason, proof = cs.live_check([c], self.oc, self.oc, loaded=lambda label: label == "com.olivercode.demo-job")
        self.assertIsNone(reason)
        self.assertIn("launchd job com.olivercode.demo-job is loaded", proof)

    def test_a_label_listed_only_as_register_data_is_not_demanded(self):
        c = self.commit("scripts/lib/features.py", 'FEATURES = {"burndown": _job("com.olivercode.burndown")}\n')
        reason, proof = cs.live_check([c], self.oc, self.oc, loaded=lambda label: self.fail(f"{label} is data, not a job"))
        self.assertIsNone(reason)
        self.assertNotIn("launchd job", proof)

    def test_a_job_built_inside_a_test_file_is_not_demanded(self):
        c = self.commit("skills/backlog/scripts/test_fake.py", 'launchd.schedule(True, "com.olivercode.fake-job", plist, "a", "b")\n')
        reason, _ = cs.live_check([c], self.oc, self.oc, loaded=lambda label: self.fail(f"{label} is a test fixture"))
        self.assertIsNone(reason)

    def test_a_commit_that_edits_unrelated_lines_demands_no_job(self):
        job = ('LABEL = "com.olivercode.version-cut"\n'
               'def schedule():\n    return launchd.schedule(True, LABEL, lambda: launchd.job(LABEL, ["x"], "x.out"), "a", "b")\n\n'
               'def cleanup():\n    pass\n')
        self.commit("scripts/lib/cmd_version.py", job)
        c = self.commit("scripts/lib/cmd_version.py", job.replace('pass', 'return "done"'))
        reason, proof = cs.live_check([c], self.oc, self.oc, loaded=lambda label: self.fail(f"{label} is unrelated to this commit"))
        self.assertIsNone(reason)
        self.assertNotIn("launchd job", proof)

    def test_a_commit_that_changes_the_job_call_demands_it_resolving_the_constant_from_the_whole_file(self):
        self.commit("scripts/lib/cmd_version.py", 'LABEL = "com.olivercode.version-cut"\ndef schedule():\n    pass\n')
        c = self.commit("scripts/lib/cmd_version.py", 'LABEL = "com.olivercode.version-cut"\n'
                        'def schedule():\n    return launchd.schedule(True, LABEL, lambda: launchd.job(LABEL, ["x"], "x.out"), "a", "b")\n')
        reason, _ = cs.live_check([c], self.oc, self.oc, loaded=lambda label: False)
        self.assertIn("com.olivercode.version-cut is not loaded", reason)

    def test_a_plist_label_or_literal_schedule_call_is_demanded(self):
        c = self.commit("scripts/lib/cmd_plist.py", 'def plist():\n    return {"Label": "com.olivercode.plist-job"}\n'
                        'launchd.schedule(True, "com.olivercode.lit-job", plist, "a", "b")\n')
        reason, _ = cs.live_check([c], self.oc, self.oc, loaded=lambda label: label != "com.olivercode.plist-job")
        self.assertIn("com.olivercode.plist-job is not loaded", reason)
        reason, _ = cs.live_check([c], self.oc, self.oc, loaded=lambda label: label != "com.olivercode.lit-job")
        self.assertIn("com.olivercode.lit-job is not loaded", reason)

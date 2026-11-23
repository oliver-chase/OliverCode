"""The candidates list holds what the automatic filers find, files nothing, and promotes a chosen candidate to the board once (#895)."""

import json
import os
import re
import subprocess
import sys
import unittest
from unittest import mock

from _support import REPO_ROOT, quiet, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import candidates, failure_log, gh_budget, intake, lesson_cover, retro, story_outbox  # noqa: E402


def origin_as_github() -> dict:
    """Environment that makes a checkout whose origin is a local path (a clean clone) read as its own GitHub repo, so a child process names a target for its candidates."""
    origin = subprocess.run(["git", "-C", str(REPO_ROOT), "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    if not origin or "github.com" in origin:
        return {}
    cfg = json.loads((REPO_ROOT / "docs" / "backlog-config.json").read_text(encoding="utf-8"))
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.https://github.com/{cfg['repoOwner']}/{cfg['repoName']}.git.insteadOf", "GIT_CONFIG_VALUE_0": origin}


class Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, f"https://github.com/acme/widget/issues/{800 + len(self.calls)}\n", "")


class TestCandidates(unittest.TestCase):
    def setUp(self):
        home = temp_dir(self)
        p = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": str(home), "OLIVERCODE_GH_POINTS_FLOOR": "0"})
        p.start()
        self.addCleanup(p.stop)

    def test_adding_files_nothing_and_the_same_story_is_held_once(self):
        candidates.add("gap-sweep", "acme/widget", "Turn on hooks", "Body")
        candidates.add("retro", "acme/widget", "Turn on hooks", "Body")
        self.assertEqual(1, candidates.count())
        self.assertEqual(0, story_outbox.count())
        self.assertTrue(candidates.has("acme/widget", "Turn on hooks"))

    def test_the_list_prints_numbered_and_promoting_files_one_story_once(self):
        candidates.add("gap-sweep", "acme/widget", "First", "A")
        candidates.add("retro", "acme/widget", "Second", "B")
        code, out = quiet(candidates.command_candidates, [])
        self.assertEqual(0, code)
        self.assertIn("1. [gap-sweep] acme/widget: First", out)
        self.assertIn("2. [retro] acme/widget: Second", out)
        runner = Runner()
        code, out = quiet(candidates.command_candidates, ["promote", "2"], runner)
        self.assertEqual(0, code)
        self.assertEqual(1, len(runner.calls))
        self.assertIn("Second", runner.calls[0])
        self.assertEqual(["First"], [i["title"] for i in candidates.items()])
        quiet(candidates.command_candidates, ["promote", "2"], runner)
        self.assertEqual(1, len(runner.calls), "a promoted candidate is not filed twice")

    def test_a_held_budget_leaves_the_promoted_story_in_the_outbox_and_off_the_list(self):
        from lib import gh_budget
        candidates.add("retro", "acme/widget", "Held", "B")
        gh_budget.note_limit(who="test")
        runner = Runner()
        code, _ = quiet(candidates.command_candidates, ["promote", "1"], runner)
        self.assertEqual((1, [], 1, 0), (code, runner.calls, story_outbox.count(), candidates.count()))

    def test_a_candidate_for_a_private_repo_is_promoted_to_that_repo_and_never_the_engine(self):
        candidates.add("maintain", "acme/private-widget", "Rebase widget", "Fix: rebase")
        runner = Runner()
        quiet(candidates.command_candidates, ["promote", "1"], runner)
        self.assertEqual(1, len(runner.calls))
        self.assertEqual("acme/private-widget", runner.calls[0][runner.calls[0].index("--repo") + 1])
        self.assertNotIn("OliverCode", " ".join(runner.calls[0]))

    def test_drop_removes_and_a_bad_number_is_refused(self):
        candidates.add("retro", "acme/widget", "One", "B")
        self.assertEqual(2, quiet(candidates.command_candidates, ["promote", "5"], Runner())[0])
        self.assertEqual(0, quiet(candidates.command_candidates, ["drop", "1"])[0])
        self.assertEqual(0, candidates.count())

    def test_add_from_the_command_line_names_its_source(self):
        code, _ = quiet(candidates.command_candidates, ["add", "--source", "audit", "--repo", "acme/widget", "--title", "Fix", "--body", "Why"])
        self.assertEqual(0, code)
        self.assertEqual("audit", candidates.items()[0]["source"])


class TestNoDirectFiling(unittest.TestCase):
    """No scheduled job or hook creates an issue (#971): each one adds a candidate, and a run stops at the per-run cap."""

    def setUp(self):
        home = temp_dir(self)
        cfg = home / "local.json"
        cfg.write_text(json.dumps({"autoCoverLessons": True}))
        env = {"OLIVERCODE_HOME": str(home), "OLIVERCODE_LOCAL_CONFIG": str(cfg), "OLIVERCODE_FAILURE_LOG": str(home / "failures.log")}
        for p in (mock.patch.dict(os.environ, env), mock.patch.object(gh_budget, "refusal", return_value=""),
                  mock.patch.object(retro, "sources", return_value=[("structure", None)]),
                  mock.patch.object(retro, "slug", return_value="o/r"),
                  mock.patch.object(lesson_cover, "own_backlog", return_value=True)):
            p.start()
            self.addCleanup(p.stop)

    def test_the_lesson_job_meets_fifty_repeated_refusals_and_adds_at_most_the_cap(self):
        for n in range(50):
            for _ in range(3):
                failure_log.record("Commit message", f"refusal {n}", "r")
        lines = []
        retro.auto_cover(out=lines.append, fetch=lambda slug: [])
        cap = int(candidates.limits()["retroFilesPerRun"])
        self.assertEqual(cap, candidates.count())
        self.assertEqual(0, story_outbox.count())
        self.assertTrue(all(i["title"].startswith(intake.PREVENT) for i in candidates.items()))
        retro.auto_cover(out=lines.append, fetch=lambda slug: [])
        self.assertEqual(2 * cap, candidates.count(), "a second run adds the next ones and never the same ones twice")

    def test_a_refusal_from_a_removed_guard_adds_no_candidate(self):
        for _ in range(3):
            failure_log.record("main_checkout_guard", "edit in the main checkout", "r")
        self.assertEqual([], intake.prevention("o/r", 1, fetch=lambda slug: []))
        self.assertEqual(0, candidates.count())
        for _ in range(3):
            failure_log.record("placement_guard", "wrong folder", "r")
        self.assertEqual(1, len(intake.prevention("o/r", 1, fetch=lambda slug: [])))

    def test_a_pasted_error_adds_a_candidate_and_creates_no_issue(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
        import error_paste
        text = error_paste.file_story("Traceback (most recent call last):\n  File \"a.py\", line 1\nValueError: bad\n", "s", "")
        self.assertIn("candidate", text)
        self.assertEqual(["Fix: ValueError: bad"], [i["title"] for i in candidates.items()])
        self.assertEqual(0, story_outbox.count())

    def test_a_creator_is_named_only_by_the_outbox_the_candidates_list_and_the_owner_commands(self):
        """Any mention of the issue creators, called or passed as a value, sits in a file the owner's commands reach."""
        allowed = {"scripts/lib/story_outbox.py", "scripts/lib/candidates.py", "scripts/hooks/gh_guard.py", "scripts/olivercode", "scripts/lib/cli.py"}
        mention = re.compile(r"story_outbox\.(add|flush|_run_gh|command_story)\b|story_outbox import|issue create|\"issue\",\s*\"create\"|createIssue")
        found = set()
        for path in (REPO_ROOT / "scripts").rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if mention.search(path.read_text(encoding="utf-8")):
                found.add(rel)
        self.assertEqual(set(), found - allowed, "a script names an issue creator outside the outbox and the candidates list")


FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$GH_RECORD"
case "$1 $2" in
  "issue list") echo "[]" ;;
  "issue create") echo "https://github.com/o/r/issues/1" ;;
esac
exit 0
"""


def creations(record) -> list[str]:
    """The recorded gh calls that create an issue: `gh issue create`, or a POST to a repo's issues endpoint."""
    lines = record.read_text().splitlines() if record.is_file() else []
    return [ln for ln in lines if ln.startswith("issue create") or re.search(r"api .*repos/[^/ ]+/[^/ ]+/issues( |$)", ln) and re.search(r"title=|-X POST", ln)]


class TestScheduledEntryPoints(unittest.TestCase):
    """Every scheduled job and hook meets a failure log of 50 repeated refusals with a recorder in place of GitHub (#971)."""

    def setUp(self):
        self.root = temp_dir(self)
        self.home = self.root / "home"
        self.oc = self.home / ".olivercode"
        self.oc.mkdir(parents=True, mode=0o700)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.record = self.root / "gh-calls.txt"
        (self.root / "local.json").write_text(json.dumps({"autoCoverLessons": True}))
        (self.oc / "failures.log").write_text("".join(
            f"2026-11-0{1 + n % 9}T10:00:{m:02d}Z\tOliverCode\tCommit message\trefusal number {n}\n" for n in range(50) for m in range(3)))
        self.env = {**os.environ, "HOME": str(self.home), "OLIVERCODE_HOME": str(self.oc), "OLIVERCODE_FAILURE_LOG": str(self.oc / "failures.log"),
                    "OLIVERCODE_LOCAL_CONFIG": str(self.root / "local.json"), "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "GH_RECORD": str(self.record), "OLIVERCODE_GH_POINTS_FLOOR": "0"}
        self.env.update(origin_as_github())
        patch = mock.patch.dict(os.environ, self.env)
        patch.start()
        self.addCleanup(patch.stop)

    def candidate_count(self) -> int:
        return len((self.oc / "candidates.jsonl").read_text().splitlines()) if (self.oc / "candidates.jsonl").is_file() else 0

    def launcher(self, *argv, stdin=None):
        done = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "olivercode"), *argv], capture_output=True, text=True, env=self.env, input=stdin, timeout=120)
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)

    def test_the_lesson_job_adds_at_most_the_cap_and_creates_no_issue(self):
        self.launcher("retro", "--auto")
        self.assertEqual([], creations(self.record))
        self.assertTrue(0 < self.candidate_count() <= candidates.limits()["retroFilesPerRun"])
        self.assertFalse((self.oc / "story-outbox.jsonl").exists())

    def test_the_hooks_create_no_issue(self):
        hooks = REPO_ROOT / "scripts" / "hooks"
        for n in range(50):
            prompt = f"Traceback (most recent call last):\n  File \"a.py\", line 1\nValueError: bad {n}\n"
            subprocess.run([sys.executable, str(hooks / "error_paste.py")], input=json.dumps({"prompt": prompt, "session_id": "s", "cwd": "/nonexistent"}),
                           capture_output=True, text=True, env=self.env, check=True)
            subprocess.run([sys.executable, str(hooks / "lesson_capture.py")], input=json.dumps({"prompt": "no, that is wrong, stop doing that", "session_id": "s"}),
                           capture_output=True, text=True, env=self.env, check=True)
        self.assertEqual([], creations(self.record))
        self.assertEqual(50, self.candidate_count(), "each pasted error adds one candidate and no more")
        self.assertFalse((self.oc / "story-outbox.jsonl").exists())

    def test_the_groom_intake_and_prevention_checks_with_their_defaults_create_no_issue(self):
        from lib import cmd_groom
        stories = {n: {"number": n, "title": f"Imported {n}", "body": "Priority: P2. Size: S.\nPriority source: imported from a file", "labels": []} for n in range(1, 11)}
        with mock.patch.object(cmd_groom, "imported", return_value=sorted(stories)):
            cmd_groom.review_imported("o/r", stories, {}, 1, run=lambda a: "")
        bad = [{"number": n, "title": f"Raw {n}", "body": "no template", "labels": []} for n in range(1, 9)]
        intake.check("Alpha", "o/r", 1, fetch=lambda slug: bad)
        intake.prevention("o/r", 1, fetch=lambda slug: [])
        self.assertEqual([], creations(self.record))
        self.assertFalse((self.oc / "story-outbox.jsonl").exists())
        self.assertTrue(candidates.count() >= 2)

    def test_maintain_with_fix_leaves_a_waiting_outbox_unfiled(self):
        from lib import maintain
        for n in range(5):
            story_outbox.add("o/r", f"Waiting {n}", "body")
        maintain.check_queues(True)
        self.assertEqual([], creations(self.record))
        self.assertEqual(5, story_outbox.count())


if __name__ == "__main__":
    unittest.main()

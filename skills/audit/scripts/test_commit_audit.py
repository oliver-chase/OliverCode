"""commit_audit.py counts each finding class in a scratch repo and reports the change since the last run."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import commit_audit  # noqa: E402

ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
       "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a" + "@x.invalid", "GIT_COMMITTER_NAME": "a",
       "GIT_COMMITTER_EMAIL": "a" + "@x.invalid"}


class CommitAudit(unittest.TestCase):
    def test_the_audit_uses_the_fleet_checks_contrast_pattern(self):
        import fleet_check
        self.assertIs(commit_audit.CONTRAST, fleet_check.CONTRAST)
        self.assertTrue(commit_audit.CONTRAST.search("less speed, more care"))

    def test_counts_each_class_and_the_change_since_the_last_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, state = Path(tmp) / "shop", Path(tmp) / "state.json"
            subprocess.run(["git", "init", "-q", str(repo)], check=True, env=ENV)

            def commit(message, *files):
                for f in files:
                    (repo / f).parent.mkdir(parents=True, exist_ok=True)
                    (repo / f).write_text(message + "\n")
                    subprocess.run(["git", "-C", str(repo), "add", f], check=True, env=ENV)
                subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", message], check=True, env=ENV)

            commit("Add a tool (#1)", "tool.py")                                   # code-no-test
            commit("Add a tool test (#2)", "tool.py", "tests/test_tool.py")       # clean
            commit("Tidy things")                                                  # no-story
            commit("Merge pull request #3 from a/b")                               # pr-merge
            commit("Work (#4)\n\nCo-authored-by: Claude <x" + "@y.invalid>")            # coauthor-form
            commit("Work (#5)\n\n- did a thing.")                                  # voice

            def run():
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    commit_audit.main([str(repo), "--state", str(state), "--since", "1.year"])
                return out.getvalue()

            first = run()
            for line in ("no-story: 1 (first run)", "pr-merge: 1", "code-no-test: 1", "coauthor-form: 1", "voice: 1"):
                self.assertIn(line, first)
            commit("More (#6)", "more.py")
            self.assertIn("code-no-test: 2 (+1 since last run)", run())
            self.assertEqual("", subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                                                capture_output=True, text=True, env=ENV).stdout)  # read-only




class CommitAuditEdges(unittest.TestCase):
    def test_a_folder_with_no_history_has_no_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([], list(commit_audit.commits(tmp, "30 days ago")))


if __name__ == "__main__":
    unittest.main()

"""Behaviour tests for fleet_check.py: each behavior of the lean-fleet pass runs against a scratch repo."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet_check  # noqa: E402

BASELINE_FILE = Path(__file__).resolve().parents[3] / "shared" / "kanban-baseline.json"
BASELINE = json.loads(BASELINE_FILE.read_text(encoding="utf-8")) if BASELINE_FILE.is_file() else None


def make_repo(tmp, files):
    root = Path(tmp)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    subprocess.run(["git", "init", "-q", str(root)], check=True, env=env)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=env)
    return root


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fleet_check.main(list(argv))
    return code, out.getvalue()


def fields(lanes):
    def single(name, options):
        return {"name": name, "type": "ProjectV2SingleSelectField", "options": [{"name": o} for o in options]}
    return {"fields": [single("Status", lanes), single("Priority", BASELINE["fields"]["Priority"]),
                       single("Size", BASELINE["fields"]["Size"]), single("Work type", BASELINE["fields"]["Work type"]),
                       single("Area", ["Core"])]}


class Tests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(fleet_check, "voice_configured", return_value=True)  # these tests run the voice scan; the next class covers its absence
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_time_runs_the_repos_validation_once_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fleet_check.os, "getloadavg", return_value=(0, 0, 0)), \
                mock.patch.object(fleet_check, "queued", side_effect=lambda c: c):
            repo = make_repo(tmp, {"scripts/validate.sh": "echo run >> ran.txt\n"})
            code, out = run("--time", str(repo))
            self.assertEqual(code, 0)
            self.assertRegex(out, r"tests: the repo's validation passed in \d+\.\ds")
            self.assertEqual(["run"], (repo / "ran.txt").read_text().split())
            (repo / "scripts/validate.sh").write_text("echo boom\nexit 1\n")
            code, out = run("--time", str(repo))
            self.assertEqual(code, 1)
            self.assertIn("failed", out)

    def test_time_waits_when_the_machine_is_overloaded(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fleet_check.os, "getloadavg", return_value=(999, 0, 0)):
            repo = make_repo(tmp, {"scripts/validate.sh": "exit 1\n"})
            code, out = run("--time", str(repo))
            self.assertEqual(code, 0)
            self.assertIn("tests: not run", out)


class AloneBoard(unittest.TestCase):
    def test_a_missing_baseline_checker_is_reported_and_the_rest_still_prints(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"docs/backlog-config.json": json.dumps(
                {"repoOwner": "o", "repoName": "r", "projectNumber": 1, "projectOwner": "o"})})
            with mock.patch.object(fleet_check, "BASELINE_SCRIPT", Path(tmp) / "absent.py"):
                _, out = run(str(repo))
            self.assertIn("board: not checked", out)
            self.assertIn("voice:", out)


class Voice(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(fleet_check, "voice_configured", return_value=True)  # the scan runs only with a voice file, which a clean home lacks
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_scan_is_skipped_when_no_voice_file_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"A.md": "It is a guide, not a rule.\n"})
            with mock.patch.object(fleet_check, "voice_configured", return_value=False):
                code, out = run(str(repo))
            self.assertEqual(code, 0)
            self.assertIn("voice: skipped, no voice file is configured", out)

    def test_names_the_file_and_line_of_each_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"docs/A.md": "# Title\n\nIt is fast, not slow, but steady.\n- ends with a period.\n- fine\n"
                                   "\n```\nnot this, but that.\n```\n"})
            code, out = run(str(repo))
            self.assertEqual(code, 1)
            self.assertIn("docs/A.md:3: contrast framing", out)
            self.assertIn("docs/A.md:4", out)
            self.assertNotIn("docs/A.md:8", out)
            self.assertNotIn("docs/A.md:5", out)

    def test_a_quoted_phrase_list_is_not_contrast_framing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"A.md": 'Never use "not X, but Y" or "rather than" here.\nIt is fast rather than slow.\n'})
            _, out = run(str(repo))
            self.assertNotIn("A.md:1", out)
            self.assertIn("A.md:2: contrast framing", out)
        # The common forms: ", not a ..." and "not X but Y" without a comma.
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"A.md": "It is a guide, not a rule.\nIt is not slow but fast.\nIt is fine.\n"})
            _, out = run(str(repo))
            self.assertIn("A.md:1: contrast framing", out)
            self.assertIn("A.md:2: contrast framing", out)
            self.assertNotIn("A.md:3", out)
        # "and not the ..." is the same framing without a comma.
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"A.md": "It reads the scopes and not the remote URL.\nIt runs and nothing else.\n"})
            _, out = run(str(repo))
            self.assertIn("A.md:1: contrast framing", out)
            self.assertNotIn("A.md:2", out)

    def test_flags_title_case_headings_and_curly_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"A.md": "## How The Gates Work\n\nA “quote” here\n\n## How the gates work\n"})
            _, out = run(str(repo))
            self.assertIn("A.md:1: Title Case heading", out)
            self.assertIn("A.md:3: curly quotes", out)
            self.assertNotIn("A.md:5", out)

    def test_a_title_that_spells_the_repo_name_is_a_proper_noun(self):
        with tempfile.TemporaryDirectory() as tmp:
            named = make_repo(Path(tmp) / "sample-planning-tool", {"A.md": "# Sample Planning Tool\n\n## How The Gates Work\n"})
            _, out = run(str(named))
            self.assertNotIn("A.md:1", out)
            self.assertIn("A.md:3: Title Case heading", out)

    def test_clean_text_reports_no_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"A.md": "## Sentence case\n\n- a bullet\n"})
            _, out = run(str(repo))
            self.assertIn("voice: no violations found", out)


@unittest.skipUnless(BASELINE, "the board baseline sits in the OliverCode repo, beside skills/")
class Board(unittest.TestCase):
    def drift(self, lanes):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"README.md": "ok\n"})
            saved = Path(tmp) / "fields.json"
            saved.write_text(json.dumps(fields(lanes)), encoding="utf-8")
            return run("--fields-file", str(saved), str(repo))

    def test_names_the_board_and_the_difference(self):
        code, out = self.drift(["Backlog", "Ready", "In Review", "Complete"])
        self.assertEqual(code, 1)
        self.assertIn("In Review", out)
        self.assertIn("missing option In Progress", out)

    def test_a_matching_board_passes(self):
        code, out = self.drift(BASELINE["lanes"])
        self.assertEqual(code, 0)
        self.assertIn("board: matches the baseline", out)

    def test_a_repo_without_a_backlog_config_skips_the_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"README.md": "ok\n"})
            _, out = run(str(repo))
            self.assertIn("board: no backlog config, not checked", out)
            # A failed board read is reported and the other measures still print.
            (repo / "docs").mkdir()
            (repo / "docs" / "backlog-config.json").write_text(json.dumps(
                {"repoOwner": "o", "repoName": "r", "projectNumber": 1, "projectOwner": "o"}), encoding="utf-8")
            gh_dir = Path(tmp) / "bin"
            gh_dir.mkdir()
            (gh_dir / "gh").write_text("#!/bin/sh\necho 'rate limit' >&2\nexit 1\n")
            (gh_dir / "gh").chmod(0o755)
            with mock.patch.dict("os.environ", {"PATH": f"{gh_dir}:/usr/bin:/bin"}):
                _, out = run(str(repo))
            self.assertIn("board: not checked", out)
            self.assertIn("voice:", out)




class BoardDriftEdges(unittest.TestCase):
    def test_a_config_missing_its_owner_reports_instead_of_crashing(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "docs").mkdir()
            (Path(tmp) / "docs" / "backlog-config.json").write_text(json.dumps({"repoName": "x"}))
            name, drift, error = fleet_check.board_drift(tmp, None)
            self.assertIsNone(drift)
            self.assertIn("unreadable", error)


class TestForkConfig(unittest.TestCase):
    def test_a_config_for_another_repo_is_not_read_as_this_repos_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"repoOwner": "owner", "repoName": "OliverCode", "projectOwner": "owner", "projectNumber": 15, "projectId": "PVT_1", "fields": {}}
            repo = make_repo(tmp, {"docs/backlog-config.json": json.dumps(config)})
            subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/me/my-fork.git"], check=True)
            name, drift, error = fleet_check.board_drift(str(repo), None)
        self.assertIsNone(drift)
        self.assertIn("this is a fork carrying the owner's config", error)

"""Behaviour tests for fleet_check.py: each Gherkin scenario of the lean-fleet pass runs against a scratch repo."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet_check  # noqa: E402

BASELINE = json.loads((Path(__file__).resolve().parents[3] / "shared" / "kanban-baseline.json").read_text(encoding="utf-8"))


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


class Budgets(unittest.TestCase):
    def test_reports_counts_against_the_budget_and_flags_the_overrun(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {
                "docs/BUDGET.json": json.dumps({"testCount": 1, "testSeconds": 60, "docWords": 1000, "skillWords": 1}),
                "tests/test_a.py": "import unittest\nclass T(unittest.TestCase):\n    def test_one(self): pass\n    def test_two(self): pass\n",
                "README.md": "one two three\n",
                "skills/x/SKILL.md": "---\nname: x\n---\nfour five six\n",
            })
            code, out = run("--time", str(repo))
            self.assertEqual(code, 1)
            self.assertIn("testCount: 2 is over the budget of 1", out)
            self.assertIn("docWords: 3 within the budget of 1000", out)
            self.assertIn("skillWords: 7 is over the budget of 1", out)
            seconds = [line for line in out.splitlines() if line.startswith("testSeconds:")][0]
            self.assertIn("within the budget of 60", seconds)
            self.assertRegex(out, r"slowest test files: test_a \d+\.\ds")

    def test_runtime_is_not_measured_without_the_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"README.md": "word\n"})
            _, out = run(str(repo))
            self.assertIn("testSeconds: not measured (pass --time)", out)


class Voice(unittest.TestCase):
    def test_names_the_file_and_line_of_each_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"docs/A.md": "# Title\n\nIt is fast, not slow, but steady.\n- ends with a period.\n- fine\n"
                                   "\n```\nnot this, but that.\n```\n"})
            code, out = run(str(repo))
            self.assertEqual(code, 1)
            self.assertIn("docs/A.md:3: contrast framing", out)
            self.assertIn("docs/A.md:4: trailing period on a bullet", out)
            self.assertNotIn("docs/A.md:8", out)
            self.assertNotIn("docs/A.md:5", out)

    def test_flags_title_case_headings_and_curly_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"A.md": "## How The Gates Work\n\nA “quote” here\n\n## How the gates work\n"})
            _, out = run(str(repo))
            self.assertIn("A.md:1: Title Case heading", out)
            self.assertIn("A.md:3: curly quotes", out)
            self.assertNotIn("A.md:5", out)

    def test_clean_text_reports_no_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, {"A.md": "## Sentence case\n\n- a bullet\n"})
            _, out = run(str(repo))
            self.assertIn("voice: no violations found", out)


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
        self.assertIn("the saved board: Status: lane In Review is driven by pull requests", out)
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


if __name__ == "__main__":
    unittest.main()

"""Rename check: a rename story lists its old name and closes only when the old name is gone (#838). Every repo here is a scratch fixture."""

import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

from _support import REPO_ROOT, temp_dir

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "backlog" / "scripts"))
from lib import rename_check  # noqa: E402
import complete_story  # noqa: E402

STORY = "Rename the chart.\n\nRenames: oldchart -> newchart\nEpic: #1\n"
BUILDER = "Agent action\n- Agent: builder\n- Role: builder\n- Result: renamed the chart"


def scratch(files):
    root = temp_dir(unittest.TestCase())
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


def close(body, root):
    """Run complete_story.py for the story against fixture comments and the scratch repo, with no network."""
    config = root / "docs" / "backlog-config.json"
    config.parent.mkdir(exist_ok=True)
    config.write_text(json.dumps({"repoOwner": "o", "repoName": "r", "projectId": "P", "projectNumber": 1, "projectOwner": "o",
                                  "fields": {"status": {"id": "F", "options": {"Complete": "D"}}}}))

    def runner(args):
        text = ""
        if "--slurp" in args:
            text = json.dumps([[{"body": BUILDER}]])
        elif ".body" in args:
            text = body
        elif any("projectsV2" in a for a in args):
            text = json.dumps({"number": 54, "id": "PVTI_1", "repo": ""})
        return subprocess.CompletedProcess([], 0, text, "")
    out = io.StringIO()
    code = complete_story.main(["--story", "54", "--config", str(config), "--evidence", "done"], runner=runner, out=out,
                               err=io.StringIO(), pushed=lambda commit, root=None: None)
    return code, out.getvalue()


class TestRenameCheck(unittest.TestCase):
    def test_the_line_is_read_and_a_story_without_one_closes_as_before(self):
        self.assertEqual(("oldchart", "newchart"), rename_check.parse(STORY))
        self.assertIsNone(rename_check.parse("Rename the chart."))
        self.assertEqual("", rename_check.refusal("A plain story.", scratch({"scripts/a.py": "oldchart\n"})))

    def test_each_remaining_file_and_line_is_listed_and_the_story_is_refused(self):
        root = scratch({"scripts/a.py": "x = 1\nuse oldchart here\n", "docs/b.md": "oldchart\n", "tests/test_a.py": "ok\n",
                        "scripts/oldchart_job.plist": "<key>Label</key>", "other/c.txt": "oldchart\n"})
        why = rename_check.refusal(STORY, root)
        for place in ("scripts/a.py:2", "docs/b.md:1", "scripts/oldchart_job.plist (file name)"):
            self.assertIn(place, why)
        self.assertNotIn("other/c.txt", why)
        self.assertIn("Change each to `newchart`", why)
        code, text = close(STORY, root)
        self.assertEqual(1, code)
        self.assertIn("not completed", text)
        self.assertIn("scripts/a.py:2", text)

    def test_an_alias_line_and_a_history_file_do_not_count(self):
        root = scratch({"scripts/a.py": "newchart = 1\nALIAS: oldchart still works as an alias\n", "docs/history.md": "oldchart\n",
                        "docs/LIMITS.json": "oldchart", "docs/guide.md": "newchart only\n", "docs/oldchartish.md": "no match: oldcharts\n"})
        self.assertEqual("", rename_check.refusal(STORY, root))
        code, text = close(STORY, root)
        self.assertEqual(0, code, text)

    def test_groom_flags_a_rename_story_with_no_line_and_names_the_fix(self):
        stories = {1: {"title": "Rename showcase to gallery", "body": "no line"},
                   2: {"title": "Rename showcase to gallery", "body": STORY},
                   3: {"title": "A rename story lists the old name", "body": "x"},
                   4: {"title": "Add a check", "body": "x"}}
        flagged = rename_check.missing_line(stories)
        self.assertEqual([1], list(flagged))
        self.assertIn("Renames: OLD -> NEW", flagged[1])


if __name__ == "__main__":
    unittest.main()

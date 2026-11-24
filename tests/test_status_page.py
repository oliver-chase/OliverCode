"""#1001: City page. The banner, the org chart, the open stories, the landed list, the nav and the REST-only read."""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from _support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import status_page  # noqa: E402

ISSUE = {"number": 7, "title": "Fix <it>", "priority": "P1", "status": "Building", "body_html": "<p>Full body</p>", "building": True}
DATA = {
    "run": {"repo": "o/a", "title": "Thread one", "models": ["Sonnet"], "builders": 2, "finish": "14:00", "plan": [7, 8], "building": [7]},
    "last_landed": {"number": 5, "title": "Old"},
    "repos": [
        {"name": "a", "slug": "o/a", "description": "Repo A", "pushed": "2026-11-22", "activity": "2026-11-23", "issues": [ISSUE, {**ISSUE, "number": 8, "building": False}]},
        {"name": "b", "slug": "o/b", "description": None, "pushed": "x", "activity": "y", "issues": []},
    ],
    "landed": [{"number": 5, "title": "Old", "repo": "o/a", "landed_at": "2026-11-22 10:00", "commit": "abc123", "model": "Sonnet"}],
}


def fake(rows, code=0):
    calls = []

    def run(args):
        calls.append(args)
        return subprocess.CompletedProcess(args, code, json.dumps([rows]), "")
    run.calls = calls
    return run


class PageCase(unittest.TestCase):
    def test_banner_live_and_idle(self):
        live = status_page.render(DATA)
        self.assertIn("marker pulse", live)
        self.assertIn("prefers-reduced-motion", live)
        for fact in ("o/a", "Thread one", "Sonnet", "14:00", "#8"):
            self.assertIn(fact, live)
        idle = status_page.render({**DATA, "run": None})
        self.assertIn("The runner is idle", idle)
        self.assertIn("#5 Old", idle)
        self.assertNotIn("marker pulse</span>", idle.split("<style>")[1].split("</style>")[1])

    def test_org_chart_highlights_active_repo(self):
        page = status_page.render(DATA)
        self.assertIn("OliverCode", page)
        self.assertEqual(page.count('details class="card live"'), 1)
        self.assertIn("2 open", page)
        self.assertIn('href="#o-a"', page)
        self.assertIn("No description", page)

    def test_stories_collapsed_and_escaped(self):
        page = status_page.render(DATA)
        self.assertEqual(len(re.findall(r'<details class="row', page)), 2)
        self.assertNotIn("<details open", page)
        self.assertIn("Fix &lt;it&gt;", page)
        self.assertIn("Full body", page)
        self.assertIn('class="row building"', page)

    def test_landed_checked_with_link(self):
        page = status_page.render(DATA)
        self.assertIn("box done", page)
        self.assertIn('href="#o-a-5"', page)
        self.assertIn("abc123", page)

    def test_nav_top_button_and_tooltips(self):
        page = status_page.render(DATA)
        for key, _ in status_page.SECTIONS:
            self.assertIn(f'href="#{key}"', page)
        self.assertIn('class="top"', page)
        self.assertIn("<abbr", status_page.tip("claim"))

    def test_design_tokens_defined_once_and_overridable(self):
        page = status_page.render(DATA)
        self.assertIn("#C4A8FF", page)
        self.assertEqual(page.count("--hi:"), 1)
        self.assertIn("--hi:#112233", status_page.render(DATA, {"highlight": "#112233"}))
        self.assertIn("min-height:var(--tap)", page)
        self.assertIn("--tap:44px", page)


class ReadCase(unittest.TestCase):
    def test_first_read_takes_all_then_only_changed(self):
        first = fake([{"number": 1, "updated_at": "2026-11-01T00:00:00Z", "state": "open"}])
        cache = status_page.refresh_issues("o/a", {}, first)
        self.assertNotIn("since=2026", " ".join(first.calls[0]))
        second = fake([{"number": 2, "updated_at": "2026-11-02T00:00:00Z", "state": "open"}, {"number": 1, "updated_at": "2026-11-02T00:00:00Z", "state": "closed"}])
        cache = status_page.refresh_issues("o/a", cache, second)
        self.assertIn("since=2026-11-01T00:00:00Z", second.calls[0])
        self.assertEqual(list(cache), [2])

    def test_rest_only_and_failure(self):
        run = fake([])
        status_page.refresh_issues("o/a", {}, run)
        self.assertNotIn("graphql", " ".join(run.calls[0]))
        self.assertIsNone(status_page.refresh_issues("o/a", {}, fake([], 1)))
        self.assertIn("<pre>", status_page.body_html("o/a", "x", lambda a: subprocess.CompletedProcess(a, 1, "", "")))


class ThreadCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.projects = Path(self.tmp.name) / "projects"
        self.repo = Path(self.tmp.name) / "work" / "repo-a"
        self.folder = status_page.project_dir(self.repo, self.projects)
        self.folder.mkdir(parents=True)
        self.now = time.time()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, rows, age):
        path = self.folder / name
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        stamp = self.now - age
        os.utime(path, (stamp, stamp))

    def gather(self):
        return status_page.threads({self.repo: "repo-a"}, self.now, self.projects)["repo-a"]

    def test_active_thread_has_title_age_and_tokens(self):
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now - 600))
        self.write("audit.jsonl", [{"type": "user", "timestamp": started, "message": {"role": "user", "content": "Audit   the repo"}}], age=60)
        found = self.gather()
        self.assertEqual(len(found["active"]), 1)
        thread = found["active"][0]
        self.assertEqual(thread["title"], "Audit the repo")
        self.assertEqual(thread["minutes"], 10)
        self.assertGreater(thread["tokens"], 0)
        self.assertEqual(found["recent"], [])

    def test_idle_thread_moves_to_recent_with_last_activity(self):
        self.write("plan.jsonl", [{"type": "summary", "summary": "Strategy plan"}], age=3600)
        found = self.gather()
        self.assertEqual(found["active"], [])
        self.assertEqual(found["recent"][0]["title"], "Strategy plan")
        self.assertIn(":", found["recent"][0]["last_activity"])

    def test_headless_builder_is_not_a_thread(self):
        self.write("builder.jsonl", [{"type": "user", "entrypoint": "sdk-cli", "message": {"content": "Build #7"}}], age=60)
        found = self.gather()
        self.assertEqual(found["active"] + found["recent"], [])

    def test_unknown_folder_and_no_transcripts(self):
        self.assertEqual(status_page.threads({Path(self.tmp.name) / "elsewhere": "x"}, self.now, self.projects), {"x": {"active": [], "recent": []}})

    def test_count_and_card_show_threads(self):
        self.write("a.jsonl", [{"type": "user", "message": {"content": "<b>Audit</b>"}}], age=60)
        repo = {"name": "repo-a", "slug": "o/a", "issues": [], "threads": self.gather()}
        page = status_page.render({"repos": [repo], "run": None})
        self.assertIn("0 headless builders and 1 interactive thread active", page)
        self.assertIn("Interactive, active for", page)
        self.assertIn("&lt;b&gt;Audit&lt;/b&gt;", page)
        self.assertNotIn("<b>Audit</b>", page)

    def test_banner_counts_builders_and_threads(self):
        self.assertIn("2 headless builders and 1 interactive thread active", status_page.banner({"builders": 2, "plan": []}, None, 1))
        self.assertIn("1 headless builder and 0 interactive threads", status_page.banner({"builders": 1, "plan": []}, None, 0))


if __name__ == "__main__":
    unittest.main()

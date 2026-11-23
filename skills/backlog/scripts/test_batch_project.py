"""Tests for shared, batched Project writes; they use no network or gh binary."""
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import batch_project as bp


CFG = {"repoOwner": "o", "repoName": "r", "projectId": "P", "fields": {
    "status": {"id": "FS", "options": {"Ready": "OS"}},
    "priority": {"id": "FP", "options": {"P1": "OP"}},
    "size": {"id": "FZ", "options": {"L": "OZ"}},
    "workType": {"id": "FW", "options": {"Story": "OW"}},
    "area": {"id": "FA", "options": {"fleet-wide": "OA"}},
}}


class Runner:
    def __init__(self): self.calls = []
    def __call__(self, args):
        self.calls.append(args[-1])
        q = args[-1]
        if "projectItems" in q:
            data = {"repository": {f"i{i}": {"projectItems": {"nodes": []}} for i in range(q.count("projectItems"))}}
        elif "issue(number" in q:
            data = {"repository": {f"i{i}": {"id": f"C{i}"} for i in range(q.count(":issue("))}}
        elif "addProject" in q:
            # GitHub names the add payload field `item`, so the fake refuses the old name like the API does.
            data = {f"a{i}": {"item": {"id": f"I{i}"}} for i in range(q.count("addProject"))} if "{item{id}}" in q else {"errors": "projectV2Item"}
        else:
            data = {f"u{i}": {"projectV2Item": {"id": f"I{i}"}} for i in range(q.count("updateProject"))}
        return subprocess.CompletedProcess(args, 0, json.dumps({"data": data}), "")


class BatchProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {"OLIVERCODE_HOME": self.tmp.name})
        self.env.start(); self.addCleanup(self.env.stop)
        self.cfg, self.input = Path(self.tmp.name) / "c.json", Path(self.tmp.name) / "i.json"
        self.cfg.write_text(json.dumps(CFG))

    def test_twelve_new_cards_use_one_add_and_four_update_mutations(self):
        self.input.write_text(json.dumps({"issues": [{"number": n, "fields": {"status": "Ready", "priority": "P1", "size": "L", "workType": "Story", "area": "fleet-wide"}}
                                                     for n in range(1, 13)]}))
        runner, out = Runner(), io.StringIO()
        self.assertEqual(0, bp.main(["--config", str(self.cfg), "--input", str(self.input)], runner=runner, out=out))
        mutations = [call for call in runner.calls if "mutation" in call]
        self.assertEqual(1, sum("addProject" in call for call in mutations))
        self.assertEqual(4, sum("updateProject" in call for call in mutations))  # 60 updates, chunks of 15
        self.assertIn("60 field update(s)", out.getvalue())

    def test_a_hold_keeps_work_in_the_shared_queue_without_calling_gh(self):
        self.input.write_text(json.dumps({"issues": [{"number": 1, "fields": {"status": "Ready"}}]}))
        bp.gh_budget.note_limit(seconds=60)
        runner, out = Runner(), io.StringIO()
        self.assertEqual(0, bp.main(["--config", str(self.cfg), "--input", str(self.input)], runner=runner, out=out))
        self.assertEqual([], runner.calls)
        self.assertIn("queued 1", out.getvalue())

    def test_a_job_that_can_never_succeed_leaves_the_queue(self):
        def failing(args):
            return subprocess.CompletedProcess(args, 1, "", "Could not resolve to an Issue")
        for number in (999999, 5):
            self.input.write_text(json.dumps({"issues": [{"number": number, "fields": {"status": "Ready"}}]}))
            err = io.StringIO()
            code = bp.main(["--config", str(self.cfg), "--input", str(self.input)], runner=failing if number == 999999 else Runner(), err=err, out=io.StringIO())
            self.assertEqual(1 if number == 999999 else 0, code)
        self.assertEqual([], json.loads((Path(self.tmp.name) / "gh-project-queue.json").read_text()))
        # A transient error keeps the job queued for the next run, and says so.
        def unavailable(args):
            return subprocess.CompletedProcess(args, 1, "", "HTTP 503: Service Unavailable")
        self.input.write_text(json.dumps({"issues": [{"number": 7, "fields": {"status": "Ready"}}]}))
        err = io.StringIO()
        bp.main(["--config", str(self.cfg), "--input", str(self.input)], runner=unavailable, err=err, out=io.StringIO())
        self.assertIn("kept #7", err.getvalue())
        queued = json.loads((Path(self.tmp.name) / "gh-project-queue.json").read_text())
        self.assertEqual([7], [i["number"] for job in queued for i in job["issues"]])

    def test_one_bad_number_leaves_the_queue_and_the_good_work_queued_with_it_applies(self):
        bp.gh_budget.note_limit(seconds=60)
        self.input.write_text(json.dumps({"issues": [{"number": 5, "fields": {"status": "Ready"}}]}))
        bp.main(["--config", str(self.cfg), "--input", str(self.input)], runner=Runner(), out=io.StringIO())
        bp.gh_budget.clear()
        good = Runner()
        def runner(args):
            if "999999" in args[-1]:
                return subprocess.CompletedProcess(args, 1, "", "Could not resolve to an Issue")
            return good(args)
        self.input.write_text(json.dumps({"issues": [{"number": 999999, "fields": {"status": "Ready"}}]}))
        out, err = io.StringIO(), io.StringIO()
        code = bp.main(["--config", str(self.cfg), "--input", str(self.input)], runner=runner, out=out, err=err)
        self.assertEqual(1, code)
        self.assertIn("across 1 queued issue(s)", out.getvalue())
        self.assertIn("dropped #999999", err.getvalue())
        self.assertEqual([], json.loads((Path(self.tmp.name) / "gh-project-queue.json").read_text()))

    def test_unknown_config_value_refuses_before_queueing(self):
        self.input.write_text(json.dumps({"issues": [{"number": 1, "fields": {"status": "Nope"}}]}))
        self.assertEqual(2, bp.main(["--config", str(self.cfg), "--input", str(self.input)], err=io.StringIO()))

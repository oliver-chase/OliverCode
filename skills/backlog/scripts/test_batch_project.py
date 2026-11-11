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
            data = {f"a{i}": {"projectV2Item": {"id": f"I{i}"}} for i in range(q.count("addProject"))}
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

    def test_unknown_config_value_refuses_before_queueing(self):
        self.input.write_text(json.dumps({"issues": [{"number": 1, "fields": {"status": "Nope"}}]}))
        self.assertEqual(2, bp.main(["--config", str(self.cfg), "--input", str(self.input)], err=io.StringIO()))

    @mock.patch("batch_project.subprocess.run")
    def test_default_runner_invokes_gh(self, run):
        bp.run_gh(["api", "graphql"])
        run.assert_called_once_with(["gh", "api", "graphql"], capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()

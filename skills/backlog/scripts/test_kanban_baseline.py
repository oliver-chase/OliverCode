"""Test the kanban baseline checker against saved field lists. No network and no gh.
Run: python3 -m unittest discover -p "test_*.py"   (from this folder)
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import check_board_hygiene as bh
import check_kanban_baseline as kb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def fixture(name):
    return json.loads((HERE / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))


def check(fields, config=None):
    return kb.check_baseline(fields, kb.load_baseline(), config)


class Baseline(unittest.TestCase):
    def test_the_baseline_names_the_five_lanes_and_no_pull_request_lane(self):
        base = kb.load_baseline()
        self.assertEqual(["Backlog", "Ready", "In Progress", "QA", "Complete"], base["lanes"])
        self.assertIn("no pull-request lane", base["rule"])

    def test_a_correct_board_has_no_differences(self):
        self.assertEqual([], check(fixture("board-correct")))

    def test_a_missing_qa_lane_is_reported_with_its_fix(self):
        problems = check(fixture("board-no-qa-lane"))
        self.assertEqual(1, len(problems))
        self.assertIn("missing option QA", problems[0])
        self.assertIn("Fix: add QA", problems[0])

    def test_a_pull_request_lane_is_reported_and_the_baseline_lanes_stay_clean(self):
        problems = check(fixture("board-pr-lane"))
        self.assertEqual(1, len(problems))
        self.assertIn("In review", problems[0])
        self.assertIn("driven by pull requests", problems[0])

    def test_every_pull_request_spelling_is_caught(self):
        for lane in ("Pull Request", "PR", "PRs open", "Under review", "Merged", "In Review"):
            fields = fixture("board-correct")
            status = next(f for f in fields["fields"] if f["name"] == "Status")
            status["options"].append({"id": "x", "name": lane})
            self.assertTrue(any("driven by pull requests" in p for p in check(fields)), lane)

    def test_qa_and_the_other_baseline_lanes_are_never_read_as_pull_request_lanes(self):
        self.assertFalse(any("pull requests" in p for p in check(fixture("board-no-qa-lane"))))

    def test_an_unknown_lane_is_extra_and_case_differences_are_allowed(self):
        fields = fixture("board-correct")
        status = next(f for f in fields["fields"] if f["name"] == "Status")
        status["options"][2]["name"] = "In progress"
        status["options"].append({"id": "x", "name": "Parked"})
        problems = check(fields)
        self.assertEqual(1, len(problems))
        self.assertIn("extra option Parked", problems[0])

    def test_a_missing_field_and_a_wrong_option_set_are_reported(self):
        fields = fixture("board-correct")
        fields["fields"] = [f for f in fields["fields"] if f["name"] != "Size"]
        priority = next(f for f in fields["fields"] if f["name"] == "Priority")
        priority["options"] = priority["options"][:2]
        problems = check(fields)
        self.assertTrue(any(p.startswith("Size: the board has no single-select Size") for p in problems))
        self.assertTrue(any("Priority: missing option P2" in p for p in problems))

    def test_area_options_come_from_the_repos_config(self):
        config = {"fields": {"area": {"id": "A", "options": {"backlog": "1", "plan": "2"}}}}
        problems = check(fixture("board-correct"), config)
        self.assertEqual(2, len(problems))
        self.assertTrue(any("missing option plan" in p for p in problems))
        self.assertTrue(any("extra option audit" in p for p in problems))

    def test_a_status_field_of_the_wrong_type_is_reported(self):
        fields = copy.deepcopy(fixture("board-correct"))
        next(f for f in fields["fields"] if f["name"] == "Status")["type"] = "ProjectV2Field"
        self.assertTrue(any("no single-select Status" in p for p in check(fields)))


class CurrentOliverCodeBoard(unittest.TestCase):
    """The live OliverCode config lists every baseline lane. A board without the QA lane is still reported."""
    CONFIG = json.loads((ROOT / "docs" / "backlog-config.json").read_text(encoding="utf-8"))

    def test_the_layout_without_a_qa_lane_is_flagged_and_nothing_else(self):
        problems = check(fixture("board-no-qa-lane"))
        self.assertEqual(1, len(problems))
        self.assertIn("missing option QA", problems[0])

    def test_the_config_stays_valid_and_names_every_lane(self):
        self.assertEqual([], bh.missing_lanes(self.CONFIG))
        bh.verify_config(self.CONFIG, ROOT / "docs" / "backlog-config.json")

    def test_the_example_config_lists_every_baseline_lane(self):
        example = json.loads((ROOT / "shared" / "backlog-config.example.json").read_text(encoding="utf-8"))
        self.assertEqual([], bh.missing_lanes(example))

    def test_qa_counts_as_open_work_in_the_sweep(self):
        self.assertIn("QA", bh.REQUIRED_STATUSES)
        self.assertNotIn("Complete", bh.REQUIRED_STATUSES)


class Command(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(HERE / "check_kanban_baseline.py"), *args],
                              capture_output=True, text=True)

    def test_exit_status_follows_the_board(self):
        ok = self.run_cli("--fields-file", str(HERE / "fixtures" / "board-correct.json"))
        self.assertEqual(0, ok.returncode)
        self.assertIn("matches", ok.stdout)
        bad = self.run_cli("--fields-file", str(HERE / "fixtures" / "board-pr-lane.json"))
        self.assertEqual(1, bad.returncode)
        self.assertIn("1 difference", bad.stdout)

    def test_verify_baseline_mode_reads_a_file_and_never_calls_gh(self):
        config = ROOT / "docs" / "backlog-config.json"
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "gh"
            stub.write_text(f"#!/bin/sh\ntouch '{tmp}/gh-was-called'\nexit 1\n")
            stub.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(HERE / "check_board_hygiene.py"), "--config", str(config),
                 "--verify-baseline", "--fields-file", str(HERE / "fixtures" / "board-no-qa-lane.json")],
                capture_output=True, text=True, env={**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"})
            self.assertFalse((Path(tmp) / "gh-was-called").exists())
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("missing option QA", result.stdout)

    def test_no_source_is_a_one_line_stop(self):
        result = self.run_cli()
        self.assertEqual(1, result.returncode)
        self.assertIn("--fields-file", result.stderr)


if __name__ == "__main__":
    unittest.main()

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
    """board-correct, or that board with one Status lane changed: no QA lane, or a pull request lane."""
    fields = json.loads((HERE / "fixtures" / "board-correct.json").read_text(encoding="utf-8"))
    options = next(f for f in fields["fields"] if f["name"] == "Status")["options"]
    if name == "board-no-qa-lane":
        options[:] = [o for o in options if o["name"] != "QA"]
    elif name == "board-pr-lane":
        options.insert(3, {"id": "St5", "name": "In review"})
    return fields


def saved(name, folder):
    path = Path(folder) / f"{name}.json"
    path.write_text(json.dumps(fixture(name)), encoding="utf-8")
    return str(path)


def check(fields, config=None):
    return kb.check_baseline(fields, kb.load_baseline(), config)


class Baseline(unittest.TestCase):
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


class FixtureBoardConfig(unittest.TestCase):
    """A fixture config stands in for the owner's board, so these tests pass on a fork."""
    CONFIG = json.loads((HERE / "fixtures" / "backlog-config.json").read_text(encoding="utf-8"))

    def test_the_fixture_config_names_every_lane_and_passes_the_placeholder_check(self):
        self.assertEqual([], bh.missing_lanes(self.CONFIG))
        self.assertFalse(bh.placeholder_values(self.CONFIG))

    def test_a_config_without_a_qa_option_is_missing_that_lane(self):
        config = copy.deepcopy(self.CONFIG)
        del config["fields"]["status"]["options"]["QA"]
        self.assertEqual(["QA"], bh.missing_lanes(config))

    def test_the_example_config_lists_every_baseline_lane(self):
        example = json.loads((ROOT / "shared" / "backlog-config.example.json").read_text(encoding="utf-8"))
        self.assertEqual([], bh.missing_lanes(example))


class Command(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(HERE / "check_kanban_baseline.py"), *args],
                              capture_output=True, text=True)

    def test_exit_status_follows_the_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = self.run_cli("--fields-file", saved("board-correct", tmp))
            bad = self.run_cli("--fields-file", saved("board-pr-lane", tmp))
        self.assertEqual(0, ok.returncode)
        self.assertIn("matches", ok.stdout)
        self.assertEqual(1, bad.returncode)
        self.assertIn("1 difference", bad.stdout)

    def test_verify_baseline_mode_reads_a_file_and_never_calls_gh(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "backlog-config.json"
            config.write_text((HERE / "fixtures" / "backlog-config.json").read_text(encoding="utf-8"), encoding="utf-8")
            stub = Path(tmp) / "gh"
            stub.write_text(f"#!/bin/sh\ntouch '{tmp}/gh-was-called'\nexit 1\n")
            stub.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(HERE / "check_board_hygiene.py"), "--config", str(config),
                 "--verify-baseline", "--fields-file", saved("board-no-qa-lane", tmp)],
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

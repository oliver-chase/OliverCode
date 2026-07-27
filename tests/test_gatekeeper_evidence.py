"""Tests for validate_evidence() in scripts/orchestration-gatekeeper.py.

This is the function whose silent failure means a false completion claim passes the
WRITE MODE gate, and it had zero coverage. One block case and one pass case per
required-evidence field, covering both the missing and the malformed shape.

scripts/orchestration-gatekeeper.py has a hyphen in its name, so it is loaded via
SourceFileLoader rather than a normal import (same approach as the launcher test).
"""

import importlib.util
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATEKEEPER_PATH = REPO_ROOT / "scripts" / "orchestration-gatekeeper.py"


def _load_gatekeeper():
    loader = SourceFileLoader("orchestration_gatekeeper", str(GATEKEEPER_PATH))
    spec = importlib.util.spec_from_loader("orchestration_gatekeeper", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


gatekeeper = _load_gatekeeper()


def validate(evidence, fields):
    return gatekeeper.validate_evidence(evidence, fields, "example-app", "write_code")


class TestMissingFields(unittest.TestCase):
    def test_absent_field_blocks(self):
        result = validate({}, ["files_changed_on_disk"])
        self.assertFalse(result["pass"])
        self.assertEqual(result["stage"], "missing_evidence:files_changed_on_disk")

    def test_null_field_blocks(self):
        result = validate({"files_changed_on_disk": None}, ["files_changed_on_disk"])
        self.assertFalse(result["pass"])
        self.assertEqual(result["stage"], "missing_evidence:files_changed_on_disk")

    def test_no_required_fields_passes(self):
        self.assertTrue(validate({}, [])["pass"])


class TestFilesChangedOnDisk(unittest.TestCase):
    FIELD = ["files_changed_on_disk"]

    def test_empty_list_blocks(self):
        result = validate({"files_changed_on_disk": []}, self.FIELD)
        self.assertFalse(result["pass"])

    def test_wrong_type_blocks(self):
        result = validate({"files_changed_on_disk": "README.md"}, self.FIELD)
        self.assertFalse(result["pass"])
        self.assertEqual(result["stage"], "files_changed_on_disk")

    def test_nonexistent_paths_block(self):
        result = validate(
            {"files_changed_on_disk": ["definitely/not/here.txt"]}, self.FIELD
        )
        self.assertFalse(result["pass"])
        self.assertEqual(result["stage"], "files_changed_on_disk")
        self.assertIn("None of the claimed changed files exist", result["message"])

    def test_real_repo_relative_path_passes(self):
        # README.md exists relative to the repo root the gatekeeper resolved.
        self.assertTrue(validate({"files_changed_on_disk": ["README.md"]}, self.FIELD)["pass"])


class TestValidationCommand(unittest.TestCase):
    FIELD = ["validation_command_executed"]

    def test_empty_string_blocks(self):
        self.assertFalse(validate({"validation_command_executed": "   "}, self.FIELD)["pass"])

    def test_wrong_type_blocks(self):
        self.assertFalse(validate({"validation_command_executed": 42}, self.FIELD)["pass"])

    def test_real_command_passes(self):
        self.assertTrue(
            validate({"validation_command_executed": "npm run build"}, self.FIELD)["pass"]
        )


class TestValidationResult(unittest.TestCase):
    FIELD = ["validation_result_captured"]

    def test_wrong_type_blocks(self):
        self.assertFalse(validate({"validation_result_captured": "ok"}, self.FIELD)["pass"])

    def test_missing_exit_code_blocks(self):
        self.assertFalse(
            validate({"validation_result_captured": {"pass": True}}, self.FIELD)["pass"]
        )

    def test_missing_pass_blocks(self):
        self.assertFalse(
            validate({"validation_result_captured": {"exitCode": 0}}, self.FIELD)["pass"]
        )

    def test_failed_validation_blocks_and_names_the_stage(self):
        result = validate(
            {
                "validation_result_captured": {
                    "exitCode": 1,
                    "pass": False,
                    "failStage": "next build",
                    "failMessage": "type error",
                }
            },
            self.FIELD,
        )
        self.assertFalse(result["pass"])
        self.assertEqual(result["stage"], "validation_failed:next build")
        self.assertIn("type error", result["message"])

    def test_passing_validation_passes(self):
        self.assertTrue(
            validate(
                {"validation_result_captured": {"exitCode": 0, "pass": True}}, self.FIELD
            )["pass"]
        )


class TestCommitHash(unittest.TestCase):
    FIELD = ["commit_hash_on_success"]

    def test_non_hex_blocks(self):
        self.assertFalse(validate({"commit_hash_on_success": "not-a-sha"}, self.FIELD)["pass"])

    def test_too_short_blocks(self):
        self.assertFalse(validate({"commit_hash_on_success": "abc12"}, self.FIELD)["pass"])

    def test_uppercase_blocks(self):
        # The pattern is lowercase-hex only; git emits lowercase.
        self.assertFalse(validate({"commit_hash_on_success": "ABCDEF1"}, self.FIELD)["pass"])

    def test_short_sha_passes(self):
        self.assertTrue(validate({"commit_hash_on_success": "ed1e4d1"}, self.FIELD)["pass"])

    def test_full_sha_passes(self):
        self.assertTrue(
            validate({"commit_hash_on_success": "a" * 40}, self.FIELD)["pass"]
        )


class TestFailureObject(unittest.TestCase):
    FIELD = ["failure_object_on_non_pass"]

    def test_wrong_type_blocks(self):
        self.assertFalse(validate({"failure_object_on_non_pass": "boom"}, self.FIELD)["pass"])

    def test_missing_key_blocks(self):
        result = validate(
            {"failure_object_on_non_pass": {"failStage": "x", "failMessage": "y"}},
            self.FIELD,
        )
        self.assertFalse(result["pass"])
        self.assertIn("stopAction", result["message"])

    def test_complete_object_passes(self):
        self.assertTrue(
            validate(
                {
                    "failure_object_on_non_pass": {
                        "failStage": "x",
                        "failMessage": "y",
                        "stopAction": "FIX_AND_RETRY",
                    }
                },
                self.FIELD,
            )["pass"]
        )


class TestNoRegressionConfirmed(unittest.TestCase):
    FIELD = ["no_regression_confirmed"]

    def test_wrong_type_blocks(self):
        self.assertFalse(validate({"no_regression_confirmed": True}, self.FIELD)["pass"])

    def test_missing_detail_blocks(self):
        self.assertFalse(
            validate({"no_regression_confirmed": {"method": "test pass"}}, self.FIELD)["pass"]
        )

    def test_complete_object_passes(self):
        self.assertTrue(
            validate(
                {"no_regression_confirmed": {"method": "test pass", "detail": "42 tests"}},
                self.FIELD,
            )["pass"]
        )


class TestFirstFailureSemantics(unittest.TestCase):
    def test_reports_the_first_failing_field_not_the_last(self):
        result = validate(
            {"files_changed_on_disk": [], "commit_hash_on_success": "nope"},
            ["files_changed_on_disk", "commit_hash_on_success"],
        )
        self.assertFalse(result["pass"])
        self.assertEqual(result["stage"], "files_changed_on_disk")


class TestFullWriteCodeEvidence(unittest.TestCase):
    def test_complete_evidence_record_passes(self):
        fields = [
            "files_changed_on_disk",
            "validation_command_executed",
            "validation_result_captured",
            "commit_hash_on_success",
        ]
        evidence = {
            "files_changed_on_disk": ["README.md"],
            "validation_command_executed": "bash scripts/validate.sh",
            "validation_result_captured": {"exitCode": 0, "pass": True},
            "commit_hash_on_success": "ed1e4d1",
        }
        self.assertTrue(validate(evidence, fields)["pass"])




class TestFindingsDocumented(unittest.TestCase):
    """`audit`'s only required field had no shape check, so an empty string passed --
    an audit that documented nothing validated as though it had."""

    FIELD = ["findings_documented"]

    def test_empty_string_blocks(self):
        self.assertFalse(validate({"findings_documented": ""}, self.FIELD)["pass"])

    def test_whitespace_only_blocks(self):
        self.assertFalse(validate({"findings_documented": "   "}, self.FIELD)["pass"])

    def test_non_string_blocks(self):
        self.assertFalse(validate({"findings_documented": True}, self.FIELD)["pass"])

    def test_real_reference_passes(self):
        self.assertTrue(
            validate(
                {"findings_documented": "docs/BACKLOG.md AUDIT-1..7, each with file:line"},
                self.FIELD,
            )["pass"]
        )

if __name__ == "__main__":
    unittest.main()

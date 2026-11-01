"""Tests for scripts/lib/token_policy.py: a profile's token policy, with absent fields as [].

Gate 8 reads every repo profile through this accessor, so a field it drops or renames
would make the gate pass a profile that declares nothing.
"""

import importlib.util
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "token_policy", REPO_ROOT / "scripts" / "lib" / "token_policy.py"
)
token_policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(token_policy)

FIELDS = ("ignore_globs", "doc_priority_hints", "generated_artifact_dirs")


class TokenPolicyFromProfile(unittest.TestCase):
    def test_declared_fields_come_back_as_written(self):
        profile = {
            "token_policy": {
                "ignore_globs": ["node_modules/**", "*.log"],
                "doc_priority_hints": ["README.md"],
                "generated_artifact_dirs": [".next"],
            }
        }
        self.assertEqual(
            {
                "ignore_globs": ["node_modules/**", "*.log"],
                "doc_priority_hints": ["README.md"],
                "generated_artifact_dirs": [".next"],
            },
            token_policy.token_policy_from_profile(profile),
        )

    def test_a_profile_without_a_policy_gets_every_field_empty(self):
        self.assertEqual(
            {field: [] for field in FIELDS},
            token_policy.token_policy_from_profile({"name": "x"}),
        )

    def test_a_partial_policy_fills_only_the_missing_fields(self):
        result = token_policy.token_policy_from_profile(
            {"token_policy": {"ignore_globs": ["dist/**"]}}
        )
        self.assertEqual(["dist/**"], result["ignore_globs"])
        self.assertEqual([], result["doc_priority_hints"])
        self.assertEqual([], result["generated_artifact_dirs"])

    def test_unknown_policy_keys_are_not_passed_through(self):
        result = token_policy.token_policy_from_profile(
            {"token_policy": {"ignore_globs": ["a"], "extra": ["b"]}}
        )
        self.assertEqual(set(FIELDS), set(result))

    def test_a_null_policy_gets_every_field_empty(self):
        # `"token_policy": null` in a profile used to raise AttributeError and crash Gate 8.
        self.assertEqual(
            {field: [] for field in FIELDS},
            token_policy.token_policy_from_profile({"token_policy": None}),
        )


def _load_gatekeeper():
    path = REPO_ROOT / "scripts" / "orchestration-gatekeeper.py"
    loader = SourceFileLoader("orchestration_gatekeeper_tp", str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


class ValidateTokenPolicy(unittest.TestCase):
    """Gate 8 runs validate_token_policy over every profile."""

    gatekeeper = _load_gatekeeper()

    def test_a_null_policy_is_reported_rather_than_crashing(self):
        errors = self.gatekeeper.validate_token_policy({"repo-x": {"token_policy": None}})
        self.assertEqual(2, len(errors), errors)
        self.assertIn("ignore_globs is missing or empty", errors[0])
        self.assertIn("generated_artifact_dirs is not declared", errors[1])

    def test_a_complete_policy_passes(self):
        profile = {"token_policy": {"ignore_globs": ["*.log"], "generated_artifact_dirs": []}}
        self.assertEqual([], self.gatekeeper.validate_token_policy({"repo-x": profile}))


if __name__ == "__main__":
    unittest.main()

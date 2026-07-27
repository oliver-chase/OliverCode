#!/usr/bin/env python3
"""
orchestration-gatekeeper — deterministic WRITE MODE completion gate.

Usage:
    python3 orchestration-gatekeeper.py --repo <repo-name> --task-type <type> --evidence-file <path>

Reads a JSON evidence file, validates it against the repo profile and task-type
policy, and returns pass/fail with exact failure stage.

If validation passes: exit 0.
If validation fails: exit 1, print exact failing field and reason.
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Resolve repo root (OliverCode) from script location. The example file (not
# the real, gitignored local/repo-profiles.json) is the marker — it's the one
# file guaranteed to exist in every checkout, including a stranger clone with
# no local fleet configured yet.
REPO_ROOT = HERE
while not (REPO_ROOT / "shared" / "repo-profiles.example.json").exists():
    REPO_ROOT = REPO_ROOT.parent
    if REPO_ROOT == Path("/"):
        print("ERROR: Could not find OliverCode root (shared/repo-profiles.example.json)", file=sys.stderr)
        sys.exit(1)

sys.path.insert(0, str(HERE))
from lib.token_policy import token_policy_from_profile
from lib.repo_profiles import load_repo_profiles


def load_json(rel_path: str) -> dict:
    path = REPO_ROOT / rel_path
    if not path.exists():
        raise FileNotFoundError(f"Policy file not found: {path}")
    with open(path) as f:
        return json.load(f)


def get_repo_profile(repo_name: str, profiles: dict) -> dict:
    profile = profiles.get(repo_name)
    if not profile:
        print(f"ERROR: No profile for repo '{repo_name}'", file=sys.stderr)
        sys.exit(1)
    return profile


def get_token_policy(repo_name: str, profiles: dict) -> dict:
    """Return token-policy fields for a repo: ignore_globs, doc_priority_hints, generated_artifact_dirs."""
    return token_policy_from_profile(get_repo_profile(repo_name, profiles))


def validate_token_policy(profiles: dict) -> list:
    """Check every repo profile's token-policy fields. Returns a list of error strings.

    This runs as Gate 8, so its output is what a forker sees when a commit is BLOCKED.
    Each message therefore names the field, the repo, and what to put there -- the
    caller adds the file path. A bare "missing token_policy.ignore_globs" sent people
    hunting for which file it even meant.
    """
    errors = []
    for name in profiles:
        tp = get_token_policy(name, profiles)
        ignore = tp["ignore_globs"]
        gen = tp["generated_artifact_dirs"]
        if not ignore:
            errors.append(
                f"  {name}: token_policy.ignore_globs is missing or empty "
                f"— add the glob patterns agents should skip (e.g. \"node_modules/**\", \"*.log\")"
            )
        elif "**" in ignore:
            errors.append(
                f"  {name}: token_policy.ignore_globs contains a bare '**' "
                f"— that excludes every file; list specific patterns instead"
            )
        if not gen:
            errors.append(
                f"  {name}: token_policy.generated_artifact_dirs is missing or empty "
                f"— add the build/output dirs (e.g. \"node_modules\", \".next\", \"coverage\")"
            )
    return errors


def get_task_policy(task_type: str, task_policies: dict) -> dict:
    policy = task_policies.get(task_type)
    if not policy:
        print(f"ERROR: No task policy for type '{task_type}'", file=sys.stderr)
        sys.exit(1)
    return policy


def validate_evidence(evidence: dict, required_fields: list, repo_name: str, task_type: str) -> dict:
    """Returns {'pass': True} or {'pass': False, 'stage': ..., 'message': ...}.

    Returns on the first failing field — the caller reports one exact failing stage."""
    def fail(stage, message):
        return {"pass": False, "stage": stage, "message": message}

    for field in required_fields:
        if field not in evidence or evidence[field] is None:
            return fail(f"missing_evidence:{field}", f"Required evidence '{field}' is missing or null.")

        value = evidence[field]

        if field == "files_changed_on_disk":
            if not isinstance(value, list) or len(value) == 0:
                return fail("files_changed_on_disk", "files_changed_on_disk must be a non-empty list of file paths.")
            # At least one claimed file must exist (absolute or relative to repo root)
            if not any(Path(fp).exists() or (REPO_ROOT / fp).exists() for fp in value):
                return fail("files_changed_on_disk", f"None of the claimed changed files exist on disk: {value}")

        elif field == "validation_command_executed":
            if not isinstance(value, str) or not value.strip():
                return fail("validation_command_executed", "validation_command_executed must be a non-empty command string.")

        elif field == "validation_result_captured":
            if not isinstance(value, dict):
                return fail("validation_result_captured", "validation_result_captured must be an object with exitCode and pass fields.")
            if value.get("exitCode") is None or value.get("pass") is None:
                return fail("validation_result_captured", "validation_result_captured must have 'exitCode' (int) and 'pass' (bool).")
            if not value.get("pass"):
                fail_stage = value.get("failStage", "unknown")
                fail_msg = value.get("failMessage", "No error message")
                return fail(f"validation_failed:{fail_stage}", f"Validation failed at stage '{fail_stage}': {fail_msg}")

        elif field == "commit_hash_on_success":
            if not isinstance(value, str) or not re.match(r'^[a-f0-9]{7,40}$', value):
                return fail("commit_hash_on_success", "commit_hash_on_success must be a valid git commit SHA (7-40 hex chars).")

        elif field == "failure_object_on_non_pass":
            # If present, validate structure (required only when validation did not pass)
            if not isinstance(value, dict):
                return fail("failure_object_on_non_pass", "failure_object_on_non_pass must be an object with failStage, failMessage, stopAction.")
            for k in ("failStage", "failMessage", "stopAction"):
                if k not in value:
                    return fail("failure_object_on_non_pass", f"failure_object_on_non_pass missing required key '{k}'.")

        elif field == "no_regression_confirmed":
            if not isinstance(value, dict) or "method" not in value or "detail" not in value:
                return fail("no_regression_confirmed", "no_regression_confirmed must be an object with 'method' and 'detail' strings.")

    return {"pass": True}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="OliverCode Orchestration Gatekeeper")
    parser.add_argument("--repo", help="Repository name (e.g. example-app)")
    parser.add_argument("--task-type", default="write_code", help="Task type (e.g. write_code, write_doc, refactor)")
    parser.add_argument("--evidence-file", help="Path to JSON evidence file")
    parser.add_argument("--check-token-policy", action="store_true", help="Validate token-policy fields across all repo profiles")
    args = parser.parse_args()

    # Load policies
    profiles, profiles_source = load_repo_profiles(REPO_ROOT)
    if profiles_source.name == "repo-profiles.example.json":
        print(f"[GATEKEEPER] WARN: no local/repo-profiles.json — using placeholder example profiles ({profiles_source})", file=sys.stderr)

    # Token policy check mode (no evidence needed)
    if args.check_token_policy:
        errors = validate_token_policy(profiles)
        if errors:
            print("[GATEKEEPER] Token policy validation FAILED:")
            for e in errors:
                print(e)
            sys.exit(1)
        else:
            print(f"[GATEKEEPER] Token policy validation PASS — {len(profiles)} profiles checked.")
            sys.exit(0)

    # Evidence validation mode (requires repo + evidence-file)
    if not args.repo or not args.evidence_file:
        parser.print_help()
        sys.exit(1)

    task_policies_data = load_json("shared/task-policies/task-types.json")
    task_policies = task_policies_data.get("taskTypes", {})

    profile = get_repo_profile(args.repo, profiles)
    task_policy = get_task_policy(args.task_type, task_policies)

    # Get required evidence for this task type in this repo
    repo_task_config = profile.get("taskTypes", {}).get(args.task_type, {})
    required_fields = repo_task_config.get("requiredEvidence", task_policy.get("requiredEvidence", []))

    # Load evidence
    evidence_path = Path(args.evidence_file)
    if not evidence_path.exists():
        print(f"ERROR: Evidence file not found: {evidence_path}", file=sys.stderr)
        sys.exit(1)
    with open(evidence_path) as f:
        evidence = json.load(f)

    # Validate
    result = validate_evidence(evidence, required_fields, args.repo, args.task_type)

    if result["pass"]:
        print(f"[GATEKEEPER] PASS — {args.repo}/{args.task_type}: all required evidence present and valid.")
        sys.exit(0)
    else:
        print(f"[GATEKEEPER] FAIL — {args.repo}/{args.task_type}")
        print(f"  Stage: {result['stage']}")
        print(f"  Message: {result['message']}")
        sys.exit(1)


if __name__ == "__main__":
    main()

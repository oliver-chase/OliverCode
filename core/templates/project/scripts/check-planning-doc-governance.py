#!/usr/bin/env python3
"""Validate planning-document governance and authority pointers."""

from __future__ import annotations

import argparse
import json
import subprocess
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "config" / "contracts" / "planning-doc-governance.json"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _git_list(cmd: list[str]) -> list[str]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _is_planning_doc(path: str, matchers: list[str], exclude_prefixes: list[str]) -> bool:
    for prefix in exclude_prefixes:
        if path.startswith(prefix):
            return False
    return any(fnmatch(path, pattern) for pattern in matchers)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate planning-doc governance contract.")
    parser.add_argument("--staged-only", action="store_true", help="Only validate staged planning docs.")
    args = parser.parse_args()

    if not CONTRACT_PATH.exists():
        print(f"FAIL planning-doc-governance: missing {CONTRACT_PATH}")
        return 1

    contract = _load_json(CONTRACT_PATH)
    if not contract:
        print(f"FAIL planning-doc-governance: invalid JSON in {CONTRACT_PATH}")
        return 1

    errors: list[str] = []
    canonical = contract.get("canonical_planning_authority", "")
    if not canonical:
        errors.append("missing canonical_planning_authority")
    elif not (ROOT / canonical).exists():
        errors.append(f"missing canonical planning authority doc: {canonical}")

    active_docs = contract.get("active_docs", [])
    supplemental_docs = contract.get("supplemental_docs", [])
    solution_docs = contract.get("current_state_solution_docs", [])
    matchers = contract.get("planning_doc_matchers", [])
    exclude_prefixes = contract.get("planning_doc_exclude_prefixes", [])
    required_contains = contract.get("required_contains", {})
    markers = contract.get("required_marker_by_class", {})
    banned_active = contract.get("banned_strings_in_active_docs", [])
    registered = set(active_docs) | set(supplemental_docs) | set(solution_docs)

    active_marker = markers.get("active", "")
    for rel in active_docs:
        path = ROOT / rel
        if not path.exists():
            errors.append(f"missing active doc: {rel}")
            continue
        text = _read(path)
        if active_marker and active_marker not in text:
            errors.append(f"active doc missing marker '{active_marker}': {rel}")
        for banned in banned_active:
            if banned and banned in text:
                errors.append(f"active doc contains banned stale text '{banned}': {rel}")

    supplemental_marker = markers.get("supplemental", "")
    for rel in supplemental_docs:
        path = ROOT / rel
        if not path.exists():
            errors.append(f"missing supplemental doc: {rel}")
            continue
        if supplemental_marker and supplemental_marker not in _read(path):
            errors.append(f"supplemental doc missing marker '{supplemental_marker}': {rel}")

    for rel in solution_docs:
        if not (ROOT / rel).exists():
            errors.append(f"missing current-state solution doc: {rel}")

    for rel, needles in required_contains.items():
        path = ROOT / rel
        if not path.exists():
            errors.append(f"missing required-reference doc: {rel}")
            continue
        text = _read(path)
        for needle in needles:
            if needle not in text:
                errors.append(f"{rel} missing required reference text: {needle}")

    tracked = (
        _git_list(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"])
        if args.staged_only
        else _git_list(["git", "ls-files"])
    )

    def _fail(errs: list[str]) -> int:
        print("FAIL planning-doc-governance:")
        for err in errs:
            print(f"- {err}")
        return 1

    # Contract-level errors (missing authority, banned stale text, missing markers)
    # were collected above and must block even when this commit stages no planning
    # docs — the early PASS returns previously discarded them.
    if args.staged_only and not tracked:
        if errors:
            return _fail(errors)
        print("PASS planning-doc-governance: no staged files to validate")
        return 0

    planning_docs = sorted(
        rel for rel in tracked if _is_planning_doc(rel, matchers, exclude_prefixes)
    )
    if args.staged_only and not planning_docs:
        if errors:
            return _fail(errors)
        print("PASS planning-doc-governance: no staged planning docs")
        return 0

    for rel in planning_docs:
        if rel not in registered:
            errors.append(
                f"unregistered planning doc: {rel} (add to planning-doc-governance contract as active or supplemental)"
            )

    if errors:
        return _fail(errors)

    mode = "staged planning docs" if args.staged_only else "all planning docs"
    print(f"PASS planning-doc-governance: authority pointers and non-contradiction checks valid for {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

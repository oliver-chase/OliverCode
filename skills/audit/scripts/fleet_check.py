#!/usr/bin/env python3
"""Fleet budgets, voice violations and board drift for one repo, as the audit's lean-fleet pass.

Usage:
    fleet_check.py [repo]                  # budgets and voice, plus board drift when the repo has a backlog config
    fleet_check.py --time [repo]           # also runs the repo's tests and reports the runtime
    fleet_check.py --fields-file F [repo]  # board drift from a saved `gh project field-list` JSON

The budget file is `docs/BUDGET.json` in the repo, with testCount, testSeconds, docWords and skillWords.
Each line of output is a measure against its budget, a voice finding as `file:line`, or a board difference.
Exit status is 1 when anything is over budget or flagged. It edits nothing.
Tests: python3 -m unittest test_fleet_check   (from this scripts/ folder)
"""

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUDGET_FILE = "docs/BUDGET.json"
BASELINE_SCRIPT = Path(__file__).resolve().parents[2] / "backlog" / "scripts" / "check_kanban_baseline.py"

CONTRAST = re.compile(
    r"\b(?:not\b[^.\n]{1,60}?,\s*but\b|rather than\b|instead of\b|less\b[^.\n]{1,40}?,\s*more\b|it is not about\b)", re.I)
SMALL = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "vs", "is", "at", "by"}
CURLY = "‘’“”"


def tracked(repo):
    out = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if (Path(repo) / f).is_file()]


def read(repo, rel):
    try:
        return (Path(repo) / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def is_test(rel):
    return rel.endswith(".py") and (Path(rel).name.startswith("test_") or rel.startswith("tests/") or "/tests/" in rel)


def measure(repo, files):
    docs = skills = tests = 0
    for rel in files:
        if rel.endswith(".md"):
            words = len(read(repo, rel).split())
            if rel.startswith("skills/") or "/skills/" in rel:
                skills += words
            else:
                docs += words
        elif is_test(rel):
            tests += len(re.findall(r"^\s*(?:async\s+)?def test_", read(repo, rel), re.M))
    return {"testCount": tests, "docWords": docs, "skillWords": skills}


def run_tests(repo, per_module=None):
    """Wall seconds to run every `tests/test_*.py` module, each in its own process as validate.sh does,
    or None when the repo has no such module. A dict passed as `per_module` gets each module's seconds."""
    tests_dir = Path(repo) / "tests"
    modules = sorted(p.stem for p in tests_dir.glob("test_*.py")) if tests_dir.is_dir() else []
    if not modules:
        return None
    def run_one(module):
        began = time.monotonic()
        subprocess.run([sys.executable, "-m", "unittest", "-b", module], cwd=tests_dir, capture_output=True)
        if per_module is not None:
            per_module[module] = time.monotonic() - began

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(run_one, modules))
    return round(time.monotonic() - start, 1)


def budget_lines(measured, budget):
    """One line per measure against its budget, and how many are over."""
    lines, over = [], 0
    for key in ("testCount", "testSeconds", "docWords", "skillWords"):
        value, limit = measured.get(key), budget.get(key)
        if value is None:
            lines.append(f"{key}: not measured" + (" (pass --time)" if key == "testSeconds" else ""))
        elif limit is None:
            lines.append(f"{key}: {value}, no budget set")
        elif value > limit:
            over += 1
            lines.append(f"{key}: {value} is over the budget of {limit}")
        else:
            lines.append(f"{key}: {value} within the budget of {limit}")
    return lines, over


def title_case(text):
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    major = [w for w in words[1:] if w.lower() not in SMALL and not w.isupper()]
    return len(major) >= 2 and all(w[0].isupper() for w in major)


def voice_findings(repo, files):
    """(file, line, kind) for each violation in a tracked markdown file, skipping fenced code."""
    found = []
    for rel in files:
        if not rel.endswith(".md"):
            continue
        fenced = False
        for n, line in enumerate(read(repo, rel).splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("```"):
                fenced = not fenced
                continue
            if fenced:
                continue
            heading = re.match(r"#{1,6}\s+(.*)", stripped)
            if CONTRAST.search(line):
                found.append((rel, n, "contrast framing"))
            if re.match(r"[-*]\s+.*\.$", stripped) and not stripped.endswith(("...", "etc.")):
                found.append((rel, n, "trailing period on a bullet"))
            if any(c in line for c in CURLY):
                found.append((rel, n, "curly quotes"))
            if heading and title_case(heading.group(1)):
                found.append((rel, n, "Title Case heading"))
    return found


def board_drift(repo, fields_file):
    """(board name, differences from shared/kanban-baseline.json), reusing the backlog checker. None without a board."""
    config_path = Path(repo) / "docs" / "backlog-config.json"
    if not fields_file and not config_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("check_kanban_baseline", BASELINE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else None
    fields = json.loads(Path(fields_file).read_text(encoding="utf-8")) if fields_file else mod.read_fields_from_gh(config)
    name = f"{config['repoOwner']}/{config['repoName']}" if config else "the saved board"
    return name, mod.check_baseline(fields, mod.load_baseline(), config)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--time", action="store_true", help="run the repo's tests and report the runtime")
    parser.add_argument("--fields-file", help="saved board field list, in place of a gh call")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    files = tracked(repo)
    problems = 0

    budget_path = repo / BUDGET_FILE
    budget = json.loads(budget_path.read_text(encoding="utf-8")) if budget_path.is_file() else {}
    measured = measure(repo, files)
    per_module = {}
    measured["testSeconds"] = run_tests(repo, per_module) if args.time else None
    print(f"== Budgets ({BUDGET_FILE if budget else 'no budget file'})")
    lines, over = budget_lines(measured, budget)
    print("\n".join(lines))
    if per_module:
        slowest = sorted(per_module.items(), key=lambda kv: kv[1], reverse=True)[:3]
        print("slowest test files: " + ", ".join(f"{m} {t:.1f}s" for m, t in slowest))
    problems += over

    print("== Voice")
    findings = voice_findings(repo, files)
    kinds = {}
    for rel, n, kind in findings:
        print(f"{rel}:{n}: {kind}")
        kinds[kind] = kinds.get(kind, 0) + 1
    print("voice: " + (", ".join(f"{v} {k}" for k, v in sorted(kinds.items())) if kinds else "no violations found"))
    problems += len(findings)

    print("== Board")
    drift = board_drift(repo, args.fields_file)
    if drift is None:
        print("board: no backlog config, not checked")
    else:
        name, diffs = drift
        for d in diffs:
            print(f"{name}: {d}")
        print(f"board: {len(diffs)} difference(s) from shared/kanban-baseline.json" if diffs else "board: matches the baseline")
        problems += len(diffs)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

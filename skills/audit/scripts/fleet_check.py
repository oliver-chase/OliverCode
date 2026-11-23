#!/usr/bin/env python3
"""Failing tests, voice violations and board drift for one repo, as the audit's lean-fleet pass.

Usage:
    fleet_check.py [repo]                  # voice, plus board drift when the repo has a backlog config
    fleet_check.py --time [repo]           # also runs the repo's tests and names each failing file
    fleet_check.py --fields-file F [repo]  # board drift from a saved `gh project field-list` JSON

Each line of output is a voice finding as `file:line`, a failing test file or a board difference.
Exit status is 1 when anything is flagged. It edits nothing.
Tests: python3 -m unittest test_fleet_check   (from this scripts/ folder)
"""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from _fleet import archived_state, read, tracked

BASELINE_SCRIPT = Path(__file__).resolve().parents[2] / "backlog" / "scripts" / "check_kanban_baseline.py"

CONTRAST = re.compile(
    r"\b(?:not\b[^.\n]{1,60}?,?\s*\bbut\b|rather than\b|instead of\b|less\b[^.\n]{1,40}?,\s*more\b|it is not about\b)"
    r"|,\s+not\s+(?:a|an|the|by|at|in|on|to|for|from|this|that|its|their|my|our|your)\b"
    r"|\band\s+not\s+(?:a|an|the|by|at|in|on|to|for|from|with)\b", re.I)
QUOTED = re.compile(r'"[^"\n]*"')
SMALL = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "vs", "is", "at", "by"}
CURLY = "‘’“”"


def queued(command):
    """The command behind the machine's validation queue helper (the same neutral `validate-queue` shim every repo's validate.sh
    uses), so a timing run waits for a slot like any validation. Inside a held slot, or with no helper, the command runs as given."""
    shim = Path.home() / ".local" / "bin" / "validate-queue"
    inside = any(os.environ.get(v, "").endswith(".json") for v in ("OLIVERCODE_VALIDATE_SLOT", "VALIDATE_QUEUE_SLOT"))
    return command if inside or not shim.is_file() else [str(shim), "run", *command]


def run_tests(repo, per_module=None, failed=None):
    """Wall seconds to run every `tests/test_*.py` and `skills/*/scripts/test_*.py` module, each in its own
    process from its own folder as validate.sh does, or None when the repo has no such module. A dict passed
    as `per_module` gets each module's seconds, and a list passed as `failed` gets each module that failed."""
    root = Path(repo)
    found = sorted(root.glob("tests/test_*.py")) + sorted(root.glob("skills/*/scripts/test_*.py"))
    modules = [(p.parent, p.stem) for p in found]
    if not modules:
        return None
    def run_one(entry):
        folder, module = entry
        began = time.monotonic()
        done = subprocess.run(queued([sys.executable, "-m", "unittest", "-b", module]), cwd=folder, capture_output=True)
        if done.returncode and failed is not None:
            failed.append(module)
        if per_module is not None:
            per_module[module] = time.monotonic() - began

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(run_one, modules))
    return round(time.monotonic() - start, 1)


def title_case(text):
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    major = [w for w in words[1:] if w.lower() not in SMALL and not w.isupper()]
    return len(major) >= 2 and all(w[0].isupper() for w in major)


def names_the_repo(text, repo, stripped):
    """A top-level title that spells the repo's own name is a proper noun, so Title Case is its name."""
    squash = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    return stripped.startswith("# ") and squash(text) == squash(Path(repo).resolve().name)


def voice_configured():
    """True when the user has a voice file: OLIVERCODE_VOICE_FILE, `voiceFile` in olivercode.local.json, or ~/.claude/VOICE.md (#719)."""
    if os.environ.get("OLIVERCODE_VOICE_FILE"):
        return Path(os.environ["OLIVERCODE_VOICE_FILE"]).expanduser().is_file()
    local = Path(os.environ.get("OLIVERCODE_LOCAL_CONFIG") or Path(__file__).resolve().parents[3] / "olivercode.local.json")
    try:
        if json.loads(local.read_text(encoding="utf-8")).get("voiceFile"):
            return True
    except (OSError, ValueError, AttributeError):
        pass
    return (Path.home() / ".claude" / "VOICE.md").is_file()


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
            if CONTRAST.search(QUOTED.sub('', line)):
                found.append((rel, n, "contrast framing"))
            if re.match(r"[-*]\s+.*\.$", stripped) and not stripped.endswith(("...", "etc.")):
                found.append((rel, n, "trailing period on a bullet"))
            if any(c in line for c in CURLY):
                found.append((rel, n, "curly quotes"))
            if heading and title_case(heading.group(1)) and not names_the_repo(heading.group(1), repo, stripped):
                found.append((rel, n, "Title Case heading"))
    return found


def board_drift(repo, fields_file):
    """(board name, differences from shared/kanban-baseline.json), reusing the backlog checker. None without a board."""
    config_path = Path(repo) / "docs" / "backlog-config.json"
    if not fields_file and not config_path.is_file():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else None
        name = f"{config['repoOwner']}/{config['repoName']}" if config else "the saved board"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return "docs/backlog-config.json", None, f"unreadable backlog config: {exc}"
    if not Path(BASELINE_SCRIPT).is_file():
        return name, None, "the backlog skill is not installed beside this one"
    try:
        spec = importlib.util.spec_from_file_location("check_kanban_baseline", BASELINE_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if config:
            check = importlib.util.spec_from_file_location("check_board_hygiene", Path(BASELINE_SCRIPT).with_name("check_board_hygiene.py"))
            hygiene = importlib.util.module_from_spec(check)
            sys.path.insert(0, str(Path(BASELINE_SCRIPT).parent))
            check.loader.exec_module(hygiene)
            hygiene.verify_config(config, config_path)  # a fork's inherited config names another repo's board (#687)
        fields = json.loads(Path(fields_file).read_text(encoding="utf-8")) if fields_file else mod.read_fields_from_gh(config)
    except (SystemExit, OSError, ValueError) as exc:
        return name, None, str(exc)
    try:
        return name, mod.check_baseline(fields, mod.load_baseline(), config), ""
    except (SystemExit, OSError, ValueError) as exc:
        return name, None, str(exc)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--time", action="store_true", help="run the repo's tests and report the runtime")
    parser.add_argument("--fields-file", help="saved board field list, in place of a gh call")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    state = archived_state(repo)
    if state:
        print(f"skip {repo.name}: {state} on GitHub")
        return 0
    files = tracked(repo)
    problems = 0

    per_module, failed = {}, []
    if args.time:
        print("== Tests")
        seconds = run_tests(repo, per_module, failed)
        print("tests: no tests/test_*.py to run" if seconds is None else f"tests: {len(per_module)} files in {seconds}s")
        if per_module:
            slowest = sorted(per_module.items(), key=lambda kv: kv[1], reverse=True)[:3]
            print("slowest test files: " + ", ".join(f"{m} {t:.1f}s" for m, t in slowest))
        if failed:
            print("failing test files: " + ", ".join(sorted(failed)))
        problems += len(failed)

    print("== Voice")
    findings = voice_findings(repo, files) if voice_configured() else []
    kinds = {}
    for rel, n, kind in findings:
        print(f"{rel}:{n}: {kind}")
        kinds[kind] = kinds.get(kind, 0) + 1
    print("voice: " + ("skipped, no voice file is configured" if not voice_configured() else ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())) if kinds else "no violations found"))
    problems += len(findings)

    print("== Board")
    drift = board_drift(repo, args.fields_file)
    if drift is None:
        print("board: no backlog config, not checked")
    else:
        name, diffs, failure = drift
        if diffs is None:
            print(f"board: not checked ({failure})")
        else:
            for d in diffs:
                print(f"{name}: {d}")
            print(f"board: {len(diffs)} difference(s) from shared/kanban-baseline.json" if diffs else "board: matches the baseline")
            problems += len(diffs)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

"""`olivercode conform`: one repo checked against docs/CONTRACT.md.

Each requirement in the contract is one function here. A miss reports the command that fixes it,
and a repo that must differ records the exception in its own docs/repo-structure-contract.md,
which this reports as an exception and not as a pass.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from lib import backlog_setup, repo_gates
from lib.local_config import OC_ROOT

REQUIRED_FILES = ("README.md", "CLAUDE.md", "docs/repo-structure-contract.md", "docs/backlog-config.json")
EXCEPTION_HEADING = "Contract exceptions"
EXCEPTION_LINE = re.compile(r"^- (?P<id>[a-z-]+): (?P<reason>.*?)\.? Expires (?P<expires>\d{4}-\d{2}-\d{2})\s*$")


@dataclass
class Row:
    requirement: str
    status: str  # pass, fail, exception, manual or skip
    detail: str = ""
    fix: str = ""


def _fail(requirement: str, detail: str, fix: str) -> Row:
    return Row(requirement, "fail", detail, fix)


def layout(repo: Path, **_) -> Row:
    missing = [rel for rel in REQUIRED_FILES if not (repo / rel).is_file()]
    if missing:
        return _fail("layout", f"missing {', '.join(missing)}", f"olivercode bootstrap {repo}")
    return Row("layout", "pass")


def validation(repo: Path, **_) -> Row:
    fix = f"add scripts/validate.sh to {repo.name} and name `bash scripts/validate.sh` in its CLAUDE.md"
    if not (repo / "scripts" / "validate.sh").is_file():
        return _fail("validation", "scripts/validate.sh is missing", fix)
    claude = repo / "CLAUDE.md"
    if not claude.is_file() or "scripts/validate.sh" not in claude.read_text(errors="ignore"):
        return _fail("validation", "CLAUDE.md does not name scripts/validate.sh", fix)
    return Row("validation", "pass")


def board(repo: Path, *, offline: bool, api=None, oc_root: Path = OC_ROOT, **_) -> Row:
    if offline:
        return Row("board", "skip", "offline")
    lines: list[str] = []
    _, failed, skipped = backlog_setup.boards_health([(repo.name, repo)], api or backlog_setup.Api(), oc_root, out=lines.append)
    detail = "; ".join(line.split("] ", 1)[-1].strip() for line in lines if "Fix:" not in line)
    if failed:
        return _fail("board", detail, backlog_setup.FIX.format(path=repo))
    return Row("board", "skip" if skipped else "pass", detail if skipped else "")


def hooks(repo: Path, *, oc_root: Path = OC_ROOT, private: bool = False, variant: str = "", **_) -> Row:
    problems = repo_gates.hook_problems(repo, oc_root / "core" / "templates" / "project", private)
    if problems and variant:
        # A declared variant replaces only pre-commit; pre-push and commit-msg stay managed.
        fatal = [p for p in problems if not p.startswith("pre-commit")]
        if not fatal:
            return Row("hooks", "pass", f"declared hook variant ({variant}); merge template hook fixes by hand")
        problems = fatal
    if problems:
        return _fail("hooks", "; ".join(problems), "olivercode sync-hooks")
    return Row("hooks", "pass")


def managed_files(repo: Path, *, oc_root: Path = OC_ROOT, private: bool = False, variant: str = "", **_) -> Row:
    """A declared variant or a private repo runs a different pre-commit, and the hooks row checks that file."""
    manifest = oc_root / "shared" / "project-bootstrap-manifest.json"
    entries = json.loads(manifest.read_text()).get("templatedFiles", [])
    drifted = []
    for entry in entries:
        if entry.get("mode") != "strict" or (entry["target"] == ".githooks/pre-commit" and (private or variant)):
            continue
        source, target = oc_root / entry["source"], repo / entry["target"]
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            drifted.append(entry["target"])
    if drifted:
        return _fail("managed-files", f"differs from the template: {', '.join(drifted)}", f"olivercode bootstrap {repo}")
    return Row("managed-files", "pass")


def size(repo: Path, *, oc_root: Path = OC_ROOT, **_) -> Row:
    fix = f"olivercode bootstrap {repo}, then olivercode size {repo} --lower"
    baseline_path = repo / "docs" / "SIZE-BASELINE.json"
    if not baseline_path.is_file():
        return _fail("size", "docs/SIZE-BASELINE.json is missing", fix)
    try:
        baseline = json.loads(baseline_path.read_text())
    except ValueError:
        return _fail("size", "docs/SIZE-BASELINE.json is not valid JSON", fix)
    recorded = baseline.get("lines")
    if recorded is None:
        return _fail("size", "the baseline records no line count", fix)
    done = subprocess.run(["bash", str(oc_root / "skills" / "audit" / "scripts" / "size.sh"), "--total", str(repo)],
                          capture_output=True, text=True)
    if done.returncode != 0 or not done.stdout.strip().isdigit():
        return _fail("size", "the line count failed", fix)
    total, allowed = int(done.stdout), recorded * (100 + baseline.get("allowancePercent", 5)) // 100
    if total > allowed:
        return _fail("size", f"{total} lines is above the baseline of {recorded} plus its allowance", fix)
    return Row("size", "pass")


def tests(repo: Path, **_) -> Row:
    return Row("tests", "manual", "no minimum is set, so there is nothing to fail", f"bash skills/audit/scripts/size.sh {repo}")


def docs(repo: Path, *, offline: bool, runner=subprocess.run, **_) -> Row:
    if offline:
        return Row("docs", "skip", "offline")
    try:
        done = runner(["gh", "repo", "view", "--json", "description,repositoryTopics"],
                      capture_output=True, text=True, timeout=15, cwd=str(repo))
        about = json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        about = None
    if about is None:
        return Row("docs", "skip", "gh cannot reach the repo")
    if not (about.get("description") or "").strip() or not about.get("repositoryTopics"):
        return _fail("docs", "the GitHub About has no description or no topics", "gh repo edit --description ... --add-topic ...")
    return Row("docs", "pass")


def audit(repo: Path, **_) -> Row:
    return Row("audit", "manual", "no command checks it", "run the audit skill on a multi-commit session")


CHECKS = (layout, validation, board, hooks, managed_files, size, tests, docs, audit)


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def exceptions(repo: Path, today: date | None = None) -> tuple[dict[str, tuple[str, str]], list[Row]]:
    """The repo's recorded exceptions by requirement id, and a failure row for each bad entry."""
    today = today or date.today()
    path = repo / "docs" / "repo-structure-contract.md"
    if not path.is_file():
        return {}, []
    text = path.read_text(errors="ignore")
    section = re.search(rf"^#+ {EXCEPTION_HEADING}\s*\n(.*?)(?=^#+ |\Z)", text, re.S | re.M)
    valid: dict[str, tuple[str, str]] = {}
    bad: list[Row] = []
    known = {check.__name__.replace("_", "-") for check in CHECKS}
    for line in (section.group(1).splitlines() if section else []):
        if not line.strip().startswith(("-", "*", "+")):
            continue
        match = EXCEPTION_LINE.match(line)
        expires = _parse_date(match["expires"]) if match else None
        if not match or not expires or not match["reason"].strip() or match["id"] not in known:
            bad.append(_fail("exceptions", f"unreadable entry: {line}", f"write it as `- <requirement>: <reason>. Expires YYYY-MM-DD` in {path.name}"))
        elif expires < today:
            bad.append(_fail("exceptions", f"the {match['id']} exception expired on {match['expires']}", f"fix {match['id']} or renew the entry in {path.name}"))
        else:
            valid[match["id"]] = (match["reason"].strip(), match["expires"])
    return valid, bad


def check_repo(repo: Path, *, oc_root: Path = OC_ROOT, offline: bool = False, private: bool = False,
               variant: str = "", api=None, today: date | None = None) -> list[Row]:
    granted, bad = exceptions(repo, today)
    rows = []
    for check in CHECKS:
        row = check(repo, oc_root=oc_root, offline=offline, private=private, variant=variant, api=api)
        if row.status == "fail" and row.requirement in granted:
            reason, expires = granted[row.requirement]
            row = Row(row.requirement, "exception", f"{reason} (expires {expires})")
        rows.append(row)
    return rows + bad


def render(name: str, rows: list[Row], out=print) -> int:
    """Print one repo's rows and return how many failed."""
    out(name)
    for row in rows:
        tag = {"pass": "OK", "fail": "FAIL", "exception": "EXCEPTION", "manual": "MANUAL", "skip": "SKIP"}[row.status]
        out(f"  [{tag}] {row.requirement}" + (f": {row.detail}" if row.detail else ""))
        if row.status in ("fail", "manual") and row.fix:
            out(f"         Fix: {row.fix}")
    return sum(row.status == "fail" for row in rows)

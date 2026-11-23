"""`olivercode conform`: one repo checked against docs/CONTRACT.md.

Each requirement in the contract guards a failure that loses work, leaks data or breaks a gate, and is one function here.
A miss reports the command that fixes it, and a repo that must differ records the exception in its own
docs/repo-structure-contract.md, which this reports as an exception and not as a pass.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from lib import backlog_setup, claude_settings, engine_only as engine_gate, local_config, open_issues, placement, repo_gates, repo_name_guard
from lib.gitfiles import tracked_files
from lib.local_config import OC_ROOT

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


IGNORE_SAMPLES = (".env.local", ".env", "credentials.pem", "private.key", ".secrets/token")


def ignore(repo: Path, runner=subprocess.run, **_) -> Row:
    """Passes when git ignores each credential path (an env file, a .pem, a .key and a .secrets file), whatever pattern does it."""
    try:
        done = runner(["git", "check-ignore", "--no-index", *IGNORE_SAMPLES], capture_output=True, text=True, cwd=str(repo), timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return Row("ignore", "skip", "git cannot run here")
    covered = set(done.stdout.split())
    missing = [p for p in IGNORE_SAMPLES if p not in covered]
    if missing:
        return _fail("ignore", f"git does not ignore {', '.join(missing)}",
                     f"add patterns for them to {repo.name}/.gitignore, such as .env.local, .env, *.pem, *.key and .secrets/*")
    return Row("ignore", "pass")


def validation(repo: Path, **_) -> Row:
    """Passes when CLAUDE.md names scripts/validate.sh, `npm run validate` or `npm run check` and that command exists."""
    fix = f"add scripts/validate.sh to {repo.name} and name `bash scripts/validate.sh` in its CLAUDE.md"
    claude = repo / "CLAUDE.md"
    text = claude.read_text(errors="ignore") if claude.is_file() else ""
    try:
        npm = json.loads((repo / "package.json").read_text()).get("scripts", {}) if (repo / "package.json").is_file() else {}
    except (OSError, ValueError):
        npm = {}
    if "scripts/validate.sh" in text and (repo / "scripts" / "validate.sh").is_file():
        return Row("validation", "pass")
    if any(f"npm run {name}" in text and name in npm for name in ("validate", "check")):
        return Row("validation", "pass")
    if not text:
        return _fail("validation", "CLAUDE.md is missing", fix)
    return _fail("validation", "CLAUDE.md names no validation command that exists (scripts/validate.sh, npm run validate or npm run check)", fix)


ENGINE_GATE = "scripts/lib/engine_only.py"


def sweep_loaded() -> bool:
    return (Path.home() / "Library" / "LaunchAgents" / "com.olivercode.board-sweep.plist").is_file()


def board(repo: Path, *, offline: bool, api=None, oc_root: Path = OC_ROOT, **_) -> Row:
    if offline:
        return Row("board", "skip", "offline")
    lines: list[str] = []
    _, failed, skipped = backlog_setup.boards_health([(repo.name, repo)], api or backlog_setup.Api(), oc_root, out=lines.append, check_hook=False)
    detail = "; ".join(line.split("] ", 1)[-1].strip() for line in lines if "Fix:" not in line)
    if failed:
        return _fail("board", detail, backlog_setup.FIX.format(path=repo))
    off = backlog_setup.workflow_problems(repo, api or backlog_setup.Api())
    if not sweep_loaded():
        # GitHub has no API for the built-in workflows, so the board sweep job keeps the board in step with its issues (#798).
        why = "the board sweep job is not loaded on this machine, so closed issues stay open on the board and new issues stay off it"
        return _fail("board", "; ".join([why, *off]), "Run `olivercode board sync --schedule`")
    return Row("board", "skip" if skipped else "pass", detail if skipped else "")


def issues(repo: Path, *, offline: bool, names: list[str] | None = None, fetch=open_issues.fetch, **_) -> Row:
    """No open issue of the OliverCode repo names a fleet repo, so the public board never leaks one (#814). The names come from the local registry and never print."""
    slug = repo_slug(repo)
    if offline or slug is None or not repo_name_guard.is_olivercode("/".join(slug)):
        return Row("issues", "skip", "offline" if offline else "not the OliverCode repo")
    names = repo_name_guard.default_names(repo) if names is None else names
    if not names:
        return Row("issues", "skip", "no fleet repo names in the registry")
    found = fetch("/".join(slug))
    if found is None:
        return Row("issues", "skip", "GitHub could not be read")
    named = sorted({row["number"] for row in found if repo_name_guard.hits(f"{row.get('title') or ''}\n{row.get('body') or ''}", names)})
    if named:
        return _fail("issues", "open issue(s) " + ", ".join(f"#{n}" for n in named) + " name a fleet repo",
                     "reword the title and body of each named issue so it says another repo, then run `olivercode conform` again")
    return Row("issues", "pass")


def hooks(repo: Path, *, oc_root: Path = OC_ROOT, private: bool = False, variant: str = "", **_) -> Row:
    problems = repo_gates.hook_problems(repo, repo_gates.hook_templates(oc_root), private)
    if problems and variant:
        # A declared variant replaces only pre-commit; pre-push and commit-msg stay managed.
        fatal = [p for p in problems if not p.startswith("pre-commit diverges")]
        if not fatal:
            return Row("hooks", "pass", f"declared hook variant ({variant}); merge template hook fixes by hand")
        problems = fatal
    if problems:
        return _fail("hooks", "; ".join(problems), "olivercode sync-hooks --commit --story N")
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


CODE_SUFFIXES = (".py", ".js", ".mjs", ".ts", ".tsx", ".sh", ".swift")
TEST_NAME = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*$|\.(test|spec)\.[a-z]+$|_test\.[a-z]+$")


def tests(repo: Path, **_) -> Row:
    """Passes when a repo with code has at least one tracked test file. No ratio is set, so the count tells nothing more."""
    tracked = tracked_files(repo)
    if not any(f.endswith(CODE_SUFFIXES) and not TEST_NAME.search(f) for f in tracked):
        return Row("tests", "skip", "no code to test")
    if any(TEST_NAME.search(f) for f in tracked):
        return Row("tests", "pass")
    return _fail("tests", "the repo has code and no tracked test file", f"add a test for the code that matters most to {repo.name}")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)


def branches(repo: Path, *, offline: bool, **_) -> Row:
    """Passes when origin holds only its default branch. Lists each other branch as one clean --apply deletes (merged story/* with no open
    pull request, the rule placement.prunable_remote applies), one it keeps, or one that has commits not on the default branch."""
    if offline:
        return Row("branches", "skip", "offline")
    if _git(repo, "remote", "get-url", "origin").returncode != 0:
        return Row("branches", "skip", "no origin remote")
    listing = _git(repo, "ls-remote", "--symref", "origin")  # one round trip answers both the default branch and the heads
    if listing.returncode != 0:
        return Row("branches", "skip", "origin unreachable")
    default = next((line.split()[1].removeprefix("refs/heads/") for line in listing.stdout.splitlines()
                    if line.startswith("ref: ")), "main")
    others = []
    for line in listing.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if not ref.startswith("refs/heads/"):
            continue
        name = ref.removeprefix("refs/heads/")
        if not name or name == default:
            continue
        if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            state = "not fetched here, so its merge state is unknown"
        elif _git(repo, "merge-base", "--is-ancestor", sha, f"origin/{default}").returncode != 0:
            state = f"has commits not on {default}"
        elif placement.prunable_remote(repo, name):
            state = f"merged into {default}, safe to delete"
        elif name.startswith("story/"):
            state = f"merged into {default}, kept by clean while its pull request is open or GitHub cannot say"
        else:
            state = f"merged into {default}, not a story branch, so clean leaves it"
        others.append(f"{name} ({state})")
    if others:
        return _fail("branches", f"origin has branches besides {default}: " + "; ".join(others),
                     "`olivercode clean --apply` deletes the merged story/* branches with no open pull request; delete the rest with `git push origin --delete <branch>`")
    return Row("branches", "pass")


def repo_slug(repo: Path) -> tuple[str, str] | None:
    """(owner, name) from the repo's docs/backlog-config.json, or None when it names no GitHub repo."""
    try:
        slug = local_config.backlog_config(repo)
        return slug["repoOwner"], slug["repoName"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def fleet_settings(slugs, runner=subprocess.run) -> dict | None:
    """Delete-on-merge and admin rights for every (owner, name) in ONE GraphQL request (#775), keyed by lower-cased "owner/name".

    None when GitHub cannot be reached, so each check falls back to its own per-repo call."""
    slugs = sorted(set(slugs))
    if not slugs:
        return {}
    parts = "".join(f'r{i}: repository(owner: {json.dumps(o)}, name: {json.dumps(n)}) {{ deleteBranchOnMerge viewerCanAdminister }} ' for i, (o, n) in enumerate(slugs))
    try:
        done = runner(["gh", "api", "graphql", "-f", f"query={{ {parts}}}"], capture_output=True, text=True, timeout=60)
        data = (json.loads(done.stdout).get("data") or {}) if done.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    found = {f"{o}/{n}".lower(): data.get(f"r{i}") for i, (o, n) in enumerate(slugs)}
    return {k: v for k, v in found.items() if v} or None


def delete_on_merge(repo: Path, *, offline: bool, settings: dict | None = None, **_) -> Row:
    """Passes when GitHub deletes a pull request's branch on merge. Skips offline or without a GitHub repo in the backlog config."""
    if offline:
        return Row("delete-on-merge", "skip", "offline")
    slug = repo_slug(repo)
    if not slug:
        return Row("delete-on-merge", "skip", "no GitHub repo named in docs/backlog-config.json")
    owner, name = slug
    known = (settings or {}).get(f"{owner}/{name}".lower())
    if known is not None:
        deletes = bool(known.get("deleteBranchOnMerge"))
    else:
        try:
            answer = subprocess.run(["gh", "api", f"repos/{owner}/{name}", "--jq", ".delete_branch_on_merge"],
                                    capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return Row("delete-on-merge", "skip", "gh unavailable")
        if answer.returncode != 0:
            return Row("delete-on-merge", "skip", "GitHub unreachable")
        deletes = answer.stdout.strip() == "true"
    if deletes:
        return Row("delete-on-merge", "pass")
    return _fail("delete-on-merge", f"{owner}/{name} keeps merged pull request branches on GitHub",
                 f"`gh repo edit {owner}/{name} --delete-branch-on-merge`")


def engine_only(repo: Path, **_) -> Row:
    """An engine checkout holds no personal file (#819). A repo that does not ship the engine gate has nothing to check."""
    if not (repo / ENGINE_GATE).is_file():
        return Row("engine-only", "skip", "not an engine checkout")
    found = engine_gate.personal_findings(repo, engine_gate.checkout_paths(repo))
    if found:
        return _fail("engine-only", f"{len(found)} personal file(s): " + "; ".join(f.split(": ", 1)[0] for f in found[:3]) + (" and more" if len(found) > 3 else ""),
                     engine_gate.FIX)
    return Row("engine-only", "pass")


def fleet_private(repo: Path, *, offline: bool, runner=subprocess.run, **_) -> Row:
    """The fleet repo found through the configured fleet path is private with no collaborator beyond its owner (#822). Runs once, on the engine checkout."""
    if offline or not (repo / ENGINE_GATE).is_file():
        return Row("fleet-private", "skip", "offline" if offline else "not an engine checkout")
    folder = local_config.fleet_registry_path().parent
    url = subprocess.run(["git", "-C", str(folder), "remote", "get-url", "origin"], capture_output=True, text=True, timeout=15).stdout
    match = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$", url)
    if not match:
        return Row("fleet-private", "skip", f"no fleet repo with a GitHub remote at {folder}")
    owner, name = match.groups()
    got = [runner(["gh", "api", f"repos/{owner}/{name}{tail}"], capture_output=True, text=True, timeout=30) for tail in ("", "/collaborators")]
    if got[0].returncode:
        return Row("fleet-private", "skip", "gh cannot reach the fleet repo")
    public = not json.loads(got[0].stdout).get("private")
    others = [p["login"] for p in json.loads(got[1].stdout or "[]") if p["login"].lower() != owner.lower()] if not got[1].returncode else []
    if public or others:
        return _fail("fleet-private", "the fleet repo " + " and ".join((["is public"] if public else []) + ([f"has {len(others)} collaborator(s) beyond the owner"] if others else [])),
                     "; ".join((["`gh repo edit %s/%s --visibility private --accept-visibility-change-consequences`" % (owner, name)] if public else []) + (["remove each collaborator in the repo settings under Collaborators"] if others else [])))
    return Row("fleet-private", "pass")


def sleep_setting(repo: Path, *, offline: bool = False, runner=None, system: str | None = None, **_) -> Row:
    """No sleep setting stops a session on this machine (#832). Runs once, on the engine checkout, and skips off macOS."""
    from lib import health_checks
    if not (repo / ENGINE_GATE).is_file() or (system or sys.platform) != "darwin":
        return Row("sleep-setting", "skip", "not an engine checkout" if (system or sys.platform) == "darwin" else "not macOS")
    try:
        warning = health_checks.sleep_warning((runner or health_checks._pmset_text)())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return Row("sleep-setting", "skip", "pmset did not answer")
    if warning:
        return _fail("sleep-setting", warning.split(". ")[0], health_checks.SLEEP_FIX)
    return Row("sleep-setting", "pass")


def permission_policy(repo: Path, **_) -> Row:
    """Passes when the repo lists what a session may do without asking, in .olivercode/policy.json."""
    if (repo / ".olivercode" / "policy.json").is_file():
        return Row("permission-policy", "pass")
    return _fail("permission-policy", f"{repo.name} has no .olivercode/policy.json, so a session has no list of what it may do unasked", f"olivercode policy init {repo}")


def unfinished_work_snapshot(repo: Path, *, home: Path | None = None, **_) -> Row:
    """Passes when the installed Claude settings still run wip_save.py, which saves work not yet landed. Runs once, on the engine checkout."""
    if not (repo / ENGINE_GATE).is_file():
        return Row("unfinished-work-snapshot", "skip", "not an engine checkout")
    if "wip_save.py" in claude_settings.missing((home or Path.home()) / ".claude" / "settings.json"):
        return _fail("unfinished-work-snapshot", "the Claude settings on this machine do not run wip_save.py, so unlanded work is never saved", "olivercode install")
    return Row("unfinished-work-snapshot", "pass")


CHECKS = (ignore, validation, engine_only, fleet_private, sleep_setting, board, issues, hooks, managed_files, tests, branches, delete_on_merge,
          permission_policy, unfinished_work_snapshot)


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
               variant: str = "", api=None, today: date | None = None, hooks_only: bool = False, home: Path | None = None, settings: dict | None = None) -> list[Row]:
    granted, bad = exceptions(repo, today)
    rows = []
    for check in ((hooks,) if hooks_only else CHECKS):
        try:
            row = check(repo, oc_root=oc_root, offline=offline, private=private, variant=variant, api=api, home=home, settings=settings)
        except subprocess.TimeoutExpired as exc:  # one slow command fails its row and the rest of the fleet is still checked (#851)
            row = _fail(check.__name__.replace("_", "-"), f"timed out after {exc.timeout:g} seconds", "run `olivercode conform` again, or check the repo's remote and disk")
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


def check_fleet(repos, *, oc_root: Path, offline: bool, hooks_only: bool = False, runner=subprocess.run) -> tuple[list[list[Row]], dict | None]:
    """Check every (name, path, private, variant) in parallel, capped at the CPU count, and return each repo's rows in order.

    One batched GitHub query answers delete-on-merge and docs for the whole fleet (#775)."""
    settings = None
    if not offline and not hooks_only:
        settings = fleet_settings([slug for slug in (repo_slug(path) for _, path, _, _ in repos) if slug], runner)

    def one(entry):
        _, path, private, variant = entry
        return check_repo(path, oc_root=oc_root, offline=offline, private=private, variant=variant, hooks_only=hooks_only, settings=settings)

    with ThreadPoolExecutor(max_workers=max(1, min(len(repos), os.cpu_count() or 1))) as pool:
        rows = list(pool.map(one, repos))
    return rows, settings


LOCAL_FIXES = ("hooks", "managed-files", "permission-policy")


def fix_kind(row: Row) -> str:
    """How `conform --fix` repairs a failing row: "local" edits the repo, "github" changes a setting the owner owns, "owner" is a step for the owner queue (#778)."""
    if row.requirement in LOCAL_FIXES:
        return "local"
    return "github" if row.requirement == "delete-on-merge" else "owner"

"""`olivercode conform`: one repo checked against docs/CONTRACT.md.

Each requirement in the contract is one function here. A miss reports the command that fixes it,
and a repo that must differ records the exception in its own docs/repo-structure-contract.md,
which this reports as an exception and not as a pass.
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

from lib import backlog_setup, engine_only as engine_gate, features as features_register, live_copy, local_config, machines as machine_records, open_issues, queue_bypass as bypass_gate, repo_gates, repo_name_guard, schedules
from lib.gitfiles import tracked_files
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
    missing = [rel for rel in REQUIRED_FILES if not (repo / rel).is_file()
               and not (rel == "docs/backlog-config.json" and backlog_setup.config_path(repo).is_file())]
    if missing:
        return _fail("layout", f"missing {', '.join(missing)}", f"olivercode bootstrap {repo}")
    return Row("layout", "pass")


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


README_ORDER = ("Install", "Documentation", "Status", "License")


def readme_order_problems(text: str) -> list[str]:
    """A README opens with a title, and its Install, Documentation, Status and License headings come in that order."""
    lines = text.splitlines()
    problems = [] if lines and lines[0].startswith("# ") else ["README.md does not open with a title line"]
    heads = [h.strip().lower() for h in re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE)]
    positions = [(name, next((i for i, h in enumerate(heads) if h.startswith(name.lower())), None)) for name in README_ORDER]
    found = [(name, at) for name, at in positions if at is not None]
    for (a, i), (b, j) in zip(found, found[1:]):
        if j < i:
            problems.append(f"README.md puts \"{b}\" before \"{a}\"; the order is {', '.join(README_ORDER)}")
    return problems


def readme(repo: Path, **_) -> Row:
    """Passes when README.md opens with a title and keeps Install, Documentation, Status and License in that order."""
    path = repo / "README.md"
    if not path.is_file():
        return Row("readme", "skip", "no README.md, which the layout row reports")
    problems = readme_order_problems(path.read_text(errors="ignore"))
    if problems:
        return _fail("readme", "; ".join(problems), f"reorder the sections of {repo.name}/README.md")
    return Row("readme", "pass")


NO_CONTRACT_NEEDED = {"docs", "scripts"}


def folders(repo: Path, **_) -> Row:
    """Passes when every tracked top-level folder besides docs and scripts appears as `name/` in docs/repo-structure-contract.md."""
    contract = repo / "docs" / "repo-structure-contract.md"
    text = contract.read_text(errors="ignore") if contract.is_file() else ""
    tops = {rel.split("/")[0] for rel in tracked_files(repo) if "/" in rel and not rel.startswith(".")}
    undeclared = sorted(t for t in tops - NO_CONTRACT_NEEDED if f"{t}/" not in text)
    if undeclared:
        return _fail("folders", f"the structure contract does not declare {', '.join(t + '/' for t in undeclared)}",
                     f"list each folder with its purpose under \"Required structure\" in {repo.name}/docs/repo-structure-contract.md")
    return Row("folders", "pass")


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


BYPASS_GATE = "scripts/lib/queue_bypass.py"
ENGINE_GATE = "scripts/lib/engine_only.py"


def queue_bypass(repo: Path, **_) -> Row:
    """The gate-queue bypass check (#757). A repo that ships the gate must still run it from scripts/validate.sh, and
    conform runs the check itself on every repo, so a repo whose validation drops it cannot pass silently."""
    script = repo / "scripts" / "validate.sh"
    if (repo / BYPASS_GATE).is_file():
        runs = script.is_file() and any(Path(BYPASS_GATE).name in line and not line.lstrip().startswith("#")
                                        for line in script.read_text(errors="ignore").splitlines())
        if not runs:
            return _fail("queue-bypass", f"scripts/validate.sh no longer runs the queue bypass check ({BYPASS_GATE})",
                         f"restore the `bypass` gate in {repo.name}/scripts/validate.sh, which runs `python3 {BYPASS_GATE}`")
    findings = bypass_gate.check(repo)
    if findings:
        shown = "; ".join(findings[:3]) + (f"; and {len(findings) - 3} more" if len(findings) > 3 else "")
        return _fail("queue-bypass", f"the queue bypass check finds {len(findings)} bypass(es): {shown}",
                     "`olivercode sync-hooks` adds a missing queue block; start every other test or validation run through `bash scripts/validate.sh`")
    return Row("queue-bypass", "pass")


def sweep_loaded() -> bool:
    return features_register._agent(None, "com.olivercode.board-sweep")


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


DEAD_SELFTEST = ".githooks/ste-lint-joined.py"


def dead_selftest(repo: Path, **_) -> Row:
    """The STE gates are gone from the fleet, so a copy of their selftest only fails at its line 97 and must not return."""
    if (repo / DEAD_SELFTEST).exists():
        return _fail("dead-selftest", f"{repo.name} holds {DEAD_SELFTEST}, a selftest that fails because the vendor linter now joins wrapped lines", f"git rm {DEAD_SELFTEST}")
    return Row("dead-selftest", "pass")


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


def docs(repo: Path, *, offline: bool, runner=subprocess.run, settings: dict | None = None, **_) -> Row:
    if offline:
        return Row("docs", "skip", "offline")
    slug = repo_slug(repo)
    known = (settings or {}).get(f"{slug[0]}/{slug[1]}".lower()) if slug else None
    if known is not None:
        about = {"description": known.get("description"), "repositoryTopics": (known.get("repositoryTopics") or {}).get("totalCount")}
    else:
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


LEARNING_HEADING = "Learning loop"
LEARNING_STEPS = ("Record", "Read", "Compare", "Decide", "Thin data")


def learning(repo: Path, **_) -> Row:
    """Passes when the repo's structure contract answers the five steps of the loop in docs/CONTRACT.md, each with a real value."""
    fix = f"fill in the \"{LEARNING_HEADING}\" section of {repo.name}/docs/repo-structure-contract.md (steps in docs/CONTRACT.md), or record an exception"
    path = repo / "docs" / "repo-structure-contract.md"
    text = path.read_text(errors="ignore") if path.is_file() else ""
    section = re.search(rf"^#+ {LEARNING_HEADING}\s*\n(.*?)(?=^#+ |\Z)", text, re.S | re.M)
    if not section:
        return _fail("learning", f"no \"{LEARNING_HEADING}\" section in docs/repo-structure-contract.md", fix)
    missing = []
    for step in LEARNING_STEPS:
        line = re.search(rf"^[-*] {step}: *(.*)$", section.group(1), re.M)
        if not line or not line.group(1).strip() or line.group(1).lstrip().startswith("<"):
            missing.append(step)
    if missing:
        return _fail("learning", f"the loop has no answer for: {', '.join(missing)}", fix)
    return Row("learning", "pass")


APPLIED_LINE = re.compile(r"^applied: *(?:none, because .+|\S.*)$", re.I | re.M)


def research(repo: Path, **_) -> Row:
    """Passes when every file under docs/research states where its findings landed, as `applied: <file>` or `applied: none, because <reason>`."""
    folder = repo / "docs" / "research"
    files = sorted(folder.glob("*.md")) if folder.is_dir() else []
    if not files:
        return Row("research", "skip", "no docs/research")
    bare = [f.name for f in files if not APPLIED_LINE.search(f.read_text(errors="ignore"))]
    if bare:
        shown = ", ".join(bare[:3]) + (f" and {len(bare) - 3} more" if len(bare) > 3 else "")
        return _fail("research", f"{len(bare)} research file(s) name no place their findings landed: {shown}",
                     "add an `applied: <file in code, data or a skill>` line to each, or `applied: none, because <reason>`")
    return Row("research", "pass")


def audit(repo: Path, **_) -> Row:
    ledger = repo / "docs" / "AUDITED.txt"
    if ledger.is_file() and ledger.read_text(encoding="utf-8").strip():
        return Row("audit", "pass")
    return Row("audit", "manual", "no command checks it", "run the audit skill on a multi-commit session")


def automation(repo: Path, *, home: Path | None = None, **_) -> Row:
    """Passes when each script a launchd job or scheduled task runs from this repo is tracked by its git, so a local
    automation is never the only copy. A repo none of them points into is skipped."""
    home = home or Path.home()
    # An empty prefix reads every job, because a job that points into this repo is this repo's whoever owns the label.
    jobs = schedules.jobs(home / ".claude" / "scheduled-tasks", home / "Library" / "LaunchAgents", home, ("",))
    root = repo.resolve()
    tracked, scripts, untracked = None, 0, []
    for name, _, paths in jobs:
        for raw in paths:
            path = Path(raw)
            if not path.is_file() or path.suffix not in schedules.SCRIPT_SUFFIXES:
                continue
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            tracked = set(tracked_files(repo)) if tracked is None else tracked
            scripts += 1
            if rel not in tracked:
                untracked.append(f"{name} runs {rel}")
    if untracked:
        return _fail("automation", "not tracked by git: " + "; ".join(untracked),
                     f"`git -C {repo} add` each script and commit it, so the automation ships inside the repo")
    return Row("automation", "pass") if scripts else Row("automation", "skip", "no local automation runs a script from this repo")


def live_launcher(repo: Path, *, oc_root: Path = OC_ROOT, **_) -> Row:
    """Passes unless OliverCode runs from a path `liveCopies` lists as live, where an update would write into a running bot."""
    found = live_copy.problem(oc_root)
    return _fail("live-launcher", found, "run olivercode from the agent copy named above") if found else Row("live-launcher", "pass")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)


def branches(repo: Path, *, offline: bool, **_) -> Row:
    """Passes when origin holds only its default branch. Lists each other branch as merged (clean --apply deletes it) or not."""
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
        elif _git(repo, "merge-base", "--is-ancestor", sha, f"origin/{default}").returncode == 0:
            state = f"merged into {default}, safe to delete"
        else:
            state = f"has commits not on {default}"
        others.append(f"{name} ({state})")
    if others:
        return _fail("branches", f"origin has branches besides {default}: " + "; ".join(others),
                     "`olivercode clean --apply` deletes the merged ones; land or delete the rest with `git push origin --delete <branch>`")
    return Row("branches", "pass")


def repo_slug(repo: Path) -> tuple[str, str] | None:
    """(owner, name) from the repo's docs/backlog-config.json, or None when it names no GitHub repo."""
    try:
        slug = local_config.backlog_config(repo)
        return slug["repoOwner"], slug["repoName"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def fleet_settings(slugs, runner=subprocess.run) -> dict | None:
    """Delete-on-merge, About and admin rights for every (owner, name) in ONE GraphQL request (#775), keyed by lower-cased "owner/name".

    None when GitHub cannot be reached, so each check falls back to its own per-repo call."""
    slugs = sorted(set(slugs))
    if not slugs:
        return {}
    parts = "".join(f'r{i}: repository(owner: {json.dumps(o)}, name: {json.dumps(n)}) {{ deleteBranchOnMerge description '
                    f'repositoryTopics(first: 1) {{ totalCount }} viewerCanAdminister }} ' for i, (o, n) in enumerate(slugs))
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


def features(repo: Path, *, home: Path | None = None, **_) -> Row:
    """Passes when every feature in docs/STANDARDS.json that is not owner-only is on for the repo. A miss names each enable command."""
    try:
        gaps = features_register.off(repo, home)
    except (OSError, ValueError) as err:
        return _fail("features", f"the feature register is unreadable: {err}", "restore docs/STANDARDS.json from git")
    if gaps:
        return _fail("features", f"{len(gaps)} feature(s) off: " + ", ".join(g.title + (f" ({g.state}: {g.note})" if g.note else "") for g in gaps),
                     "; ".join(dict.fromkeys(features_register.command_for(g, repo) for g in gaps)))
    gone = [f for f in features_register.evaluate(repo, home) if f.retired]
    return Row("features", "pass", "retired: " + "; ".join(f"{f.title} ({f.retired})" for f in gone) if gone else "")


def machines(repo: Path, *, oc_root: Path = OC_ROOT, **_) -> Row:
    """Passes when every machine that recorded itself in the repo runs the newest version with the commit gates and the permission policy (#740)."""
    lines = machine_records.problems(repo, oc_root)
    if lines:
        return _fail("machines", "; ".join(lines), f"on each machine named: olivercode update, olivercode sync-hooks, olivercode policy init {repo}, then olivercode machines record --repo {repo}")
    count = len(machine_records.records(repo))
    return Row("machines", "pass", f"{count} machine(s) recorded" if count else "")


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


CHECKS = (layout, ignore, readme, folders, validation, queue_bypass, engine_only, fleet_private, sleep_setting, board, issues, hooks, managed_files, dead_selftest, tests, docs, learning, research, audit,
          automation, live_launcher, branches, delete_on_merge, features, machines)


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


LOCAL_FIXES = ("hooks", "queue-bypass", "managed-files", "features", "dead-selftest")


def fix_kind(row: Row) -> str:
    """How `conform --fix` repairs a failing row: "local" edits the repo, "github" changes a setting the owner owns, "owner" is a step for the owner queue (#778)."""
    if row.requirement in LOCAL_FIXES and not (row.requirement == "queue-bypass" and "sync-hooks" not in row.fix):
        return "local"
    return "github" if row.requirement == "delete-on-merge" else "owner"

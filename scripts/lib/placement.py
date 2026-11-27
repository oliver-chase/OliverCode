"""One home for repos: every checkout, worktree and backup lives under repoRoot.

`olivercode.local.json` names the root (`repoRoot`, default the folder that holds OliverCode),
the folders to scan for strays (`watchRoots`, default ~/Developer, ~/Desktop and ~/Documents)
and the checkouts allowed to stay elsewhere (`allowOutside`). Worktrees live in
`<repoRoot>/_worktrees` and backups in `<repoRoot>/_archive`.

`health`, `place` and the session-start hook read findings from here, `placement_guard.py`
refuses a new clone or worktree outside the root, and `clean` removes what is reclaimable.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from lib import gh_budget, repo_gates
from lib.local_config import OC_ROOT, load_local, other_device

# A builder's worktree and its dispatch claim are held this long. CLAIM_HOURS matches skills/backlog/scripts/log_action.py.
CLAIM_HOURS = 2
FRESH_HOURS = 2

SKIP_DIRS = {"node_modules", ".git", "Library", ".Trash", ".venv", "venv", "__pycache__", ".next", "dist", "build"}
BACKUP_NAME = re.compile(r"(backup|\.bak$|-old$|-copy$)", re.IGNORECASE)
MAX_DEPTH = 3


@dataclass
class Config:
    root: Path
    worktrees: Path
    archive: Path
    watch: list
    allow: list


@dataclass
class Finding:
    kind: str  # repo, worktree, backup, broken-link
    path: Path
    fix: str


def _p(value: str) -> Path:
    return Path(value).expanduser()


def config() -> Config:
    local = load_local()
    root = _p(local["repoRoot"]) if local.get("repoRoot") else OC_ROOT.parent
    home = Path.home()
    watch = [_p(w) for w in local["watchRoots"]] if "watchRoots" in local else [home / "Developer", home / "Desktop", home / "Documents"]
    return Config(root=root, worktrees=root / "_worktrees", archive=root / "_archive",
                  watch=watch, allow=[_p(a) for a in local.get("allowOutside", [])])


def inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# Folders a sync service mirrors and can evict when the disk fills, which takes a repo's working files away.
SYNCED_PLACES = ("Documents", "Desktop", "Library/Mobile Documents", "Library/CloudStorage", "Dropbox", "OneDrive", "Google Drive")
FILE_PROVIDER_XATTR = "com.apple.file-provider-domain-id"
SAFE_ROOT = "~/Developer/Repos"  # the suggested default for the fix text; the owner's own repoRoot is what counts
# Ignored files a worktree may hold that exist nowhere else: environment files, secrets and local settings.
LOCAL_ONLY = re.compile(r"(^|/)(\.env[^/]*|\.secrets/|[^/]*\.local(\.[^/]*)?)$|(^|/)\.secrets/")


def has_file_provider_xattr(path: Path) -> bool:
    """True when macOS marks the folder as managed by a File Provider (iCloud Drive, Dropbox, OneDrive, Google Drive)."""
    try:
        ran = subprocess.run(["xattr", str(path)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return FILE_PROVIDER_XATTR in ran.stdout


def synced_place(path: Path, home: Path | None = None) -> str:
    """The synced folder that holds path, or "" when none: a known synced place under home, or a File Provider folder."""
    home = home or Path.home()
    real = Path(path).expanduser().resolve()
    for place in SYNCED_PLACES:
        if inside(real, home / place):
            return f"~/{place}"
    for folder in (real, *real.parents):
        if folder == Path(folder.anchor):
            break
        if has_file_provider_xattr(folder):
            return str(folder)
    return ""


def is_worktree(path: Path) -> bool:
    """A linked worktree has a `.git` file that points into the owner's .git/worktrees."""
    git = path / ".git"
    if not git.is_file():
        return False
    try:
        return "/worktrees/" in git.read_text(errors="ignore")
    except OSError:
        return False


def checkouts(base: Path, depth: int = MAX_DEPTH):
    """Yield every folder under base (to `depth`) that holds a `.git`, without descending into one."""
    if not base.is_dir():
        return
    base_depth = len(base.parts)
    for here, dirs, _ in os.walk(base):
        here_path = Path(here)
        if (here_path / ".git").exists():
            dirs[:] = []
            yield here_path
            continue
        if len(here_path.parts) - base_depth >= depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (here_path / d).is_symlink()]


def _git(path: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=timeout)


def linked_worktrees(cfg: Config) -> list[tuple[Path, Path]]:
    """(worktree, owning repo) for every linked worktree git knows about, wherever it sits (including /tmp)."""
    found = []
    if not cfg.root.is_dir():
        return found
    for repo in sorted(cfg.root.iterdir()):
        if repo.name.startswith("_") or not (repo / ".git").is_dir():
            continue
        try:
            out = _git(repo, "worktree", "list", "--porcelain").stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for line in out.splitlines():
            if line.startswith("worktree "):
                path = Path(line[9:])
                if path.name == ".git.nosync":  # git names the main checkout after a protected repo's git folder
                    path = path.parent
                if path.resolve() != repo.resolve():
                    found.append((path, repo))
    return found


def belongs_to_other_device(name: str, slug: str | None) -> bool:
    """True when a repo's folder or clone name is listed in otherDeviceRepos, or its GitHub owner in otherDeviceOwners."""
    repos, owners = other_device()
    return name.lower() in repos or bool(slug and slug.split("/")[0].lower() in owners)


def _origin_slug(path: Path) -> str | None:
    out = _git(path, "remote", "get-url", "origin")
    found = re.search(r"github\.com[:/]([^/:\s]+)/([^/\s]+?)(?:\.git)?/?$", out.stdout.strip()) if out.returncode == 0 else None
    return f"{found.group(1)}/{found.group(2)}" if found else None


def findings(cfg: Config | None = None) -> list[Finding]:
    """Everything out of place: repos and worktrees outside the root, worktrees outside _worktrees, backups and broken links."""
    cfg = cfg or config()
    out: list[Finding] = []
    seen: set[Path] = set()
    for base in cfg.watch:
        for repo in checkouts(base):
            real = repo.resolve()
            if real in seen or inside(repo, cfg.root) or any(inside(repo, a) or repo.resolve() == a.resolve() for a in cfg.allow):
                continue
            seen.add(real)
            if is_worktree(repo):
                out.append(Finding("worktree", repo, f"move it to {cfg.worktrees}/{repo.name}"))
            else:
                out.append(Finding("repo", repo, f"move it to {cfg.root}/{repo.name}"))
    if cfg.root.is_dir():
        for child in sorted(cfg.root.iterdir()):
            if child.name.startswith("_"):
                continue
            if child.is_symlink() and not child.exists():
                out.append(Finding("broken-link", child, "remove the dead link"))
            elif child.is_symlink():
                out.append(Finding("repo", child, f"replace the link with the real folder {child.resolve()}"))
            elif is_worktree(child):
                out.append(Finding("worktree", child, f"move it to {cfg.worktrees}/{child.name}"))
            elif (child / ".git").exists() and belongs_to_other_device(child.name, _origin_slug(child)):
                out.append(Finding("other-device", child, "it belongs to another device: move it out of the repo root or remove it"))
            elif BACKUP_NAME.search(child.name):
                out.append(Finding("backup", child, f"move it to {cfg.archive}/{child.name}"))
    for path, repo in linked_worktrees(cfg):
        if path.resolve().parent == (repo / ".claude" / "worktrees").resolve():
            continue  # Claude Code puts a subagent's isolated worktree here and removes it when the agent ends
        if path.resolve() not in seen and not inside(path, cfg.worktrees) and not any(f.path == path for f in out):
            out.append(Finding("worktree", path, f"move it with `git -C {repo} worktree move {path} {cfg.worktrees}/{path.name}`"))
    if cfg.worktrees.is_dir():
        for child in sorted(cfg.worktrees.iterdir()):
            if child.name.startswith("."):
                continue
            if not is_worktree(child):
                out.append(Finding("repo", child, "only linked worktrees belong in _worktrees"))
            elif repo_gates.has_gates(child) and repo_gates.gate_problem(child):
                out.append(Finding("worktree-hooks", child, f"run `{repo_gates.fix_command(child)}`, so its first commit is not refused ({repo_gates.gate_problem(child)})"))
    return out


@dataclass
class Worktree:
    path: Path
    branch: str
    dirty: bool
    merged: bool
    common: Path


def worktrees(cfg: Config | None = None) -> list[Worktree]:
    """Every linked worktree under the root, the watched folders or _worktrees, with its merge and dirty state."""
    cfg = cfg or config()
    found = []
    seen: set[Path] = set()
    candidates = [path for path, _ in linked_worktrees(cfg)]
    for base in cfg.watch:
        candidates += [r for r in checkouts(base) if is_worktree(r)]
    for repo in candidates:
        if repo.resolve() in seen or not repo.is_dir():
            continue
        seen.add(repo.resolve())
        try:
            # Ignored files count when they hold local secrets or settings, which a worktree removal would delete.
            status = _git(repo, "status", "--short", "--ignored").stdout.splitlines()
            dirty = any(not line.startswith("!!") or LOCAL_ONLY.search(line[3:]) for line in status if line.strip())
            head = _git(repo, "rev-parse", "--abbrev-ref", "origin/HEAD")
            default = head.stdout.strip() if head.returncode == 0 and head.stdout.strip() != "origin/HEAD" else "origin/main"
            merged = _git(repo, "merge-base", "--is-ancestor", "HEAD", default).returncode == 0
            common = Path(_git(repo, "rev-parse", "--git-common-dir").stdout.strip()).resolve().parent
            branch = _git(repo, "branch", "--show-current").stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        found.append(Worktree(repo, branch, dirty, merged, common))
    return found


def _story_of(wt: Worktree) -> str:
    """The story a worktree's unlanded work belongs to: the number in its last commit subject or its branch name."""
    subject = _git(wt.path, "log", "-1", "--format=%s").stdout
    found = re.search(r"\(#(\d+)\)", subject) or re.search(r"(\d+)", wt.branch or "")
    return f"story #{found.group(1)}" if found else "its story"


def held_reason(wt: Worktree) -> str:
    """Why a merged and clean worktree stays anyway: a live dispatch claim holds its story, or a builder used it in the last
    FRESH_HOURS. Empty when nothing holds it."""
    story = re.fullmatch(r"story/(\d+)", wt.branch or "")
    if story and _claimed(story.group(1)):
        return f"a dispatch claim holds story #{story.group(1)}"
    touched = _last_touched(wt)
    if not touched:
        return "its folder cannot be read"
    if time.time() - touched < FRESH_HOURS * 3600:
        return f"used in the last {FRESH_HOURS} hours, so a builder may still be working in it"
    return ""


def _last_touched(wt: Worktree) -> float:
    """The newest change time of the folder, its .git file and the index git keeps for it. Any git command a builder runs
    rewrites that index, so an idle worktree shows its age and an active one shows it. 0 when none of them can be read."""
    gitdir = _git(wt.path, "rev-parse", "--git-dir").stdout.strip()
    stamps = []
    for path in (wt.path, wt.path / ".git", wt.path / gitdir / "index"):
        try:
            stamps.append(path.stat().st_mtime)
        except OSError:
            pass
    return max(stamps, default=0.0)


def _claimed(number: str) -> bool:
    """True while a dispatch claim on this story number is younger than CLAIM_HOURS, in any repo. The claims are written by cmd_dispatch."""
    try:
        claims = json.loads((gh_budget.home() / "dispatch-claims.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    now = time.time()
    return any(key.endswith(f"#{number}") and isinstance(v, dict) and now - float(v.get("at", 0)) < CLAIM_HOURS * 3600
               for key, v in claims.items())


def clean(cfg: Config | None = None, apply: bool = False, remote: bool = True) -> list[str]:
    """Lines saying what happens to each worktree: merged and clean ones are removed unless held_reason keeps them, and the rest are
    kept and why. Remote branches merged into their repo's default branch follow, see remote_branches, unless `remote` is False."""
    cfg = cfg or config()
    lines = []
    for wt in worktrees(cfg):
        if wt.dirty:
            lines.append(f"KEEP   {wt.path} (uncommitted changes)")
        elif not wt.merged:
            lines.append(f"KEEP   {wt.path} (finish or discard {_story_of(wt)}: branch {wt.branch or 'detached'} has commits not on origin/main)")
        elif held := held_reason(wt):
            lines.append(f"KEEP   {wt.path} ({held})")
        elif apply:
            done = _git(wt.common, "worktree", "remove", str(wt.path))
            lines.append(f"REMOVE {wt.path}" if done.returncode == 0 else f"FAILED {wt.path}: {done.stderr.strip()[:80]}")
        else:
            lines.append(f"REMOVE {wt.path} (merged and clean; run with --apply)")
    if remote:
        lines += remote_branches(cfg, apply=apply)
    return lines


PROTECTED_REMOTE_BRANCHES = {"main", "master", "develop"}


def _default_ref(repo: Path) -> str:
    """The default branch as a remote-tracking ref: origin's HEAD when it names one, else origin/main."""
    head = _git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    return head.stdout.strip() if head.returncode == 0 and head.stdout.strip() else "origin/main"


def _open_pr(repo: Path, name: str) -> bool:
    """True when an open pull request has this branch as its head, or when GitHub cannot say, so the branch stays. The REST call
    spends no GraphQL points, and a hit per-minute call cap counts as cannot say."""
    slug = _origin_slug(repo)
    refused = gh_budget.reserve_call()  # '' when the call may go ahead, else the text naming the wait
    if not slug or refused:
        return True
    head = quote(f"{slug.split('/')[0]}:{name}")
    try:
        done = subprocess.run(["gh", "api", f"repos/{slug}/pulls?state=open&head={head}", "--jq", "length"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return True
    count = done.stdout.strip()
    return done.returncode != 0 or not count.isdigit() or int(count) > 0


def prunable_remote(repo: Path, name: str) -> bool:
    """True when clean --apply may delete this merged origin branch: a story/* branch with no open pull request."""
    return name.startswith("story/") and not _open_pr(repo, name)


def remote_branches(cfg: Config | None = None, apply: bool = False) -> list[str]:
    """One line per origin story/* branch merged into its repo's default branch, unless it has an open pull request. With apply it is
    deleted on origin. Any other branch is someone's own and is never listed. A branch a worktree has checked out, and the protected
    names, are never touched."""
    cfg = cfg or config()
    if not cfg.root.is_dir():
        return []
    lines = []
    for repo in sorted(cfg.root.iterdir()):
        if repo.name.startswith("_") or not (repo / ".git").is_dir():
            continue
        if apply and _git(repo, "fetch", "--prune", "--quiet", "origin").returncode != 0:
            lines.append(f"FAILED {repo.name}: could not fetch origin, so no remote branch was checked")
            continue
        default = _default_ref(repo)
        listing = _git(repo, "worktree", "list", "--porcelain").stdout.splitlines()
        busy = {line[len("branch refs/heads/"):] for line in listing if line.startswith("branch refs/heads/")}
        merged = _git(repo, "branch", "-r", "--merged", default, "--format=%(refname:short)").stdout.split()
        for ref in sorted(merged):
            name = ref[len("origin/"):] if ref.startswith("origin/") else ""
            if not name or name == "HEAD" or ref == default or name in busy or name in PROTECTED_REMOTE_BRANCHES:
                continue
            if not prunable_remote(repo, name):
                continue
            if not apply:
                lines.append(f"REMOVE {repo.name}: {ref} (merged into {default}; run with --apply)")
                continue
            # The lease makes the push refuse if origin's branch has moved since the merge check, so unmerged commits survive.
            sha = _git(repo, "rev-parse", "--verify", "--quiet", ref).stdout.strip()
            done = _git(repo, "push", f"--force-with-lease=refs/heads/{name}:{sha}", "origin", "--delete", name)
            lines.append(f"REMOVE {repo.name}: {ref} (merged into {default})" if done.returncode == 0
                         else f"FAILED {repo.name}: {ref} {done.stderr.strip()[:80]}")
    return lines


# --- the creation gate -------------------------------------------------------------------------

_VALUE_OPTIONS_ADD = {"-b", "-B", "--reason"}
_VALUE_OPTIONS_CLONE = {"-b", "--branch", "--depth", "-o", "--origin", "--reference", "--separate-git-dir",
                        "--template", "-c", "--config", "-j", "--jobs", "--filter", "-u", "--upload-pack", "--shallow-since"}


def _positional(args: list[str], value_options) -> list[str]:
    """The arguments that are not options, skipping the value each of `value_options` takes."""
    skip, positional = False, []
    for a in args:
        if skip:
            skip = False
        elif a in value_options:
            skip = True
        elif not a.startswith("-"):
            positional.append(a)
    return positional


def violation(command_words: list[str], cwd: Path, cfg: Config | None = None) -> str:
    """The refusal text when `git worktree add` or `git clone` would create a checkout outside its home, or ''."""
    cfg = cfg or config()
    words = list(command_words)
    if "git" not in words:
        return ""
    rest = words[words.index("git") + 1:]
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in ("-C", "-c", "--git-dir", "--work-tree") else rest[1:]
    if rest[:2] == ["worktree", "add"]:
        positional = _positional(rest[2:], _VALUE_OPTIONS_ADD)
        if not positional:
            return ""
        dest = (cwd / _p(positional[0])).resolve()
        if not inside(dest, cfg.worktrees):
            return (f"Worktrees live under {cfg.worktrees.name}, so this one goes in {cfg.worktrees.name}/{dest.name}. "
                    "See docs/RULES.md, File locations.")
    elif rest[:1] == ["clone"]:
        positional = _positional(rest[1:], _VALUE_OPTIONS_CLONE)
        if not positional:
            return ""
        name = re.sub(r"\.git$", "", positional[0].rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])
        dest = (cwd / _p(positional[1])).resolve() if len(positional) > 1 else (cwd / name).resolve()
        if not inside(dest, cfg.root):
            return f"Repos live under the repo root, so clone it as {dest.name}. See docs/RULES.md, File locations."
        owner = re.search(r"github\.com[:/]([^/:\s]+)/", positional[0])
        if belongs_to_other_device(name, f"{owner.group(1)}/{name}" if owner else None):
            return f"{name} belongs to another device and never lives on this machine, so do not clone it. See docs/RULES.md, Execution."
    return ""


def repo_create_violation(command_words: list[str], cwd: Path) -> str:
    """The refusal text when `gh repo create` would publish a folder that has no origin, or ''.

    An agent never creates a GitHub repo for a folder: a folder without an origin is reported to the owner (#637)."""
    words = list(command_words)
    if "gh" not in words:
        return ""
    rest = words[words.index("gh") + 1:]
    if rest[:2] != ["repo", "create"]:
        return ""
    args = rest[2:]
    source = None
    for i, a in enumerate(args):
        if a == "--source" and i + 1 < len(args):
            source = args[i + 1]
        elif a.startswith("--source="):
            source = a.split("=", 1)[1]
    positional = _positional(args, {"--source", "-d", "--description", "-h", "--homepage", "-g", "--gitignore", "-l", "--license",
                                    "-p", "--template", "-r", "--remote", "--team"})
    if source is None and positional:
        return ""  # a new empty repo by name touches no folder
    folder = (cwd / _p(source)).resolve() if source else cwd.resolve()
    if (folder / ".git").exists() and _origin_slug(folder):
        return ""
    return (f"{folder.name} has no origin, and no agent creates a GitHub repo for a folder: report the folder to the owner "
            "and stop. See docs/RULES.md, Execution.")

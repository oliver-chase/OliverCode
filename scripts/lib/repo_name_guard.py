"""OliverCode's issues, comments and commit messages never name the owner's other repos.

The names come from the local registry through fleet_name_check.fleet_names, read from the main checkout when
this is a linked worktree, so no repo name is ever written
in a tracked file. This module refuses a text that names one (a commit message, a story body, a comment) and
lists the existing issues and comments that already do. It edits nothing on GitHub.

Usage: python3 -m lib.repo_name_guard --text-file FILE      (exit 1 and the lines to reword when FILE names a repo)
       python3 -m lib.repo_name_guard --scan-issues [--repo OWNER/NAME]   (prints the numbers that name a repo)
A checkout with an empty registry has no names, so it passes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.fleet_name_check import fleet_names  # noqa: E402
REPLACEMENT = 'another repo'


def _main_checkout(root: Path) -> Path | None:
    """The main checkout behind a linked worktree, or None. Only the main checkout holds olivercode.local.json."""
    done = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                          capture_output=True, text=True)
    common = Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None
    if common is None or common.name != ".git":
        return None
    main = common.parent
    return main if main.resolve() != Path(root).resolve() and (main / "scripts" / "lib").is_dir() else None


def default_names(root: Path = ROOT) -> list[str]:
    """The registry names for `root`. A worktree has no local registry, so it reads its main checkout's."""
    names = fleet_names(root)
    main = None if names else _main_checkout(root)
    if main is None:
        return names
    code = ("import json, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1] + '/scripts'); "
            "from lib.fleet_name_check import fleet_names; print(json.dumps(fleet_names(Path(sys.argv[1]))))")
    done = subprocess.run([sys.executable, "-c", code, str(main)], capture_output=True, text=True, timeout=60)
    try:
        found = json.loads(done.stdout or "[]")
    except ValueError:
        return []
    return [n for n in found if isinstance(n, str)] if isinstance(found, list) else []


def is_olivercode(repo: str) -> bool:
    """True for OWNER/OliverCode, the only repo whose text this guard protects."""
    return repo.rsplit("/", 1)[-1].lower() == "olivercode"


def _pattern(names: list[str]):
    if not names:
        return None
    return re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9])", re.IGNORECASE)


def hits(text: str, names: list[str] | None = None, root: Path = ROOT) -> list[tuple[int, str]]:
    """(line number, matched name) for each line of `text` that names a fleet repo."""
    pattern = _pattern(default_names(root) if names is None else names)
    if pattern is None:
        return []
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        match = pattern.search(line)
        if match:
            found.append((number, match.group(1).lower()))
    return found


def refusal(text: str, names: list[str] | None = None, root: Path = ROOT) -> str:
    """The refusal text for `text`, or "" when it names no other repo. The message never prints the name it found."""
    found = hits(text, names, root)
    if not found:
        return ""
    lines = ", ".join(str(n) for n, _ in found[:10])
    return (f"this text names another repo on line {lines}. OliverCode issues, comments and commits "
            f'write "{REPLACEMENT}" instead. Reword those lines and try again.')


def redact(text: str, names: list[str] | None = None, root: Path = ROOT) -> str:
    """`text` with each fleet repo name replaced by REPLACEMENT, so a candidate for OliverCode's board keeps its meaning and names no other repo (#978)."""
    pattern = _pattern(default_names(root) if names is None else names)
    return text if pattern is None else pattern.sub(REPLACEMENT, text)


def _gh_pages(path: str, params: list[str]) -> list[dict] | None:
    done = subprocess.run(["gh", "api", "-X", "GET", path, *params, "-f", "per_page=100", "--paginate", "--slurp"],
                          capture_output=True, text=True, timeout=300)
    if done.returncode:
        return None
    try:
        pages = json.loads(done.stdout or "[]")
    except ValueError:
        return None
    return [r for page in pages for r in (page if isinstance(page, list) else [page]) if isinstance(r, dict)]


def scan_issues(repo: str, names: list[str], fetch=_gh_pages) -> tuple[list[int], str]:
    """(sorted issue numbers whose title, body or comment names a fleet repo, error text). Reads over REST only."""
    issues = fetch(f"repos/{repo}/issues", ["-f", "state=all"])
    comments = fetch(f"repos/{repo}/issues/comments", [])
    if issues is None or comments is None:
        return [], f"GitHub could not be read for {repo}"
    numbers = set()
    for row in issues:
        if "pull_request" not in row and hits(f"{row.get('title') or ''}\n{row.get('body') or ''}", names):
            numbers.add(row["number"])
    for row in comments:
        tail = str(row.get("issue_url") or "").rsplit("/", 1)[-1]
        if tail.isdigit() and hits(row.get("body") or "", names):
            numbers.add(int(tail))
    return sorted(numbers), ""


def main(argv=None, out=sys.stdout, err=sys.stderr, fetch=_gh_pages, names: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Keep other repo names out of OliverCode's text.")
    p.add_argument("--text-file", help="a commit message, story body or comment to check")
    p.add_argument("--scan-issues", action="store_true", help="list the issue numbers that already name a repo")
    p.add_argument("--repo", default="", help="OWNER/NAME for --scan-issues, default the origin of this checkout")
    args = p.parse_args(argv)
    names = default_names(ROOT) if names is None else names
    if args.text_file:
        try:
            text = Path(args.text_file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"repo_name_guard: cannot read {args.text_file}: {exc}", file=err)
            return 2
        reason = refusal(text, names)
        if reason:
            print(f"repo_name_guard: {reason}", file=err)
        return 1 if reason else 0
    if args.scan_issues:
        repo = args.repo
        if not repo:
            url = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True, text=True).stdout
            repo = re.sub(r"\.git$", "", url.strip().rstrip("/"))
            repo = "/".join(re.split(r"[/:]", repo)[-2:])
        if not names:
            print("No registry names to look for, so no issue can be listed.", file=out)
            return 0
        numbers, error = scan_issues(repo, names, fetch)
        if error:
            print(f"repo_name_guard: {error}", file=err)
            return 2
        for number in numbers:
            print(number, file=out)
        print(f"{len(numbers)} issue(s) in {repo} name another repo. Reword them by hand.", file=err)
        return 1 if numbers else 0
    p.error("pass --text-file FILE or --scan-issues")
    return 2


if __name__ == "__main__":
    sys.exit(main())

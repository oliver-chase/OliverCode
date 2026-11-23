#!/usr/bin/env python3
"""The bloat check and the code quality check of validate.sh, each one pass over one `git ls-files` listing (#757).

    repo_checks.py bloat DIR      # archive-style directories, files that mark themselves historical, a docs-to-code ratio warning
    repo_checks.py quality DIR    # TypeScript files over 400 lines, Python syntax errors, scripts/lib modules no test mentions

Both print what validate.sh printed when it forked wc, head, grep and python3 once per file, and exit 1 on a failure. The
checks run in-process, so a repo of hundreds of files costs one git call and one Python start.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

RATIO_MAX = 0.60
TS_LINE_LIMIT = 400
ARCHIVE = re.compile(r"(^|/)(archive|archived|old|legacy)/", re.I)
HISTORICAL = re.compile(r"^\**\s*(status:\s*)?(HISTORICAL|DEPRECATED|SUPERSEDED|ARCHIVED)\b", re.I)


def tracked(dir_: str, *patterns: str) -> list[str] | None:
    """The tracked files (optionally matching pathspecs), or None when dir_ is not a git repository."""
    if subprocess.run(["git", "-C", dir_, "rev-parse", "--show-toplevel"], capture_output=True).returncode != 0:
        return None
    done = subprocess.run(["git", "-C", dir_, "-c", "core.quotepath=false", "ls-files", "-z", *(["--", *patterns] if patterns else [])],
                          capture_output=True)
    return [f for f in done.stdout.decode("utf-8", "surrogateescape").split("\0") if f]


def _lines(path: Path) -> int:
    """What `wc -l` reports: the newline count. A missing file counts 0."""
    try:
        return path.read_bytes().count(b"\n")
    except OSError:
        return 0


def bloat(dir_: str) -> int:
    print("=== validate: checking for bloat and legacy files ===")
    files = tracked(dir_)
    if files is None:
        print(f"  [SKIP] {dir_} is not a git repository")
        return 0
    archive, marked, doc_loc, total_loc = [], [], 0, 0
    for f in files:
        path = Path(dir_) / f
        n = _lines(path) if path.is_file() else 0
        total_loc += n
        if f.endswith(".md"):
            doc_loc += n
        if ARCHIVE.search(f):
            archive.append(f)
        if f.endswith(".md"):
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    head = [next(fh, "") for _ in range(5)]
            except OSError:
                head = []
            if any(HISTORICAL.search(line) for line in head):
                marked.append(f)
    hits = 0
    if archive:
        print("  [FAIL] tracked files under archive-style directories (delete them, git history is the archive):" + "".join(f"\n  - {f}" for f in archive))
        hits = 1
    if marked:
        print("  [FAIL] files that mark themselves historical or deprecated (delete or update them):" + "".join(f"\n  - {f}" for f in marked))
        hits = 1
    if total_loc > 0:
        ratio = doc_loc / total_loc
        if ratio > RATIO_MAX:
            print(f"  [WARN] docs are {ratio:.2f} of the repo's lines ({doc_loc} of {total_loc}; threshold {RATIO_MAX:.2f}) - run the audit skill on the docs")
    if hits:
        print("=== validate: bloat check FAILED ===")
        return 1
    print("=== validate: bloat check passed ===")
    return 0


def _syntax_error(path: Path) -> bool:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except Exception:  # a syntax error, a null byte, a bad encoding or a missing file all fail the file
        return True
    return False


def quality(dir_: str) -> int:
    print("=== validate: checking code quality ===")
    issues = 0
    for rel in tracked(dir_, "*.ts", "*.tsx") or []:
        if re.search(r"\.test\.", rel):
            continue
        n = _lines(Path(dir_) / rel)
        if n > TS_LINE_LIMIT:
            print(f"  [FAIL] {dir_}/{rel} has {n} lines (limit {TS_LINE_LIMIT})")
            issues += 1
    for rel in tracked(dir_, "*.py") or []:
        if _syntax_error(Path(dir_) / rel):
            print(f"  [FAIL] syntax error in {dir_}/{rel}")
            issues += 1
    lib, tests = Path(dir_) / "scripts" / "lib", Path(dir_) / "tests"
    if lib.is_dir() and tests.is_dir():
        corpus = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(tests.glob("*.py")))
        for module in sorted(lib.glob("*.py")):
            if module.stem == "__init__":
                continue
            if not re.search(rf"(^|[^A-Za-z0-9_]){re.escape(module.stem)}([^A-Za-z0-9_]|$)", corpus, re.M):
                print(f"  [FAIL] no test file mentions scripts/lib/{module.stem}.py")
                issues += 1
    if issues:
        print(f"=== validate: code quality FAILED ({issues} issue(s)) ===")
        return 1
    print("=== validate: code quality passed ===")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] in ("bloat", "quality"):
        return {"bloat": bloat, "quality": quality}[argv[0]](argv[1])
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

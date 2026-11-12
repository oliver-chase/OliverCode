#!/usr/bin/env python3
"""Portability: what stops a repo from being shared, found with no model.

Usage:
    portability.py [repo]   # prints one `kind  where  detail` row per blocker; exit 1 when any
Kinds:
    secret-file      a tracked credential file (.env, key, token or credentials file)
    home-path        a tracked text file with an absolute home path of a real user
    owner-identity   a git author name or address that also appears in tracked files
    personal-email   an author or committer address in history that is not a noreply or example address
    history-secret   a commit whose diff adds a secret-shaped value or a private key
    missing          no LICENSE, no README, or a .gitignore that does not ignore .env
A `signals:` line lists personal-account terms in the docs, which help decide whether the repo should be
shared at all. The rows are blockers to judge, never a verdict. Tests: python3 -m unittest test_portability
"""

import re
import subprocess
import sys
from pathlib import Path

from _fleet import scan_root, tracked

SECRET_NAME = re.compile(r"(^|/)(\.env(\.(?!example|sample|template)[^/]+)?|id_rsa[^/]*|[^/]*\.(pem|key|p12)|[^/]*(token|credentials)[^/]*\.json)$", re.I)
HOME = re.compile(r"/(?:Users|home)/([A-Za-z0-9._-]+)/")
PLACEHOLDER_USERS = {"you", "name", "user", "username", "example", "me", "yourname", "your-name", "runner", "shared", "someone", "nobody", "alice", "bob", "jane", "pat", "foo", "test", "x"}
SAFE_EMAIL = re.compile(r"noreply|no-reply|@example\.|\.invalid$|\.test$|@localhost|@users\.noreply\.github\.com", re.I)
SECRET_VALUE = r"(api[_-]?key|secret|token|passw(or)?d)[\"']?[ ]*[:=][ ]*[\"']?[A-Za-z0-9/+_=-]{20,}|BEGIN [A-Z ]*PRIVATE KEY"
PERSONAL = re.compile(r"Apple (Notes|Photos|Reminders)|iCloud|Obsidian|Instagram|personal vault|\bmy (family|kids|health|finances)\b", re.I)
QUIET = {"LICENSE", "LICENSE.md", "CHANGELOG.md", "AUTHORS", ".mailmap", "COPYING"}


def git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ""


def read(repo, rel):
    try:
        return (Path(repo) / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def identities(repo):
    """{(name, address): commits} over every author and committer in all history."""
    seen = {}
    for line in git(repo, "log", "--all", "--format=%an%x09%ae%n%cn%x09%ce").splitlines():
        if "\t" in line:
            key = tuple(line.split("\t", 1))
            seen[key] = seen.get(key, 0) + 1
    return seen


def scan(repo):
    files = tracked(repo)
    rows, texts = [], {f: read(repo, f) for f in files}
    for f in files:
        if SECRET_NAME.search(f):
            rows.append(("secret-file", f, "credential file is tracked"))
    for f, t in texts.items():
        users = {u for u in HOME.findall(t) if u not in PLACEHOLDER_USERS and not u.startswith("<")}
        if users:
            rows.append(("home-path", f, "names " + ", ".join(sorted(users))))
    people = identities(repo)
    for (name, addr), n in sorted(people.items()):
        if addr and not SAFE_EMAIL.search(addr):
            rows.append(("personal-email", addr, f"{n} author or committer entries; use a noreply address and a .mailmap"))
    needles = {a for (_, a) in people if a and not SAFE_EMAIL.search(a)} | {nm for (nm, _) in people if len(nm) >= 5 and " " in nm}
    for f, t in texts.items():
        if Path(f).name in QUIET:
            continue
        for needle in sorted(needles):
            if needle in t:
                rows.append(("owner-identity", f, needle))
    shas = git(repo, "log", "--all", "-E", "-i", "-G", SECRET_VALUE, "--format=%h").split()
    for sha in shas[:10]:
        rows.append(("history-secret", sha, f"a diff adds a secret-shaped value ({len(shas)} commits in all); revoke it first, then decide on a history rewrite"))
    names = {Path(f).name for f in files}
    if not any(n.startswith(("LICENSE", "COPYING")) for n in names):
        rows.append(("missing", "LICENSE", "no license"))
    if not any(n.lower().startswith("readme") for n in names):
        rows.append(("missing", "README", "no README"))
    if ".gitignore" in files and not re.search(r"^\.env\b", texts[".gitignore"], re.M):
        rows.append(("missing", ".gitignore", "does not ignore .env"))
    return rows, personal_signals(texts)


def personal_signals(texts):
    found = {}
    for f, t in texts.items():
        if f.endswith(".md"):
            for m in PERSONAL.finditer(t):
                found[m.group(0).lower()] = found.get(m.group(0).lower(), 0) + 1
    return found


def main(argv):
    rows, signals = scan(scan_root(argv[1:], Path(".")))
    for kind, where, detail in rows:
        print(f"{kind:15} {where}  {detail}")
    print("signals: " + (", ".join(f"{k} x{v}" for k, v in sorted(signals.items())) or "none"))
    print(f"portability: {len(rows)} blocker(s)")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""Portability: what stops a repo from being shared, found with no model.

Usage:
    portability.py [repo]   # prints one `kind  where  detail` row per blocker; exit 1 when any
    portability.py --help   # prints this text
The scan reads every ref of the repo's history (`git log --all`), so one run covers each branch and tag. The output holds
counts and file paths only: never an address, a secret value or a commit hash. A path with a space prints in double quotes. A home-path row names the account folder.
Kinds:
    secret-file      a tracked credential file (.env, key, token or credentials file)
    home-path        a tracked text file with an absolute home path of a real user
    owner-identity   a file that holds a git author name or address from history (the row gives a count, never the text)
    personal-email   `N-addresses`: author or committer addresses in history that are not noreply or example addresses
    history-secret   `N-commits`: commits whose diff changes a secret-shaped value or a private key (an added or a removed one)
    missing          no LICENSE, no README, or a .gitignore that does not ignore .env
A `signals:` line lists personal-account terms in the docs, which help decide whether the repo should be
shared at all. The rows are blockers to judge, never a verdict. Tests: python3 -m unittest test_portability
"""

import re
import sys
from pathlib import Path

from _fleet import git, read, scan_root, tracked

SECRET_NAME = re.compile(r"(^|/)(\.env(?!\.[^/]*(example|sample|template)$)(\.[^/]+)?|id_rsa(?![^/]*\.pub$)[^/]*|[^/]*\.(pem|key|p12)|([^/]*[-_.])?(token|credentials)s?([-_.][^/]*)?\.json)$", re.I)
HOME = re.compile(r"/(?:Users|home)/([A-Za-z0-9._-]+)/")
PLACEHOLDER_USERS = {"you", "name", "user", "username", "example", "me", "yourname", "your-name", "runner", "shared", "someone", "nobody", "alice", "bob", "jane", "pat", "foo", "test", "x"}
SAFE_EMAIL = re.compile(r"noreply|no-reply|@example\.|\.invalid$|\.test$|@localhost|@users\.noreply\.github\.com", re.I)
SECRET_VALUE = r"(api[_-]?key|secret|token|passw(or)?d)[\"']?[ ]*[:=][ ]*[\"']?[A-Za-z0-9/+_=-]{20,}|BEGIN [A-Z ]*PRIVATE KEY"
PERSONAL = re.compile(r"Apple (Notes|Photos|Reminders)|iCloud|Obsidian|Instagram|personal vault|\bmy (family|kids|health|finances)\b", re.I)
QUIET = {"LICENSE", "LICENSE.md", "CHANGELOG.md", "AUTHORS", ".mailmap", "COPYING"}
# done_check.py reads the accepted rows from this file, so it names each accepted address by design.
ACCEPTED_FILE = "docs/AUDIT-ACCEPTED.md"


def identities(repo):
    """{(name, address): commits} over every author and committer in all history."""
    seen = {}
    for line in git(repo, "log", "--all", "--format=%aN%x09%aE%n%cN%x09%cE").splitlines():
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
    personal = {a for (_, a) in people if a and not SAFE_EMAIL.search(a)}
    if personal:
        entries = sum(n for (_, a), n in people.items() if a in personal)
        rows.append(("personal-email", f"{len(personal)}-addresses", f"{entries} author or committer entries; use a noreply address and a .mailmap"))
    needles = personal | {nm for (nm, _) in people if len(nm) >= 5 and " " in nm}
    for f, t in texts.items():
        if Path(f).name in QUIET or f == ACCEPTED_FILE:
            continue
        hits = sum(1 for needle in needles if needle in t)
        if hits:
            rows.append(("owner-identity", f, f"holds {hits} author name or address"))
    shas = git(repo, "log", "--all", "-E", "-i", "-G", SECRET_VALUE, "--format=%h").split()
    if shas:
        rows.append(("history-secret", f"{len(shas)}-commits", "a diff changes a secret-shaped value; revoke it first, then decide on a history rewrite"))
    names = {Path(f).name for f in files}
    if not any(n.startswith(("LICENSE", "COPYING")) for n in names):
        rows.append(("missing", "LICENSE", "no license"))
    if not any(n.lower().startswith("readme") for n in names):
        rows.append(("missing", "README", "no README"))
    if not re.search(r"^/?\.env\*?/?\s*$", texts.get(".gitignore", ""), re.M):
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
    if "--help" in argv or "-h" in argv:
        print(__doc__.strip())
        return 0
    rows, signals = scan(scan_root(argv[1:], Path(".")))
    for kind, where, detail in rows:
        print(f"{kind:15} {chr(34) + where + chr(34) if any(c.isspace() for c in where) else where}  {detail}")
    print("signals: " + (", ".join(f"{k} x{v}" for k, v in sorted(signals.items())) or "none"))
    print(f"portability: {len(rows)} blocker(s)")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

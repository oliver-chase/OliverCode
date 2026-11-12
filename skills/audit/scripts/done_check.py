#!/usr/bin/env python3
"""The done check: is a repo finished by the audit's own definition?

Usage:
    done_check.py [repo] [--epic N]... [--validate "command"]   # exit 0 only when every check passes
Checks: the repo's validation passes; fleet_check.py --time reports no budget overrun, voice violation or
board difference; sweep.py and catalog.py --check find nothing; a sharing verdict is recorded ("Sharing:
portable" or "Sharing: personal" with a reason, in the README or docs/SHARING.md) and portability.py
finds no blocker that the verdict says matters; and, with --epic, the epic and every story citing it are
closed (--epic repeats for each epic). A row the owner decided to keep is listed in docs/AUDIT-ACCEPTED.md as
`Accepted: <kind> <where> - <reason>` and is not counted. Tests: python3 -m unittest test_done_check
"""

import re
import subprocess
import sys
from pathlib import Path

from _fleet import scan_root

HERE = Path(__file__).resolve().parent
VERDICT = re.compile(r"^\W*Sharing:?\W*\s*(portable|personal)\b", re.I | re.M)
ACCEPTED = re.compile(r"^Accepted:\s*(\S+)\s+(\S+)", re.M)
PERSONAL_BLOCKERS = {"secret-file", "history-secret"}


def sh(cmd, cwd):
    done = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def accepted(repo):
    f = Path(repo) / "docs" / "AUDIT-ACCEPTED.md"
    return {(k, w) for k, w in ACCEPTED.findall(f.read_text(encoding="utf-8"))} if f.exists() else set()


def rows(output, width=2):
    """(kind, where) from `kind  where  detail` lines."""
    out = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= width and re.fullmatch(r"[a-z-]+", parts[0]) and not line.startswith(("signals", "portability", "catalog", "doc ")):
            out.append((parts[0], parts[1]))
    return out


def verdict(repo):
    for name in ("docs/SHARING.md", "README.md"):
        f = Path(repo) / name
        if f.exists():
            m = VERDICT.search(f.read_text(encoding="utf-8"))
            if m:
                return m.group(1).lower()
    return None


def checks(repo, epics=(), validate=None, run=sh):
    repo = Path(repo)
    skip = accepted(repo)
    out = []
    cmd = validate or ("bash scripts/validate.sh" if (repo / "scripts/validate.sh").exists() else "npm run validate")
    rc, text = run(cmd, repo)
    out.append(("validation", rc == 0, "" if rc == 0 else text.strip().splitlines()[-1][:120] if text.strip() else "failed"))
    rc, text = run([sys.executable, str(HERE / "fleet_check.py"), "--time", str(repo)], repo)
    bad = [l for l in text.splitlines() if "over the budget" in l or l.startswith("voice:") or "difference(s)" in l]
    out.append(("budgets, voice and board", not bad, "; ".join(bad)[:200]))
    _, text = run([sys.executable, str(HERE / "sweep.py"), str(repo)], repo)
    left = [r for r in re.findall(r"^(\S+)\s+(\S+)", text, re.M) if r not in skip]
    out.append(("sweep", not left, f"{len(left)} row(s), first {left[0][1]}" if left else ""))
    rc, text = run([sys.executable, str(HERE / "catalog.py"), str(repo), "--check"], repo)
    out.append(("documentation catalog", rc == 0, text.strip().splitlines()[0][:120] if rc else ""))
    v = verdict(repo)
    out.append(("sharing verdict recorded", v is not None, "" if v else 'add "Sharing: portable" or "Sharing: personal - reason" to README.md or docs/SHARING.md'))
    _, text = run([sys.executable, str(HERE / "portability.py"), str(repo)], repo)
    blockers = [(k, w) for k, w in rows(text) if (k, w) not in skip and (v != "personal" or k in PERSONAL_BLOCKERS)]
    out.append(("portability", not blockers, f"{len(blockers)} blocker(s), first {blockers[0][0]} {blockers[0][1]}" if blockers else ""))
    for epic in epics:
        rc, text = run(["gh", "issue", "view", str(epic), "--json", "state", "--jq", ".state"], repo)
        out.append((f"epic #{epic} closed", rc == 0 and text.strip() == "CLOSED", text.strip()[:80]))
        rc, text = run(["gh", "issue", "list", "--state", "open", "--search", f'"Epic: #{epic}" in:body', "--json", "number", "--jq", "length"], repo)
        out.append((f"no open story under epic #{epic}", rc == 0 and text.strip() == "0", text.strip()[:80]))
    return out


def main(argv):
    args = argv[1:]
    epics = [args[i + 1] for i, a in enumerate(args) if a == "--epic"]
    validate = args[args.index("--validate") + 1] if "--validate" in args else None
    positional = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--epic", "--validate"))]
    repo = Path(positional[0]) if positional else Path(".")
    results = checks(repo, epics, validate)
    for name, ok, detail in results:
        print(f"{'ok  ' if ok else 'FAIL'} {name}{': ' + detail if detail and not ok else ''}")
    failing = [r for r in results if not r[1]]
    print("done" if not failing else f"not done: {len(failing)} check(s) failing")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

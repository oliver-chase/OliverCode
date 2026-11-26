#!/usr/bin/env python3
"""The done check: is a repo finished by the audit's own definition?

Usage:
    done_check.py [repo] [--epic N]... [--validate "command"]   # exit 0 only when every check passes
Checks: the repo's validation passes (scripts/validate.sh, else npm run validate or check, which fails when neither exists); fleet_check.py reports no voice violation or board difference; sweep.py finds nothing; a sharing verdict is recorded ("Sharing:
portable" or "Sharing: personal" with a reason, in the README or docs/SHARING.md) and portability.py
finds no blocker that the verdict says matters; and, with --epic, the epic and every story citing it are
closed (--epic repeats for each epic); the repo has no open issue except one labeled
owner-action (an issue labeled program, which a fleet program tracks on its own epic, is skipped and listed by number), and the backlog skill's board hygiene check is clean when the repo has docs/backlog-config.json. A row the owner decided to keep is listed in docs/AUDIT-ACCEPTED.md as
`Accepted: <kind> <where> - <reason>` and is not counted. A portability row names a count (`2-addresses`,
`2-commits`), so a new address or commit changes the row and shows again. Tests: python3 -m unittest test_done_check
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from _fleet import FLEET_ROOT, validation_command

HERE = Path(__file__).resolve().parent
# "personal" counts only with its reason after a dash or colon.
VERDICT = re.compile(r"^\W*Sharing:\W*\s*(portable\b|personal(?=[ \t]*[-:\u2013\u2014][ \t]*\S))", re.I | re.M)
ACCEPTED = re.compile(r"^Accepted:[ \t]*(\S+)[ \t]+(\"[^\"]*\"|\S+)[ \t]+-[ \t]*\S", re.M)  # a row without its reason does not count
ROW = re.compile(r"^([a-z-]+)\s+(\"[^\"]*\"|\S+)")
PERSONAL_BLOCKERS = {"secret-file", "history-secret"}
HYGIENE = FLEET_ROOT / "backlog" / "scripts" / "check_board_hygiene.py"
OWNER_ACTION = "owner-action"  # an open issue only the owner can do, with its steps in the body
PROGRAM = "program"  # an open issue of a fleet program tracked on its own epic, outside this repo's audit


def sh(cmd, cwd):
    done = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def accepted(repo):
    f = Path(repo) / "docs" / "AUDIT-ACCEPTED.md"
    return {(k, w.strip('"')) for k, w in ACCEPTED.findall(f.read_text(encoding="utf-8"))} if f.exists() else set()


def rows(output):
    """(kind, where) from `kind  where  detail` lines."""
    out = []
    for line in output.splitlines():
        m = ROW.match(line)
        if m:
            out.append((m.group(1), m.group(2).strip('"')))
    return out


def verdict(repo):
    for name in ("docs/SHARING.md", "README.md"):
        f = Path(repo) / name
        if f.exists():
            m = VERDICT.search(f.read_text(encoding="utf-8"))
            if m:
                return m.group(1).lower()
    return None


def crashed(text, rc=0):
    """Why a helper broke: the last line of its traceback, or an exit above 1, which no clean or finding run uses (a
    missing script exits 2), so a crash fails its check where the text alone would read as clean."""
    last = (text.strip().splitlines() or ["no output"])[-1][:120]
    if "Traceback (most recent call last)" in text:
        return ["helper crashed: " + last]
    return [f"helper exited {rc}: {last}"] if rc > 1 else []


def checks(repo, epics=(), validate=None, run=sh):
    repo = Path(repo)
    skip = accepted(repo)
    out = []
    cmd = validate or validation_command(repo)
    rc, text = run(cmd, repo)
    out.append(("validation", rc == 0, "" if rc == 0 else text.strip().splitlines()[-1][:120] if text.strip() else "failed"))
    rc, text = run([sys.executable, str(HERE / "fleet_check.py"), str(repo)], repo)
    bad = crashed(text, rc) + [l for l in text.splitlines() if (l.startswith("voice:") and "no violations" not in l) or "difference(s)" in l
           or l.startswith("board: not checked (")]
    out.append(("voice and board", not bad, "; ".join(bad)[:200]))
    rc, text = run([sys.executable, str(HERE / "sweep.py"), str(repo)], repo)
    # A sweep row names `file:line`, and an accepted row holds while the file keeps the def, so the line number is not compared.
    kept = {(k, re.sub(r":\d+$", "", w)) for k, w in skip}
    left = [(k, w) for k, w in rows(text) if (k, re.sub(r":\d+$", "", w)) not in kept]
    out.append(("sweep", not left and not crashed(text, rc), "; ".join(crashed(text, rc)) or (f"{len(left)} row(s), first {left[0][0]} {left[0][1]}" if left else "")))
    v = verdict(repo)
    out.append(("sharing verdict recorded", v is not None, "" if v else 'add "Sharing: portable" or "Sharing: personal - reason" to README.md or docs/SHARING.md'))
    rc, text = run([sys.executable, str(HERE / "portability.py"), str(repo)], repo)
    blockers = [(k, w) for k, w in rows(text) if (k, w) not in skip and (v != "personal" or k in PERSONAL_BLOCKERS)]
    out.append(("portability", not blockers and not crashed(text, rc),
                "; ".join(crashed(text, rc)) or (f"{len(blockers)} blocker(s), first {blockers[0][0]} {blockers[0][1]}" if blockers else "")))
    for epic in epics:
        rc, text = run(["gh", "issue", "view", str(epic), "--json", "state,body"], repo)
        try:
            issue = json.loads(text) if rc == 0 else {}
        except ValueError:
            issue = {}
        closed = issue.get("state") == "CLOSED"
        out.append((f"epic #{epic} closed", closed, "" if closed else (issue.get("state") or text.strip())[:80]))
        rc, text = run(["gh", "issue", "list", "--state", "open", "--search", f'"Epic: #{epic}" in:body', "--json", "number", "--jq", "length"], repo)
        none_open = rc == 0 and text.strip() == "0"
        out.append((f"no open story under epic #{epic}", none_open, "" if none_open else text.strip()[:80]))
    return out + backlog(repo, run)


def backlog(repo, run):
    """The board half of done: no open issue except one labeled owner-action, which is the owner's to do and is
    named, or one labeled program, which a fleet program tracks elsewhere and is named too, and a clean board hygiene report when the repo has a backlog config and the backlog skill is beside this one."""
    rc, text = run(["gh", "api", "--paginate", "repos/{owner}/{repo}/issues?state=open&per_page=100", "--jq",
                    '.[] | select(.pull_request | not) | [.number, ([.labels[].name] | join(","))] | @tsv'], repo)
    issues = [line.split("\t") for line in text.splitlines() if line.strip()] if rc == 0 else None
    if issues is None:
        out = [("no open issue", False, text.strip()[:80] or "gh api failed")]
    else:
        owner = [f"#{r[0]}" for r in issues if OWNER_ACTION in r[1].split(",")]
        program = [f"#{r[0]}" for r in issues if PROGRAM in r[1].split(",") and OWNER_ACTION not in r[1].split(",")]
        rest = [f"#{r[0]}" for r in issues if f"#{r[0]}" not in owner + program]
        note = "; ".join(n for n in (f"{len(owner)} owner action(s) left for the owner: {', '.join(owner)}" if owner else "",
                                     f"{len(program)} program item(s) skipped: {', '.join(program)}" if program else "") if n)
        out = [("no open issue", not rest, f"{len(rest)} open, first {', '.join(rest[:5])}" if rest else note)]
    config = Path(repo) / "docs" / "backlog-config.json"
    if not config.is_file():
        return out + [("board hygiene", True, "no backlog config, not checked")]
    if not HYGIENE.is_file():
        return out + [("board hygiene", False, "board hygiene could not run: the backlog skill is missing from this checkout")]
    rc, text = run([sys.executable, str(HYGIENE), "--config", str(config)], repo)
    first = next((line.strip(" -") for line in text.splitlines() if line.strip().startswith("- [")), text.strip()[-100:])
    return out + [("board hygiene", rc == 0, "" if rc == 0 else first[:120])]


def main(argv):
    args = argv[1:]
    if args and args[-1] in ("--epic", "--validate"):
        print(__doc__.strip())
        return 2
    epics = [args[i + 1] for i, a in enumerate(args) if a == "--epic"]
    validate = args[args.index("--validate") + 1] if "--validate" in args else None
    positional = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--epic", "--validate"))]
    repo = Path(positional[0]) if positional else Path(".")
    results = checks(repo, epics, validate)
    for name, ok, detail in results:
        print(f"{'ok  ' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}")
    failing = [r for r in results if not r[1]]
    print("done" if not failing else f"not done: {len(failing)} check(s) failing")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

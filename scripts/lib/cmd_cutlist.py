"""Launcher command `cutlist`: the re-runnable audit of what in OliverCode earns its place (#562).

For each guard, command and document it prints the story that created it, its last trigger and its line count,
flags what has not triggered inside the window, and lists the owner rules that no gate or check covers.
Guards trigger through the failure log, a registered Claude Code hook through its hook-fires file (lib/hook_fires.py), commands through the launcher's command log, and a document's
last trigger is its last change. Standard library only, and it changes nothing.
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from lib import failure_log, hook_fires, limits
from lib.claude_settings import MANAGED
from lib.cli import COMMANDS
from lib.local_config import OC_ROOT

USAGE = "Usage: olivercode cutlist [--days N] [--memory USER.md] | --dupes"
COMMAND_LOG = "commands.log"
RULE_GATES = "shared/owner-rule-gates.json"

# Each guard file and the gate name it writes to the failure log. A guard missing here logs nothing.
GUARD_LABELS = {
    "core/hooks/gates/secrets.sh": "Secrets",
    "core/hooks/gates/pii.sh": "PII",
    "core/hooks/gates/owner-identifiers.sh": "Owner identifiers",
    "core/hooks/gates/repo-local.sh": "Repo-local gates",
    "core/hooks/gates/commit-msg.sh": "Commit message",
    "scripts/hooks/policy_guard.py": "policy",
    "scripts/hooks/commit_guard.py": "commit_guard",
    "scripts/hooks/archived_guard.py": "archived_guard",
    "scripts/hooks/placement_guard.py": "placement_guard",
    "scripts/hooks/gh_guard.py": "gh_guard",
    "scripts/hooks/memory_guard.py": "memory_guard",
}
# A registered hook is judged by its last action. These two act without output, so their last run counts.
SILENT_HOOKS = {"gh_watch", "wip_save"}
_STORY = re.compile(r"#(\d+)")


def record_command(cmd: str) -> None:
    """Append one line per launcher run to ~/.olivercode/commands.log, so the audit can count use. Never raises."""
    if not cmd or cmd.startswith("-"):
        return
    try:
        path = failure_log.home() / COMMAND_LOG
        if not path.parent.is_dir():
            return
        when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{when}\t{cmd}\n")
        failure_log.trim(path)
    except OSError:
        pass


def _story(subject: str) -> str:
    m = _STORY.search(subject)
    return f"#{m.group(1)}" if m else "pre-story"


def file_history(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """(path -> story of the commit that added it, path -> date of its last change), from two passes over history."""
    added: dict[str, str] = {}
    subject = ""
    for line in limits.git(root, "log", "--no-renames", "--diff-filter=A", "--format=@@%s", "--name-only").splitlines():
        if line.startswith("@@"):
            subject = line[2:]
        elif line:
            added[line] = _story(subject)  # newest first, so the oldest add wins
    changed: dict[str, str] = {}
    day = ""
    for line in limits.git(root, "log", "--format=@@%cs", "--name-only").splitlines():
        if line.startswith("@@"):
            day = line[2:]
        elif line and line not in changed:
            changed[line] = day
    return added, changed


def command_origins(root: Path) -> dict[str, str]:
    """Command name -> story of the commit that first added its row to the command table."""
    origins: dict[str, str] = {}
    subject = ""
    out = limits.git(root, "log", "--reverse", "--format=@@%s", "-p", "--", "scripts/lib/cli.py", "scripts/olivercode")
    for line in out.splitlines():
        if line.startswith("@@") and not line.startswith("@@ "):
            subject = line[2:]
            continue
        m = re.match(r'^\+\s*\("olivercode ([a-z][a-z-]*)', line)
        if m and m.group(1) not in origins:
            origins[m.group(1)] = _story(subject)
    return origins


def _lines(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def _last_by_key(rows: list[tuple[str, str]]) -> dict[str, str]:
    last: dict[str, str] = {}
    for when, key in rows:
        if when > last.get(key, ""):
            last[key] = when
    return last


def command_uses() -> tuple[dict[str, str], str]:
    """(command -> last run, the date the log begins), from the launcher's command log."""
    try:
        text = (failure_log.home() / COMMAND_LOG).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}, ""
    rows = [tuple(l.split("\t")[:2]) for l in text.splitlines() if l.count("\t") >= 1]
    return _last_by_key(rows), min((r[0] for r in rows), default="")[:10]


def _command_lines(root: Path, name: str) -> int:
    """A dedicated cmd_NAME.py counts whole; otherwise the lines of the command_NAME function wherever it lives."""
    under = name.replace("-", "_")
    module = root / "scripts" / "lib" / f"cmd_{under}.py"
    if module.is_file():
        return _lines(module)
    for path in sorted((root / "scripts" / "lib").glob("*.py")):
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, line in enumerate(lines):
            if re.match(rf"def command_{under}\b", line):
                end = next((j for j in range(i + 1, len(lines)) if re.match(r"(def |class |\S)", lines[j]) and lines[j].strip()), len(lines))
                return end - i
    return 0


def _stale(when: str, cutoff: str) -> bool:
    return not when or when[:10] < cutoff


def guards(root: Path, added: dict, cutoff: str) -> list[dict]:
    triggers = _last_by_key([(e[0], e[2]) for e in failure_log.entries()])
    paths = sorted(str(p.relative_to(root)) for pat in ("core/hooks/gates/*.sh", "core/hooks/pre-push.sh", "scripts/hooks/*.py")
                   for p in root.glob(pat))
    fires, registered = hook_fires.last_fires(), {Path(script).stem: script for _e, _m, script in MANAGED}
    rows = []
    for rel in paths:
        stem = Path(rel).stem
        if rel.startswith("scripts/hooks/") and Path(rel).name in registered.values():
            seen = fires.get(stem, {})
            last = seen.get("ran" if stem in SILENT_HOOKS else "acted", "")
            judged = bool(seen.get("since")) and seen["since"][:10] <= cutoff
            rows.append({"item": rel, "origin": added.get(rel, "unknown"), "last": last[:10] or "-", "lines": _lines(root / rel),
                         "flag": "no trigger" if judged and _stale(last, cutoff) else ""})
            continue
        label = GUARD_LABELS.get(rel)
        last = triggers.get(label, "") if label else ""
        flag = "not logged" if not label else ("no trigger" if _stale(last, cutoff) else "")
        rows.append({"item": rel, "origin": added.get(rel, "unknown"), "last": last[:10] or "-", "lines": _lines(root / rel), "flag": flag})
    return rows


def commands(root: Path, cutoff: str) -> tuple[list[dict], str]:
    """The command rows and the date the command log begins. A log younger than the window flags nothing yet."""
    origins, (uses, began) = command_origins(root), command_uses()
    judged = bool(began) and began <= cutoff
    rows, seen = [], set()
    for usage, _ in COMMANDS:
        name = usage.split()[1]
        if name in seen:
            continue
        seen.add(name)
        last = uses.get(name, "")
        rows.append({"item": name, "origin": origins.get(name, "unknown"), "last": last[:10] or "-",
                     "lines": _command_lines(root, name), "flag": "no trigger" if judged and _stale(last, cutoff) else ""})
    return rows, began


def documents(root: Path, added: dict, changed: dict) -> list[dict]:
    tracked = limits.git(root, "ls-files", "*.md").splitlines()
    docs = [p for p in tracked if not p.startswith(("tests/", "core/templates/"))]
    # A document that something still names is never a cut until the owner or the story says why it is safe (#732).
    return [{"item": p, "origin": added.get(p, "unknown"), "last": changed.get(p, "-"), "lines": _lines(root / p),
             "flag": f"linked from {len(refs)}" if (refs := limits.inbound(root, p)) else ""} for p in sorted(docs)]


def carrier(gate: dict, root: Path) -> str:
    """The check that carries a rule, or '' when the entry names one that does not hold (#679).

    A path names a file or hook. "judgment: SKILL" counts only when skills/SKILL/SKILL.md exists and holds the entry's `stated`
    phrase, so a person's judgment is carried by a skill that says the rule. "repo: NAME" counts only when NAME's owner-rules.json
    beside this checkout holds a rule with the entry's `id`."""
    check = str(gate.get("check", "")).strip()
    kind, _, name = check.partition(":")
    name = name.strip()
    if kind == "judgment":
        stated = str(gate.get("stated", "")).strip().lower()
        try:
            text = (root / "skills" / name / "SKILL.md").read_text(encoding="utf-8").lower()
        except (OSError, ValueError):
            return ""
        return check if name and stated and stated in text else ""
    if kind == "repo":
        try:
            held = json.loads((root.parent / name / "owner-rules.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        return check if name and gate.get("id") and any(isinstance(r, dict) and r.get("id") == gate["id"] for r in held) else ""
    return check


def owner_rules(memory: Path, root: Path) -> list[tuple[str, str]]:
    """(rule, the check that covers it or '') for each bullet under the memory file's rule and preference headings."""
    try:
        text = memory.read_text(encoding="utf-8")
        gates = json.loads((root / RULE_GATES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rules, section = [], ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].lower()
        elif line.startswith("- ") and ("rule" in section or "preference" in section):
            rule = re.sub(r"\*\*", "", line[2:]).strip()
            check = next((c for c in (carrier(g, root) for g in gates if g["match"].lower() in rule.lower()) if c), "")
            rules.append((rule, check))
    return rules


def _table(title: str, rows: list[dict], last_label: str) -> list[str]:
    total = sum(r["lines"] for r in rows)
    out = [f"\n{title}: {len(rows)} items, {total} lines", f"  {'item':<44} {'origin':<10} {last_label:<11} {'lines':>6}  flag"]
    out += [f"  {r['item']:<44} {r['origin'][:10]:<10} {r['last']:<11} {r['lines']:>6}  {r['flag']}" for r in rows]
    return out


def default_memory() -> Path:
    """USER.md in the installed checkout, which ~/.claude/CLAUDE.md links to, so a worktree finds it too."""
    link = Path.home() / ".claude" / "CLAUDE.md"
    base = link.resolve().parent if link.is_symlink() else OC_ROOT
    return base / ".claude-optimization" / "memory" / "USER.md"


def report(root: Path, days: int, memory: Path, now: float | None = None) -> str:
    cutoff = time.strftime("%Y-%m-%d", time.gmtime((now or time.time()) - days * 86400))
    added, changed = file_history(root)
    tracked = limits.git(root, "ls-files").splitlines()
    total = sum(_lines(root / p) for p in tracked)
    tests = sum(len(re.findall(r"^\s*def test_", (root / p).read_text(encoding="utf-8", errors="ignore"), re.M))
                for p in tracked if p.startswith("tests/") and p.endswith(".py") and (root / p).is_file())
    g, (c, began), d = guards(root, added, cutoff), commands(root, cutoff), documents(root, added, changed)
    out = [f"OliverCode holds {total} tracked lines in {len(tracked)} files, {tests} test functions, {len(g)} guards and {len(c)} commands.",
           f"A flag marks an item with no trigger since {cutoff} ({days} days), or a guard that logs no trigger at all."]
    out += _table("Guards", g, "last block")
    out += _table("Commands", c, "last run")
    if not began or began > cutoff:
        out.append(f"  The command log began {began or 'today'}, so no command is flagged until it covers {days} days.")
    out += _table("Documents", d, "last edit")
    rules = owner_rules(memory, root)
    lost = [r for r, chk in rules if not chk]
    out.append(f"\nOwner rules: {len(rules)} in the memory file, {len(lost)} with no gate or check named in {RULE_GATES}")
    out += [f"  covered by {chk}: {r[:90]}" for r, chk in rules if chk]
    out += [f"  no gate: {r[:100]}" for r in lost]
    flagged = sum(1 for r in g + c if r["flag"])
    out.append(f"\n{flagged} guards and commands are flagged. File one story per boundary with a cut, a merge or a keep and its reason. A document flagged linked is not cut until a story names why it is safe.")
    return "\n".join(out)


def duplicate_helpers(root: Path) -> list[list[tuple[str, str, int]]]:
    """Groups of functions of three or more lines with the same body and arguments in two or more files of scripts/ (#869). Each member is (file, name, line)."""
    groups: dict[str, list[tuple[str, str, int]]] = {}
    for path in sorted((root / "scripts").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.end_lineno - node.lineno < 2:
                continue
            body = node.body[1:] if ast.get_docstring(node, clean=False) is not None else node.body
            if body:
                key = ast.dump(ast.Module(body=body, type_ignores=[])) + ast.dump(node.args)
                groups.setdefault(key, []).append((str(path.relative_to(root)), node.name, node.lineno))
    return [rows for rows in groups.values() if len({r[0] for r in rows}) > 1]


def dupes_report(root: Path) -> str:
    groups = duplicate_helpers(root)
    pairs = sum(len(g) * (len(g) - 1) // 2 for g in groups)
    out = [f"{pairs} duplicate helper pairs in {len(groups)} groups"]
    out += ["  " + ", ".join(f"{f}:{n} {name}" for f, name, n in g) for g in groups]
    return "\n".join(out)


def command_cutlist(argv: list[str]) -> int:
    if argv == ["--dupes"]:
        print(dupes_report(Path(os.environ.get("OLIVERCODE_CUTLIST_ROOT") or OC_ROOT)))
        return 0
    days, memory, rest = 60, default_memory(), list(argv)
    try:
        while rest:
            flag = rest.pop(0)
            if flag == "--days":
                days = int(rest.pop(0))
            elif flag == "--memory":
                memory = Path(rest.pop(0)).expanduser()
            else:
                raise ValueError(flag)
    except (ValueError, IndexError):
        print(USAGE)
        return 1
    print(report(Path(os.environ.get("OLIVERCODE_CUTLIST_ROOT") or OC_ROOT), days, memory))
    return 0

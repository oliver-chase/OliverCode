"""Launcher command `rule`: an owner rule becomes a check in the repo it governs (#628).

owner-rules.json in a repo holds [{"id", "text", "paths": [glob], "forbid": regex}]. `rule check` fails when a file matching
a rule's paths matches its forbid pattern, so the repo's tests can run it. Standard library only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lib.cli import flags as _flags

USAGE = """Usage:
  olivercode rule add --repo PATH --id ID --text "RULE" --paths GLOB --forbid REGEX
  olivercode rule check --repo PATH"""


def _rules_file(repo: Path) -> Path:
    return repo / "owner-rules.json"


class RulesUnreadable(Exception):
    """owner-rules.json exists and cannot be read as a list of rules."""


def load(repo: Path) -> list[dict]:
    """The rules in the repo's owner-rules.json. No file is no rules, and a file that cannot be read raises RulesUnreadable."""
    path = _rules_file(repo)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RulesUnreadable(f"{path} could not be read ({exc})") from exc
    if not isinstance(data, list):
        raise RulesUnreadable(f"{path} must hold a list of rules")
    return [r for r in data if isinstance(r, dict)]


def add(repo: Path, rid: str, text: str, paths: str, forbid: str) -> None:
    re.compile(forbid)
    rules = [r for r in load(repo) if r.get("id") != rid]  # a malformed file raises here, so add never overwrites it
    rules.append({"id": rid, "text": text, "paths": [paths], "forbid": forbid})
    _rules_file(repo).write_text(json.dumps(rules, indent=2) + "\n", encoding="utf-8")


def violations(repo: Path) -> list[str]:
    out = []
    for rule in load(repo):
        pattern = re.compile(rule.get("forbid", "(?!)"))
        for glob in rule.get("paths", []):
            for path in sorted(repo.glob(glob)):
                if path.is_file() and pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                    out.append(f"{path.relative_to(repo)} breaks owner rule {rule.get('id')}: {rule.get('text')}")
    return out


def command_rule(argv: list[str]) -> int:
    sub, rest = (argv[0], argv[1:]) if argv else ("", [])
    parsed = _flags(rest, {"--repo", "--id", "--text", "--paths", "--forbid"})
    if parsed is None or "--repo" not in parsed[0]:
        print(USAGE)
        return 1
    vals, repo = parsed[0], Path(parsed[0]["--repo"])
    if sub == "add" and all(k in vals for k in ("--id", "--text", "--paths", "--forbid")):
        try:
            add(repo, vals["--id"], vals["--text"], vals["--paths"], vals["--forbid"])
        except RulesUnreadable as exc:
            print(f"Refused: {exc}. Nothing was written. Fix the file first.")
            return 1
        except re.error as exc:
            print(f"Refused: the forbid pattern does not compile ({exc}). Nothing was written.")
            return 1
        print(f"Rule {vals['--id']} is in {_rules_file(repo)}. Run `olivercode rule check --repo {repo}` in the repo's validation.")
        return 0
    if sub == "check":
        try:
            found = violations(repo)
            held = len(load(repo))
        except RulesUnreadable as exc:
            print(f"Unknown: {exc}, so no owner rule was checked. Fix the file.")
            return 1
        print("\n".join(found) if found else f"{held} owner rule(s) hold.")
        return 1 if found else 0
    print(USAGE)
    return 1

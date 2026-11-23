"""One protocol on every machine that works on a repo (#740): each machine records its version, hooks and permission policy in the repo,
and `conform` compares the records, so a machine that is behind or lacks the policy fails by name.

A record is `<repo>/.olivercode/machines/NAME.json`, tracked by the repo's git so every machine reads the others' records.
"""

from __future__ import annotations

import json
import re
import socket
import sys
from datetime import date
from pathlib import Path

from lib.local_config import OC_ROOT

USAGE = "Usage: olivercode machines record|show [--repo DIR] [--name NAME]"
FIELDS = ("machine", "version", "hooks", "policy", "recorded")


def folder(repo: Path) -> Path:
    return repo / ".olivercode" / "machines"


def default_name() -> str:
    return re.sub(r"[^a-z0-9-]+", "-", socket.gethostname().split(".")[0].lower()).strip("-") or "machine"


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text)[:3])


def oc_version(oc_root: Path = OC_ROOT) -> str:
    try:
        return (oc_root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


def records(repo: Path) -> list[dict]:
    """Every machine record in REPO. An unreadable file is a record with no fields, so it fails by its name."""
    found = []
    for path in sorted(folder(repo).glob("*.json")) if folder(repo).is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        found.append({**data, "machine": data.get("machine") or path.stem})
    return found


def record(repo: Path, name: str | None = None, oc_root: Path = OC_ROOT, hooks: bool | None = None, today: date | None = None) -> Path:
    """Write this machine's record for REPO: its OliverCode version, whether git runs the gates and whether the permission policy is here."""
    if hooks is None:
        from lib import conform
        hooks = conform.hooks(repo, oc_root=oc_root).status == "pass"
    name = name or default_name()
    data = {"machine": name, "version": oc_version(oc_root), "hooks": bool(hooks),
            "policy": (repo / ".olivercode" / "policy.json").is_file(), "recorded": (today or date.today()).isoformat()}
    path = folder(repo) / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def problems(repo: Path, oc_root: Path = OC_ROOT) -> list[str]:
    """One line per machine that differs from the protocol: older than the newest version seen, or without the hooks or the permission policy."""
    found = records(repo)
    newest = max([_version(oc_version(oc_root))] + [_version(str(r.get("version", ""))) for r in found])
    lines = []
    for r in found:
        gaps = []
        if _version(str(r.get("version", ""))) < newest:
            gaps.append(f"runs version {r.get('version') or 'unknown'}, behind {'.'.join(map(str, newest))}")
        if r.get("hooks") is not True:
            gaps.append("has no commit gates")
        if r.get("policy") is not True:
            gaps.append("lacks the permission policy")
        if gaps:
            lines.append(f"{r['machine']} " + " and ".join(gaps))
    return lines


def command_machines(argv: list[str], out=print, oc_root: Path = OC_ROOT) -> int:
    args = list(argv)
    sub = args.pop(0) if args else ""
    opts = {}
    while args:
        flag = args.pop(0)
        if flag not in ("--repo", "--name") or not args:
            out(USAGE)
            return 1
        opts[flag] = args.pop(0)
    repo = Path(opts.get("--repo", ".")).expanduser().resolve()
    if sub == "record":
        out(f"Recorded {record(repo, opts.get('--name'))}")
        return 0
    if sub == "show":
        for r in records(repo):
            out(f"  {r['machine']}: version {r.get('version', '?')}, hooks {'on' if r.get('hooks') else 'off'}, policy {'on' if r.get('policy') else 'off'}")
        lines = problems(repo, oc_root=oc_root)
        for line in lines:
            out(f"  [DIFFERS] {line}")
        return 1 if lines else 0
    out(USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(command_machines(sys.argv[1:]))

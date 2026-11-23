"""Launcher command `init-fleet`: scaffold a private fleet repo from core/templates/fleet (#820).

`olivercode init-fleet [--owner LOGIN] [--name REPO] [--dir PATH]` copies the template into PATH (default: the folder of the
fleet registry path), creates a private GitHub repo through gh REST, confirms it is private with no collaborators and only then pushes.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lib.local_config import OC_ROOT, fleet_registry_path

TEMPLATE = OC_ROOT / "core" / "templates" / "fleet"
USAGE = "Usage: olivercode init-fleet [--owner LOGIN] [--name REPO] [--dir PATH]"


def run(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(args, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def scaffold(dest: Path, owner: str, name: str) -> None:
    for src in sorted(TEMPLATE.iterdir()):
        text = src.read_text(encoding="utf-8").replace("{{OWNER}}", owner).replace("{{REPO}}", name)
        (dest / src.name).write_text(text, encoding="utf-8")


def command_init_fleet(argv: list[str], runner=run) -> int:
    opts = {"--owner": "", "--name": "olivercode-fleet", "--dir": ""}
    rest = list(argv)
    while rest:
        flag = rest.pop(0)
        if flag not in opts or not rest:
            print(USAGE)
            return 1
        opts[flag] = rest.pop(0)
    dest = Path(opts["--dir"] or fleet_registry_path().parent).expanduser()
    name = opts["--name"]
    if (dest / "repo-profiles.json").exists():
        print(f"{dest} already holds a fleet. Nothing was changed.")
        return 1
    owner = opts["--owner"]
    if not owner:
        rc, out = runner(["gh", "api", "user", "--jq", ".login"])
        if rc:
            print(f"Could not read your GitHub login ({out}). Run `gh auth login` or pass --owner.")
            return 1
        owner = out
    dest.mkdir(parents=True, exist_ok=True)
    scaffold(dest, owner, name)
    rc, out = runner(["gh", "api", "-X", "POST", "user/repos", "-f", f"name={name}", "-F", "private=true", "-f", "auto_init=false"])
    if rc:
        print(f"Could not create {owner}/{name} ({out}). The files are in {dest}; nothing was pushed.")
        return 1
    rc, out = runner(["gh", "api", f"repos/{owner}/{name}", "--jq", ".private"])
    if rc or out != "true":
        print(f"{owner}/{name} is not confirmed private, so nothing was pushed. Make it private on GitHub, then push from {dest}.")
        return 1
    rc, out = runner(["gh", "api", f"repos/{owner}/{name}/collaborators?affiliation=direct", "--jq", "[.[].login]"])
    others = [] if rc else [c for c in json.loads(out or "[]") if c.lower() != owner.lower()]
    if rc or others:
        print(f"{owner}/{name} must have no collaborators ({out}), so nothing was pushed. Remove them, then push from {dest}.")
        return 1
    url = f"https://github.com/{owner}/{name}.git"
    for step in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "Scaffold the fleet from the OliverCode template"],
                 ["remote", "add", "origin", url], ["push", "-q", "-u", "origin", "main"]):
        rc, out = runner(["git", "-C", str(dest), *step])
        if rc:
            print(f"git {step[0]} failed in {dest}: {out}")
            return 1
    print(f"Created private repo {owner}/{name} in {dest}. Registry: {dest / 'repo-profiles.json'}")
    if dest / "repo-profiles.json" != fleet_registry_path():
        print(f"Set \"fleetRegistry\": \"{dest / 'repo-profiles.json'}\" in olivercode.local.json so the fleet commands read it.")
    return 0

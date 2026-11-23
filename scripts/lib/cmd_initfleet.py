"""Launcher command `init-fleet`: scaffold a private fleet repo from core/templates/fleet (#820).

`olivercode init-fleet [--owner LOGIN] [--name REPO] [--dir PATH]` copies the template into PATH (default: the folder of the
fleet registry path), creates a private GitHub repo through gh REST, confirms it is private with no collaborators and only then pushes.
Install makes that folder a local git repo first (#993), so the push reuses its commit and fills in the owner and repo name.
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


def scaffold_local(dest: Path) -> None:
    """Copies the template into dest as it ships, placeholders and all, until the owner and repo name are known (#993). A file that is already there stays."""
    dest.mkdir(parents=True, exist_ok=True)
    for src in sorted(TEMPLATE.iterdir()):
        if not (dest / src.name).exists():
            (dest / src.name).write_bytes(src.read_bytes())


def make_local_repo(dest: Path) -> tuple[bool, str]:
    """Makes dest a git repo with its files in one commit (#993). Returns (made, error); a folder that is already a repo is left alone."""
    if (dest / ".git").exists():
        return False, ""
    dest.mkdir(parents=True, exist_ok=True)
    for step in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "--allow-empty", "-m", "Start the fleet repo from the OliverCode template"]):
        rc, out = run(["git", "-C", str(dest), *step])
        if rc:
            return False, f"git {step[0]} failed: {out}"
    return True, ""


def fill_placeholders(dest: Path, owner: str, name: str) -> bool:
    """Writes the owner and repo name into the template placeholders of a local fleet folder. True when a file changed."""
    changed = False
    for path in sorted(p for p in dest.iterdir() if p.is_file()):
        text = path.read_text(encoding="utf-8")
        if "{{" in text:
            path.write_text(text.replace("{{OWNER}}", owner).replace("{{REPO}}", name), encoding="utf-8")
            changed = True
    return changed


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
    local = (dest / ".git").exists()
    if (dest / "repo-profiles.json").exists() and not local:
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
    if local:
        if fill_placeholders(dest, owner, name):
            for step in (["add", "-A"], ["commit", "-q", "-m", "Fill in the fleet repo's owner and name"]):
                rc, out = runner(["git", "-C", str(dest), *step])
                if rc:
                    print(f"git {step[0]} failed in {dest}: {out}")
                    return 1
    else:
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
    steps = [["remote", "add", "origin", url], ["push", "-q", "-u", "origin", "main"]]
    if not local:
        steps = [["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "Scaffold the fleet from the OliverCode template"], *steps]
    for step in steps:
        rc, out = runner(["git", "-C", str(dest), *step])
        if rc:
            print(f"git {step[0]} failed in {dest}: {out}")
            return 1
    print(f"Created private repo {owner}/{name} in {dest}. Registry: {dest / 'repo-profiles.json'}")
    if dest / "repo-profiles.json" != fleet_registry_path():
        print(f"Set \"fleetRegistry\": \"{dest / 'repo-profiles.json'}\" in olivercode.local.json so the fleet commands read it.")
    return 0

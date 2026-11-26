"""Launcher command `init-fleet`: scaffold a private fleet repo from core/templates/fleet (#820).

`olivercode init-fleet [--owner LOGIN] [--name REPO] [--dir PATH]` copies the template into PATH (default: the folder of the
fleet registry path), creates a private GitHub repo through gh REST, confirms it is private with no collaborators and only then pushes.
A folder that is already a local git repo keeps its commit, and the push fills in the owner and repo name.
A name already taken on GitHub is never created over: a fleet repo there is cloned instead, and any other repo stops the command (#1057).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lib.local_config import OC_ROOT, fleet_registry_path

TEMPLATE = OC_ROOT / "core" / "templates" / "fleet"
USAGE = "Usage: olivercode init-fleet [--owner LOGIN] [--name REPO] [--dir PATH]"
REGISTRY = "repo-profiles.json"


def run(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(args, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def scaffold(dest: Path, owner: str, name: str) -> None:
    for src in sorted(TEMPLATE.iterdir()):
        text = src.read_text(encoding="utf-8").replace("{{OWNER}}", owner).replace("{{REPO}}", name)
        (dest / src.name).write_text(text, encoding="utf-8")


def fill_placeholders(dest: Path, owner: str, name: str) -> bool:
    """Writes the owner and repo name into the template placeholders of a local fleet folder. True when a file changed."""
    changed = False
    for path in sorted(p for p in dest.iterdir() if p.is_file()):
        text = path.read_text(encoding="utf-8")
        if "{{" in text:
            path.write_text(text.replace("{{OWNER}}", owner).replace("{{REPO}}", name), encoding="utf-8")
            changed = True
    return changed


def github_login(runner=run) -> tuple[str, str]:
    """The signed-in GitHub login, or ("", reason) when gh cannot say."""
    rc, out = runner(["gh", "api", "user", "--jq", ".login"])
    return ("", out) if rc else (out, "")


def github_repo_kind(owner: str, name: str, runner=run) -> tuple[str, str]:
    """What GitHub holds under owner/name: "none", "fleet" (a repo-profiles.json at its root), "other", or "error" with the reason (#1057)."""
    rc, out = runner(["gh", "api", f"repos/{owner}/{name}", "--jq", ".name"])
    if rc:
        return ("none", "") if "404" in out or "Not Found" in out else ("error", out)
    rc, _ = runner(["gh", "api", f"repos/{owner}/{name}/contents/{REGISTRY}", "--jq", ".name"])
    return ("fleet" if rc == 0 else "other"), ""


def connect_fleet(dest: Path, owner: str, name: str, runner=run) -> int:
    """Clones the owner's existing fleet repo into dest. Nothing is created on GitHub, and the registry it holds is what the fleet commands read (#1057)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    rc, out = runner(["git", "clone", "-q", f"https://github.com/{owner}/{name}.git", str(dest)])
    if rc:
        print(f"Could not clone {owner}/{name} into {dest} ({out}). Nothing was created.")
        return 1
    print(f"Connected to the existing fleet repo {owner}/{name} in {dest}. Registry: {dest / REGISTRY}")
    return 0


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
        owner, out = github_login(runner)
        if not owner:
            print(f"Could not read your GitHub login ({out}). Run `gh auth login` or pass --owner.")
            return 1
    kind, out = github_repo_kind(owner, name, runner)
    if kind == "error":
        print(f"Could not check {owner}/{name} on GitHub ({out}). Nothing was changed.")
        return 1
    if kind == "fleet":
        if local:
            print(f"{owner}/{name} already exists on GitHub, so nothing was pushed. Move {dest} aside, then run this again to clone the GitHub copy.")
            return 1
        if connect_fleet(dest, owner, name, runner):
            return 1
        return _registry_hint(dest)
    if kind == "other":
        print(f"{owner}/{name} already exists on GitHub and has no {REGISTRY}, so it is not a fleet repo. Nothing was pushed. "
              f"Remove it with `{_remove_hint(owner, name)}` or rename it, then run this again.")
        return 1
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
        print(f"{owner}/{name} is not confirmed private, so nothing was pushed. Make it private on GitHub, then push from {dest}, or remove the repo with `{_remove_hint(owner, name)}`.")
        return 1
    rc, out = runner(["gh", "api", f"repos/{owner}/{name}/collaborators?affiliation=direct", "--jq", "[.[].login]"])
    others = [] if rc else [c for c in json.loads(out or "[]") if c.lower() != owner.lower()]
    if rc or others:
        print(f"{owner}/{name} must have no collaborators ({out}), so nothing was pushed. Remove them, then push from {dest}, or remove the repo with `{_remove_hint(owner, name)}`.")
        return 1
    url = f"https://github.com/{owner}/{name}.git"
    steps = [["remote", "add", "origin", url], ["push", "-q", "-u", "origin", "main"]]
    if not local:
        steps = [["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "Scaffold the fleet from the OliverCode template"], *steps]
    for step in steps:
        rc, out = runner(["git", "-C", str(dest), *step])
        if rc:
            print(f"git {step[0]} failed in {dest}: {out}. {owner}/{name} was created on GitHub: finish from {dest}, or remove it with `{_remove_hint(owner, name)}`.")
            return 1
    print(f"Created private repo {owner}/{name} in {dest}. Registry: {dest / REGISTRY}")
    return _registry_hint(dest)


def _remove_hint(owner: str, name: str) -> str:
    """The command that removes a repo this command created, for a run that stopped after the create."""
    return f"gh repo delete {owner}/{name} --yes"


def _registry_hint(dest: Path) -> int:
    """Says how to point fleetRegistry at dest when the fleet commands read another registry. Returns 0."""
    if dest / REGISTRY != fleet_registry_path():
        print(f"Set \"fleetRegistry\": \"{dest / REGISTRY}\" in olivercode.local.json so the fleet commands read it.")
    return 0

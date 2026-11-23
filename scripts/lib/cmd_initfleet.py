"""Launcher command `init-fleet`: scaffold a private fleet repo from core/templates/fleet (#820).

`olivercode init-fleet [--owner LOGIN] [--name REPO] [--dir PATH]` copies the template into PATH (default: the folder of the
fleet registry path), creates a private GitHub repo through gh REST, confirms it is private with no collaborators and only then pushes.
Install makes that folder a local git repo first (#993), so the push reuses its commit and fills in the owner and repo name.
A name already taken on GitHub is never created over: a fleet repo there is cloned instead, and any other repo stops the command (#1057).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from lib.local_config import FLEET_NAME, OC_ROOT, fleet_home, fleet_registry_path

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


def _origin_name(folder: Path) -> str:
    """The repo name at the end of folder's origin URL, or "" when it has none."""
    if not (folder / ".git").exists():
        return ""
    rc, out = run(["git", "-C", str(folder), "remote", "get-url", "origin"])
    return "" if rc else out.strip().removesuffix(".git").rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def is_fleet(folder: Path) -> bool:
    """A fleet repo by content: a repo-profiles.json beside owner-rules.json or the fleet CLAUDE.md, or an origin named olivercode-fleet (#1057)."""
    if (folder / REGISTRY).is_file() and ((folder / "owner-rules.json").is_file() or (folder / "CLAUDE.md").is_file()):
        return True
    return _origin_name(folder) == FLEET_NAME


def fleet_copies(oc_root: Path = OC_ROOT) -> list[Path]:
    """Other fleet repos on this machine: folders under ~/.olivercode and the repo root, and the folder fleetRegistry names. The checkout,
    olivercode-fleet, hidden folders and symlinks are left out (#1057)."""
    dest = fleet_home(oc_root).resolve()
    seen = {dest, Path(oc_root).resolve()}
    candidates = []
    for root in (Path.home() / ".olivercode", dest.parent):
        if root.is_dir():
            candidates += sorted(p for p in root.iterdir() if not p.name.startswith("."))
    candidates.append(fleet_registry_path().parent)
    found = []
    for folder in candidates:
        if folder.is_symlink() or not folder.is_dir() or folder.name.startswith(".") or folder.resolve() in seen:
            continue
        seen.add(folder.resolve())
        if is_fleet(folder):
            found.append(folder)
    return found


def merge_fleet_copies(dest: Path, copies: list[Path], oc_root: Path = OC_ROOT) -> list[str]:
    """Moves each file found only in another fleet copy into dest and keeps dest's copy where both have one. A link into the OliverCode checkout
    is dropped, and each other copy is removed once its files are moved. A change to dest is committed when dest is already a git repo (#1057).
    Returns one line per entry for the output."""
    dest.mkdir(parents=True, exist_ok=True)
    checkout = Path(oc_root).resolve()
    lines, moved = [], False
    for copy in copies:
        for entry in sorted(copy.iterdir()):
            if entry.name == ".git":
                continue
            target = dest / entry.name
            if entry.is_symlink() and Path(os.path.realpath(entry)).is_relative_to(checkout):
                lines.append(f"  dropped {entry.name}: a link into the OliverCode checkout")
            elif target.exists() or target.is_symlink():
                lines.append(f"  kept {entry.name}: {dest} already has it")
            else:
                shutil.move(str(entry), str(target))
                moved = True
                lines.append(f"  moved {entry.name} from {copy}")
        shutil.rmtree(copy)
        lines.append(f"Removed the other fleet copy {copy}")
    if moved and (dest / ".git").exists():
        for step in (["add", "-A"], ["commit", "-q", "-m", "Bring the files of another fleet copy into olivercode-fleet"]):
            rc, out = run(["git", "-C", str(dest), *step])
            if rc and "nothing to commit" not in out:
                lines.append(f"git {step[0]} failed in {dest}: {out}")
                break
    return lines


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

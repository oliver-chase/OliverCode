"""One repeatable setup and repair for a repo's GitHub Project board.

`olivercode backlog-setup [DIR] [--apply]` calls `run_setup`, and `olivercode conform` calls
`boards_health`. The baseline itself lives once in `shared/kanban-baseline.json`, and the
comparison lives once in `skills/backlog/scripts/check_kanban_baseline.py`, which this module imports.

Every GitHub call goes through the injectable `Api` in `lib/board_api.py`, so the unit tests run with a fake runner and no network.

Why the repair is safe: GitHub's `updateProjectV2Field` keeps an option's id and every item value on it when the
option is sent with its `id`, and clears those values when it is sent without one. The command sends every
existing option with its id, snapshots every item first and verifies the per-option counts afterward.
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

from lib.local_config import OC_ROOT  # noqa: E402
sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))
import check_kanban_baseline as kanban  # noqa: E402
from lib import board_api, repo_gates  # noqa: E402
# The board's GraphQL side lives in board_api.py.
from lib.board_api import (  # noqa: E402
    FIELD_KEYS, Api, SetupError, count_problems, create_field, describe_plans, field_key,
    gh_field_list, plan_board, read_board, read_fields, restore_values, snapshot_board,
    update_field)

FIX = "olivercode backlog-setup {path} --apply"
WORKFLOWS = (("Item closed", "set Status to Complete"), ("Auto-add to project", "set the filter to is:issue is:open"))
WORKFLOW_URL = "https://github.com/users/{owner}/projects/{number}/workflows"


def workflow_steps(owner: str, number: int) -> list[str]:
    """The two workflow toggles GitHub offers no API for, with the board's page and the clicks."""
    return [f"Two board workflows need you, because GitHub has no API for them. Open {WORKFLOW_URL.format(owner=owner, number=number)}, "
            "pick each workflow in the left list, set the value, save, then reload to check it is on:",
            "  - Item closed: turn it on and " + WORKFLOWS[0][1],
            "  - Auto-add to project: choose this repo, " + WORKFLOWS[1][1] + ", then turn it on"]


def workflow_problems(target: Path, api: Api) -> list[str]:
    """Names each readable workflow that is off on the repo's board. An unreadable board or workflow list reports nothing."""
    slug = origin_owner_name(target)
    try:
        config = load_config(config_path(target))
    except SetupError:
        return []
    if slug is None or config is None:
        return []
    state = board_api.read_workflows(api, config["projectId"])
    if not state:
        return []
    by_lower = {k.lower(): v for k, v in state.items()}
    off = [name for name, _ in WORKFLOWS if by_lower.get(name.lower()) is False]
    if not off:
        return []
    try:
        number = read_fields(api, config["projectId"])["number"]
    except SetupError:
        return []
    return [f"the board {slug[0]}/{slug[1]} has the workflow '{name}' off. Turn it on at "
            f"{WORKFLOW_URL.format(owner=slug[0], number=number)}" for name in off]


def write_snapshot(snapshot: dict, target: Path, stamp: str) -> Path:
    # The git dir is never tracked, so a snapshot of item titles cannot be committed by accident.
    found = subprocess.run(["git", "-C", str(target), "rev-parse", "--absolute-git-dir"], capture_output=True, text=True)
    if found.returncode != 0 or not found.stdout.strip():
        raise SetupError(f"{target} has no git dir to keep the board snapshot in. Run git init there first.")
    path = Path(found.stdout.strip()) / "backlog-backups" / f"backlog-snapshot-{stamp}.json"
    write_config(path, snapshot)
    return path


def origin_owner_name(target: Path) -> tuple[str, str] | None:
    p = subprocess.run(["git", "-C", str(target), "remote", "get-url", "origin"], capture_output=True, text=True)
    if p.returncode != 0:
        return None
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", p.stdout.strip())
    return (m.group(1), m.group(2)) if m else None


def config_path(target: Path) -> Path:
    """The config file the repo's CLAUDE.md names, else docs/backlog-config.json."""
    claude = target / "CLAUDE.md"
    if claude.is_file():
        names = [n for n in re.findall(r"`?([\w./-]*backlog-config\.json)`?", claude.read_text(encoding="utf-8", errors="ignore"))
                 if not n.startswith("$")]
        # A prose mention of the bare file name must not hide the path the file really has.
        for name in names:
            if (target / name).is_file():
                return target / name
        if names:
            return target / next((n for n in names if "/" in n), "docs/backlog-config.json")
    return target / "docs" / "backlog-config.json"


def load_config(path: Path) -> dict | None:
    """The repo's config, or None when it is absent or still the example's placeholders."""
    if not path.is_file():
        return None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise SetupError(f"{path.name} cannot be read as JSON. Fix the file or delete it, then run backlog-setup again.")
    if not isinstance(config, dict) or not (config.get("repoOwner") and config.get("repoName")):
        raise SetupError(f"{path.name} names no repoOwner and repoName. Copy shared/backlog-config.example.json over it.")
    text = json.dumps(config)
    if "your-github-org-or-user" in text or '"PVT_..."' in text or '"..."' in text or not config.get("projectId"):
        return None
    return config


def config_from_board(board: dict, owner: str, repo: str, existing: dict | None) -> dict:
    config = dict(existing) if existing else {}
    config.update({"repoOwner": owner, "repoName": repo, "projectOwner": board["owner"] or owner,
                   "projectNumber": board["number"], "projectId": board["id"]})
    fields = {}
    for f in board["fields"]:
        key = field_key(f["name"])
        if f["type"] == kanban.SINGLE_SELECT and key in FIELD_KEYS.values():
            fields[key] = {"id": f["id"], "options": {o["name"]: o["id"] for o in f["options"]}}
    config["fields"] = fields
    return config


def config_problems(config: dict, board: dict) -> list[str]:
    """Differences between a config's IDs and the live board. Empty means every ID is real."""
    problems = []
    if config.get("projectId") != board["id"]:
        problems.append("projectId differs from the board")
    for key, entry in config.get("fields", {}).items():
        live = next((f for f in board["fields"] if f["id"] == entry.get("id")), None)
        if live is None:
            problems.append(f"{key}: field id {entry.get('id')} is not on the board")
            continue
        ids = {o["name"]: o["id"] for o in live["options"]}
        for name, oid in (entry.get("options") or {}).items():
            if ids.get(name) != oid:
                problems.append(f"{key}: option {name} id does not match the board")
        problems += [f"{key}: board option {n} is missing from the config" for n in ids if n not in (entry.get("options") or {})]
    return problems


def write_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def hooks_dir_for(target: Path) -> tuple[Path, bool]:
    """(the folder git reads hooks from, whether core.hooksPath is unset)."""
    configured = repo_gates.hooks_path(target)
    path = Path(configured or ".githooks").expanduser()
    return (path if path.is_absolute() else target / path), not configured


def commit_msg_problem(target: Path, oc_root: Path) -> str:
    """Why the repo's commit-msg hook would not run or differs from the template, or "" when it is right."""
    template = repo_gates.hook_templates(oc_root) / "commit-msg"
    hooks, _ = hooks_dir_for(target)
    hook = hooks / "commit-msg"
    if not hook.is_file():
        return f"no commit-msg hook in {hooks}"
    if not hook.stat().st_mode & 0o111:
        return f"{hook} is not executable"
    return "" if hook.read_bytes() == template.read_bytes() else "commit-msg differs from the template"


def deploy_hook(hooks_dir: Path, templates_dir: Path, name: str) -> None:
    hooks_dir.mkdir(parents=True, exist_ok=True)
    dst = hooks_dir / name
    dst.write_bytes((templates_dir / name).read_bytes())
    dst.chmod(0o755)


def run_setup(target: Path, apply: bool, api: Api, oc_root: Path = OC_ROOT, out=print) -> int:
    """Plan, and with `apply` carry out, one repo's board setup. Returns the exit status."""
    try:
        return _run_setup(target, apply, api, oc_root, out)
    except SetupError as exc:
        out(f"backlog-setup stopped: {exc}")
        return 1


def _run_setup(target, apply, api, oc_root, out) -> int:
    target = Path(target).resolve()
    if not (target / ".git").exists():
        raise SetupError(f"{target} is not a git repository. Run git init and add an origin remote first.")
    slug = origin_owner_name(target)
    if not slug:
        raise SetupError(f"{target} has no origin remote, so the repo and its owner are unknown. "
                         "Add one with git remote add origin <url>.")
    owner, repo = slug
    baseline = kanban.load_baseline()
    cfg_path = config_path(target)
    rel_cfg = str(cfg_path.relative_to(target)) if cfg_path.is_relative_to(target) else str(cfg_path)
    config = load_config(cfg_path)
    inherited = ""
    if config and f"{config['repoOwner']}/{config['repoName']}".lower() != f"{owner}/{repo}".lower():
        inherited = f"{config['repoOwner']}/{config['repoName']}"
        config = None
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    changes: list[str] = []
    out(f"backlog-setup {'--apply' if apply else '(dry run)'} for {owner}/{repo}")
    if inherited:
        out(f"{rel_cfg} is {inherited}'s config, inherited from the repo this checkout came from. It is never read, "
            f"and {'it is replaced with' if apply else '--apply replaces it with'} {owner}/{repo}'s own.")
        changes.append(f"replace {inherited}'s inherited {rel_cfg} with {owner}/{repo}'s own")

    # 1. The Project
    board = None
    if config:
        board = read_board(api, config["projectId"])
        out(f"Project: {board['title']} (number {board['number']}, {len(board['items'])} item(s))")
    else:
        found = find_project(api, owner, repo)
        if found:
            board = read_board(api, found["id"])
            out(f"Project: none named in {rel_cfg}, so the existing '{found['title']}' (number {found['number']}, {len(board['items'])} item(s)) is used")
            if not apply:
                changes.append(f"write {rel_cfg} for the existing Project '{found['title']}' (number {found['number']})")
        else:
            changes.append(f"create the Project '{repo}' under {owner}")
            out(f"Project: none named in {rel_cfg}")
    if apply and board is None:
        board = _create_project(api, owner, repo, cfg_path, out)
        config = load_config(cfg_path)

    # 2. Fields
    plans = plan_board(board, baseline, config)
    field_lines = describe_plans(plans)
    needs_write = [p for p in plans if p["action"] != "ok"]
    changes += field_lines
    backup = None
    remap: dict[str, dict[str, str]] = {}
    if apply and needs_write:
        snapshot = snapshot_board(board, {"id": board["id"], "number": board["number"], "title": board["title"]},
                                  stamp)
        backup = write_snapshot(snapshot, target, stamp)
        out(f"Snapshot of {snapshot['itemCount']} item(s) saved to {backup}")
        for p in needs_write:
            if p["action"] == "update":
                update_field(api, p["field"]["id"], p["plan"]["final"])
                if p["plan"]["remap"]:
                    remap[p["key"]] = p["plan"]["remap"]
            else:
                create_field(api, board["id"], p["name"], p["plan"]["final"])
        after = read_board(api, board["id"])
        restored = restore_values(api, after, snapshot, remap)
        after = read_board(api, board["id"]) if restored else after
        mismatches = count_problems(after, snapshot, remap)
        if mismatches:
            restore_values(api, after, snapshot, remap)
            raise SetupError("item values do not match the snapshot after the change: " + "; ".join(mismatches)
                             + f". A restore was attempted. The snapshot is {backup}")
        out(f"Item values verified against the snapshot: {restored} restored, counts per option equal.")
        board = after

    # 3. Config
    if apply and board:
        wanted = config_from_board(board, owner, repo, config)
        if config != wanted:
            write_config(cfg_path, wanted)
            changes.append(f"write {rel_cfg} with the board's field and option IDs")
        config = wanted
    elif not board:
        changes.append(f"write {rel_cfg} with the new Project's field and option IDs")

    # 3b. Labels
    try:
        absent = board_api.missing_labels(api, f"{owner}/{repo}")
    except SetupError:
        absent = []
    if absent:
        changes.append("create the label" + ("s " if len(absent) > 1 else " ") + " and ".join(n for n, _, _ in absent))
        if apply:
            board_api.create_labels(api, f"{owner}/{repo}", absent)

    # 4. Hook
    hooks, unset = hooks_dir_for(target)
    if commit_msg_problem(target, oc_root):
        changes.append(f"install the story-reference commit-msg hook in {hooks}")
        if apply:
            deploy_hook(hooks, repo_gates.hook_templates(oc_root), "commit-msg")
    if unset:
        changes.append("set core.hooksPath to .githooks")
        if apply:
            done = subprocess.run(["git", "-C", str(target), "config", "core.hooksPath", ".githooks"], capture_output=True, text=True)
            if done.returncode != 0:
                raise SetupError(f"git could not set core.hooksPath: {done.stderr.strip()}. Run git -C {target} config core.hooksPath .githooks yourself.")
    # 5. Report
    verdict = 0
    if apply and board:
        problems = kanban.check_baseline(gh_field_list(board), baseline, config)
        if problems:
            verdict = 1
            out(f"The board is still {len(problems)} difference(s) from the baseline:")
            for p in problems:
                out(f"  - {p}")
        else:
            out("The board matches shared/kanban-baseline.json.")
    if changes:
        out(("Changed:" if apply else "Would change:"))
        for c in changes:
            out(f"  - {c}")
    else:
        out("Nothing to change. The repo is already set up.")
    out(kanban.NOT_VISIBLE)
    if apply and board:
        for line in workflow_steps(owner, board["number"]):
            out(line)
    if not apply and changes:
        out(f"Next: run `olivercode backlog-setup {target} --apply` to make these changes.")
    return verdict


def find_project(api: Api, owner: str, repo: str) -> dict | None:
    """The open Project the owner already has under the repo's name, or None. Two of them need the owner's choice."""
    data = api.graphql("query($o:String!,$t:String!){repositoryOwner(login:$o){... on ProjectV2Owner{"
                       "projectsV2(first:20,query:$t){nodes{id number title closed}}}}}", o=owner, t=repo)
    nodes = (((data.get("repositoryOwner") or {}).get("projectsV2") or {}).get("nodes")) or []
    same = [n for n in nodes if n and not n.get("closed") and n["title"].lower() == repo.lower()]
    if len(same) > 1:
        raise SetupError(f"{owner} has {len(same)} open Projects named '{repo}' (numbers {', '.join(str(n['number']) for n in same)}). "
                         "Copy shared/backlog-config.example.json to docs/backlog-config.json and set the right one.")
    return same[0] if same else None


def _create_project(api, owner, repo, cfg_path, out) -> dict:
    owner_id = (api.graphql("query($o:String!){repositoryOwner(login:$o){id}}", o=owner).get("repositoryOwner") or {}).get("id")
    if not owner_id:
        raise SetupError(f"GitHub owner {owner} was not found.")
    made = api.graphql("mutation($o:ID!,$t:String!){createProjectV2(input:{ownerId:$o,title:$t}){projectV2{id number title}}}",
                       o=owner_id, t=repo)["createProjectV2"]["projectV2"]
    out(f"Created Project '{made['title']}' (number {made['number']}).")
    # Write the config stub now, so a run that stops later finds this Project and creates no second one.
    write_config(cfg_path, config_from_board({"id": made["id"], "number": made["number"], "owner": owner, "fields": []}, owner, repo, None))
    repo_id = api.graphql("query($o:String!,$r:String!){repository(owner:$o,name:$r){id}}", o=owner, r=repo)["repository"]["id"]
    api.graphql("mutation($p:ID!,$r:ID!){linkProjectV2ToRepository(input:{projectId:$p,repositoryId:$r}){repository{id}}}",
                p=made["id"], r=repo_id)
    return read_board(api, made["id"])


def board_status(target: Path, api: Api, oc_root: Path = OC_ROOT) -> tuple[str, list[str]]:
    """('ok'|'fail'|'warn', problems) for one repo's board against the baseline."""
    slug = origin_owner_name(target)
    if slug is None:
        return "warn", ["board check skipped: the checkout has no origin remote, so there is no board to verify"]
    cfg_path = config_path(target)
    try:
        config = load_config(cfg_path)
    except SetupError as exc:
        return "fail", [str(exc)]
    if config is None:
        return "fail", [f"no usable backlog config at {cfg_path.relative_to(target) if cfg_path.is_relative_to(target) else cfg_path}"]
    if f"{config['repoOwner']}/{config['repoName']}".lower() != f"{slug[0]}/{slug[1]}".lower():
        return "fail", ["the backlog config names another repo's Project"]
    baseline = kanban.load_baseline()
    try:
        board = read_fields(api, config["projectId"])
    except SetupError as exc:
        return "warn", [f"board not read ({exc})"]
    problems = kanban.check_baseline(gh_field_list(board), baseline, config) + config_problems(config, board)
    return ("fail" if problems else "ok"), problems


def boards_health(repos: list[tuple[str, Path]], api: Api, oc_root: Path = OC_ROOT, out=print, check_hook: bool = True) -> tuple[int, int, int]:
    """Per repo: does its board match the baseline and, with `check_hook`, does it carry the commit-msg hook. Lists the fix. conform passes
    check_hook=False, because its hooks row already reports the hook."""
    passed = failed = skipped = 0
    seen: set[Path] = set()
    for name, path in repos:
        if Path(path).resolve() in seen:
            continue
        seen.add(Path(path).resolve())
        fix = FIX.format(path=path)
        status, problems = board_status(path, api, oc_root)
        hook = commit_msg_problem(path, oc_root) if check_hook else ""
        optout = (hooks_dir_for(path)[0] / "commit-msg.optout").exists()
        if status == "ok" and (not hook or optout):
            out(f"  [OK] {name}: board matches the baseline" + (", commit-msg hook present" if check_hook else ""))
            passed += 1
            continue
        if status == "warn" and not hook:
            out(f"  [WARN] {name}: {problems[0]}")
            skipped += 1
            continue
        detail = ([hook] if hook and not optout else []) + [p.split(". Fix:")[0] for p in problems]
        shown = "; ".join(detail[:4]) + (f"; and {len(detail) - 4} more" if len(detail) > 4 else "")
        out(f"  [FAIL] {name}: {shown}")
        out(f"         Fix: {fix}")
        failed += 1
    return passed, failed, skipped

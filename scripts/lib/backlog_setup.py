"""One repeatable setup and repair for a repo's GitHub Project board (story #55).

`olivercode backlog-setup [DIR] [--apply]` calls `run_setup`, and `olivercode health` calls
`boards_health`. The baseline itself lives once in `shared/kanban-baseline.json`, and the
comparison lives once in `skills/backlog/scripts/check_kanban_baseline.py`, which this module imports.

Every GitHub call goes through an injectable `Api`, so the unit tests run with a fake runner and no network.

Why the repair is safe: GitHub's `updateProjectV2Field` rewrites a single-select field's options. An option
sent with its `id` keeps that id and every item value that points at it. An option sent without one is
created new, and the items that pointed at the old option lose their value. A test against a live Project
showed both behaviors. The command therefore sends every existing option with its id, and still snapshots
every item first and verifies the per-option counts afterward, because that is the only protection against
a change in GitHub's behavior.
"""

from __future__ import annotations

import datetime
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

OC_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))
import check_kanban_baseline as kanban  # noqa: E402
import log_action  # noqa: E402

COLORS = ["GRAY", "BLUE", "GREEN", "YELLOW", "ORANGE", "RED", "PINK", "PURPLE"]
LANE_COLORS = {"backlog": "GRAY", "ready": "BLUE", "in progress": "YELLOW", "qa": "ORANGE", "complete": "GREEN"}
# GitHub's default Status field ships Todo, In Progress and Done. These carry their items to the baseline lanes.
DEFAULT_STATUS_MAP = {"todo": "Backlog", "done": "Complete"}
FIELD_KEYS = {"status": "status", "priority": "priority", "size": "size", "work type": "workType", "area": "area"}
BACKUP_DIR = Path("scratch") / "backlog-backups"
BATCH = 25
FIX = "olivercode backlog-setup {path} --apply"


class SetupError(Exception):
    """A step that cannot continue. The message says what happened and what to do."""


def field_key(name: str) -> str:
    key = FIELD_KEYS.get(name.lower())
    if key:
        return key
    words = re.split(r"\W+", name.strip())
    return words[0].lower() + "".join(w.title() for w in words[1:])


# --------------------------------------------------------------------------- GitHub access

def default_runner(args, stdin=None):
    p = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


class Api:
    """GraphQL through `gh api graphql`. `runner(args, stdin) -> (returncode, stdout, stderr)`."""

    def __init__(self, runner=None):
        self.runner = runner or default_runner
        self.calls = 0

    def graphql(self, query: str, **variables):
        args = ["api", "graphql", "-f", f"query={query}"]
        for name, value in variables.items():
            if value is None:
                continue
            args += ["-F" if isinstance(value, int) and not isinstance(value, bool) else "-f", f"{name}={value}"]
        self.calls += 1
        code, out, err = self.runner(args, None)
        try:
            data = json.loads(out) if out.strip() else {}
        except json.JSONDecodeError:
            data = {}
        text = " ".join([err or "", json.dumps(data.get("errors", "")) if isinstance(data, dict) else ""])
        if re.search(r"rate.?limit", text, re.IGNORECASE):
            raise SetupError("GitHub's GraphQL rate limit is reached. Nothing further was changed. "
                             "Wait for the hourly reset and run the same command again.")
        if isinstance(data, dict) and data.get("errors"):
            messages = "; ".join(e.get("message", str(e)) for e in data["errors"])
            raise SetupError(f"GitHub rejected a request: {messages}")
        if code != 0 or not isinstance(data, dict) or "data" not in data:
            raise SetupError(f"gh api graphql failed: {(err or out).strip() or 'no output'}")
        return data["data"]


# --------------------------------------------------------------------------- reading a board

FIELDS_QUERY = """query($p:ID!){node(id:$p){... on ProjectV2{id title number
 owner{... on User{login} ... on Organization{login}}
 fields(first:100){nodes{__typename ... on ProjectV2FieldCommon{id name dataType}
 ... on ProjectV2SingleSelectField{options{id name color description}}}}}}}"""

ITEMS_QUERY = """query($p:ID!,$c:String){node(id:$p){... on ProjectV2{items(first:100,after:$c){
 pageInfo{hasNextPage endCursor}
 nodes{id content{__typename ... on Issue{number title} ... on PullRequest{number title} ... on DraftIssue{title}}
 fieldValues(first:30){nodes{... on ProjectV2ItemFieldSingleSelectValue{optionId name field{... on ProjectV2FieldCommon{id name}}}}}}}}}}"""


def read_fields(api: Api, project_id: str) -> dict:
    node = api.graphql(FIELDS_QUERY, p=project_id).get("node")
    if not node or not node.get("id"):
        raise SetupError(f"Project {project_id} cannot be read. The backlog config names a Project that does not exist "
                         "or that this account cannot open.")
    fields = []
    for f in node["fields"]["nodes"]:
        if not f or "id" not in f:
            continue
        fields.append({"id": f["id"], "name": f["name"], "type": f["__typename"], "options": f.get("options") or []})
    return {"id": node["id"], "title": node["title"], "number": node["number"],
            "owner": (node.get("owner") or {}).get("login", ""), "fields": fields}


def read_items(api: Api, project_id: str) -> list[dict]:
    items, cursor = [], None
    while True:
        page = api.graphql(ITEMS_QUERY, p=project_id, c=cursor)["node"]["items"]
        for n in page["nodes"]:
            content = n.get("content") or {}
            values = {}
            for v in (n.get("fieldValues") or {}).get("nodes", []):
                if v and v.get("field"):
                    values[v["field"]["id"]] = {"optionId": v["optionId"], "name": v["name"]}
            items.append({"id": n["id"], "number": content.get("number"), "title": content.get("title", ""),
                          "values": values})
        if not page["pageInfo"]["hasNextPage"]:
            return items
        cursor = page["pageInfo"]["endCursor"]


def read_board(api: Api, project_id: str, with_items: bool = True) -> dict:
    board = read_fields(api, project_id)
    board["items"] = read_items(api, project_id) if with_items else []
    return board


def gh_field_list(board: dict) -> dict:
    """The board's fields in the shape `gh project field-list --format json` returns, for the baseline checker."""
    return {"fields": [{"name": f["name"], "type": f["type"], "options": [{"name": o["name"]} for o in f["options"]]}
                       for f in board["fields"]]}


def find_field(board: dict, name: str) -> dict | None:
    return next((f for f in board["fields"] if f["name"].lower() == name.lower()), None)


# --------------------------------------------------------------------------- planning

def desired_area(config: dict | None, extra: list[str] | None, target: Path) -> list[str]:
    """Area options for a new Area field: the config's, else --area, else the repo's skills folders and its
    areaPolicy names, else General."""
    existing = ((config or {}).get("fields", {}).get("area") or {}).get("options")
    if existing:
        return list(existing)
    if extra:
        return list(extra)
    names = []
    skills = target / "skills"
    if skills.is_dir():
        names += sorted(p.name for p in skills.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
    policy = (config or {}).get("areaPolicy", {})
    names += [n for n in policy.get("parked", []) + policy.get("catchAll", []) if n not in names]
    return names or ["General"]


def plan_options(existing: list[dict], desired: list[str], mapping: dict[str, str], patterns) -> dict:
    """Decide the final option list of one single-select field.

    Returns {final, added, renamed, dropped, extras, pr_lanes, remap}. `final` keeps the id of every option it
    carries over, which is what keeps item values attached. An existing option the baseline does not name is
    renamed or merged only when `mapping` says so (Status also applies GitHub's Todo and Done defaults),
    and otherwise stays and is reported."""
    by_lower = {o["name"].lower(): o for o in existing}
    wanted = {d.lower() for d in desired}
    claimed = {d.lower(): by_lower[d.lower()] for d in desired if d.lower() in by_lower}
    renamed, dropped, remap, extras = [], [], {}, []
    for o in existing:
        if o in claimed.values():
            continue
        target = mapping.get(o["name"].lower())
        if target and target.lower() in wanted:
            tl = target.lower()
            if tl in claimed:
                dropped.append(o["name"])
            else:
                claimed[tl] = o
                renamed.append((o["name"], next(d for d in desired if d.lower() == tl)))
            remap[o["name"]] = next(d for d in desired if d.lower() == tl)
        else:
            extras.append(o)
    final, added = [], []
    for i, d in enumerate(desired):
        o = claimed.get(d.lower())
        if o:
            final.append({"id": o["id"], "name": d, "color": o.get("color") or "GRAY", "description": o.get("description") or ""})
        else:
            added.append(d)
            final.append({"name": d, "color": LANE_COLORS.get(d.lower(), COLORS[i % len(COLORS)]), "description": ""})
    final += [{"id": o["id"], "name": o["name"], "color": o.get("color") or "GRAY", "description": o.get("description") or ""}
              for o in extras]
    pr_lanes = [o["name"] for o in extras if any(p.search(o["name"]) for p in patterns)]
    return {"final": final, "added": added, "renamed": renamed, "dropped": dropped,
            "extras": [o["name"] for o in extras], "pr_lanes": pr_lanes, "remap": remap}


def parse_map(pairs: list[str]) -> dict[str, str]:
    mapping = {}
    for pair in pairs or []:
        old, sep, new = pair.partition("=")
        if not sep or not old.strip() or not new.strip():
            raise SetupError(f"--map expects OLD=NEW, such as --map 'In Review=QA'. Got: {pair}")
        mapping[old.strip().lower()] = new.strip()
    return mapping


def plan_board(board: dict | None, baseline: dict, config: dict | None, target: Path,
               areas: list[str] | None = None, mapping: dict[str, str] | None = None) -> list[dict]:
    """One entry per baseline field: {name, key, action: create|update|ok, plan, field}."""
    mapping = mapping or {}
    patterns = [re.compile(p, re.IGNORECASE) for p in baseline["forbiddenLanePatterns"]]
    specs = [("Status", baseline["lanes"])]
    for name, wanted in baseline["fields"].items():
        specs.append((name, desired_area(config, areas, target) if wanted == "config" else wanted))
    plans = []
    for name, desired in specs:
        field = find_field(board, name) if board else None
        key = field_key(name)
        if field is None or field["type"] != kanban.SINGLE_SELECT:
            plans.append({"name": name, "key": key, "action": "create", "field": None,
                          "plan": plan_options([], desired, {}, patterns)})
            continue
        field_map = dict(DEFAULT_STATUS_MAP) if key == "status" else {}
        field_map.update(mapping)
        plan = plan_options(field["options"], desired, field_map, patterns)
        # An extra option stays only when it is unmapped; one that is mapped but whose target is not a
        # baseline option for this field is also reported by the checker, not silently moved.
        changed = plan["added"] or plan["renamed"] or plan["dropped"]
        plans.append({"name": field["name"], "key": key, "action": "update" if changed else "ok",
                      "field": field, "plan": plan})
    return plans


def describe_plans(plans: list[dict]) -> list[str]:
    lines = []
    for p in plans:
        pl = p["plan"]
        if p["action"] == "create":
            lines.append(f"create field {p['name']} with options {', '.join(o['name'] for o in pl['final'])}")
        elif p["action"] == "update":
            bits = []
            if pl["added"]:
                bits.append("add " + ", ".join(pl["added"]))
            bits += [f"rename {a} to {b}" for a, b in pl["renamed"]]
            if pl["dropped"]:
                bits.append("merge " + ", ".join(f"{d} into {pl['remap'][d]}" for d in pl["dropped"]))
            lines.append(f"update field {p['name']}: " + "; ".join(bits))
        for lane in (pl["pr_lanes"] if p["key"] == "status" else []):
            lines.append(f"{p['name']}: lane {lane} is driven by pull requests and stays until its items are moved. "
                         f"Fix: rerun with --map '{lane}=In Progress' (or QA) to move them and drop the lane")
        other = [e for e in pl["extras"] if e not in pl["pr_lanes"]]
        if other and p["key"] != "area":
            lines.append(f"{p['name']}: option(s) {', '.join(other)} are outside the baseline and stay. "
                         "Fix: rerun with --map 'OLD=NEW' to merge one into a baseline option")
    return lines


# --------------------------------------------------------------------------- snapshot, restore, verify

def snapshot_board(board: dict, project: dict, taken: str) -> dict:
    keys = {f["id"]: field_key(f["name"]) for f in board["fields"]
            if f["type"] == kanban.SINGLE_SELECT and field_key(f["name"]) in set(FIELD_KEYS.values())}
    items = []
    for it in board["items"]:
        items.append({"id": it["id"], "number": it["number"], "title": it["title"],
                      "values": {keys[fid]: v for fid, v in it["values"].items() if fid in keys}})
    counts: dict[str, dict[str, int]] = {}
    for it in items:
        for key, v in it["values"].items():
            counts.setdefault(key, {})
            counts[key][v["name"]] = counts[key].get(v["name"], 0) + 1
    return {"taken": taken, "project": project, "itemCount": len(items), "counts": counts, "items": items}


def write_snapshot(snapshot: dict, target: Path, stamp: str) -> Path:
    path = target / BACKUP_DIR / f"backlog-snapshot-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return path


def current_values(board: dict) -> dict[str, dict[str, str]]:
    keys = {f["id"]: field_key(f["name"]) for f in board["fields"] if f["type"] == kanban.SINGLE_SELECT}
    return {it["id"]: {keys[fid]: v["name"] for fid, v in it["values"].items() if fid in keys} for it in board["items"]}


def expected_name(remap: dict[str, dict[str, str]], key: str, name: str) -> str:
    return remap.get(key, {}).get(name, name)


def restore_values(api: Api, board: dict, snapshot: dict, remap: dict[str, dict[str, str]]) -> int:
    """Set back every tracked value that differs from the snapshot (after the remap). Returns how many were set."""
    now = current_values(board)
    fields = {field_key(f["name"]): f for f in board["fields"] if f["type"] == kanban.SINGLE_SELECT}
    todo = []
    for it in snapshot["items"]:
        if it["id"] not in now:
            continue
        for key, v in it["values"].items():
            want = expected_name(remap, key, v["name"])
            if (now[it["id"]].get(key) or "").lower() == want.lower() or key not in fields:
                continue
            option = next((o for o in fields[key]["options"] if o["name"].lower() == want.lower()), None)
            if option is None:
                raise SetupError(f"Cannot restore {key} {want} on {it['title'] or it['id']}: the option no longer exists. "
                                 "The snapshot file holds every original value.")
            todo.append((it["id"], fields[key]["id"], option["id"]))
    for start in range(0, len(todo), BATCH):
        chunk = todo[start:start + BATCH]
        body = " ".join(
            f'm{i}: updateProjectV2ItemFieldValue(input:{{projectId:{json.dumps(board["id"])},itemId:{json.dumps(item)},'
            f'fieldId:{json.dumps(field)},value:{{singleSelectOptionId:{json.dumps(opt)}}}}}){{projectV2Item{{id}}}}'
            for i, (item, field, opt) in enumerate(chunk))
        api.graphql("mutation{" + body + "}")
    return len(todo)


def count_problems(board: dict, snapshot: dict, remap: dict[str, dict[str, str]]) -> list[str]:
    """Per-option counts after the change against the snapshot's counts, carried through the remap."""
    expected: dict[str, dict[str, int]] = {}
    for key, counts in snapshot["counts"].items():
        for name, n in counts.items():
            target = expected_name(remap, key, name).lower()
            expected.setdefault(key, {})
            expected[key][target] = expected[key].get(target, 0) + n
    ids = {it["id"] for it in snapshot["items"]}
    now = current_values(board)
    actual: dict[str, dict[str, int]] = {}
    for item_id, values in now.items():
        if item_id not in ids:
            continue
        for key, name in values.items():
            if key in expected:
                actual.setdefault(key, {})
                actual[key][name.lower()] = actual[key].get(name.lower(), 0) + 1
    problems = []
    for key, counts in expected.items():
        for name in sorted(set(counts) | set(actual.get(key, {}))):
            if counts.get(name, 0) != actual.get(key, {}).get(name, 0):
                problems.append(f"{key} {name}: snapshot {counts.get(name, 0)}, board {actual.get(key, {}).get(name, 0)}")
    return problems


# --------------------------------------------------------------------------- writing fields

def _option_literal(o: dict) -> str:
    color = o.get("color") if o.get("color") in COLORS else "GRAY"
    parts = ([f"id:{json.dumps(o['id'])}"] if o.get("id") else [])
    parts += [f"name:{json.dumps(o['name'])}", f"color:{color}", f"description:{json.dumps(o.get('description') or '')}"]
    return "{" + ",".join(parts) + "}"


def update_field(api: Api, field_id: str, options: list[dict]) -> None:
    api.graphql("mutation{updateProjectV2Field(input:{fieldId:%s,singleSelectOptions:[%s]}){projectV2Field{"
                "... on ProjectV2SingleSelectField{id}}}}" % (json.dumps(field_id), ",".join(_option_literal(o) for o in options)))


def create_field(api: Api, project_id: str, name: str, options: list[dict]) -> None:
    api.graphql("mutation{createProjectV2Field(input:{projectId:%s,dataType:SINGLE_SELECT,name:%s,singleSelectOptions:[%s]}){"
                "projectV2Field{... on ProjectV2SingleSelectField{id}}}}"
                % (json.dumps(project_id), json.dumps(name), ",".join(_option_literal({**o, "id": None}) for o in options)))


# --------------------------------------------------------------------------- the repo side

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
            return target / next((n for n in names if "/" in n), names[0])
    return target / "docs" / "backlog-config.json"


def load_config(path: Path) -> dict | None:
    """The repo's config, or None when it is absent or still the example's placeholders."""
    if not path.is_file():
        return None
    config = json.loads(path.read_text(encoding="utf-8"))
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
        for name in ids:
            if name not in (entry.get("options") or {}):
                problems.append(f"{key}: board option {name} is missing from the config")
    return problems


def write_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


STORY_RULE = re.compile(r"(filed|saved) as a story", re.IGNORECASE)


def story_rule_line(oc_root: Path) -> str:
    for line in (oc_root / "core" / "templates" / "project" / "CLAUDE.md").read_text(encoding="utf-8").splitlines():
        if STORY_RULE.search(line):
            return line
    raise SetupError("The project template's CLAUDE.md carries no story rule to copy.")


def claude_md_additions(target: Path, oc_root: Path, rel_config: str) -> tuple[str, list[str]]:
    """The CLAUDE.md text after the story rule and the config pointer are in place, and what was added."""
    path = target / "CLAUDE.md"
    if not path.is_file():
        return (oc_root / "core" / "templates" / "project" / "CLAUDE.md").read_text(encoding="utf-8"), ["create CLAUDE.md from the template"]
    text, added = path.read_text(encoding="utf-8"), []
    bullets = []
    if "backlog-config.json" not in text:
        bullets.append(f"- Open work lives in the GitHub Project that `{rel_config}` names, per the `backlog` skill")
        added.append("name the backlog config")
    if not STORY_RULE.search(text):
        bullets.append(story_rule_line(oc_root))
        added.append("add the story rule")
    if not bullets:
        return text, []
    if not re.search(r"^Rules:\s*$", text, re.MULTILINE):
        text = text.rstrip("\n") + "\n\nRules:\n"
    else:
        text = text.rstrip("\n") + "\n"
    return text + "\n".join(bullets) + "\n", added


def hooks_dir_for(target: Path) -> tuple[Path, bool]:
    """(the folder git reads hooks from, whether core.hooksPath is unset)."""
    p = subprocess.run(["git", "-C", str(target), "config", "--get", "core.hooksPath"], capture_output=True, text=True)
    configured = p.stdout.strip()
    if not configured:
        return target / ".githooks", True
    path = Path(configured).expanduser()
    return (path if path.is_absolute() else target / path), False


def commit_msg_problem(target: Path, oc_root: Path) -> str:
    """Why the repo's commit-msg hook would not run or differs from the template, or "" when it is right."""
    template = oc_root / "core" / "templates" / "project" / "commit-msg"
    hooks, _ = hooks_dir_for(target)
    hook = hooks / "commit-msg"
    if not hook.is_file():
        return f"no commit-msg hook in {hooks}"
    if not hook.stat().st_mode & 0o111:
        return f"{hook} is not executable"
    if hook.read_bytes() != template.read_bytes():
        return "commit-msg differs from the template"
    return ""


def deploy_hook(hooks_dir: Path, templates_dir: Path, name: str) -> None:
    hooks_dir.mkdir(parents=True, exist_ok=True)
    dst = hooks_dir / name
    dst.write_bytes((templates_dir / name).read_bytes())
    dst.chmod(0o755)


# --------------------------------------------------------------------------- the command

def run_setup(target: Path, apply: bool, api: Api, oc_root: Path = OC_ROOT, out=print, title: str | None = None,
              areas: list[str] | None = None, maps: list[str] | None = None, link: bool = True,
              now: datetime.datetime | None = None, story: int | None = None, agent: str = "backlog-setup") -> int:
    """Plan, and with `apply` carry out, one repo's board setup. Returns the exit status."""
    try:
        return _run_setup(target, apply, api, oc_root, out, title, areas, maps, link, now, story, agent)
    except SetupError as exc:
        out(f"backlog-setup stopped: {exc}")
        return 1


def _run_setup(target, apply, api, oc_root, out, title, areas, maps, link, now, story=None, agent="backlog-setup") -> int:
    target = Path(target).resolve()
    if not (target / ".git").exists():
        raise SetupError(f"{target} is not a git repository. Run git init and add an origin remote first.")
    slug = origin_owner_name(target)
    if not slug:
        raise SetupError(f"{target} has no origin remote, so the repo and its owner are unknown. "
                         "Add one with git remote add origin <url>.")
    owner, repo = slug
    baseline = kanban.load_baseline()
    mapping = parse_map(maps)
    cfg_path = config_path(target)
    rel_cfg = str(cfg_path.relative_to(target)) if cfg_path.is_relative_to(target) else str(cfg_path)
    config = load_config(cfg_path)
    if config and f"{config['repoOwner']}/{config['repoName']}".lower() != f"{owner}/{repo}".lower():
        raise SetupError(f"{rel_cfg} names {config['repoOwner']}/{config['repoName']}'s Project but this checkout's origin is "
                         f"{owner}/{repo}. That is another repo's config, so nothing was read or written. Delete it or "
                         "copy shared/backlog-config.example.json over it.")
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    changes: list[str] = []
    out(f"backlog-setup {'--apply' if apply else '(dry run)'} for {owner}/{repo}")

    # 1. The Project
    board = None
    if config:
        board = read_board(api, config["projectId"])
        out(f"Project: {board['title']} (number {board['number']}, {len(board['items'])} item(s))")
    else:
        changes.append(f"create the Project '{title or repo}' under {owner}")
        out(f"Project: none named in {rel_cfg}")
    if apply and board is None:
        board = _create_project(api, owner, repo, title or repo, link, cfg_path, config, out)
        config = load_config(cfg_path)
        changes[0] += " (done)"

    # 2. Fields
    plans = plan_board(board, baseline, config, target, areas, mapping)
    field_lines = describe_plans(plans)
    needs_write = [p for p in plans if p["action"] != "ok"]
    unresolved = [line for line in field_lines if "Fix: rerun" in line]
    changes += [line for line in field_lines if "Fix: rerun" not in line]
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
        problems = config_problems(json.loads(cfg_path.read_text(encoding="utf-8")), board)
        if problems:
            raise SetupError(f"{rel_cfg} does not match the board after writing: " + "; ".join(problems))
        config = wanted
    elif board and config:
        wanted = config_from_board(board, owner, repo, config)
        if config != wanted or needs_write:
            changes.append(f"update {rel_cfg} to the board's current IDs")
    elif not board:
        changes.append(f"write {rel_cfg} with the new Project's field and option IDs")

    # 4. Hook, CLAUDE.md, scratch ignore
    hooks, unset = hooks_dir_for(target)
    templates = oc_root / "core" / "templates" / "project"
    if commit_msg_problem(target, oc_root):
        changes.append(f"install the story-reference commit-msg hook in {hooks.relative_to(target) if hooks.is_relative_to(target) else hooks}")
        if apply:
            deploy_hook(hooks, templates, "commit-msg")
    if unset:
        changes.append("set core.hooksPath to .githooks")
        if apply:
            subprocess.run(["git", "-C", str(target), "config", "core.hooksPath", ".githooks"], check=True)
    new_text, added = claude_md_additions(target, oc_root, rel_cfg)
    if added:
        changes.append("CLAUDE.md: " + ", ".join(added))
        if apply:
            (target / "CLAUDE.md").write_text(new_text, encoding="utf-8")
    ignore = target / ".gitignore"
    ignore_text = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    if not re.search(r"^/?scratch/?\s*$", ignore_text, re.MULTILINE):
        changes.append("ignore scratch/ in .gitignore so snapshots stay local")
        if apply:
            ignore.write_text(ignore_text + ("" if not ignore_text or ignore_text.endswith("\n") else "\n") + "scratch/\n", encoding="utf-8")

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
    for line in unresolved:
        out(f"  - {line}")
    if changes:
        out(("Changed:" if apply else "Would change:"))
        for c in changes:
            out(f"  - {c}")
    else:
        out("Nothing to change. The repo is already set up.")
    out(kanban.NOT_VISIBLE)
    if not apply and (changes or unresolved):
        out(f"Next: run `olivercode backlog-setup {target} --apply` to make these changes.")
    code = 1 if (verdict or (apply and unresolved)) else 0
    if apply and changes and code == 0:
        code = _log_repair(api, target, f"{owner}/{repo}", cfg_path, changes, board, story, agent, out)
    return code


def _repair_summary(changes: list[str], board: dict | None) -> str:
    """The one-line result for the story comment."""
    kept = len((board or {}).get("items", []))
    head = f"Repaired board: {len(changes)} change(s), {kept} items kept. "
    detail = "; ".join(" ".join(c.split()) for c in changes)
    room = 300 - len(head)
    return head + (detail if len(detail) <= room else detail[:room - 3] + "...")


def _log_repair(api, target, slug, cfg_path, changes, board, story, agent, out) -> int:
    """Post the repair on its story, or print the log_action.py line that does. Returns the exit status."""
    done = subprocess.run(["git", "-C", str(target), "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True)
    commit = done.stdout.strip() if done.returncode == 0 else ""
    if not log_action.HASH.match(commit):
        out("The repair was not logged on a story because the repo has no commit to name. "
            "Commit once, then run log_action.py with that hash.")
        return 0
    result = _repair_summary(changes, board)
    line = ("python3 skills/backlog/scripts/log_action.py --config " + shlex.quote(str(cfg_path))
            + f" --story {story if story else 'N'} --agent {shlex.quote(agent)} --role builder --commit {commit}"
            + f" --files {len(changes)} --result {shlex.quote(result)}")
    if story is None:
        out("Log this repair on its story from the OliverCode repo (replace N with the story number), or rerun with --story N:")
        out(line)
        return 0

    def runner(args):
        code, stdout, stderr = api.runner(["api"] + args, None)
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)

    body = log_action.build_comment(agent, "builder", commit, len(changes), result)
    try:
        url = log_action.post_comment(slug, story, body, runner)
    except RuntimeError as exc:
        out(f"The repair is done, but the comment on {slug}#{story} was not posted: {exc}. Run:")
        out(line)
        return 1
    out(f"Logged on {slug}#{story}: {url}")
    return 0


def _create_project(api, owner, repo, title, link, cfg_path, config, out) -> dict:
    owner_id = (api.graphql("query($o:String!){repositoryOwner(login:$o){id}}", o=owner).get("repositoryOwner") or {}).get("id")
    if not owner_id:
        raise SetupError(f"GitHub owner {owner} was not found.")
    made = api.graphql("mutation($o:ID!,$t:String!){createProjectV2(input:{ownerId:$o,title:$t}){projectV2{id number title}}}",
                       o=owner_id, t=title)["createProjectV2"]["projectV2"]
    out(f"Created Project '{made['title']}' (number {made['number']}).")
    # Write the config stub now, so a run that stops later finds this Project and creates no second one.
    write_config(cfg_path, config_from_board({"id": made["id"], "number": made["number"], "owner": owner, "fields": []}, owner, repo, None))
    if link:
        try:
            repo_id = api.graphql("query($o:String!,$r:String!){repository(owner:$o,name:$r){id}}", o=owner, r=repo)["repository"]["id"]
            api.graphql("mutation($p:ID!,$r:ID!){linkProjectV2ToRepository(input:{projectId:$p,repositoryId:$r}){repository{id}}}",
                        p=made["id"], r=repo_id)
        except (SetupError, TypeError) as exc:
            out(f"  The Project was not linked to the repo: {exc}")
    return read_board(api, made["id"])


# --------------------------------------------------------------------------- fleet health

def board_status(target: Path, api: Api, oc_root: Path = OC_ROOT) -> tuple[str, list[str]]:
    """('ok'|'fail'|'warn', problems) for one repo's board against the baseline."""
    slug = origin_owner_name(target)
    if slug is None:
        return "warn", ["board check skipped: the checkout has no origin remote, so there is no board to verify"]
    cfg_path = config_path(target)
    config = load_config(cfg_path)
    if config is None:
        return "fail", [f"no usable backlog config at {cfg_path.relative_to(target) if cfg_path.is_relative_to(target) else cfg_path}"]
    if f"{config['repoOwner']}/{config['repoName']}".lower() != f"{slug[0]}/{slug[1]}".lower():
        return "fail", ["the backlog config names another repo's Project"]
    baseline = kanban.load_baseline()
    try:
        board = read_fields(api, config["projectId"])
    except SetupError as exc:
        # The board cannot be read. Compare what the config alone shows.
        stub = {"fields": [{"name": {"workType": "Work type"}.get(k, k.title()), "type": kanban.SINGLE_SELECT,
                            "options": [{"name": n} for n in v.get("options", {})]}
                           for k, v in config.get("fields", {}).items()]}
        problems = kanban.check_baseline(stub, baseline, config)
        if problems:
            return "fail", [f"board not read ({exc})"] + problems
        return "warn", [f"board not read ({exc}); the config alone matches the baseline"]
    problems = kanban.check_baseline(gh_field_list(board), baseline, config) + config_problems(config, board)
    return ("fail" if problems else "ok"), problems


def boards_health(repos: list[tuple[str, Path]], api: Api, oc_root: Path = OC_ROOT, out=print) -> tuple[int, int, int]:
    """Per repo: does its board match the baseline and does it carry the commit-msg hook. Lists the fix."""
    passed = failed = skipped = 0
    seen: set[Path] = set()
    for name, path in repos:
        if Path(path).resolve() in seen:
            continue
        seen.add(Path(path).resolve())
        fix = FIX.format(path=path)
        status, problems = board_status(path, api, oc_root)
        hook = commit_msg_problem(path, oc_root)
        optout = (path / ".githooks" / "commit-msg.optout").exists()
        if status == "ok" and (not hook or optout):
            out(f"  [OK] {name}: board matches the baseline, commit-msg hook present")
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

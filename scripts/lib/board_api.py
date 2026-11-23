"""The GitHub Project side of `olivercode backlog-setup`: GraphQL reads of a board, the plan that brings its
fields to the baseline, the item snapshot, the value restore and count check, and the field writes.

`lib/backlog_setup.py` runs the command and imports these. Every call goes through an injectable `Api`, so the
unit tests run with a fake runner and no network.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

from lib.local_config import OC_ROOT
sys.path.insert(0, str(OC_ROOT / "skills" / "backlog" / "scripts"))
import check_kanban_baseline as kanban  # noqa: E402

COLORS = ["GRAY", "BLUE", "GREEN", "YELLOW", "ORANGE", "RED", "PINK", "PURPLE"]
LANE_COLORS = {"backlog": "GRAY", "ready": "BLUE", "in progress": "YELLOW", "qa": "ORANGE", "complete": "GREEN"}
# GitHub's default Status field ships Todo, In Progress and Done. These carry their items to the baseline lanes.
DEFAULT_STATUS_MAP = {"todo": "Backlog", "done": "Complete"}
FIELD_KEYS = {"status": "status", "priority": "priority", "size": "size", "work type": "workType", "area": "area"}
BATCH = 25


class SetupError(Exception):
    """A step that cannot continue. The message says what happened and what to do."""


def field_key(name: str) -> str:
    key = FIELD_KEYS.get(name.lower())
    if key:
        return key
    words = re.split(r"\W+", name.strip())
    return words[0].lower() + "".join(w.title() for w in words[1:])


def default_runner(args, stdin=None):
    p = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


class Api:
    """GraphQL through `gh api graphql`. `runner(args, stdin) -> (returncode, stdout, stderr)`."""

    def __init__(self, runner=None):
        self.runner = runner or default_runner

    def graphql(self, query: str, **variables):
        args = ["api", "graphql", "-f", f"query={query}"]
        for name, value in variables.items():
            if value is None:
                continue
            args += ["-F" if isinstance(value, int) and not isinstance(value, bool) else "-f", f"{name}={value}"]
        code, out, err = self.runner(args, None)
        try:
            data = json.loads(out) if out.strip() else {}
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict) and data.get("errors"):
            messages = "; ".join(e.get("message", str(e)) for e in data["errors"])
            raise SetupError(f"GitHub rejected a request: {messages}")
        if code != 0 or not isinstance(data, dict) or "data" not in data:
            raise SetupError(f"gh api graphql failed: {(err or out).strip() or 'no output'}")
        return data["data"]


# The labels the backlog skill and the audit's done check read: an issue only the owner can do, and one a fleet program tracks elsewhere (#687).
LABELS = (("owner-action", "D93F0B", "Only the owner can do this: an account sign-in, a device, a purchase or a decision"),
          ("program", "5319E7", "Tracked by a fleet program on its own epic, outside this repo's audit"))


def missing_labels(api: Api, slug: str) -> list[tuple[str, str, str]]:
    """The LABELS this repo lacks. An unreadable list counts every label as missing, and creating one with --force is harmless."""
    code, out, _ = api.runner(["label", "list", "--repo", slug, "--limit", "200", "--json", "name"], None)
    try:
        have = {str(l.get("name", "")).lower() for l in json.loads(out)} if code == 0 else set()
    except (ValueError, AttributeError):
        have = set()
    return [l for l in LABELS if l[0] not in have]


def create_labels(api: Api, slug: str, labels) -> None:
    for name, color, description in labels:
        code, out, err = api.runner(["label", "create", name, "--repo", slug, "--color", color, "--description", description, "--force"], None)
        if code != 0:
            raise SetupError(f"gh could not create the label {name} in {slug}: {(err or out).strip() or 'no output'}")


FIELDS_QUERY = """query($p:ID!){node(id:$p){... on ProjectV2{id title number
 owner{... on User{login} ... on Organization{login}}
 fields(first:100){nodes{__typename ... on ProjectV2FieldCommon{id name}
 ... on ProjectV2SingleSelectField{options{id name color description}}}}}}}"""

WORKFLOWS_QUERY = """query($p:ID!){node(id:$p){... on ProjectV2{workflows(first:50){nodes{name enabled}}}}}"""

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


def read_workflows(api: Api, project_id: str) -> dict[str, bool] | None:
    """{workflow name: enabled} for a Project, or None when GitHub does not let this account read them."""
    try:
        node = api.graphql(WORKFLOWS_QUERY, p=project_id).get("node")
    except SetupError:
        return None
    if not node or "workflows" not in node:
        return None
    return {w["name"]: bool(w["enabled"]) for w in node["workflows"]["nodes"] if w}


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


def read_board(api: Api, project_id: str) -> dict:
    board = read_fields(api, project_id)
    board["items"] = read_items(api, project_id)
    return board


def gh_field_list(board: dict) -> dict:
    """The board's fields in the shape `gh project field-list --format json` returns, for the baseline checker."""
    return {"fields": [{"name": f["name"], "type": f["type"], "options": [{"name": o["name"]} for o in f["options"]]}
                       for f in board["fields"]]}


def find_field(board: dict, name: str) -> dict | None:
    return next((f for f in board["fields"] if f["name"].lower() == name.lower()), None)


def plan_options(existing: list[dict], desired: list[str], mapping: dict[str, str]) -> dict:
    """Decide the final option list of one single-select field.

    Returns {final, added, renamed, dropped, remap}. `final` keeps the id of every option it
    carries over, which is what keeps item values attached. An existing option the baseline does not name is
    renamed or merged only for Status, through GitHub's Todo and Done defaults, and otherwise stays and is
    reported by the baseline check."""
    names = {d.lower(): d for d in desired}
    claimed = {o["name"].lower(): o for o in existing if o["name"].lower() in names}
    renamed, dropped, remap, extras = [], [], {}, []
    for o in existing:
        if o["name"].lower() in names:
            continue
        tl = (mapping.get(o["name"].lower()) or "").lower()
        if tl not in names:
            extras.append(o)
            continue
        remap[o["name"]] = names[tl]
        if tl in claimed:
            dropped.append(o["name"])
        else:
            claimed[tl] = o
            renamed.append((o["name"], names[tl]))
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
    return {"final": final, "added": added, "renamed": renamed, "dropped": dropped, "remap": remap}


def plan_board(board: dict | None, baseline: dict, config: dict | None) -> list[dict]:
    """One entry per baseline field: {name, key, action: create|update|ok, plan, field}."""
    specs = [("Status", baseline["lanes"])]
    for name, wanted in baseline["fields"].items():
        specs.append((name, list(((config or {}).get("fields", {}).get("area") or {}).get("options") or ["General"]) if wanted == "config" else wanted))
    plans = []
    for name, desired in specs:
        field = find_field(board, name) if board else None
        key = field_key(name)
        if field is None or field["type"] != kanban.SINGLE_SELECT:
            plans.append({"name": name, "key": key, "action": "create", "field": None,
                          "plan": plan_options([], desired, {})})
            continue
        field_map = DEFAULT_STATUS_MAP if key == "status" else {}
        plan = plan_options(field["options"], desired, field_map)
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
            bits = ["add " + o for o in pl["added"]] + [f"rename {a} to {b}" for a, b in pl["renamed"]]
            bits += [f"merge {d} into {pl['remap'][d]}" for d in pl["dropped"]]
            lines.append(f"update field {p['name']}: " + "; ".join(bits))
    return lines


def snapshot_board(board: dict, project: dict, taken: str) -> dict:
    keys = {f["id"]: field_key(f["name"]) for f in board["fields"]
            if f["type"] == kanban.SINGLE_SELECT and field_key(f["name"]) in set(FIELD_KEYS.values())}
    items = [{"id": it["id"], "number": it["number"], "title": it["title"],
              "values": {keys[fid]: v for fid, v in it["values"].items() if fid in keys}} for it in board["items"]]
    counts: dict[str, dict[str, int]] = {}
    for it in items:
        for key, v in it["values"].items():
            by_name = counts.setdefault(key, {})
            by_name[v["name"]] = by_name.get(v["name"], 0) + 1
    return {"taken": taken, "project": project, "itemCount": len(items), "counts": counts, "items": items}


def current_values(board: dict) -> dict[str, dict[str, str]]:
    keys = {f["id"]: field_key(f["name"]) for f in board["fields"] if f["type"] == kanban.SINGLE_SELECT}
    return {it["id"]: {keys[fid]: v["name"] for fid, v in it["values"].items() if fid in keys} for it in board["items"]}


def restore_values(api: Api, board: dict, snapshot: dict, remap: dict[str, dict[str, str]]) -> int:
    """Set back every tracked value that differs from the snapshot (after the remap). Returns how many were set."""
    now = current_values(board)
    fields = {field_key(f["name"]): f for f in board["fields"] if f["type"] == kanban.SINGLE_SELECT}
    todo = []
    for it in snapshot["items"]:
        if it["id"] not in now:
            continue
        for key, v in it["values"].items():
            want = remap.get(key, {}).get(v["name"], v["name"])
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
            target = remap.get(key, {}).get(name, name).lower()
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

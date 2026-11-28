#!/usr/bin/env python3
"""Close a story or epic: check its builder entry or sub-issues, then move it to Complete, comment the evidence and close it.

Usage: complete_story.py --story N --config CONFIG --evidence TEXT
A story needs a builder entry and every builder commit on origin/main. An epic (an issue with sub-issues) needs no
builder entry: every sub-issue closed, at least one as completed, each other one named in TEXT, and run output in TEXT.
An open sub-issue, or a run output line starting `FAILED (`, refuses any close. On a refusal it prints the reason and
changes nothing. On success it finds the story's project item through the REST items list, posts TEXT as a
comment and closes the issue through REST, then sets Status to Complete by the config's ids and archives the card (the only GraphQL
calls, queued for the reset replay while GraphQL is held). A story in the OliverCode repo also closes only
once the installed checkout at $OC holds its commits (live_check, run after `olivercode update` when the checkout is
behind) and the hook entry or launchd job the story's files define or schedule is loaded; the evidence comment names that proof.
Exits 0 when all three writes succeeded or queued, 1 on a refusal or a
failed call, 2 on a usage error.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import board_mirror  # noqa: E402
import gh_budget  # noqa: E402
import repo_name_guard  # noqa: E402
from lib import rename_check  # noqa: E402
from lib import claude_settings  # noqa: E402
from lib import main_checkout  # noqa: E402
from log_action import commit_pushed, gh_api  # noqa: E402  one gh runner for the backlog scripts

ITEM_JQ = '.[] | select(.content.number != null) | {number: .content.number, id: .node_id, repo: (.content.repository_url // "")}'
MOVE = ("mutation($p:ID!,$i:ID!,$f:ID!,$v:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,"
        "itemId:$i,fieldId:$f,value:{singleSelectOptionId:$v}}){projectV2Item{id}}}")
ARCHIVE = ("mutation($p:ID!,$i:ID!){archiveProjectV2Item(input:{projectId:$p,itemId:$i}){item{id}}}")
COMMIT = re.compile(r"^\s*-?\s*Commit:\s*([0-9a-f]{7,40})\b", re.M)
CLOSE_MARKER = "Closed by complete_story.py."  # the last line of the evidence comment complete_story.py posts (#836)


def parse_action(body):
    """Return (agent, role, result) from an agent-action comment, or None for any other comment."""
    if not body.lstrip().startswith("Agent action"):
        return None
    fields = {k.lower(): v for k, v in re.findall(r"^\s*-?\s*(Agent|Role|Result):\s*(.*?)\s*$", body, re.M)}
    if "agent" not in fields or "role" not in fields:
        return None
    return fields["agent"], fields["role"].lower(), fields.get("result", "")


def builder_commits(bodies):
    """The commits named by the builder entries, in order."""
    found = []
    for body in bodies:
        action = parse_action(body)
        match = COMMIT.search(body)
        if action and action[1] == "builder" and match:
            found.append(match.group(1))
    return found


def closed_by_script(data) -> bool:
    """True when a comment ends with the marker line itself. A quote or a mention of it does not count (#853)."""
    return any(b.rstrip().splitlines()[-1:] == [CLOSE_MARKER] for b in flatten(data))


def flatten(data):
    """Accept a list of comments or a list of pages and return the comment bodies in order."""
    bodies = []
    for item in data:
        if isinstance(item, list):
            bodies.extend(flatten(item))
        elif isinstance(item, dict) and isinstance(item.get("body"), str):
            bodies.append(item["body"])
    return bodies


def fetch(repo, story, runner):
    """The story's comments and body, read through REST. Raises RuntimeError on a failed read."""
    comments = runner(["--paginate", "--slurp", f"repos/{repo}/issues/{story}/comments"])
    issue = runner([f"repos/{repo}/issues/{story}", "--jq", ".body"])
    for result in (comments, issue):
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "gh api failed").strip())
    return json.loads(comments.stdout or "[]"), issue.stdout


def sub_issues(repo, story, runner):
    """The story's sub-issues, read through REST: empty for a story that is no epic. Raises RuntimeError on a failed read."""
    text = call(runner, ["--paginate", f"repos/{repo}/issues/{story}/sub_issues?per_page=100", "--jq", ".[] | {number, state, state_reason}"])
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def epic_refusal(subs, evidence):
    """Why closed sub-issues do not close an epic that has no builder entry, or None when they do (#1568)."""
    if not any(s["state_reason"] == "completed" for s in subs):
        return "it has no builder entry and no sub-issue closed as completed"
    unnamed = [f"#{s['number']}" for s in subs if s["state_reason"] != "completed" and not re.search(rf"#{s['number']}(?!\d)", evidence)]
    if unnamed:
        return f"the evidence does not name {', '.join(unnamed)}, closed as not planned; name each one and say why it was dropped"
    if not RUN_OUTPUT.search(evidence):
        return NO_RUN_OUTPUT
    return None


def failed_run(evidence):
    """The first line starting `FAILED (` after `Run output:`, or None: a failed run is never proof (#1568)."""
    start = RUN_START.search(evidence)
    found = start and FAILED_RUN.search(evidence[start.end():])
    return found.group(1).rstrip() if found else None


LABEL_CONST = re.compile(r"""^\s*(\w+)\s*=\s*["'](com\.olivercode\.[\w.-]+)["']""", re.M)
DEFINES = re.compile(r"""launchd\.job\(\s*([\w"'.-]+)|launchd\.schedule\(\s*[^,()]+,\s*([\w"'.-]+)"""
                     r"""|["']Label["']\s*:\s*([\w"'.-]+)|<key>Label</key>\s*<string>([\w.-]+)</string>""")


def job_labels(text):
    """The com.olivercode.* labels a file defines or schedules: the label of each launchd.job or launchd.schedule
    call, plist "Label" key, or LaunchAgent <key>Label</key>, read literally or through a NAME = "label" constant.
    A label that only appears as data, such as an entry in the feature register, is not a job this file runs (#767)."""
    consts = dict(LABEL_CONST.findall(text))
    found = set()
    for groups in DEFINES.findall(text):
        arg = next(g for g in groups if g).strip("\"'")
        label = consts.get(arg, arg)
        if label.startswith("com.olivercode."):
            found.add(label)
    return found


def is_olivercode(root):
    return (Path(root) / "scripts" / "olivercode").is_file() and (Path(root) / "docs" / "RULES.md").is_file()


def installed_root():
    """$OC, the checkout ~/.claude/CLAUDE.md links to, or None when install has not linked one."""
    link = Path.home() / ".claude" / "CLAUDE.md"
    try:
        return Path(os.path.realpath(link)).parent if link.is_symlink() else None
    except OSError:
        return None


def _git(oc, *args):
    return subprocess.run(["git", "-C", str(oc), *args], capture_output=True, text=True)


def _missing(oc, commits):
    return [c for c in commits if _git(oc, "merge-base", "--is-ancestor", c, "HEAD").returncode != 0]


def run_update(oc):
    return subprocess.run([sys.executable, str(Path(oc) / "scripts" / "olivercode"), "update"], capture_output=True, text=True).returncode == 0


def job_loaded(label):
    return subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"], capture_output=True).returncode == 0


def job_scheduled(label):
    """True when the owner turned the job on: its plist is in ~/Library/LaunchAgents."""
    return (Path.home() / "Library" / "LaunchAgents" / f"{label}.plist").is_file()


def live_check(commits, oc, root, update=run_update, loaded=job_loaded, settings=None, scheduled=job_scheduled):
    """(reason, proof): reason is None when the installed checkout `oc` holds `commits` and what they change is loaded (#713).

    An installed checkout that is behind is updated once with `olivercode update`, then checked again. Proof names the
    installed commit, plus each hook entry or launchd job label the commits touch that is confirmed active."""
    if oc is None or not is_olivercode(oc):
        return "the installed OliverCode checkout ($OC) was not found; run `olivercode install` from it", None
    ahead = main_checkout.ahead_refusal(Path(oc)) or main_checkout.stale_refusal(Path(oc))  # an ahead checkout is refused before any update runs, so nothing changes (#785)
    if ahead:
        return ahead, None
    missing = _missing(oc, commits)
    if missing:
        update(oc)
        missing = _missing(oc, commits)
    if missing:
        return (f"the installed checkout at {oc} lacks {missing[0][:10]} even after `olivercode update`; "
                "run `olivercode update` there and fix what it reports"), None
    head = _git(oc, "rev-parse", "--short", "HEAD").stdout.strip()
    proof = [f"installed checkout {head} holds {', '.join(c[:10] for c in commits)}"]
    files = {f for c in commits for f in _git(oc, "diff-tree", "--no-commit-id", "--name-only", "-r", c).stdout.split()}
    settings = settings or Path.home() / ".claude" / "settings.json"
    managed = {script: (event, matcher) for event, matcher, script in claude_settings.MANAGED}
    changed = {Path(f).name for f in files if f.startswith("scripts/hooks/")} & set(managed)
    if "scripts/lib/claude_settings.py" in files:
        changed = set(managed)
    if changed:
        lacking = set(claude_settings.missing(settings, Path(oc) / "scripts" / "hooks"))
        if changed & lacking:
            return f"the hook entry for {', '.join(sorted(changed & lacking))} is not in {settings}; run `olivercode install`", None
        proof += [f"hook entry {managed[s][0]} {s} is in settings.json" for s in sorted(changed)]
    labels = set()
    for f in files:
        if Path(f).name.startswith("test_") or "/tests/" in f"/{f}":
            continue  # a test builds fake jobs; it does not run one (#767)
        try:
            labels |= job_labels((Path(oc) / f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    for label in sorted(labels):
        if not scheduled(label):
            continue  # a job this machine never scheduled is not one it runs (#1373)
        if not loaded(label):
            return f"launchd job {label} is not loaded; run `olivercode install`", None
        proof.append(f"launchd job {label} is loaded")
    return None, "Live: " + "; ".join(proof) + "."


RUN_OUTPUT = re.compile(r"^\s*Run output:\s*\S|^\s*Run output:\s*\n\s*\S", re.M)  # the live run of the story's scenario (#836)
RUN_START = re.compile(r"^\s*Run output:", re.M)
FAILED_RUN = re.compile(r"^[ \t]*(FAILED \(.*)", re.M)  # the summary line unittest prints for a failed run
NO_RUN_OUTPUT = ("the evidence holds no run output. Run the story's own Gherkin scenario live and add its output after a line "
                 "that starts with `Run output:`")


def call(runner, args):
    done = runner(args)
    if done.returncode != 0:
        raise RuntimeError((done.stderr or "gh api failed").strip())
    return done.stdout


def item_id(cfg, story, runner):
    """The story's project item id, read through REST (the core budget), so only the Status write spends GraphQL."""
    owner, number, repo = cfg["projectOwner"], cfg["projectNumber"], f"{cfg['repoOwner']}/{cfg['repoName']}"
    for kind in ("users", "orgs"):
        done = runner(["-H", "X-GitHub-Api-Version: 2022-11-28", f"{kind}/{owner}/projectsV2/{number}/items?per_page=100",
                       "--paginate", "--jq", ITEM_JQ])
        for line in done.stdout.splitlines():  # a paged read that broke partway still printed its early pages
            try:
                row = json.loads(line) if line.strip() else {}
            except ValueError:
                break
            if row.get("number") == story and (not row["repo"] or row["repo"].endswith("/" + repo)):
                return row["id"]
        if done.returncode == 0:
            return None
    # REST could not read the whole board (a later page failed): the one-issue GraphQL lookup costs one call (#1304)
    owner_name, name = cfg["repoOwner"], cfg["repoName"]
    query = (f'{{ repository(owner: "{owner_name}", name: "{name}") {{ issue(number: {story}) '
             "{ projectItems(first: 5) { nodes { id project { number } } } } } }")
    data = json.loads(call(runner, ["graphql", "-f", f"query={query}"]))
    issue = ((data.get("data") or {}).get("repository") or {}).get("issue") or {}
    for node in (issue.get("projectItems") or {}).get("nodes") or []:
        if node["project"]["number"] == number:
            return node["id"]
    return None


def main(argv=None, runner=gh_api, out=sys.stdout, err=sys.stderr, pushed=commit_pushed, live=live_check, oc=None):
    p = argparse.ArgumentParser(description="Close a story on its builder entry and its builder commits on origin/main, or an epic on its closed sub-issues.")
    p.add_argument("--story", type=int, required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--evidence", required=True, help="the comment: files touched and what shipped")
    args = p.parse_args(argv)
    if not args.evidence.strip():
        print("complete_story: --evidence is empty; name the files touched and what shipped", file=err)
        return 2
    try:
        with open(args.config, encoding="utf-8") as h:
            cfg = json.load(h)
        repo = f"{cfg['repoOwner']}/{cfg['repoName']}"
        status = cfg["fields"]["status"]
        finished = {k.lower(): v for k, v in status["options"].items()}
        option = finished.get("complete") or finished["done"]  # a board names its finished lane Complete or Done (#1012)
    except (OSError, ValueError, KeyError) as exc:
        print(f"complete_story: cannot read the config: {exc}", file=err)
        return 2
    try:
        data, body = fetch(repo, args.story, runner)
        subs = sub_issues(repo, args.story, runner)
    except (RuntimeError, ValueError) as exc:
        print(f"complete_story: cannot read #{args.story}: {exc}", file=err)
        return 1
    roles = {a[1] for a in (parse_action(b) for b in flatten(data)) if a}
    still_open = [f"#{s['number']}" for s in subs if s["state"] != "closed"]
    if still_open:
        print(f"complete_story: #{args.story} not completed: open sub-issue {', '.join(still_open)}; close each one first", file=out)
        return 1
    if "builder" not in roles and not subs:
        print(f"complete_story: #{args.story} has no builder entry; log one with log_action.py --role builder", file=out)
        print(f"complete_story: #{args.story} not completed", file=out)
        return 1
    if "builder" not in roles and (reason := epic_refusal(subs, args.evidence)):
        print(f"complete_story: #{args.story} not completed: {reason}", file=out)
        return 1
    if line := failed_run(args.evidence):
        print(f"complete_story: #{args.story} not completed: the run output shows a failed run: `{line}`. "
              "Fix it, run the scenario again and pass the new output", file=out)
        return 1
    root = Path(args.config).resolve().parent.parent  # the config sits in <repo>/docs
    for commit in builder_commits(flatten(data)):  # a story closes only on work that reached origin/main or the engine branch
        reason = pushed(commit, root)
        if reason:
            print(f"complete_story: #{args.story} not completed: {reason}", file=out)
            return 1
    left = rename_check.refusal(body, root)  # a rename story closes only once its old name is gone (#838)
    if left:
        print(f"complete_story: #{args.story} not completed: {left}", file=out)
        return 1
    gate_from = cfg.get("closeGateFromIssue")
    if isinstance(gate_from, int) and not isinstance(gate_from, bool) and args.story >= gate_from and not RUN_OUTPUT.search(args.evidence):
        print(f"complete_story: #{args.story} not completed: {NO_RUN_OUTPUT}", file=out)
        return 1
    evidence = args.evidence
    commits = builder_commits(flatten(data))
    if commits and is_olivercode(root):  # done means live: the installed checkout holds the work before the story closes
        reason, proof = live(commits, oc or installed_root(), root)
        if reason:
            print(f"complete_story: #{args.story} not completed: {reason}", file=out)
            return 1
        evidence = f"{evidence}\n\n{proof}"
    evidence = f"{evidence}\n\n{CLOSE_MARKER}"  # the mark check_board_hygiene.py reads to tell this close from an API close
    reason = repo_name_guard.refusal(evidence) if repo_name_guard.is_olivercode(repo) else ""
    if reason:
        print(f"complete_story: #{args.story}: the evidence was not posted: {reason}", file=err)
        return 1
    try:
        item = item_id(cfg, args.story, runner)
        if not item:
            print(f"complete_story: cannot find #{args.story} on the board: #{args.story} is not on the project board, so nothing changed", file=out)
            return 1
    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"complete_story: cannot find #{args.story} on the board: {exc}", file=err)
        return 1
    # The comment and the close go through REST first, so a spent GraphQL share never blocks them. The Status field
    # needs GraphQL; when GraphQL is held or limited, that one write waits in the shared gh queue for the reset replay.
    steps = [
        ("evidence comment posted", [f"repos/{repo}/issues/{args.story}/comments", "-f", f"body={evidence}"]),
        ("issue closed", ["-X", "PATCH", f"repos/{repo}/issues/{args.story}", "-f", "state=closed"]),
    ]
    for i, (label, call_args) in enumerate(steps):
        try:
            call(runner, call_args)
        except (RuntimeError, ValueError) as exc:
            landed = ", ".join(s for s, _ in steps[:i]) or "nothing"
            print(f"complete_story: #{args.story}: {label.split(' ', 1)[0]} write failed ({exc}); already done: {landed}", file=err)
            return 1
    move = ["graphql", "-f", f"query={MOVE}", "-f", f"p={cfg['projectId']}", "-f", f"i={item}",
            "-f", f"f={status['id']}", "-f", f"v={option}"]
    queued = gh_budget.refusal("graphql")
    if not queued:
        try:
            call(runner, move)
            board_mirror.invalidate()  # the Status changed, so the shared board copy is stale
        except (RuntimeError, ValueError) as exc:
            if not gh_budget.is_limit(str(exc)):
                print(f"complete_story: #{args.story}: status write failed ({exc}); already done: "
                      "evidence comment posted, issue closed", file=err)
                return 1
            gh_budget.note_limit(who="complete_story", resources=gh_budget.limit_resources("gh api graphql", str(exc)))
            queued = "GraphQL hit its limit"
    archive = ["graphql", "-f", f"query={ARCHIVE}", "-f", f"p={cfg['projectId']}", "-f", f"i={item}"]
    if queued:
        gh_budget.enqueue(["gh", "api", *move])
        gh_budget.enqueue(["gh", "api", *archive])  # the card leaves the board after its move, in the same replay
        print(f"#{args.story} is commented and closed; its Complete status and archive are queued for the GraphQL reset", file=out)
        return 0
    try:
        call(runner, archive)  # a closed story's card leaves the board, so every board read covers open work only (#1323)
        board_mirror.invalidate()
    except (RuntimeError, ValueError) as exc:
        if not gh_budget.is_limit(str(exc)):
            print(f"complete_story: #{args.story}: archive write failed ({exc}); already done: "
                  "evidence comment posted, issue closed, status Complete", file=err)
            return 1
        gh_budget.note_limit(who="complete_story", resources=gh_budget.limit_resources("gh api graphql", str(exc)))
        gh_budget.enqueue(["gh", "api", *archive])
        print(f"#{args.story} is Complete, commented and closed; its archive is queued for the GraphQL reset", file=out)
        return 0
    print(f"#{args.story} is Complete, commented, closed and archived", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

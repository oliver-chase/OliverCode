#!/usr/bin/env python3
"""Check that a story has an independent QA pass before it moves to Complete.

Usage: check_qa_signoff.py --story N (--config CONFIG | --repo OWNER/NAME)
                           [--comments FILE] [--body FILE]
Reads the story's comments (a JSON list of objects with a "body", or a list of lists as
`gh api --paginate --slurp` prints) from --comments, or fetches them through the gh REST
API when the file is omitted. The acceptance criteria come from --body, or from the story
body fetched the same way. Comments are the ones log_action.py posts.
Exits 0 when the story has a builder comment and the newest QA comment from an agent that is not a
builder on the story says PASS and lists every Gherkin scenario by its whole name after "confirmed:",
separated by ";", and prints each confirmed scenario. Exits 1 and prints
the reason otherwise, and 2 on a usage error.
A scenario also counts as confirmed when its segment is the name plus a note after ".", ",", ":", " (" or " -".
A story body line `QA: mechanical` accepts a builder comment saying "validate.sh exits 0" without a QA comment.
"""
import argparse
import json
import re
import subprocess
import sys

FIELD = re.compile(r"^\s*-?\s*(Agent|Role|Result):\s*(.*?)\s*$", re.M)
SCENARIO = re.compile(r"^\s*Scenario(?: Outline)?:\s*(.+?)\s*$", re.M)
CONFIRMED = re.compile(r"\bconfirmed:(.*)$", re.I | re.S)
MECHANICAL = re.compile(r"^\s*QA:\s*mechanical\s*$", re.I | re.M)
NOTE = re.compile(r"^(?:[.,:]|\s+[(\-\u2014\u2013])")
VERDICT = re.compile(r"^\s*(PASS|FAIL)\b", re.I)
REPO = re.compile(r"^[\w.-]+/[\w.-]+$")


def gh_api(args):
    """Run `gh api ARGS` and return the CompletedProcess. Tests pass their own runner instead."""
    return subprocess.run(["gh", "api"] + args, capture_output=True, text=True)


def parse_action(body):
    """Return (agent, role, result) from an agent-action comment, or None for any other comment."""
    if not body.lstrip().startswith("Agent action"):
        return None
    fields = {k.lower(): v for k, v in FIELD.findall(body)}
    if "agent" not in fields or "role" not in fields:
        return None
    return fields["agent"], fields["role"].lower(), fields.get("result", "")


def flatten(data):
    """Accept a list of comments or a list of pages and return the comment bodies in order."""
    bodies = []
    for item in data:
        if isinstance(item, list):
            bodies.extend(flatten(item))
        elif isinstance(item, dict) and isinstance(item.get("body"), str):
            bodies.append(item["body"])
    return bodies


def scenarios(story_body):
    return SCENARIO.findall(story_body or "")


def confirmed_names(result):
    """The scenario names after "confirmed:" in a QA result, split on ";", trimmed and lower-cased."""
    found = CONFIRMED.search(result or "")
    if not found:
        return set()
    return {part.strip().lower() for part in found.group(1).split(";") if part.strip()}


def is_confirmed(name, confirmed):
    """True when a segment is the whole name, or the name followed by a sentence break and a note."""
    name = name.lower()
    return any(seg == name or (seg.startswith(name) and NOTE.match(seg[len(name):])) for seg in confirmed)


def check(comment_bodies, story_body):
    """Return (ok, lines). Lines are the confirmed scenarios on success, the reasons on failure."""
    if not MECHANICAL.search(story_body or ""):
        return check_independent(comment_bodies, story_body)
    for agent, role, result in filter(None, map(parse_action, comment_bodies)):
        if role == "builder" and "validate.sh exits 0" in result.lower():
            return True, [f"mechanical: proof from {agent}: {result}"]
    ok, lines = check_independent(comment_bodies, story_body)
    if ok:
        return ok, lines
    return ok, lines + ['mechanical proof missing: the builder comment must say "validate.sh exits 0"']


def check_independent(comment_bodies, story_body):
    actions = [a for a in map(parse_action, comment_bodies) if a]
    builders = {agent.strip().lower() for agent, role, _ in actions if role == "builder"}
    if not builders:
        return False, ["no builder comment: independence cannot be shown without one, so log the build with log_action.py --role builder"]
    qa = [(agent, result) for agent, role, result in actions if role == "qa"]
    if not qa:
        return False, ["no QA comment: log one with log_action.py --role qa"]
    independent = [(a, r) for a, r in qa if a.strip().lower() not in builders]
    if not independent:
        names = ", ".join(sorted({a for a, _ in qa}))
        return False, [f"the QA agent is a builder on this story ({names}): a different agent must QA it"]
    agent, result = independent[-1]
    verdict = VERDICT.match(result)
    if not verdict or verdict.group(1).upper() != "PASS":
        return False, [f"QA result from {agent} is not PASS: {result or '(empty)'}"]
    names = scenarios(story_body)
    if not names:
        return False, ["the story has no Gherkin scenario to confirm"]
    confirmed = confirmed_names(result)
    missing = [n for n in names if not is_confirmed(n, confirmed)]
    if missing:
        return False, [f"scenario unconfirmed by {agent}: {n}" for n in missing]
    return True, [f"confirmed by {agent}: {n}" for n in names]


def fetch(repo, story, runner):
    comments = runner(["--paginate", "--slurp", f"repos/{repo}/issues/{story}/comments"])
    issue = runner([f"repos/{repo}/issues/{story}", "--jq", ".body"])
    for result in (comments, issue):
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "gh api failed").strip())
    return json.loads(comments.stdout or "[]"), issue.stdout


def main(argv=None, runner=gh_api, out=sys.stdout, err=sys.stderr):
    p = argparse.ArgumentParser(description="Check a story's independent QA sign-off.")
    p.add_argument("--story", type=int, required=True)
    p.add_argument("--config")
    p.add_argument("--repo")
    p.add_argument("--comments", help="JSON file of the story's comments, in place of a fetch")
    p.add_argument("--body", help="file holding the story body, in place of a fetch")
    args = p.parse_args(argv)
    try:
        if args.comments and args.body:
            with open(args.comments, encoding="utf-8") as h:
                data = json.load(h)
            with open(args.body, encoding="utf-8") as h:
                body = h.read()
        else:
            repo = args.repo
            if not repo and args.config:
                with open(args.config, encoding="utf-8") as h:
                    cfg = json.load(h)
                repo = f"{cfg['repoOwner']}/{cfg['repoName']}"
            if not repo or not REPO.match(repo):
                print("check_qa_signoff: pass --repo OWNER/NAME or --config, or both --comments and --body", file=err)
                return 2
            data, body = fetch(repo, args.story, runner)
            if args.comments:
                with open(args.comments, encoding="utf-8") as h:
                    data = json.load(h)
            if args.body:
                with open(args.body, encoding="utf-8") as h:
                    body = h.read()
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"check_qa_signoff: cannot read the story: {exc}", file=err)
        return 2
    ok, lines = check(flatten(data), body)
    if ok:
        print(f"QA sign-off accepted for #{args.story}", file=out)
        for line in lines:
            print(f"  {line}", file=out)
        return 0
    print(f"QA sign-off refused for #{args.story}", file=out)
    for line in lines:
        print(f"  {line}", file=out)
    return 1


if __name__ == "__main__":
    sys.exit(main())

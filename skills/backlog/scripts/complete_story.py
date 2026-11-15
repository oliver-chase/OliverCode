#!/usr/bin/env python3
"""Close a story: run the QA sign-off check, then move it to Complete, comment the evidence and close it.

Usage: complete_story.py --story N --config CONFIG --evidence TEXT
Runs check_qa_signoff.py's check for the story first. On a refusal it prints the check's reason and
changes nothing. On success it finds the story's project item with a GraphQL query on the issue's
projectItems (`gh project item-list` can omit items), sets Status to Complete by the config's ids,
posts TEXT as a comment and closes the issue. Exits 0 when all three writes succeeded, 1 on a refusal or a
failed call, 2 on a usage error.
"""
import argparse
import json
import sys

import check_qa_signoff as qa

ITEMS = ("query($o:String!,$n:String!,$num:Int!){repository(owner:$o,name:$n){issue(number:$num)"
         "{projectItems(first:50){nodes{id project{id}}}}}}")
MOVE = ("mutation($p:ID!,$i:ID!,$f:ID!,$v:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,"
        "itemId:$i,fieldId:$f,value:{singleSelectOptionId:$v}}){projectV2Item{id}}}")


def call(runner, args):
    done = runner(args)
    if done.returncode != 0:
        raise RuntimeError((done.stderr or "gh api failed").strip())
    return done.stdout


def item_id(cfg, story, runner):
    owner, name = cfg["repoOwner"], cfg["repoName"]
    data = json.loads(call(runner, ["graphql", "-f", f"query={ITEMS}", "-f", f"o={owner}", "-f", f"n={name}",
                                    "-F", f"num={story}"]))
    nodes = data["data"]["repository"]["issue"]["projectItems"]["nodes"]
    return next((n["id"] for n in nodes if n["project"]["id"] == cfg["projectId"]), None)


def main(argv=None, runner=qa.gh_api, out=sys.stdout, err=sys.stderr):
    p = argparse.ArgumentParser(description="Close a story on its builder entry, and its QA sign-off when it had a QA pass.")
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
        option = status["options"]["Complete"]
    except (OSError, ValueError, KeyError) as exc:
        print(f"complete_story: cannot read the config: {exc}", file=err)
        return 2
    try:
        data, body = qa.fetch(repo, args.story, runner)
    except (RuntimeError, ValueError) as exc:
        print(f"complete_story: cannot read #{args.story}: {exc}", file=err)
        return 1
    roles = {a[1] for a in (qa.parse_action(b) for b in qa.flatten(data)) if a}
    if "builder" not in roles:
        print(f"complete_story: #{args.story} has no builder entry; log one with log_action.py --role builder", file=out)
        print(f"complete_story: #{args.story} not completed", file=out)
        return 1
    required_from = cfg.get("qaRequiredFromIssue")
    qa_required = isinstance(required_from, int) and args.story >= required_from
    if "qa" in roles or qa_required:  # a story with a QA pass, or one the config requires QA for, closes only on its sign-off
        ok, lines = qa.check(qa.flatten(data), body)
        if not ok:
            for line in lines:
                print(f"check_qa_signoff: {line}", file=out)
            print(f"complete_story: #{args.story} not completed", file=out)
            return 1
    try:
        item = item_id(cfg, args.story, runner)
        if not item:
            print(f"complete_story: #{args.story} is not on the project board, so nothing changed", file=out)
            return 1
    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"complete_story: cannot find #{args.story} on the board: {exc}", file=err)
        return 1
    # Three writes in order. When one fails, the message names the ones that landed, so a rerun finishes the rest.
    steps = [
        ("status set to Complete", ["graphql", "-f", f"query={MOVE}", "-f", f"p={cfg['projectId']}", "-f", f"i={item}",
                                    "-f", f"f={status['id']}", "-f", f"v={option}"]),
        ("evidence comment posted", [f"repos/{repo}/issues/{args.story}/comments", "-f", f"body={args.evidence}"]),
        ("issue closed", ["-X", "PATCH", f"repos/{repo}/issues/{args.story}", "-f", "state=closed"]),
    ]
    for i, (label, call_args) in enumerate(steps):
        try:
            call(runner, call_args)
        except (RuntimeError, ValueError) as exc:
            landed = ", ".join(s for s, _ in steps[:i]) or "nothing"
            print(f"complete_story: #{args.story}: {label.split(' ', 1)[0]} write failed ({exc}); already done: {landed}", file=err)
            return 1
    print(f"#{args.story} is Complete, commented and closed", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
    p = argparse.ArgumentParser(description="Close a story after its QA sign-off passes.")
    p.add_argument("--story", type=int, required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--evidence", required=True, help="the comment: files touched and what shipped")
    args = p.parse_args(argv)
    try:
        with open(args.config, encoding="utf-8") as h:
            cfg = json.load(h)
        repo = f"{cfg['repoOwner']}/{cfg['repoName']}"
        status = cfg["fields"]["status"]
        option = status["options"]["Complete"]
    except (OSError, ValueError, KeyError) as exc:
        print(f"complete_story: cannot read the config: {exc}", file=err)
        return 2
    check_out = type(out)()
    code = qa.main(["--story", str(args.story), "--config", args.config], runner=runner, out=check_out, err=err)
    if code != 0:
        out.write(check_out.getvalue())
        print(f"complete_story: #{args.story} not completed", file=out)
        return code
    try:
        item = item_id(cfg, args.story, runner)
        if not item:
            print(f"complete_story: #{args.story} is not on the project board, so nothing changed", file=out)
            return 1
        call(runner, ["graphql", "-f", f"query={MOVE}", "-f", f"p={cfg['projectId']}", "-f", f"i={item}",
                      "-f", f"f={status['id']}", "-f", f"v={option}"])
        call(runner, [f"repos/{repo}/issues/{args.story}/comments", "-f", f"body={args.evidence}"])
        call(runner, ["-X", "PATCH", f"repos/{repo}/issues/{args.story}", "-f", "state=closed"])
    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"complete_story: a write failed after the check passed: {exc}", file=err)
        return 1
    print(f"#{args.story} is Complete, commented and closed", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Record an agent action on its story as an issue comment.

Usage: log_action.py --config CONFIG --story N --agent NAME --role builder|qa
                     --commit HASH --files N --result TEXT [--dry-run]
Posts one comment on the story through the gh REST API: agent, role, commit, files changed
and result. --dry-run prints the comment and calls nothing. The repo comes from the backlog
config (repoOwner and repoName), or from --repo OWNER/NAME. Exits 1 when the comment could
not be posted and 2 on a usage error.
"""
import argparse
import json
import re
import subprocess
import sys

ROLES = ("builder", "qa")
HASH = re.compile(r"^[0-9a-f]{7,40}$")
REPO = re.compile(r"^[\w.-]+/[\w.-]+$")


def build_comment(agent, role, commit, files, result):
    """The comment text. One fact per line, so the story reads as a log."""
    return "\n".join([
        "Agent action",
        f"- Agent: {agent}",
        f"- Role: {role}",
        f"- Commit: {commit}",
        f"- Files changed: {files}",
        f"- Result: {result}",
    ])


def gh_api(args):
    """Run `gh api ARGS` and return the CompletedProcess. Tests pass their own runner instead."""
    return subprocess.run(["gh", "api"] + args, capture_output=True, text=True)


def post_comment(repo, story, body, runner=gh_api):
    """Post `body` on issue `story` of `repo` and return the comment URL. Raises RuntimeError."""
    result = runner([f"repos/{repo}/issues/{story}/comments", "-f", f"body={body}", "--jq", ".html_url"])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "gh api failed").strip())
    return result.stdout.strip()


def repo_from_config(path):
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    return f"{config['repoOwner']}/{config['repoName']}"


def parse_args(argv):
    p = argparse.ArgumentParser(description="Log an agent action on its story.")
    p.add_argument("--config", help="path to the repo's backlog-config.json")
    p.add_argument("--repo", help="OWNER/NAME, when no config is given")
    p.add_argument("--story", type=int, required=True, help="the story's issue number")
    p.add_argument("--agent", required=True, help="the agent's name")
    p.add_argument("--role", required=True, choices=ROLES)
    p.add_argument("--commit", required=True, help="the commit hash, or the hash the work ended on")
    p.add_argument("--files", type=int, required=True, help="number of files changed")
    p.add_argument("--result", required=True, help="what the action produced, in one line")
    p.add_argument("--dry-run", action="store_true", help="print the comment and post nothing")
    return p.parse_args(argv)


def main(argv=None, runner=gh_api, out=sys.stdout, err=sys.stderr):
    args = parse_args(argv)
    problems = []
    if not HASH.match(args.commit):
        problems.append(f"--commit {args.commit!r} is not a commit hash (7 to 40 hex characters)")
    if args.files < 0:
        problems.append("--files cannot be negative")
    if "\n" in args.result or not args.result.strip():
        problems.append("--result must be one non-empty line")
    repo = args.repo
    if not repo:
        if not args.config:
            problems.append("pass --config or --repo so the comment has a repo to go to")
        else:
            try:
                repo = repo_from_config(args.config)
            except (OSError, KeyError, ValueError) as exc:
                problems.append(f"cannot read the repo from {args.config}: {exc}")
    if repo and not REPO.match(repo):
        problems.append(f"repo {repo!r} is not OWNER/NAME")
    if problems:
        for line in problems:
            print(f"log_action: {line}", file=err)
        return 2
    body = build_comment(args.agent, args.role, args.commit, args.files, args.result)
    if args.dry_run:
        print(f"Dry run: would comment on {repo}#{args.story}\n\n{body}", file=out)
        return 0
    try:
        url = post_comment(repo, args.story, body, runner)
    except RuntimeError as exc:
        print(f"log_action: the comment on {repo}#{args.story} was not posted: {exc}", file=err)
        return 1
    print(f"Logged on {repo}#{args.story}: {url}", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

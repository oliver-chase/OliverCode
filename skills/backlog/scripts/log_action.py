#!/usr/bin/env python3
"""Record an agent action on its story as an issue comment.

Usage: log_action.py --config CONFIG --story N --agent NAME --role builder|qa
                     --commit HASH --files N --result TEXT [--dry-run]
       log_action.py --config CONFIG --agent NAME --commit HASH --from-report FILE [--files N]
       log_action.py ... --role builder --agent-from-commit   (agent = the commit's author)
Posts one comment on the story through the gh REST API: agent, role, commit, files changed
and result. --dry-run prints the comment and calls nothing. The repo comes from the backlog
config (repoOwner and repoName), or from --repo OWNER/NAME. Exits 1 when the comment could
not be posted and 2 on a usage error. --from-report logs one qa entry per "Story N: PASS|FAIL|
BLOCKED ..." line of a QA report (the last line per story counts).
"""
import argparse
import json
import re
import subprocess
import sys

from check_qa_signoff import REPO, gh_api  # one gh runner and one repo pattern for the backlog scripts

ROLES = ("builder", "qa")
HASH = re.compile(r"^[0-9a-f]{7,40}$")
VERDICT = re.compile(r"^\s*Story (\d+):\s*(PASS|FAIL|BLOCKED)\b(.*)$")


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



def post_comment(repo, story, body, runner=gh_api):
    """Post `body` on issue `story` of `repo` and return the comment URL. Raises RuntimeError."""
    result = runner([f"repos/{repo}/issues/{story}/comments", "-f", f"body={body}", "--jq", ".html_url"])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "gh api failed").strip())
    return result.stdout.strip()


def git_author(commit):
    """The author name of `commit`, from git in the current directory. Tests pass their own."""
    done = subprocess.run(["git", "log", "-1", "--format=%an", commit], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else ""


def report_results(path):
    """{story: result} from the report's verdict lines. The last line per story wins."""
    found = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            m = VERDICT.match(line.rstrip("\n"))
            if m:
                found[int(m.group(1))] = (m.group(2) + m.group(3)).strip()
    return found


def repo_from_config(path):
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    return f"{config['repoOwner']}/{config['repoName']}"


def parse_args(argv):
    p = argparse.ArgumentParser(description="Log an agent action on its story.")
    p.add_argument("--config", help="path to the repo's backlog-config.json")
    p.add_argument("--repo", help="OWNER/NAME, when no config is given")
    p.add_argument("--story", type=int, help="the story's issue number")
    p.add_argument("--agent", help="the agent's name")
    p.add_argument("--role", choices=ROLES)
    p.add_argument("--commit", required=True, help="the commit hash, or the hash the work ended on")
    p.add_argument("--files", type=int, help="number of files changed")
    p.add_argument("--result", help="what the action produced, in one line")
    p.add_argument("--from-report", metavar="FILE", help="log one qa entry per story in a QA report")
    p.add_argument("--agent-from-commit", action="store_true", help="builder only: agent = --commit's author")
    p.add_argument("--dry-run", action="store_true", help="print the comment and post nothing")
    args = p.parse_args(argv)
    if args.from_report and args.files is None:
        args.files = 0
    need = ["files"] + ([] if args.from_report else ["story", "role", "result"])
    need += [] if args.agent_from_commit else ["agent"]
    for name in need:
        if getattr(args, name) is None:
            p.error(f"the following arguments are required: --{name}")
    return args


def main(argv=None, runner=gh_api, out=sys.stdout, err=sys.stderr, git=git_author):
    args = parse_args(argv)
    problems = []
    if not HASH.match(args.commit):
        problems.append(f"--commit {args.commit!r} is not a commit hash (7 to 40 hex characters)")
    if args.files < 0:
        problems.append("--files cannot be negative")
    agent, role, jobs = args.agent, args.role, [(args.story, args.result)]
    if args.from_report:
        role, jobs = "qa", []
        if args.story is not None or args.result is not None or args.role == "builder":
            problems.append("--from-report cannot be combined with --story, --result or --role builder")
        else:
            try:
                jobs = sorted(report_results(args.from_report).items())
            except OSError as exc:
                problems.append(f"cannot read the report {args.from_report}: {exc}")
            else:
                if not jobs:
                    problems.append(f"{args.from_report} has no 'Story N: PASS|FAIL|BLOCKED' line")
    if args.agent_from_commit:
        if args.role != "builder" or args.agent:
            problems.append("--agent-from-commit needs --role builder and no --agent")
        elif HASH.match(args.commit):
            agent = git(args.commit)
            if not agent:
                problems.append(f"git found no author for commit {args.commit}")
    if any("\n" in str(r) or not str(r).strip() for _, r in jobs):
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
    code = 0
    for story, result in jobs:
        body = build_comment(agent, role, args.commit, args.files, result)
        if args.dry_run:
            print(f"Dry run: would comment on {repo}#{story}\n\n{body}", file=out)
            continue
        try:
            url = post_comment(repo, story, body, runner)
        except RuntimeError as exc:
            print(f"log_action: the comment on {repo}#{story} was not posted: {exc}", file=err)
            code = 1
            continue
        print(f"Logged on {repo}#{story}: {url}", file=out)
    return code


if __name__ == "__main__":
    sys.exit(main())

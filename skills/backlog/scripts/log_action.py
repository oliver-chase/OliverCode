#!/usr/bin/env python3
"""Record an agent action on its story as an issue comment. A builder entry is refused while its commit is not on origin/main (#533).

Usage: log_action.py --config CONFIG --story N --agent SESSION --role claim   (claim a story)
       log_action.py --config CONFIG --story N --check-claim   (prints "claimed by NAME at TIME" or "free")
       log_action.py --config CONFIG --story N --agent NAME --role builder
                     --commit HASH --files N --result TEXT [--dry-run]
       log_action.py ... --role builder --agent-from-commit   (agent = the commit's author)
Posts one comment on the story through the gh REST API: agent, role, commit, files changed
and result. --dry-run prints the comment and calls nothing. The repo comes from the backlog
config (repoOwner and repoName), or from --repo OWNER/NAME. A comment on OliverCode that names another repo from the local registry is refused before the post. Exits 1 when the comment could
not be posted and 2 on a usage error.
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "lib"))

import repo_name_guard  # noqa: E402

ROLES = ("builder", "claim")
CLAIM_HOURS = 2
HASH = re.compile(r"^[0-9a-f]{7,40}$")
REPO = re.compile(r"^[\w.-]+/[\w.-]+$")
COMMIT = re.compile(r"^\s*-?\s*Commit:\s*([0-9a-f]{7,40})\b", re.M)


def gh_api(args):
    """Run `gh api ARGS` and return the CompletedProcess. Tests pass their own runner instead."""
    return subprocess.run(["gh", "api"] + args, capture_output=True, text=True)


def commit_pushed(commit, root=None):
    """None when `commit` is on the repo's default branch at origin in the checkout at `root`, else the reason it is not (#533, #1012)."""
    git = ["git"] + (["-C", str(root)] if root else [])
    done = subprocess.run(git + ["branch", "-r", "--contains", commit], capture_output=True, text=True)
    if done.returncode != 0:
        return f"commit {commit} is not in this checkout; fetch it, or run this from the repo that holds it"
    head = subprocess.run(git + ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], capture_output=True, text=True).stdout.strip()
    base = head or "origin/main"
    holds = {line.strip() for line in done.stdout.splitlines()}
    if not (holds & ({base} if head else {"origin/main", "origin/master", "origin/develop"})):
        return f"commit {commit} is not on {base}; push it first: git push origin HEAD:{base.removeprefix('origin/')}"
    return None


def commit_names_story(commit, story, root=None):
    """None when the message of `commit` contains #STORY, else the reason it does not, so a close names its own commit (#1011)."""
    git = ["git"] + (["-C", str(root)] if root else [])
    done = subprocess.run(git + ["log", "-1", "--format=%B", commit], capture_output=True, text=True)
    if done.returncode != 0:
        return f"commit {commit} is not in this checkout, so its message cannot be read"
    if not re.search(rf"#{story}(?!\d)", done.stdout):
        return f"commit {commit} does not name #{story} in its message, so it is not this story's commit"
    return None


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

def build_claim(agent, now):
    """The claim comment: the session name and a UTC timestamp."""
    return f"Claim\n- Session: {agent}\n- Time: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}"


def claim_status(repo, story, runner=gh_api, now=None):
    """'claimed by NAME at TIME' for a claim under two hours old with no later commit comment, else 'free'
    (no claim, a stale claim or a claim followed by a commit). Reads comments over REST. Raises RuntimeError."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    done = runner([f"repos/{repo}/issues/{story}/comments?per_page=100", "--paginate", "--jq", ".[] | {body}"])
    if done.returncode != 0:
        raise RuntimeError((done.stderr or "gh api failed").strip())
    claim = None
    for line in done.stdout.splitlines():
        body = json.loads(line)["body"] if line.strip() else ""
        m = re.match(r"Claim\n- Session: (.+)\n- Time: (\S+)$", body)
        if m:
            claim = (m.group(1), m.group(2))
        elif claim and body.startswith("Claim released\n"):
            claim = None
        elif claim and re.search(r"^- Commit: [0-9a-f]{7,40}$", body, re.M):
            claim = None
    if claim:
        try:
            at = datetime.datetime.strptime(claim[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            return "free"  # a claim with no readable time holds nothing
        if now - at < datetime.timedelta(hours=CLAIM_HOURS):
            return f"claimed by {claim[0]} at {claim[1]}"
    return "free"


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
    p.add_argument("--commit", help="the commit hash, or the hash the work ended on")
    p.add_argument("--files", type=int, help="number of files changed")
    p.add_argument("--result", help="what the action produced, in one line")
    p.add_argument("--agent-from-commit", action="store_true", help="builder only: agent = --commit's author")
    p.add_argument("--check-claim", action="store_true", help="print 'claimed by NAME at TIME' or 'free' for --story")
    p.add_argument("--dry-run", action="store_true", help="print the comment and post nothing")
    args = p.parse_args(argv)
    if args.check_claim:
        need = ["story"]
    elif args.role == "claim":
        need = ["story", "agent"]
    else:
        need = ["commit", "files", "story", "role", "result"] + ([] if args.agent_from_commit else ["agent"])
    for name in need:
        if getattr(args, name) is None:
            p.error(f"the following arguments are required: --{name}")
    return args


def main(argv=None, runner=gh_api, out=sys.stdout, err=sys.stderr, git=git_author, pushed=commit_pushed, names=None, names_story=commit_names_story):
    args = parse_args(argv)
    problems = []
    plain = args.check_claim or args.role == "claim"
    if not plain and not HASH.match(args.commit):
        problems.append(f"--commit {args.commit!r} is not a commit hash (7 to 40 hex characters)")
    if args.role == "builder" and not args.dry_run and HASH.match(args.commit or ""):
        reason = pushed(args.commit)
        if reason:
            problems.append(reason)
        elif args.story is not None:
            reason = names_story(args.commit, args.story)
            if reason:
                problems.append(reason)
    if not plain and args.files < 0:
        problems.append("--files cannot be negative")
    agent = args.agent
    if args.agent_from_commit:
        if args.role != "builder" or args.agent:
            problems.append("--agent-from-commit needs --role builder and no --agent")
        elif HASH.match(args.commit):
            agent = git(args.commit)
            if not agent:
                problems.append(f"git found no author for commit {args.commit}")
    if args.check_claim and args.role:
        problems.append("--check-claim takes only --story")
    if args.result is not None and ("\n" in args.result or not args.result.strip()):
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
    if args.check_claim:
        try:
            print(claim_status(repo, args.story, runner), file=out)
        except RuntimeError as exc:
            print(f"log_action: the comments on {repo}#{args.story} were not read: {exc}", file=err)
            return 1
        return 0
    if args.role == "claim":
        body = build_claim(agent, datetime.datetime.now(datetime.timezone.utc))
    else:
        body = build_comment(agent, args.role, args.commit, args.files, args.result)
    reason = repo_name_guard.refusal(body, names) if repo_name_guard.is_olivercode(repo) else ""
    if reason:
        print(f"log_action: the comment on {repo}#{args.story} was not posted: {reason}", file=err)
        return 1
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

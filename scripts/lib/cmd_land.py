"""Launcher command `land`: `olivercode land WORKTREE STORY` puts a story's commit on origin/main (#608).

It rebases the worktree on origin/main, squashes a branch of several commits into one whose message is the first commit's title and the story number (#898), runs the repo's validation up to twice unless a passing run already recorded the same tree (#910), pushes HEAD:main and retries up to four times when main moves. After a push it fast-forwards the main
checkout when that is clean and prints how far behind an edited or diverged one is. The log is ~/.olivercode/land/land-REPO-N.log (under OLIVERCODE_HOME when set) and ends
with `RESULT pushed SHA`, `RESULT rebase-conflict`, `RESULT validate-failed`, `RESULT squash-failed` (the commits could not be squashed), `RESULT push-failed` (the push failed while main stood still) or `RESULT main-kept-moving` (a land keeps retrying with a short pause for ten minutes while main moves and each rebase is clean). A second land for a story that is already running refuses. Land never edits docs/LIMITS.json: the size ceiling only warns (#879).
A commit that changes a file outside its story's Files area lands and the story gets a comment naming the files; a commit that adds a skip or `|| true` to a test, or removes assertions without removing code, ends with `RESULT weakened-test`; a story that cannot be read over REST ends with `RESULT scope-unchecked` (#1073).
A story's `Removes tests: file::test` line lets that test go when the commit deletes it whole and the Files area lists its file; the log and a story comment name it (#1484).
A pushed story whose body has a section headed `After landing` or `Machine step` gets one open owner-queue line naming the step, and the land prints and logs it (#1566).

A landed story is cleaned up here (#712): the worktree, the local branch and the remote branch are deleted, so no session needs a removal permission. Work that did not land
stays in its worktree, and no branch is pushed for it.
"""

from __future__ import annotations

import ast
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from lib import agent_loop, backlog_setup, cmd_owner, failure_log, intake, local_config, maintain, run_lock, usage_sessions, validated
from lib.validate_gates import PROGRESS  # the lines that also print on the terminal while a land validates (#776)
from lib.local_config import OC_ROOT
from lib import gitfiles

LOG_DIR: Path | None = None  # None means failure_log.home() / "land", which belongs to the user running it
TRIES = 4
BUDGET = 600  # seconds a land keeps retrying after TRIES clean rebases while main keeps moving (#784)
PAUSE = 5
SLOWER = 1.25  # staging whose quick validation takes this many times main's promotes nothing (#1305)
USAGE = "Usage: olivercode land WORKTREE STORY [--session SESSION_ID]"
CUT_LOCK = "version-cut.lock"
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*$|[._](test|spec)\.\w+$")
VALIDATION_FILE = re.compile(r"validat|\.githooks/|\.github/workflows/")
SKIP = re.compile(r"@(?:unittest\.|pytest\.mark\.)?skip|\bskip(?:Test|If|Unless)?\(|\.skip\(|\bx(?:it|describe|test)\(|mark\.xfail")
OR_TRUE = re.compile(r"\|\|\s*true\b")
ASSERT = re.compile(r"\bassert\w*\(|\bassert\s|\bexpect\(")
PENDING = "After-landing step pending"  # how the line starts that the drain reads from a land's output (#1566)
# a section headed by a Markdown heading or a bold line, up to the next heading, so a scenario that only says "after landing" is none
AFTER_LANDING = re.compile(r"^[ \t]*(?:#{1,6}[ \t]*\**|\*\*)(?:After landing|Machine step)\b(.*?)(?=^#{1,6}[ \t]|\Z)", re.I | re.M | re.S)


def _run(wt: Path, log, *cmd: str, env: dict | None = None) -> bool:
    try:
        return subprocess.run(cmd, cwd=wt, stdout=log, stderr=log, env=env).returncode == 0
    except OSError as exc:
        log.write(f"{cmd[0]}: {exc}\n")
        return False


def _validates(wt: Path, log, say=print) -> bool:
    """Validate up to twice. Every line goes to the log, and each gate's start, finish and budget line also prints at that moment."""
    for _ in range(2):
        try:
            proc = subprocess.Popen(agent_loop.validation_command(wt) or ["false"], cwd=wt, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    errors="replace")
        except OSError as exc:
            log.write(f"validate: {exc}\n")
        else:
            for line in proc.stdout:
                log.write(line)
                if line.startswith(PROGRESS):
                    say(line.rstrip("\n"), flush=True)
            if proc.wait() == 0:
                return True
        log.write("--- validate failed, rerun\n")
        log.flush()
    return False


def link_venv(main: Path, wt: Path) -> bool:
    """Link the main checkout's .venv and node_modules into a new worktree so validation finds the repo's interpreter (#752) and
    dependencies (#1294). Returns True when it linked either. A repo without a folder, or a worktree that already has one, is left alone."""
    linked = False
    for name in (".venv", "node_modules"):
        source, target = main / name, wt / name
        if not source.is_dir() or target.exists() or target.is_symlink():
            continue
        try:
            target.symlink_to(source, target_is_directory=True)
        except OSError:
            continue
        linked = True
        # a .gitignore that matches directories only (`node_modules/`) misses a symlink, so info/exclude keeps the link out of `git add -A`
        ignored = gitfiles.run(wt, "check-ignore", "-q", name).returncode != 1
        exclude = "" if ignored else gitfiles.run(wt, "rev-parse", "--git-path", "info/exclude").stdout.strip()
        if exclude:
            with contextlib.suppress(OSError):
                (wt / exclude).parent.mkdir(parents=True, exist_ok=True)
                with (wt / exclude).open("a") as f:
                    f.write(f"/{name}\n")
    return linked


def prepare_worktree(wt: Path, main: Path | None = None) -> list[str]:
    """Make a worktree accept its first commit (#786): hooksPath set for this worktree alone (plain `git config` does not override
    config.worktree), the hooks built, the virtualenv linked. Returns what failed, each with its words."""
    main, problems = main or _main_checkout(wt), []
    if main and main != wt:
        link_venv(main, wt)
    builder = wt / "scripts" / "build-hooks.py"
    if builder.is_file() and subprocess.run([sys.executable, str(builder)], cwd=wt, capture_output=True).returncode:
        problems.append("scripts/build-hooks.py failed, so the hooks are not built")
    if gitfiles.run(wt, "config", "extensions.worktreeConfig", "true").returncode or gitfiles.run(wt, "config", "--worktree", "core.hooksPath", ".githooks").returncode:
        problems.append("git would not set core.hooksPath for this worktree")
    return problems


def add_worktree(repo: Path, wt: Path, n: str, base: str = "") -> list[str]:
    """`olivercode worktree add N`: create story/N from base, then prepare it. Returns what failed, empty when it is ready to commit."""
    base = base or f"origin/{agent_loop.default_branch(repo)}"
    made = subprocess.run(["git", "-C", str(repo), "worktree", "add", str(wt), "-b", f"story/{n}", base], capture_output=True, text=True)
    if made.returncode:
        return [f"the worktree was not created: {(made.stderr or made.stdout).strip()}"]
    return prepare_worktree(wt, repo)


RESUME_NOTE = ("Earlier partial work is present on branch story/{n}. Run `git status` and `git log` first, check what the earlier session already did, "
               "and continue from it without redoing it.")
HELD_NOTE = " The fresh reader held this story. Fix its latest finding on this branch, unless a later commit already did:\n{finding}\n"


def resume_worktree(repo: Path, wt: Path, n: str, base: str = "") -> tuple[list[str], str]:
    """Make story/N's worktree for a builder (#877). A fresh story gets a new branch from base. When the branch or worktree already exists
    (an earlier session stopped), the branch is reused: the worktree is attached when missing, commits and uncommitted changes stay, and the
    branch is rebased onto base when that is clean. Returns (problems, note for the builder's brief), the note empty for a fresh story."""
    base = base or f"origin/{agent_loop.default_branch(repo)}"
    first = add_worktree(repo, wt, n, base)
    if not first or "already" not in first[0]:
        return first, ""
    branch = f"story/{n}"
    if not (wt / ".git").exists():
        gitfiles.run(repo, "worktree", "prune")
        made = gitfiles.run(repo, "worktree", "add", str(wt), branch)
        if made.returncode:
            return [f"the worktree was not attached to {branch}: {(made.stderr or made.stdout).strip()}"], ""
    problems = prepare_worktree(wt, repo)
    note = RESUME_NOTE.format(n=n)
    if gitfiles.run(wt, "merge-base", "--is-ancestor", base, "HEAD").returncode == 0:
        return problems, note
    if gitfiles.run(wt, "rebase", "--autostash", base).returncode:
        gitfiles.run(wt, "rebase", "--abort")
        note += f" The branch conflicts with {base}, so it was left where it was and not rebased."
    else:
        note += f" The branch was rebased onto {base}."
    return problems, note


def _main_checkout(wt: Path) -> Path | None:
    common = gitfiles.run(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return Path(common).parent if common else None


def squash(wt: Path, story: str, log) -> bool:
    """Replace a branch's commits on top of origin/main with one commit holding the same tree, so main gains one commit per story (#898).
    Its message is the first commit's subject with the story number. A branch of one commit keeps its own message. Returns False when the squash failed."""
    subjects = gitfiles.run(wt, "log", "--reverse", "--format=%s", f"origin/{agent_loop.default_branch(wt)}..HEAD").stdout.splitlines()
    if len(subjects) < 2:
        return True
    title = re.sub(r"\s*\(#\d+\)\s*$", "", subjects[0]).strip() or f"Story {story}"
    tree = gitfiles.run(wt, "rev-parse", "HEAD^{tree}").stdout.strip()
    made = gitfiles.run(wt, "commit-tree", tree, "-p", f"origin/{agent_loop.default_branch(wt)}", "-m", f"{title} (#{story})")
    new = made.stdout.strip()
    if made.returncode or not new or gitfiles.run(wt, "reset", "--soft", new).returncode:
        log.write(f"--- squash failed: {made.stderr.strip()}\n")
        return False
    log.write(f"--- squashed {len(subjects)} commits into {new[:8]}\n")
    return True


def refusal(wt: Path) -> tuple[str, str]:
    """(result word, message) when wt must not land: it holds uncommitted files, which the push would leave behind, or it has no validation command,
    which no run can pass (#1011). ("", "") when it may land."""
    dirty = [line[3:] for line in gitfiles.run(wt, "status", "--porcelain").stdout.splitlines() if line.strip()]
    if dirty:
        return "dirty-worktree", f"Refused: {wt} has uncommitted files, so nothing landed: {', '.join(dirty[:10])}. Commit them by explicit path or remove them."
    if agent_loop.validation_command(wt) is None:
        return "no-validate", f"Refused: {wt} has no validation command, so nothing can check the commit and it is not read as done. Fix: {agent_loop.NO_VALIDATION_FIX}"
    return "", ""


def _story_slug(wt: Path) -> str:
    """owner/name of the repo the story lives in: the origin remote names it, so a fork's inherited config does not (#754, #1012). "" when none is found."""
    main = _main_checkout(wt) or wt
    try:
        origin = backlog_setup.origin_owner_name(main)
        if origin:
            return f"{origin[0]}/{origin[1]}"
        cfg = local_config.backlog_config(main)
        return f"{cfg['repoOwner']}/{cfg['repoName']}"
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def _gh(*args: str) -> str | None:
    """The output of one `gh api` REST call, which spends no GraphQL points (#1073). None when it fails."""
    try:
        done = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def story_body(wt: Path, story: str) -> str | None:
    """The story's body, or None when it cannot be read."""
    slug = _story_slug(wt)
    return _gh(f"repos/{slug}/issues/{story}", "--jq", '.body // ""') if slug else None


def _story_comment(wt: Path, story: str, text: str, told: set[str]) -> None:
    """Post text on the story unless this land already did, as `told` records, so a retry repeats no comment. A failed post changes nothing about
    the landing, whose log already says it (#1073)."""
    if text not in told and (slug := _story_slug(wt)):
        told.add(text)
        _gh(f"repos/{slug}/issues/{story}/comments", "-f", f"body={text}")


def pending_step(wt: Path, story: str, body: str, log) -> None:
    """For a body with an after-landing section, queue one open owner line naming the story and the step, and say it in the log and on the terminal
    (#1566). Its key is its own, so it never holds back the story's stop line. The push is done, so a queue that cannot be written fails nothing."""
    found = AFTER_LANDING.findall(body)
    if not found:
        return
    step = " ".join(" ".join(found).split()).strip(" :*")[:300] or "read it in the story"
    key = f"after-landing:{_story_slug(wt)}#{story}"
    line = f"{PENDING} for story #{story}: {step}"
    try:
        if not any(i["status"] == "open" and i.get("key") == key for i in cmd_owner.items()):
            try:
                cmd_owner.add("land", line, extra={"key": key})
            except ValueError:  # the queue refuses text that reads as a secret, so the line points at the story instead
                line = f"{PENDING} for story #{story}: read it in the story"
                cmd_owner.add("land", line, extra={"key": key})
    except OSError as exc:
        line += f" (no owner line was written: {exc})"
    log.write(line + "\n")
    print(line, flush=True)


def _changed_lines(diff: str) -> list[tuple[str, int, str, str, int]]:
    """(path, line, sign, text, was) for each changed line of a zero-context diff. The line is its number in the file after the commit, so a
    removed line names the spot it left (#1073). `was` is a removed line's number in the file before the commit, and 0 for an added one (#1484)."""
    rows, old, path, new, was, header = [], "", "", 0, 0, False
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            header = True
        elif header and raw.startswith("--- "):
            old = raw[6:] if raw.startswith("--- a/") else ""
        elif header and raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else old
        elif raw.startswith("@@"):
            header, new = False, max(1, int(re.search(r"\+(\d+)", raw).group(1)))  # git writes +0 for a removal before line 1
            was = int(re.search(r"-(\d+)", raw).group(1))
        elif raw.startswith("+"):
            rows.append((path, new, "+", raw[1:], 0))
            new += 1
        elif raw.startswith("-"):
            rows.append((path, new, "-", raw[1:], was))
            was += 1
    return rows


def _test_functions(source: str) -> dict[str, tuple[int, int]] | None:
    """{`name` or `Class::name`: (first line, last line)} of each function in a Python file, decorators included. None when it does not parse."""
    try:
        todo = [("", ast.parse(source))]
    except (SyntaxError, ValueError):
        return None
    found = {}
    while todo:
        prefix, node = todo.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix + child.name] = (min(n.lineno for n in [child, *child.decorator_list]), child.end_lineno)
            else:
                todo.append((f"{prefix}{child.name}::" if isinstance(child, ast.ClassDef) else prefix, child))
    return found


def _removed_whole(wt: Path, since: str, declared: list[str]) -> tuple[list[str], dict[str, set[int]]]:
    """(the declared tests this commit deletes whole, {file: the base line numbers of the assertions in them}) (#1484). A test is deleted whole
    when exactly one function on the base answers to its name, none in the commit does and the commit adds none of its bare name, so a test that
    stays, moves to another class or shares its name excuses nothing; `Class::name` tells two of one name apart.
    shortcut: only Python files parse, so a declared test in another language is still refused; upgrade when a story has to remove one."""
    gone, excused = [], {}
    for entry in declared:
        path, _, name = entry.partition("::")
        before = gitfiles.run(wt, "show", f"{since}:{path}").stdout
        old, new = _test_functions(before), _test_functions(gitfiles.run(wt, "show", f"HEAD:{path}").stdout)  # a deleted file reads as empty
        if old is None or new is None:
            continue
        was, left = ([q for q in found if q == name or q.endswith(f"::{name}")] for found in (old, new))
        if len(was) != 1 or left or any(q.split("::")[-1] == was[0].split("::")[-1] for q in new.keys() - old.keys()):
            continue
        first, last = old[was[0]]
        lines = before.split("\n")
        gone.append(entry)
        excused.setdefault(path, set()).update(n for n in range(first, last + 1) if ASSERT.search(lines[n - 1]))
    return gone, excused


def weakened(rows: list[tuple[str, int, str, str, int]], excused: dict[str, set[int]] | None = None) -> list[str]:
    """What in a commit weakens a test, each as `file:line reason` (#1073): a skip added to a test file, `|| true` added to a test or validation
    file, or assertions removed from a test file net of the ones added to it. Assertions may go when the commit deletes more non-blank code
    outside the tests than it adds there, since that is the code they covered. A one-line edit nets to zero, so it covers nothing.
    `excused` holds the assertion lines of the declared tests the commit deletes whole. Only those the diff removes are left out of the count, and an
    added assertion with the text of one is that line moved, so it makes up for no other removal (#1484)."""
    found, lost, excused = [], {}, excused or {}
    moved = Counter(text.strip() for path, _, sign, text, was in rows if sign == "-" and ASSERT.search(text) and was in excused.get(path, ()))
    code = [sign for path, _, sign, text, _ in rows if not TEST_FILE.search(path) and text.strip()]
    net_code = code.count("-") - code.count("+")
    for path, line, sign, text, was in rows:
        test = TEST_FILE.search(path)
        if sign == "+" and test and SKIP.search(text):
            found.append(f"{path}:{line} adds a skip")
        if sign == "+" and (test or VALIDATION_FILE.search(path)) and OR_TRUE.search(text):
            found.append(f"{path}:{line} adds || true to a test command")
        if test and ASSERT.search(text) and not (sign == "-" and was in excused.get(path, ())):
            if sign == "+" and moved[text.strip()]:
                moved[text.strip()] -= 1
                continue
            first, net = lost.get(path, (None, 0))
            if sign == "-" and first is None:
                first = line
            lost[path] = (first, net + (1 if sign == "-" else -1))
    if net_code <= 0:
        found += [f"{path}:{first} removes {net} assertion(s) without removing the code they cover" for path, (first, net) in lost.items() if net > 0]
    return found


def weakening(wt: Path, since: str, body: str) -> tuple[str, list[str]]:
    """(the refusal of the commit since `since` for a weakened test, or "", the tests the story names that it deletes whole). The drain's loop asks it
    of the merge base before the reader (#1551), and land asks it of the base it rebased on."""
    area, declared = intake.files_area(body), intake.removed_tests(body)
    # a Removes tests entry excuses a test only in a file the Files area lists by name, and a test file listed nowhere there refuses the commit (#1484)
    unlisted = [p for p in dict.fromkeys(entry.partition("::")[0] for entry in declared) if p not in area]
    gone, excused = _removed_whole(wt, since, declared)
    found = [f"{p} is on the Removes tests line and the Files area does not list it" for p in unlisted]
    found += weakened(_changed_lines(gitfiles.run(wt, "diff", "--no-renames", "--no-ext-diff", "-U0", since, "HEAD").stdout), excused)
    return f"Refused: this commit weakens a test, so nothing landed: {'; '.join(found)}." if found else "", gone


def land(wt: Path, story: str, log) -> tuple[str, str]:
    """Run the landing recipe in wt, writing to log. Returns (result word, short sha)."""
    word, why = refusal(wt)
    if word:
        log.write(why + "\n")
        return word, ""
    main = _main_checkout(wt)
    if main and main != wt and link_venv(main, wt):
        log.write(f"linked the dependency folders of {main} into {wt}\n")
    base = agent_loop.default_branch(wt)
    body = story_body(wt, story)
    if body is None:
        log.write(f"Refused: story #{story} could not be read over REST, so its Files area is unknown and nothing landed.\n")
        return "scope-unchecked", ""
    area = intake.files_area(body)
    deadline, attempt, told = time.monotonic() + BUDGET, 0, set()
    while attempt < TRIES or time.monotonic() < deadline:
        if attempt >= TRIES:
            log.write("--- main moved again, waiting to retry\n")
            log.flush()
            time.sleep(PAUSE)
        attempt += 1
        _run(wt, log, "git", "fetch", "-q", "origin")
        if not _run(wt, log, "git", "rebase", f"origin/{base}"):
            _run(wt, log, "git", "rebase", "--abort")
            return "rebase-conflict", ""
        if not squash(wt, story, log):
            return "squash-failed", ""
        # a file outside the Files area is named and still lands: refusing it made every restart repeat the edit, and the reader judges it (#1073)
        outside = [p for p in gitfiles.run(wt, "diff", "--name-only", "--no-renames", f"origin/{base}", "HEAD").stdout.splitlines()
                   if area and not intake.in_area(p, area)]
        if outside:
            names = ", ".join(outside)
            log.write(f"Note: this commit changes {names}, outside story #{story}'s Files area ({', '.join(area)}).\n")
            _story_comment(wt, story, f"This commit changes files outside the Files area: {names}. The Files area is {', '.join(area)}.", told)
        refused, gone = weakening(wt, f"origin/{base}", body)
        if refused:
            log.write(refused + "\n")
            return "weakened-test", ""
        if gone:
            names = ", ".join(gone)
            log.write(f"Removed tests that story #{story} names: {names}.\n")
            _story_comment(wt, story, f"This commit removes the tests the story names: {names}.", told)
        tree = gitfiles.run(wt, "rev-parse", "HEAD^{tree}").stdout.strip()
        passed = validated.recorded_pass(tree) if tree else None  # a pass on record for this tree stands; a rebase that changed it has none (#910)
        if passed:
            log.write(f"--- tree {tree[:12]} passed validation at {passed['time']}, so land reuses that record and does not validate again\n")
        elif not _validates(wt, log):
            return "validate-failed", ""
        _run(wt, log, "git", "fetch", "-q", "origin")
        if not _run(wt, log, "git", "merge-base", "--is-ancestor", f"origin/{base}", "HEAD"):
            continue
        if _run(wt, log, "git", "push", "origin", f"HEAD:{base}", env={**os.environ, "ALLOW_BRANCH_PUSH": "1"}):  # land pushes only its own landing branch, which may be the owner's engineBranch (#1293)
            sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=wt, capture_output=True, text=True).stdout.strip()
            pending_step(wt, story, body, log)
            return "pushed", sha
        _run(wt, log, "git", "fetch", "-q", "origin")
        if _run(wt, log, "git", "merge-base", "--is-ancestor", f"origin/{base}", "HEAD"):
            return "push-failed", ""  # main did not move, so the push error in the log is the reason (#851)
    return "main-kept-moving", ""


def stack(items: list[tuple[Path, str]], say=print) -> bool:
    """Stack the commits of several finished stories on the landing branch in a scratch worktree, run the repo's quick validation once on the stack,
    and record that pass for the tree after each story, so each story's own land reuses it and validates nothing again (#1317). The stories' worktrees are
    never touched. A story whose commits conflict with the stack is left out and lands alone. Returns True when two or more stories stacked and the
    stack passed. On False nothing is recorded, so each land validates its own story.
    shortcut: a pass is recorded for each intermediate tree without running it, since the tip's pass covers them, and a story that breaks only a
    middle tree lands anyway; upgrade when the landing branch must pass at every commit."""
    main, base = _main_checkout(items[0][0]), agent_loop.default_branch(items[0][0])
    if not main:
        return False
    with tempfile.TemporaryDirectory(prefix="land-stack-") as tmp:
        scratch = Path(tmp)
        gitfiles.run(main, "fetch", "-q", "origin")
        if gitfiles.run(main, "worktree", "add", "--detach", tmp, f"origin/{base}").returncode:
            return False
        try:
            trees: list[str] = []
            for wt, story in items:
                first = gitfiles.run(wt, "merge-base", "HEAD", f"origin/{base}").stdout.strip()
                head = gitfiles.run(wt, "rev-parse", "HEAD").stdout.strip()
                if not first or not head or gitfiles.run(scratch, "cherry-pick", f"{first}..{head}").returncode:
                    gitfiles.run(scratch, "cherry-pick", "--abort")
                    say(f"Story #{story} does not stack on the others, so it lands alone.")
                    continue
                trees.append(gitfiles.run(scratch, "rev-parse", "HEAD^{tree}").stdout.strip())
            if len(trees) < 2:
                return False
            link_venv(main, scratch)
            passed, tail = agent_loop.validate(scratch)
            say(f"A batch of {len(trees)} stories {'passed' if passed else 'failed'} its one validation." + ("" if passed else f"\n{tail}"))
            if passed:
                for tree in trees[:-1]:
                    validated.record(scratch, tree)
            return passed
        finally:
            gitfiles.run(main, "worktree", "remove", "--force", tmp)


def cleanup(wt: Path) -> list[str]:
    """Delete a landed story's worktree, local branch and remote branch. Returns one line per thing removed or kept and why.
    Nothing is removed while the worktree has uncommitted changes or a commit that is not on origin/main, and main is never touched."""
    branch = gitfiles.run(wt, "branch", "--show-current").stdout.strip()
    common = gitfiles.run(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    if not common or gitfiles.run(wt, "merge-base", "--is-ancestor", "HEAD", f"origin/{agent_loop.default_branch(wt)}").returncode != 0:
        return [f"Kept {wt}: it has commits that are not on origin/{agent_loop.default_branch(wt)}."]
    if gitfiles.run(wt, "status", "--porcelain").stdout.strip():
        return [f"Kept {wt}: it has uncommitted changes."]
    lines = []
    gone = gitfiles.run(Path(common), "worktree", "remove", str(wt))
    lines.append(f"Removed worktree {wt}." if gone.returncode == 0 else f"Kept {wt}: {gone.stderr.strip()[:100]}")
    if gone.returncode != 0 or not branch or branch in {"main", "master", "develop"}:
        return lines
    if gitfiles.run(Path(common), "branch", "-D", branch).returncode == 0:
        lines.append(f"Deleted local branch {branch}.")
    if gitfiles.run(Path(common), "ls-remote", "--exit-code", "--heads", "origin", branch).returncode == 0:
        done = gitfiles.run(Path(common), "push", "origin", "--delete", branch)
        lines.append(f"Deleted remote branch {branch}." if done.returncode == 0 else f"Remote branch {branch} stays: {done.stderr.strip()[:100]}")
    return lines


def _repo_name(wt: Path) -> str:
    main = _main_checkout(wt)
    return (main or wt).name


def log_dir() -> Path:
    return LOG_DIR or failure_log.home() / "land"


def cut_running(directory: Path) -> int | None:
    """The pid the version cut lock names when that process is alive and is not this one."""
    try:
        pid = int((directory / CUT_LOCK).read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if pid != os.getpid() and run_lock.pid_alive(pid) else None


@contextlib.contextmanager
def _claim(lock: Path):
    """Hold the story's lock while the block runs (#880). Yields "" once it is held here, else the pid of the land that holds it. The kernel drops a
    flock when its holder exits, so no lock goes stale. The file stays, since removing it would let two lands each lock their own copy."""
    with open(lock, "a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            yield handle.read().strip() or "unknown"
            return
        handle.truncate(0)
        handle.write(str(os.getpid()))
        handle.flush()
        yield ""


def _stamp(at: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))


def log_chat_build(wt: Path, story: str, session: str, size: str, began: float) -> None:
    """Write a chat build's run-log rows (#1533): claimed, the lead thread's tokens, one row per subagent transcript, and landed, from BEGAN (the branch's first reflog entry) to now.
    The rows carry no cost_usd, since a transcript holds no price, and a `round` so status counts their tokens."""
    key, repo, end = f"story-{story}", _repo_name(wt), time.time()
    agent_loop.STORY_SIZE[key] = size
    agent_loop.log_stage(key, repo, "claimed", runner="thread", at=_stamp(began))  # the claim is when the window began, so time to land is not zero
    lead = usage_sessions.transcript(session)
    if lead:
        for runner, path in [("thread", lead), *(("subagent", p) for p in sorted((lead.parent / session / "subagents").rglob("*.jsonl")))]:  # a workflow's agents sit a folder deeper
            tokens = usage_sessions.usage_between(path, began, end)
            if tokens["model"]:
                agent_loop.append_run_log({"story": key, "repo": repo, "runner": runner, "round": 1, "size": size, "at": _stamp(end), **tokens})
    agent_loop.log_stage(key, repo, "landed", started_at=began, runner="thread")


def _began(wt: Path) -> float:
    """When the worktree's branch got its first reflog entry, as epoch seconds; now when it has none."""
    entries = gitfiles.run(wt, "reflog", "show", "--date=unix", "--format=%gd", "HEAD").stdout.split()  # HEAD@{seconds}: the entry's own time, not its commit's
    return float(entries[-1].partition("{")[2].rstrip("}")) if entries else time.time()


def command_land(argv: list[str]) -> int:
    session = ""
    if len(argv) == 4 and argv[2] == "--session":
        session, argv = argv[3], argv[:2]
    if len(argv) != 2 or argv[0].startswith("-") or not argv[1].lstrip("#").isdigit() or not (Path(argv[0]) / ".git").exists():
        print(USAGE)
        return 2
    wt, story = Path(argv[0]).resolve(), argv[1].lstrip("#")
    folder = log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    while cut_running(folder):  # a land waits until a running version cut finishes (#789)
        time.sleep(PAUSE)
    began = _began(wt)
    key = f"{_repo_name(wt)}-{story}"
    path = folder / f"land-{key}.log"
    with _claim(folder / f"land-{key}.lock") as running:
        if running:
            print(f"A land for story #{story} is already running (pid {running}). Its log: {path}")
            return 1
        with path.open("w") as log:
            result, sha = land(wt, story, log)
            line = f"RESULT {result} {sha}".strip()
            log.write(line + "\n")
    print(f"{line} (log: {path})")
    if session and result == "pushed":
        log_chat_build(wt, story, session, intake.size_of({"body": story_body(wt, story) or ""}), began)
    if result in ("dirty-worktree", "no-validate"):
        print(refusal(wt)[1])
    if result != "pushed":
        print(f"No branch was pushed. The work stays in {wt}.")
        return 1
    root, branch = _main_checkout(wt) or OC_ROOT, agent_loop.default_branch(wt)  # read before cleanup removes the worktree
    for line in cleanup(wt):
        print(line)
    behind, state, moved = maintain.fast_forward(root, fetch=True, branch=branch)  # the story's own repo, never OliverCode's checkout (#1012)
    if moved:
        print(f"Main checkout fast-forwarded {behind} commit(s).")
    elif behind:
        print(f"Main checkout left alone: {behind} commit(s) behind origin/{branch} and {state}.")
    return 0


def _rehearse_upgrade(repo: Path, wt: Path, head: str) -> tuple[bool, str]:
    """(passed, output) of the update a main user runs, rehearsed to head in a sandbox HOME by scripts/qa/rehearse-upgrade.sh (#1389)."""
    try:
        ran = subprocess.run(["bash", str(wt / "scripts" / "qa" / "rehearse-upgrade.sh"), str(repo), head], capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as err:
        return False, f"the rehearsal could not run: {err}"
    return ran.returncode == 0, (ran.stdout + ran.stderr).strip()


def _ci_refusal(slug: str, sha: str) -> str:
    """The check and its state when CI has not passed on sha, else "" (#1305)."""
    try:
        runs = json.loads(_gh(f"repos/{slug}/commits/{sha}/check-runs?per_page=100") or "")["check_runs"]
    except (ValueError, KeyError):
        runs = None
    if runs is None:
        return f"Refused: CI on {sha[:8]} could not be read, so nothing was promoted."
    for r in runs:
        if r.get("status") != "completed" or r.get("conclusion") not in ("success", "neutral", "skipped"):
            return f"Refused: CI check {r.get('name')} is {r.get('conclusion') or r.get('status')} on {sha[:8]}, so nothing was promoted."
    return "" if runs else f"Refused: CI has no check on {sha[:8]}, so nothing was promoted."


def promote(repo: Path, say=print) -> int:
    """Fast-forward main to staging's head after CI and one validation, so every story keeps its own commit, and label each story it carries `on-main`.
    The stories closed when they landed on staging, so none is reopened or closed again (#1305). Everything that can refuse runs before the push, so a
    refusal leaves main, staging and every label as they were."""
    staging, slug = local_config.setting("engineBranch") or "", _story_slug(repo)
    if not staging or not agent_loop.is_engine_repo(repo):
        say("Refused: promote moves the owner's engineBranch to main, and this machine's settings name none for this repo.")
        return 1
    if slug and run_lock.active(slug):
        say("Refused: a drain is running in this repo, which would slow the timings. Stop it or wait until it ends.")
        return 1
    if gitfiles.run(repo, "fetch", "-q", "origin").returncode:
        say("Refused: git fetch origin failed, so staging and main are unknown.")
        return 1
    main = "main"  # shortcut: promote targets main by name, the story's own word for it; upgrade when a repo promotes to another branch
    if gitfiles.run(repo, "merge-base", "--is-ancestor", f"origin/{main}", f"origin/{staging}").returncode:
        say(f"Refused: origin/{main} has a commit origin/{staging} lacks, so nothing was pushed. Merge {main} into {staging} first.")
        return 1
    ahead = gitfiles.run(repo, "log", "--reverse", "--no-merges", "--format=%s", f"origin/{main}..origin/{staging}").stdout.splitlines()
    if not ahead:
        say(f"origin/{staging} holds nothing that origin/{main} lacks, so nothing was promoted.")
        return 0
    head = gitfiles.run(repo, "rev-parse", f"origin/{staging}").stdout.strip()
    why = _ci_refusal(slug, head)
    if why:
        say(why)
        return 1
    stories = list(dict.fromkeys(m.group(1) for s in ahead if (m := re.search(r"\(#(\d+)\)\s*$", s))))
    with tempfile.TemporaryDirectory(prefix="olivercode-promote-") as tmp:
        wt = Path(tmp)
        try:
            if gitfiles.run(repo, "worktree", "add", "-q", "--detach", str(wt), f"origin/{main}").returncode:
                say("Refused: a worktree for the promotion could not be made.")
                return 1
            link_venv(repo, wt)
            took = []
            for ref, label in ((f"origin/{main}", main), (head, staging)):
                gitfiles.run(wt, "checkout", "-q", "--detach", ref)
                began = time.monotonic()
                passed, tail = agent_loop.validate(wt)
                took.append(time.monotonic() - began)
                if not passed:
                    say(f"Refused: {label} quick validation:\n{tail}")
                    return 1
            main_s, stg_s = took
            if stg_s >= main_s * SLOWER:
                say(f"Staging is slower than main, so nothing was promoted: {staging} took {stg_s:.0f}s and {main} took {main_s:.0f}s (limit {SLOWER}x).")
                return 1
            rehearsed, said = _rehearse_upgrade(repo, wt, head)
            if not rehearsed:
                say(f"Refused: a main user's update to {staging} fails in a sandbox, so nothing was promoted.\n{said}")
                return 1
            passed, tail = agent_loop.validate(wt)
            if not passed:
                say(f"Refused: the repo's validation failed on {staging}, so nothing was promoted. Failing gate output:\n{tail}")
                return 1
            env = {**os.environ, "ALLOW_BRANCH_PUSH": "1"}
            old = gitfiles.run(repo, "rev-parse", f"origin/{main}").stdout.strip()
            archive = f"archive/{main}-{time.strftime('%Y-%m-%d')}"
            if subprocess.run(["git", "-C", str(wt), "push", "origin", f"{old}:refs/tags/{archive}"], env=env, capture_output=True, text=True).returncode:
                say(f"Refused: the tag {archive} could not be pushed at main's old head, so main was not moved and nothing was promoted.")
                return 1
            if subprocess.run(["git", "-C", str(wt), "push", "origin", f"{head}:refs/heads/{main}"], env=env, capture_output=True, text=True).returncode:
                say(f"Refused: origin/{main} moved or rejected the push, so nothing was promoted. Run promote again.")
                return 1
            names = ", ".join(f"#{n}" for n in stories) or "no numbered story"
            say(f"{main} fast-forwarded to {head[:8]}, which carries {names}.")
            unlabeled = [n for n in stories if _gh(f"repos/{slug}/issues/{n}/labels", "-f", "labels[]=on-main") is None]
            if unlabeled:
                say("These stories lack on-main (GitHub may be rate limited; queue with `olivercode gh-limit queue -- gh ...`): " + ", ".join(f"#{n}" for n in unlabeled))
                return 1
            say(f"{len(stories)} stories carry on-main.")
            return 0
        finally:
            gitfiles.run(repo, "worktree", "remove", "--force", tmp)


def command_promote(argv: list[str]) -> int:
    if argv:
        print("Usage: olivercode promote")
        return 2
    top = gitfiles.run(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip()
    if not top:
        print("Refused: promote runs inside the OliverCode checkout.")
        return 1
    return promote(Path(top))

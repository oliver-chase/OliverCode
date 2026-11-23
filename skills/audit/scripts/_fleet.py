"""The fleet root, the skill walk and the scan-root argument that the audit scripts share."""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT_ENV = "SKILL_FLEET_ROOT"
NON_SKILL_DIRS = {"docs"}


def fleet_root(environ=None):
    """The folder that holds the skills: `$SKILL_FLEET_ROOT` when set, else the skills folder
    this skill sits in, two folders above `scripts/`."""
    environ = os.environ if environ is None else environ
    return Path(environ[ROOT_ENV]).expanduser() if environ.get(ROOT_ENV) else Path(__file__).resolve().parents[2]


FLEET_ROOT = fleet_root()
TEST = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*$|_test\.[^/]*$|\.(?:test|spec)\.[^/]*$")


def is_test(rel):
    """Whether a repo-relative path is a test file."""
    return bool(TEST.search(rel))


def personal_repos():
    """Names listed under `personalRepos` in olivercode.local.json (git-ignored, so a name stays on this machine). Those repos are left out of every fleet audit. A copy of this skill outside a checkout skips nothing."""
    lib = Path(__file__).resolve().parents[3] / "scripts"
    if not (lib / "lib" / "local_config.py").is_file():
        return set()
    sys.path.insert(0, str(lib))
    try:
        from lib import local_config
        return set(local_config.load_local().get("personalRepos", []))
    except Exception:  # noqa: BLE001 -- fail open, a config bug never stops an audit
        return set()
    finally:
        sys.path.remove(str(lib))


def archived_state(repo):
    """"archived" or "deleted" when GitHub says the repo is, else None. The check lives in OliverCode's
    scripts/lib/repo_state.py; a copy of this skill outside a checkout has no lookup and skips nothing."""
    lib = Path(__file__).resolve().parents[3] / "scripts"
    if not (lib / "lib" / "repo_state.py").is_file():
        return None
    sys.path.insert(0, str(lib))
    try:
        from lib import repo_state
        return repo_state.archived(repo)
    except Exception:  # noqa: BLE001 -- fail open, a lookup bug never stops an audit
        return None
    finally:
        sys.path.remove(str(lib))


def read(repo, rel):
    """A repo file's text, or "" when it cannot be read as UTF-8."""
    try:
        return (Path(repo) / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def git(repo, *args):
    """The output of `git -C repo ...`, or "" when git fails."""
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ""


def tracked(repo):
    """Tracked files of a git repo that exist on disk. Outside git, every file under `repo` except hidden ones."""
    done = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True)
    if done.returncode:
        root = Path(repo)
        return sorted(str(p.relative_to(root)) for p in root.rglob("*")
                      if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts))
    return [f for f in done.stdout.splitlines() if (Path(repo) / f).is_file()]


def scan_root(argv, default=FLEET_ROOT):
    """The first argument that is not a flag, else `default`. Call it from `main()`: an import
    must never read `sys.argv`, because a test runner's own arguments would become the root."""
    paths = [a for a in argv if not a.startswith("--")]
    return Path(paths[0]) if paths else default


def find_skills(root):
    """Every skill folder under `root`, sorted: `root` itself when it holds a SKILL.md, a folder
    directly in it, or a folder one level inside a family folder. Nothing deeper counts, so a
    skill's own sub-folders never read as skills."""
    root = Path(root)
    if (root / "SKILL.md").is_file():
        return [root]
    skills = []
    for family in sorted(root.iterdir()) if root.is_dir() else []:
        if not family.is_dir() or family.name in NON_SKILL_DIRS or family.name.startswith("."):
            continue
        if (family / "SKILL.md").is_file():
            skills.append(family)
            continue
        skills += [d for d in sorted(family.iterdir())
                   if d.is_dir() and not d.name.startswith(".") and (d / "SKILL.md").is_file()]
    return skills


def description_text(skill_md_text):
    """The frontmatter `description`, whether it is a quoted line or a folded block. The one parser for it."""
    m = re.search(r"^description:\s*(.*?)(?=^\w[\w-]*:|^---)", skill_md_text, re.S | re.M)
    return m.group(1).strip() if m else ""


def description_words(skill_md_text):
    """Words in the frontmatter `description`."""
    return len(description_text(skill_md_text).lstrip(">|-").split())

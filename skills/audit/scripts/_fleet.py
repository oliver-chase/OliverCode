"""The fleet root, the skill walk and the scan-root argument that the audit scripts share."""

import os
import re
import subprocess
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
    """Whether a repo-relative path is a test file. size.sh keeps the same rule in shell."""
    return bool(TEST.search(rel))


def tracked(repo):
    """Tracked files of a git repo that exist on disk. Exits with one line when `repo` is not a git repo."""
    done = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"{repo} is not a git repo, so there is no tracked-file list")
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


def description_words(skill_md_text):
    """Words in the frontmatter `description`, whether it is a quoted line or a folded block."""
    m = re.search(r"^description:\s*(.*?)(?=^\w[\w-]*:|^---)", skill_md_text, re.S | re.M)
    return len(m.group(1).lstrip(">|-").split()) if m else 0

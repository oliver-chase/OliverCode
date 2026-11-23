"""The fleet root, the skill walk and the scan-root argument that the audit scripts share."""

import json
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


def local_config_path():
    """The settings file: `$OLIVERCODE_LOCAL_CONFIG` when set, else `olivercode.local.json` at the root of the git repo
    this skill sits in, else in the working folder."""
    if os.environ.get("OLIVERCODE_LOCAL_CONFIG"):
        return Path(os.environ["OLIVERCODE_LOCAL_CONFIG"]).expanduser()
    here = Path(__file__).resolve()
    root = next((d for d in here.parents if (d / ".git").exists()), Path.cwd())
    return root / "olivercode.local.json"


def load_local():
    """The settings file's contents, or {} when it is missing or unreadable."""
    try:
        return json.loads(local_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_local(values):
    """Merge `values` into the settings file, keeping every other key."""
    path = local_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**load_local(), **values}, indent=2) + "\n", encoding="utf-8")


def archived_state(repo):
    """"archived" or "deleted" when GitHub says the repo is, else None. It runs OliverCode's scripts/lib/repo_state.py
    as a program when this skill sits in a checkout of it; a copy elsewhere has no lookup and skips nothing."""
    script = Path(__file__).resolve().parents[3] / "scripts" / "lib" / "repo_state.py"
    if not script.is_file():
        return None
    try:
        done = subprocess.run([sys.executable, str(script), str(repo)], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    state = done.stdout.strip().splitlines()[-1:] or [""]
    return state[0] if done.returncode == 0 and state[0] in ("archived", "deleted") else None


def validation_command(repo):
    """The repo's own validation: scripts/validate.sh, else its package's validate script, else its check script."""
    repo = Path(repo)
    if (repo / "scripts/validate.sh").exists():
        return "bash scripts/validate.sh"
    try:
        scripts = json.loads((repo / "package.json").read_text(encoding="utf-8")).get("scripts", {})
    except (OSError, ValueError):
        scripts = {}
    return "npm run check" if "validate" not in scripts and "check" in scripts else "npm run validate"


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

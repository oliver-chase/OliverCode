"""Launcher commands that read or stamp one repo: skills, discover and bootstrap."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from lib.cli import reject_extra as _reject_extra
from lib import repo_gates, repo_state
from lib.local_config import OC_ROOT, claude_dir as _claude_dir
from lib.repo_profiles import REGISTRY_NAME, registry_file, registry_write_file
from lib.skills_catalog import _load_skills


def command_skills(argv: list[str]) -> int:
    """List every skill under skills/, optionally filtered by --grep TERM."""
    term = None
    rest = list(argv)
    if "--grep" in rest:
        idx = rest.index("--grep")
        if idx + 1 >= len(rest):
            print("Error: --grep requires a search term.")
            return 1
        term = rest[idx + 1].lower()
        del rest[idx : idx + 2]
    _reject_extra("skills", rest)

    skills = _load_skills(OC_ROOT)
    if not skills:
        print("No skills found under skills/.")
        return 1

    if term:
        skills = [(n, d) for n, d in skills if term in n.lower() or term in d.lower()]
        if not skills:
            print(f"No skills match '{term}'.")
            return 0

    width = max((len(n) for n, _ in skills), default=0)
    for name, description in skills:
        summary = description if len(description) <= 100 else description[:97] + "..."
        print(f"{name:<{width}}  {summary}")
    print(f"\n{len(skills)} skill(s).")
    return 0


def _report_claude_dir(oc_root: Path) -> None:
    """Inventory ~/.claude, classifying what is OliverCode's and what is not.

    An existing setup accumulates a mix: symlinks into this checkout, symlinks into
    somewhere else entirely, real directories holding untracked content, and broken
    links pointing at things that moved. `install` only manages the first kind and
    deliberately leaves the rest alone -- which is safe, but silent. Adoption needs the
    full picture, because the foreign and real entries are exactly the ones a human has
    to make a decision about.
    """
    claude_dir = _claude_dir()
    print("\n~/.claude inventory")
    print("-" * 40)
    if not claude_dir.is_dir():
        print("  not present — `olivercode install` creates it")
        return

    rules = claude_dir / "CLAUDE.md"
    if rules.is_symlink():
        target = rules.resolve()
        owner = "OliverCode" if Path(target).is_relative_to(oc_root) else f"elsewhere -> {target}"
        print(f"  CLAUDE.md   symlink ({owner})")
    elif rules.is_file():
        print("  CLAUDE.md   REAL FILE — `install` backs it up and keeps it")
    else:
        print("  CLAUDE.md   absent")

    skills_dir = claude_dir / "skills"
    if not skills_dir.is_dir():
        print("  skills/     absent")
        return

    ours, foreign, real, broken = [], [], [], []
    for entry in sorted(skills_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_symlink():
            if not entry.exists():
                broken.append(entry.name)
            elif entry.resolve().is_relative_to(oc_root):
                ours.append(entry.name)
            else:
                foreign.append((entry.name, entry.resolve()))
        elif entry.is_dir():
            real.append(entry.name)

    print(f"  skills/     {len(ours)} linked to this checkout, {len(foreign)} linked elsewhere, "
          f"{len(real)} real dirs, {len(broken)} broken")
    if foreign:
        print("\n  Symlinked outside this checkout — fine if deliberate (personal/business")
        print("  skills belong in your own area per docs/RULES.md):")
        for name, target in foreign:
            print(f"    {name} -> {target}")
    if real:
        print("\n  Real directories, untracked by any repo. `install` does NOT touch these.")
        print("  Vendor skills are the usual reason; anything else is content with no backup:")
        for name in real:
            print(f"    {name}")
    if broken:
        print("\n  BROKEN — the target moved or was deleted. `olivercode health` FAILs on these:")
        for name in broken:
            print(f"    {name}")


_NOISE = {"node_modules", ".next", "vendor", "worktrees", "_worktrees"}


def _git_entries(root: Path):
    """Every `.git` file or folder under root, never descending into vendored or nested-checkout noise or into a `.git` folder."""
    if _NOISE & set(root.parts):
        return
    for here, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _NOISE]
        if ".git" in dirs:
            dirs.remove(".git")
            yield Path(here) / ".git"
        if ".git" in files:
            yield Path(here) / ".git"


def command_discover(oc_root: Path, roots: list[Path], register: bool = False) -> int:
    """Find git repos under the given roots and report what governance they already have.

    Adoption docs assume you know where your repos are. Someone folding this into an
    existing, un-tidy setup often does not: repos spread over several directories,
    agent-rules files under three different names, hooks installed in some places and
    not others. This is the inventory step made mechanical. It changes no repo. Without
    --register it prints a profile per repo, and with it writes each repo that is not yet
    registered into the registry, with the validation command the repo itself names.
    """
    print("OliverCode discover — " + ("scan and register" if register else "read-only scan"))
    print("=" * 40)
    found: list[tuple[str, Path, str, str]] = []
    for root in roots:
        for git_dir in sorted(_git_entries(root)):
            repo = git_dir.parent
            if git_dir.is_file():
                continue  # a linked worktree points back to its repo through a .git file
            if repo.resolve() == oc_root.resolve():
                continue  # the framework repo governs the fleet; it is not part of it
            if repo_state.skipped(repo.name, repo):
                continue
            rules = next((n for n in ("CLAUDE.md", "AGENTS.md", ".cursorrules") if (repo / n).is_file()), "none")
            hooks = subprocess.run(
                ["git", "-C", str(repo), "config", "--get", "core.hooksPath"],
                capture_output=True, text=True,
            ).stdout.strip() or "unset"
            found.append((repo.name, repo, rules, hooks))

    if not found:
        print("  No git repositories found under: " + ", ".join(str(r) for r in roots))
        return 1

    width = max(len(n) for n, _, _, _ in found)
    for name, repo, rules, hooks in found:
        flag = "" if hooks != "unset" else "   <- ungoverned: git runs no hooks here"
        print(f"  {name:<{width}}  rules={rules:<12} hooksPath={hooks}{flag}")

    print(f"\n{len(found)} repo(s). Rules files named anything other than CLAUDE.md do not")
    print("auto-load in Claude Code — merge them into CLAUDE.md (docs/SETUP.md Step 4).")

    _report_claude_dir(oc_root)
    skeleton = {
        name: {"name": name, "path": str(repo), "canonicalValidationCommand": _validation_command(repo)}
        for name, repo, _, _ in found
    }
    path = registry_file(oc_root)
    if not register:
        print(f"\nProfiles for {registry_write_file(oc_root)}. Run again with --register to add the new ones there:\n")
        print(json.dumps(skeleton, indent=2))
        return 0
    tracked = Path(oc_root) / "shared" / REGISTRY_NAME
    path = registry_write_file(oc_root)
    source = path if path.is_file() else tracked
    data = json.loads(source.read_text()) if source.is_file() else {"profiles": {}}
    profiles = data.setdefault("profiles", {})
    added = [name for name in skeleton if name not in profiles]
    for name in added:
        profiles[name] = skeleton[name]
    path.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(path, 0o600)
    print(f"\nRegistered {len(added)} repo(s) in {path}: {', '.join(added) or 'none new'}.")
    unknown = [n for n in added if profiles[n]["canonicalValidationCommand"] == "<command>"]
    if unknown:
        print(f"Set canonicalValidationCommand by hand for: {', '.join(unknown)}. Nothing in those repos names one.")
    print("Next: `olivercode conform` checks each registered repo.")
    return 0


def _validation_command(repo: Path) -> str:
    """The validation command a repo names itself: scripts/validate.sh, then an npm validate or check script."""
    if (repo / "scripts" / "validate.sh").is_file():
        return "bash scripts/validate.sh"
    try:
        scripts = json.loads((repo / "package.json").read_text()).get("scripts", {})
    except (OSError, ValueError):
        scripts = {}
    for name in ("validate", "check"):
        if name in scripts:
            return f"npm run {name}"
    return "<command>"


def repo_visibility(slug: tuple[str, str] | None) -> tuple[str, str]:
    """The repo's GitHub visibility as ("public" | "private", reason). Anything unreadable is private, the stricter variant."""
    if not slug:
        return "private", "the repo has no origin remote"
    try:
        done = subprocess.run(["gh", "api", f"repos/{slug[0]}/{slug[1]}", "--jq", ".visibility"],
                              capture_output=True, text=True, timeout=30)
        if done.returncode == 0 and done.stdout.strip():
            return ("public" if done.stdout.strip() == "public" else "private"), ""
    except (OSError, subprocess.SubprocessError):
        pass
    return "private", "gh could not read the repo's visibility"


def command_bootstrap(oc_root: Path, target: Path, dry_run: bool) -> int:
    """Stamp the project template into a repo, per shared/project-bootstrap-manifest.json.

    The manifest lists the templated files and the required directories, so a new repo starts
    compliant on day one.

    Honours the manifest's modes: `strict` files are overwritten (their contract is
    byte-identity with the template), `presence` files are only created when missing so
    repo-specific content is never clobbered. `offered` files (CODEOWNERS) are created
    only in a repo that was never bootstrapped, so a repo that dropped them as unused is not told to add them back.
    """
    manifest_path = oc_root / "shared" / "project-bootstrap-manifest.json"
    if not manifest_path.is_file():
        print(f"  [FAIL] manifest not found: {manifest_path}")
        return 1
    manifest = json.loads(manifest_path.read_text())
    repo_gates.hook_templates(oc_root)  # the manifest copies the built hooks

    if not (target / ".git").exists():
        print(f"  [FAIL] {target} is not a git repository.")
        print("         Run `git init` there first — the hooks need a real .git.")
        return 1

    label = "DRY RUN — nothing written" if dry_run else f"stamping into {target}"
    print(f"OliverCode bootstrap — {label}")
    print("=" * 40)

    made_dirs = []
    for rel in manifest.get("requiredDirectories", []):
        d = target / rel
        if not d.is_dir():
            made_dirs.append(rel)
            if not dry_run:
                d.mkdir(parents=True, exist_ok=True)
    if made_dirs:
        print(f"  directories: {', '.join(made_dirs)}")

    # Placeholders the template ships, filled from the target's and this checkout's origin remotes.
    fills = {}
    from lib.backlog_setup import origin_owner_name
    target_origin = origin_owner_name(target)
    if target_origin:
        fills["<your-github-owner>"] = target_origin[0]
    fills["<Repo>"] = target.name
    visibility, why = repo_visibility(target_origin)
    if why: print(f"  pre-commit: private variant written, because {why}.")

    new = overwritten = kept = 0
    first_run = not (target / "QUALITY_BASELINE.md").exists()
    missing_src = []
    for entry in manifest.get("templatedFiles", []):
        src, dst_rel, mode = oc_root / entry["source"], entry["target"], entry.get("mode", "presence")
        if dst_rel == ".githooks/pre-commit" and visibility != "public":
            src = src.with_name("pre-commit-private")
        dst = target / dst_rel
        if not src.is_file():
            missing_src.append(entry["source"])
            continue
        exists = dst.exists()
        if mode == "offered" and (exists or not first_run):
            kept += 1
            continue
        if exists and mode == "presence":
            kept += 1
            continue
        action = "OVERWRITE" if exists else "NEW"
        if exists:
            overwritten += 1
        else:
            new += 1
        print(f"  [{action:<9}] {dst_rel}" + (f"   ({mode})" if exists else ""))
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            for placeholder, value in fills.items():
                data = data.replace(placeholder.encode(), value.encode())
            dst.write_bytes(data)
            if src.suffix == ".sh" or dst_rel.startswith(".githooks/"):
                dst.chmod(0o755)

    print(f"\n  {new} new, {overwritten} overwritten (strict), {kept} kept (presence, already present)")
    for rel in missing_src:
        print(f"  [FAIL] template source missing from this checkout: {rel}")
    from lib import validate_snippet
    line = validate_snippet.report(target.name, *validate_snippet.ensure_queue_snippet(oc_root, target, dry_run), dry_run=dry_run)
    if line:
        print(line)

    if dry_run:
        print("\nRe-run without --dry-run to apply.")
    else:
        print("\nNext: run `olivercode sync-hooks`, which installs the hooks and sets core.hooksPath.")
        if not target_origin:
            print("The repo has no origin remote, so .github/CODEOWNERS still names <your-github-owner>.")
    return 1 if missing_src else 0


def command_place() -> int:
    """`olivercode place`: every repo, worktree and backup is under repoRoot or a named exception."""
    from lib import placement
    cfg = placement.config()
    print(f"OliverCode placement (repoRoot {cfg.root})")
    print("=" * 40)
    found = placement.findings(cfg)
    for f in found:
        print(f"  [FAIL] {f.kind} out of place: {f.path}. {f.fix}")
    if not found:
        print("  [OK] every repo, worktree and backup is under repoRoot")
    return 1 if found else 0


def rebuild_stale_hooks(apply: bool) -> list[str]:
    """Rebuild the hooks of each clean, unmerged worktree whose hooks predate origin/main (#902): rebase it onto origin/main, then build its hooks again.
    A merged worktree is retired by `clean` itself, and a dirty one is kept. A rebase that conflicts is aborted and named."""
    from lib import cmd_land, health_checks, placement
    lines = []
    for wt in placement.worktrees():
        if wt.dirty or wt.merged or not health_checks.stale_hook(wt.path):
            continue
        if not apply:
            lines.append(f"REBUILD {wt.path} (its hooks predate origin/main; run with --apply to rebase it and rebuild them)")
            continue
        rebased = subprocess.run(["git", "-C", str(wt.path), "rebase", "origin/main"], capture_output=True, text=True)
        if rebased.returncode:
            subprocess.run(["git", "-C", str(wt.path), "rebase", "--abort"], capture_output=True)
            lines.append(f"FAILED {wt.path}: the rebase onto origin/main conflicts, so rebase it by hand")
            continue
        problems = cmd_land.prepare_worktree(wt.path)
        lines.append(f"FAILED {wt.path}: {problems[0]}" if problems else f"REBUILT {wt.path} (rebased onto origin/main, hooks built)")
    return lines


def command_clean(apply: bool) -> int:
    """`olivercode clean [--apply]`: remove merged, clean worktrees, rebuild the hooks of stale clean ones and say why the rest stay."""
    from lib import placement
    lines = placement.clean(apply=apply) + rebuild_stale_hooks(apply)
    print("\n".join(lines) if lines else "No linked worktrees found.")
    return 1 if any(line.startswith("FAILED") for line in lines) else 0


def command_worktree(argv: list[str]) -> int:
    """`olivercode worktree add N` makes story N's worktree ready to commit, `fix [PATH]` repairs one made by hand (#786)."""
    from lib import cmd_land, placement
    usage = "Usage: olivercode worktree add N | olivercode worktree fix [PATH]"
    if len(argv) == 2 and argv[0] == "add" and argv[1].isdigit():
        repo = Path(subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True).stdout.strip() or ".git").parent
        wt = placement.config().worktrees / f"{repo.name}-{argv[1]}"
        problems = cmd_land.add_worktree(repo, wt, argv[1])
    elif argv[:1] == ["fix"] and len(argv) <= 2:
        wt = Path(argv[1] if len(argv) > 1 else ".").expanduser().resolve()
        problems = cmd_land.prepare_worktree(wt) if placement.is_worktree(wt) else [f"{wt} is not a linked worktree"]
    else:
        print(usage)
        return 1
    print("\n".join(f"Error: {p}" for p in problems) if problems else f"{wt} is ready: hooks set and built, virtualenv linked. Commit there.")
    return 1 if problems else 0


def command_policy(argv: list[str]) -> int:
    """`olivercode policy init [DIR]`: write the default permission policy into a repo."""
    from lib import policy
    if not argv or argv[0] != "init" or len(argv) > 2:
        print("Usage: olivercode policy init [DIR]")
        return 1
    target = Path(argv[1] if len(argv) > 1 else ".").expanduser().resolve()
    if not target.is_dir():
        print(f"Error: {target} is not a directory.")
        return 1
    if (target / policy.POLICY_FILE).exists():
        print(f"{target / policy.POLICY_FILE} already exists; left as it is.")
        return 0
    print(f"Wrote {policy.write_default(target)}")
    return 0


def command_gh_limit(argv: list[str]) -> int:
    """`olivercode gh-limit [clear|report]`: the shared GitHub rate-limit hold and what each session spent."""
    from lib import gh_budget
    if argv == ["clear"]:
        gh_budget.clear()
        print("GitHub hold cleared.")
        return 0
    if argv == ["report"]:
        print(gh_budget.report())
        return 0
    if argv[:1] == ["queue"] and argv[1:2] in (["--"], []) and argv[2:3] == ["gh"]:
        print(f"Queued. {gh_budget.enqueue(argv[2:])} gh command(s) wait for the GraphQL reset.")
        return 0
    if argv == ["replay"]:
        print(gh_budget.replay())
        return 0
    if argv in (["--schedule"], ["--unschedule"]):
        from lib import cmd_ghreplay
        return cmd_ghreplay.schedule(argv == ["--schedule"])
    if argv:
        print("Usage: olivercode gh-limit [clear|report|replay|--schedule|--unschedule|queue -- gh ...]")
        return 1
    why = gh_budget.refusal()
    print(why or "No GitHub rate-limit hold is on.")
    return 1 if why else 0


def command_queue(argv: list[str]) -> int:
    """`olivercode queue show` lists the runs holding a validation or render slot, and `queue run [--render] -- COMMAND...` runs one inside a queue."""
    from lib import validate_queue
    if argv[:1] == ["run"]:
        queue = "render" if argv[1:2] == ["--render"] else "validate"
        rest = argv[2:] if queue == "render" else argv[1:]
        command = rest[1:] if rest[:1] == ["--"] else rest
        if command:
            return validate_queue.run(command, queue)
    if argv in ([], ["show"]):
        print(validate_queue.show())
        return 0
    print("Usage: olivercode queue show | olivercode queue run [--render] -- COMMAND...")
    return 1

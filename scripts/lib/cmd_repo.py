"""Launcher commands that read or stamp one repo: skills, discover, bootstrap and size."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from lib.cli import reject_extra as _reject_extra
from lib.local_config import OC_ROOT
from lib.repo_profiles import registry_file
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
    claude_dir = Path.home() / ".claude"
    print("\n~/.claude inventory")
    print("-" * 40)
    if not claude_dir.is_dir():
        print("  not present — `olivercode install` creates it")
        return

    rules = claude_dir / "CLAUDE.md"
    if rules.is_symlink():
        target = rules.resolve()
        owner = "OliverCode" if str(target).startswith(str(oc_root)) else f"elsewhere -> {target}"
        print(f"  CLAUDE.md   symlink ({owner})")
    elif rules.is_file():
        print("  CLAUDE.md   REAL FILE — `install` will back it up, not overwrite it")
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
            elif str(entry.resolve()).startswith(str(oc_root)):
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


def command_discover(oc_root: Path, roots: list[Path]) -> int:
    """Find git repos under the given roots and report what governance they already have.

    Adoption docs assume you know where your repos are. Someone folding this into an
    existing, un-tidy setup often does not: repos spread over several directories,
    agent-rules files under three different names, hooks installed in some places and
    not others. This is the inventory step made mechanical -- read-only, and it emits
    a profile skeleton with explicit `path` values so a scattered layout is registrable
    without hand-writing JSON.
    """
    print("OliverCode discover — read-only scan")
    print("=" * 40)
    found: list[tuple[str, Path, str, str]] = []
    for root in roots:
        for git_dir in sorted(root.rglob(".git")):
            repo = git_dir.parent
            # Don't descend into vendored or nested-checkout noise.
            if any(part in {"node_modules", ".next", "vendor", "worktrees"} for part in repo.parts):
                continue
            if repo.resolve() == oc_root.resolve():
                continue  # the framework repo governs the fleet; it is not part of it
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
    print(f"\nProfile skeleton — paste into {registry_file(oc_root, 'repo-profiles.json')} under \"profiles\",")
    print("and replace <command> with each repo's validation command:\n")
    skeleton = {
        name: {"name": name, "path": str(repo), "canonicalValidationCommand": "<command>"}
        for name, repo, _, _ in found
    }
    print(json.dumps(skeleton, indent=2))
    return 0


def command_bootstrap(oc_root: Path, target: Path, dry_run: bool) -> int:
    """Stamp the project template into a repo, per shared/project-bootstrap-manifest.json.

    The manifest lists the templated files and the required directories, so a new repo starts
    compliant on day one.

    Honours the manifest's modes: `strict` files are overwritten (their contract is
    byte-identity with the template), `presence` files are only created when missing so
    repo-specific content is never clobbered.
    """
    manifest_path = oc_root / "shared" / "project-bootstrap-manifest.json"
    if not manifest_path.is_file():
        print(f"  [FAIL] manifest not found: {manifest_path}")
        return 1
    manifest = json.loads(manifest_path.read_text())

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

    new = overwritten = kept = 0
    missing_src = []
    for entry in manifest.get("templatedFiles", []):
        src, dst_rel, mode = oc_root / entry["source"], entry["target"], entry.get("mode", "presence")
        dst = target / dst_rel
        if not src.is_file():
            missing_src.append(entry["source"])
            continue
        exists = dst.exists()
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
            dst.write_bytes(src.read_bytes())
            if src.suffix == ".sh" or dst_rel.startswith(".githooks/"):
                dst.chmod(0o755)

    print(f"\n  {new} new, {overwritten} overwritten (strict), {kept} kept (presence, already present)")
    for rel in missing_src:
        print(f"  [FAIL] template source missing from this checkout: {rel}")

    if dry_run:
        print("\nRe-run without --dry-run to apply.")
    else:
        print("\nNext: `olivercode sync-hooks` installs the hooks and sets core.hooksPath,")
        print("then fill in the placeholders in docs/repo-structure-contract.md.")
    return 1 if missing_src else 0


def command_size(oc_root: Path, target: Path, lower: bool) -> int:
    """Print a repo's line total against docs/SIZE-BASELINE.json, or lower the baseline to it.

    The total comes from skills/audit/scripts/size.sh --total, the counter the size-ratchet gate
    uses. The baseline only moves down here: raising it is an edit to the file in a commit that
    names a story (docs/GATES.md, "Size ratchet").
    """
    baseline_path = target / "docs" / "SIZE-BASELINE.json"
    if not baseline_path.is_file():
        print(f"  [FAIL] {baseline_path} not found. `olivercode bootstrap` adds it.")
        return 1
    try:
        baseline = json.loads(baseline_path.read_text())
    except ValueError as exc:
        print(f"  [FAIL] {baseline_path} is not valid JSON: {exc}")
        return 1
    done = subprocess.run(["bash", str(oc_root / "skills" / "audit" / "scripts" / "size.sh"),
                           "--total", str(target)], capture_output=True, text=True)
    if done.returncode != 0 or not done.stdout.strip().isdigit():
        print(f"  [FAIL] could not count lines in {target}: {done.stderr.strip() or done.stdout.strip()}")
        return 1
    total = int(done.stdout)
    recorded = baseline.get("lines")
    percent = baseline.get("allowancePercent", 5)

    if lower:
        if recorded is not None and total > recorded:
            print(f"  [FAIL] {total} lines is above the baseline of {recorded}; --lower never raises it.")
            print("         To grow the repo for a story, edit docs/SIZE-BASELINE.json in that story's commit.")
            return 1
        baseline.update({"lines": total, "allowancePercent": percent,
                         "updated": datetime.now().date().isoformat()})
        baseline_path.write_text(json.dumps(baseline, indent=2) + "\n")
        print(f"Baseline set to {total} lines (was {recorded if recorded is not None else 'unset'}).")
        return 0

    print(f"Total lines: {total}")
    if recorded is None:
        print("Baseline: unset (run `olivercode size --lower` to record the current total)")
        return 0
    allowed = recorded * percent // 100
    print(f"Baseline: {recorded} lines, allowance {percent}% ({allowed} lines)")
    print(f"Headroom: {recorded + allowed - total} lines before the commit gate blocks")
    return 0

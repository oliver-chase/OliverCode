---
name: repo-structural-cleanup
description: "Execute large-scale file-move, file-rename, and file-delete operations without breaking imports, references, or git history."
---

# Repo Structural Cleanup

## Principles

- **One operation at a time.** Moving 20 files in one command breaks everything at once.
- **Update references before moving.** Search for all imports/requires referencing the old path.
- **No `git mv` without updating downstream.** Git tracks history, but code doesn't know about history.
- **Run tests after every batch.** Don't accumulate regressions.

## Process

### Step 1 — Inventory

```bash
find <target-dirs> -name "*.js" -o -name "*.ts" -o -name "*.py" | sort
```

Group files by target directory. Plan the move.

### Step 2 — Reference Scan

For each file being moved, search for all references:

```bash
grep -rn "old/path/filename" --include="*.js" --include="*.ts" --include="*.json"
```

### Step 3 — Move + Update

```bash
mkdir -p <new-dir>
git mv <old-path> <new-path>
```

Then update every reference found in Step 2.

### Step 4 — Structural Validator Sync

If the repo has a structural validator (`_validate_repo_structure.js`), update its expected paths to match. The validator must reflect the NEW structure, not a stale snapshot.

### Step 5 — Doc Update

Update:
- Any ARCHITECTURE.md or docs that reference old paths
- CLAUDE.md if the layout changed significantly
- CI config if test paths changed

### Step 6 — Verify

```bash
node <test-runner>  # all pass?
ls <new-dir>         # files where expected?
grep -rn "old/path"  # any stale references left?
```

## Pitfalls

- **Don't delete files that are imported.** Search for imports first.
- **Don't move files that are deployed.** Check if the path is referenced in Dockerfiles, CI, cron scripts, or shell wrappers.
- **Don't change the public API surface** during a structural move. Internal module paths change, but entry points (main script, CLI) should stay the same.
- **Update the structural validator last**, after all moves are done and tests pass.
- **Commit structural changes separately from functional changes.** A PR that moves 20 files AND adds a feature is impossible to review.

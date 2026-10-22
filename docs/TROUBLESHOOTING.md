# OliverCode Troubleshooting Guide

Purpose: short current-state fixes for common operator failures.

## Command not found

`scripts/olivercode` has no global alias — it only runs from inside this checkout, not from
an arbitrary cwd. `cd` into the OliverCode repo first, then run:

```zsh
scripts/olivercode --help
```

If a host sets up its own alias or PATH entry for convenience, verify that separately; do not
commit host-specific paths into this repo.

## Governance failure

Run the full gate suite:

```zsh
.githooks/pre-commit
```

## Product commands are not here

Product runtime authority lives in the owning project repo (see `local/repo-map.json`,
gitignored). OliverCode ships standards, not product implementations — use that repo's own
scripts and docs.

## Gate 5 blocks a staged workflow file

Gate 5 checks the actual credential's scopes (`gh api user -i`), not the remote URL scheme.
Fix: `gh auth login --scopes workflow` (or `gh auth refresh -s workflow` if already logged in).

## Commits are passing gates that should have blocked them

Git runs hooks only when `core.hooksPath` resolves to a directory holding an executable
`pre-commit`. If that config is unset, points at a missing directory, or the file is
non-executable, git runs **no hooks and prints nothing** — every gate is simply absent and
every commit succeeds. Verified: a commit containing an `sk-` key goes straight through.

```zsh
git config --get core.hooksPath      # expect: .githooks
scripts/olivercode health            # FAILs with the exact reason if any repo is in that state
scripts/olivercode sync-hooks        # repairs it across the fleet and the vault
```

Prefer the relative `.githooks` over an absolute path — an absolute one breaks the moment the
repo or vault moves, and it breaks silently.

## Fleet hooks report drift after a template edit

`scripts/olivercode health`'s placement-drift check compares each fleet repo's live hook
against `core/templates/project/pre-commit`(`-private`). Any edit to the template makes
every fleet repo diverge until re-synced:

```zsh
scripts/olivercode sync-hooks
```

## `bash scripts/validate.sh` fails at "not a git repository"

`validate.sh` shells out to `.githooks/pre-commit`, which runs `git diff --cached` — it
needs a real `.git`. Running it against an extracted archive/tarball without `git init`
first will fail this way. This is expected, not a bug.

## More context

- `README.md`
- `docs/ADOPTING.md`

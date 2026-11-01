# Execution Contract

Every change, in any project, follows this locked process. No gate is skippable.

`core/contracts/DEVELOPMENT_LIFECYCLE_STANDARD.md` owns the human-facing sequence this
mechanism sits inside — gap analysis, spec, priority, the build/verify/commit loop. This
file owns the gate and evidence mechanics that loop ends in: what runs, what blocks, and
the fleet registry behind it (`repo-profiles.json`; `docs/DECISIONS.md` `REGISTRY-PRIVATE-1`
says where).

## The Process

```
User says "yes" / approves change
    |
    v
1.  CODE -- implement the change fully
    |
    v
2.  DOCS -- update affected documentation to current state
    |   Audit for stale references across all related docs
    |
    v
3.  AUDIT -- scan for stale references, conflict markers, ordering hazards
    |
    v
4.  QA -- verify the change end-to-end
    |   Run the repo's own validation command, which its CLAUDE.md names
    |
    v
5.  GATE -- pre-commit enforcement runs automatically (see below; how many gates
    |   depends on the repo -- OliverCode/docs/GOVERNANCE.md has the table)
    |   BLOCKED = must fix before commit
    |
    v
6.  COMMIT -- only on pass, with descriptive message
    |
    v
7.  PUSH -- to the correct repo
```

## Gates (Non-Negotiable)

`.githooks/pre-commit` runs the gates automatically on every commit. BLOCKED means fix
before commit. There is no bypass mode. The gate list and what each one blocks lives in
`docs/GOVERNANCE.md` — one home, so a hook change updates exactly one table.

## Session Hooks (Claude Code, not git)

`.githooks/pre-commit` runs inside git. Three Claude Code hooks run inside every
session, and `olivercode install` writes them into `~/.claude/settings.json`, each
pointing at this checkout's script:

- `scripts/hooks/session_check.py` (`SessionStart`) tells the session once what
  would fail silently in the folder it opened: a repo whose gates git skips, a git
  repo with no gates, or a broken rules link. It prints nothing when all is well.
- `scripts/hooks/commit_guard.py` (`PreToolUse` on Bash) refuses a `git commit` that
  would skip the repo's gates: gates present while `core.hooksPath` does not run
  them, `--no-verify`, or a `core.hooksPath` override.
- `scripts/hooks/early-stop-guard.py` (`Stop`, `EARLY-STOP-1` in `docs/DECISIONS.md`)
  sends a turn back to work when it ends by promising work it did not do.

All three are deterministic and fail open: a hook's own bug never blocks a commit or
a session. `olivercode health` fails when one is missing on a machine where install
linked this checkout.

## Completion

Run the repo's canonical validation before committing, and stop on failure rather than
claiming completion. The mechanically enforced requirement is the pre-commit hook plus the
repo's own `scripts/validate.sh`.

### Authority hierarchy

The deploy platform must not be the first place a build or type error is discovered. Each
repo profile declares its own `canonicalValidationCommand` and `finalAuthority` — run the
canonical command locally before the commit, and treat the declared final authority (a full
build, not a lint pass) as the thing that decides whether the change is sound. Pre-commit
gates catch secrets, structure, and hygiene. They do not catch a block-scoped `const`
referenced before declaration, which only a full type-checking build surfaces.

## Secrets vs Git Boundary

```
project/
├── .secrets/            Gitignored. Actual credentials live here.
│   └── gtm.env          Private -- never committed
├── .env.example         In git. Variable names only, no values.
├── .env.local           Gitignored. Local overrides.
└── .githooks/
    └── pre-commit       The enforcement gate
```

## Install in a new project

Hooks are installed by the launcher, from OliverCode:

```bash
scripts/olivercode sync-hooks
```

It deploys `core/templates/project/pre-commit` (or the private variant for a private repo) to
each repo's `.githooks/` and sets `core.hooksPath`. Planning-doc governance needs no separate
install step: the hook runs `scripts/check-planning-doc-governance.py` automatically whenever
that file is present in the repo, and skips the gate when it is not.

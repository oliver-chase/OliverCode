# Execution Contract

Every change, in any project, follows this locked process. No gate is skippable.

**Backend policies (machine-readable, loaded per task):**
- `local/repo-profiles.json` (gitignored, real fleet) or `shared/repo-profiles.example.json` (tracked placeholder) -- per-repo validation and evidence requirements
- `shared/task-policies/task-types.json` -- per-task-type evidence requirements
- `shared/task-policies/result-schema.json` -- evidence record shape
- `scripts/orchestration-gatekeeper.py` -- deterministic pass/fail validation

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
    |   See task-types.json for per-type audit list
    |
    v
4.  QA -- verify the change end-to-end
    |   Run repo's canonical validation command (from repo-profiles.json)
    |
    v
5.  GATE -- pre-commit enforcement runs automatically (8 gates, see below)
    |   BLOCKED = must fix before commit
    |
    v
6.  COMMIT -- only on pass, with descriptive message
    |   Populate evidence record matching result-schema.json
    |
    v
7.  PUSH -- to the correct repo
```

## Gates (Non-Negotiable)

`.githooks/pre-commit`'s 8 gates, in run order (see `docs/governance.md` for detail):

| Gate | What it blocks |
|------|---------------|
| 1. Secrets | API keys, tokens, JWTs, private keys in staged files |
| 2. Icons/Emoji | Unicode emoji and icon characters |
| 3. PII | Host paths (`/Users/*`, `/home/*`), email addresses |
| 4. Deleted repo refs | References to removed repos |
| 5. Workflow push auth | Staged `.github/workflows/` files without a workflow-scoped credential |
| 6. Contract integrity | `_Management/`/`/workspace/` path refs; declared-dependency paths that don't exist |
| 7. Planning doc governance | Contract violations in staged planning docs (when the checker is present) |
| 8. Token policy | Invalid token-policy declarations in repo profiles |

Separately, on demand (not a pre-commit gate): `orchestration-gatekeeper.py
--evidence-file <path>` blocks a WRITE MODE completion claim without required evidence.

## Completion Gate

A WRITE MODE task is NOT complete unless:
- The evidence record (matching result-schema.json for its task type) is populated
- `orchestration-gatekeeper.py --repo <name> --task-type <type> --evidence-file <path>` exits 0

If validation fails, no commit. No completion claim. Record the exact failing stage.

### Authority hierarchy

The deploy platform must not be the first place a build or type error is discovered. Each
repo profile declares its own `canonicalValidationCommand` and `finalAuthority` — run the
canonical command locally before the commit, and treat the declared final authority (a full
build, not a lint pass) as the thing that decides whether the change is sound. Pre-commit
gates catch secrets, structure, and hygiene; they do not catch a block-scoped `const`
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

It deploys `core/templates/project/pre-commit` (or the private variant for the vault) to
each repo's `.githooks/` and sets `core.hooksPath`. Planning-doc governance is layered on
afterwards with `core/templates/project/scripts/install-planning-governance-hook.sh`.

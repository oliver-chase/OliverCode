# Execution Contract

Every change, in any project, follows this locked process. No gate is skippable.

`core/contracts/DEVELOPMENT_LIFECYCLE_STANDARD.md` owns the human-facing sequence this
mechanism sits inside — gap analysis, spec, priority, the build/verify/commit loop. This
file owns the gate and evidence mechanics that loop ends in: what runs, what blocks, and
the machine-readable policies behind it.

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
5.  GATE -- pre-commit enforcement runs automatically (see below; how many gates
    |   depends on the repo -- OliverCode/docs/GOVERNANCE.md has the table)
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

`.githooks/pre-commit` runs the gates automatically on every commit. BLOCKED means fix
before commit; there is no bypass mode. The gate list and what each one blocks lives in
`docs/GOVERNANCE.md` — one home, so a hook change updates exactly one table.

Separately, on demand (not a pre-commit gate): `orchestration-gatekeeper.py
--evidence-file <path>` blocks a WRITE MODE completion claim without required evidence.

## Completion Gate (opt-in, on demand)

The gatekeeper can validate a completion claim against a machine-readable evidence record:

```bash
python3 scripts/orchestration-gatekeeper.py --repo <name> --task-type <type> --evidence-file <path>
```

It checks the fields `shared/task-policies/task-types.json` requires for that task type, in
the shape `shared/task-policies/result-schema.json` declares, and exits nonzero naming the
exact failing stage. Use it when a completion claim needs to be auditable by something other
than trust — a long autonomous run, a handoff, a task where "I ran the tests" needs proof.

**It is opt-in, not a precondition for every commit.** Stating it as a universal requirement
would be false: nothing invokes it automatically, no evidence record exists anywhere in this
fleet, and every commit in this repo's history was made without one. A contract that every
commit violates teaches agents that written rules are optional, which costs more than the
gate was worth. The mechanically-enforced completion requirement is the pre-commit hook plus
the repo's own `scripts/validate.sh`.

What IS required on every change: run the repo's canonical validation before committing, and
stop on failure rather than claiming completion.

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
each repo's `.githooks/` and sets `core.hooksPath`. Planning-doc governance needs no separate
install step: the hook runs `scripts/check-planning-doc-governance.py` automatically whenever
that file is present in the repo, and skips the gate when it is not.

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
5.  GATE -- pre-commit enforcement runs automatically
    |   Secrets scan, .env check, legacy language, privacy, credentials
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

| Gate | What it blocks | How |
|------|---------------|-----|
| Secrets | API keys, tokens, private keys in code | `pre-commit` (pattern match) |
| .env files | Any `.env` except `.env.example` | filename match |
| Legacy language | Past-tense removal phrasing in docs | grep pattern match |
| Privacy | `/Users/*`, `/home/*` host paths in docs | grep pattern match |
| Credentials | `auth.json`, `credentials.json` files | filename match |
| Validation | WRITE MODE completion without required evidence | `orchestration-gatekeeper.py` |

## Completion Gate

A WRITE MODE task is NOT complete unless:
- The evidence record (matching result-schema.json for its task type) is populated
- `orchestration-gatekeeper.py --repo <name> --task-type <type> --evidence-file <path>` exits 0

If validation fails, no commit. No completion claim. Record the exact failing stage.

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

```bash
bash Oliver/Project Repos/OliverCode/core/templates/project/scripts/install-enforcement.sh path/to/project
```

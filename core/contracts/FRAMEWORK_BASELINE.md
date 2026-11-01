# Framework Baseline

Status: Locked
Scope: OliverCode core and all downstream project baselines moving forward

## Purpose

Keep the framework at runtime minimum and make the same baseline reusable across all project repos.

Every tracked file in framework core must justify itself as one of:
- run
- verify
- ship
- support

If it does none of those, it does not belong in OliverCode core.

## Core Baseline

### Run
Required active runtime surfaces:
- `scripts/olivercode`

### Verify
Required active verification surfaces:
- `scripts/validate.sh` (unified entrypoint, wraps `.githooks/pre-commit`)
- `.githooks/pre-commit`

### Ship
Required reusable contract/template surfaces:
- `core/contracts/`
- `core/templates/project/QUALITY_BASELINE.md`
- `shared/project-bootstrap-manifest.json`

### Support
Required current-state authority docs:
- `README.md`
- `docs/ADOPTING.md`
- `CONTRIBUTING.md`
- `ARCHITECTURE.md`
- `docs/GOVERNANCE.md`
- `docs/OLIVERCODE-LAUNCHER.md`
- `docs/DOCUMENTATION-STANDARD.md`

## Removal Rules

Default action for non-runtime files:
- duplicate explainer -> merge
- roadmap/migration/status/history doc -> delete or archive outside active authority
- project-specific helper -> move to owning project repo
- generated report/cache -> ignore, never track
- validator that duplicates another validator's failure class -> collapse

## Future Framework Rule

New files are allowed only when they do at least one of:
- reduce runtime complexity
- replace duplicated authority
- tighten baseline verification
- improve reusable downstream shipping surface

Otherwise reject them.

## Cross-Project Lock

Downstream managed repos must inherit this runtime-minimal baseline through the shared template/bootstrap path, not by repo-local reinterpretation.

Required lock points:
- `core/templates/project/QUALITY_BASELINE.md`
- `shared/project-bootstrap-manifest.json`

Any variance must be explicit, temporary, and recorded in the repo's profile in `repo-profiles.json`.

## Design Decisions

### Template Directory Architecture
- `core/templates/project/` -- the single template home. CI workflows, docs, governance scripts and the built hooks all ship to downstream repos from here, through the bootstrap manifest and `sync-hooks`. A second template directory drifts from the masters.
- The hooks are written in `core/hooks/` and built into `core/templates/project/` and `.githooks/` by `scripts/build-hooks.py`. Edit the gate files there, never a built hook.

### Runtime Manifests
`runtime/manifests/` does not exist as a tracked path. `.gitignore` reserves the path
(generated observability reports, inventory scans, status snapshots) so any future
manifest generation writes to an untracked location by default -- no active validator
consumes manifests.

### Validation Surface
Run `bash scripts/validate.sh` from repo root for unified validation. It wraps:
- `.githooks/pre-commit` (primary gate — `docs/GOVERNANCE.md` has the current per-repo gate count and table)
- Optional smoke tests in `tests/` (WARN-skip if absent)

CI and why it is paused on the origin repo: `docs/GOVERNANCE.md` "Unified Validation
Entrypoint". There is no type checker or schema validator beyond
what the gates above cover -- this is acceptable for a framework repo whose primary change
risk is secrets/PII leaks and drift, not compiled-language runtime correctness. Downstream
project repos have their own validation commands declared in the fleet registry
(`repo-profiles.json`; `docs/DECISIONS.md` `REGISTRY-PRIVATE-1` says where).

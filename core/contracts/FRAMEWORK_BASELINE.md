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
- `scripts/validate.sh` (unified entrypoint — wraps `.githooks/pre-commit` and `scripts/orchestration-gatekeeper.py`)
- `.githooks/pre-commit`
- `scripts/orchestration-gatekeeper.py`

### Ship
Required reusable contract/template surfaces:
- `core/contracts/`
- `core/templates/project/QUALITY_BASELINE.md`
- `shared/project-bootstrap-manifest.json`

### Support
Required current-state authority docs:
- `README.md`
- `INSTALL.md`
- `CONTRIBUTING.md`
- `ARCHITECTURE.md`
- `docs/governance.md`
- `docs/OLIVERCODE_LAUNCHER.md`
- `docs/FEATURE_MAP.md`
- `docs/DOCUMENTATION_STANDARD.md`

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

Any variance must be explicit, temporary, and recorded in `shared/repo-map.json`.

## Historical Note

Previous versions of this document listed 9 validator scripts (validate-framework-baseline.sh, validate-doc-suite.sh, validate-feature-coverage.sh, etc.) as required verify surfaces. These scripts were never implemented. The active verification surfaces are the pre-commit hook and the orchestration gatekeeper. Cross-project sync/governance scripts (sync-project-hygiene.sh, install-governance-hook.sh, validate-governance-wiring.sh) were also never implemented — lock points are handled through the shared bootstrap manifest and template sync mechanisms.

## Design Decisions

### Personas and Teams
Only one persona (`oliver`) is defined and no team template. This is intentional -- the framework ships one authoritative orchestration persona. Additional personas and teams can be added by downstream projects or by extending `core/personas/`. The CLAUDE.md and ARCHITECTURE.md describe the composable system that the framework enables, not the current inventory count.

### Template Directory Architecture
- `core/templates/project/` -- the canonical template repository. All project templates are authored here.
- Rule: `core/templates/project/` is the single template home -- hooks, CI workflows, keepalive scripts, docs, and governance scripts all ship to downstream repos from here via the bootstrap manifest. No second template directory exists; a synced-subset copy was retired 2026-07-08 after its hook copies drifted from the masters once.

### Runtime Manifests
`runtime/manifests/` contains 77 tracked files (796KB) of generated observability reports, inventory scans, and status snapshots. These are historical artifacts from runtime inspection sessions. They are gitignored going forward (`.gitignore` entry added). No active validator consumes them -- they serve as a record of past runtime state. New manifest generation should write to an untracked directory.

### Validation Surface
Run `bash scripts/validate.sh` from repo root for unified validation. It wraps:
- `.githooks/pre-commit` (primary gate — 8 checks: secrets, emoji, PII, deleted repo refs, workflow push-auth, contract integrity, planning-doc governance, token policy)
- `scripts/orchestration-gatekeeper.py` (optional, with `--evidence <file>`)

There is no CI pipeline, no type checker, and no schema validator. This is acceptable for a 291-file framework repo where the primary change risk is secrets/PII leaks, not runtime correctness. Downstream project repos have their own validation commands declared in `local/repo-profiles.json` (gitignored, real fleet) or `shared/repo-profiles.example.json` (tracked placeholder).

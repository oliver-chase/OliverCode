# Project Standardization Lifecycle

## Purpose
Define one standard lifecycle for project bootstrap, governance sync, drift audit, and promotion across all Oliver repos.

## Source of Truth
1. `core/templates/project/**` for the master scaffold templates (the single template home).
2. `shared/project-bootstrap-manifest.json` for managed files and strictness modes.
3. `shared/repo-map.json` for managed repo inventory.
4. `shared/project-structure-rules.json` for structure and backlog-location enforcement.
5. `core/contracts/PROJECT_STRUCTURE_STANDARD.md` for locked story/backlog/index naming and folder shape.

## Lifecycle
1. Bootstrap new project:
- `scripts/olivercode bootstrap <repo-path>` stamps every managed file from
  `core/templates/project/` per the manifest, honouring strict/presence modes.
  Add `--dry-run` first to see the plan.
- Install hooks with `scripts/olivercode sync-hooks` (run from OliverCode) — it deploys the
  hook template and sets `core.hooksPath`. Planning-doc governance activates itself: the hook
  runs `scripts/check-planning-doc-governance.py` whenever that file is present.
- Add the project to `shared/repo-map.json`.
- Add structure rules entry in `shared/project-structure-rules.json`.

2. Sync existing projects:
- Hooks: `scripts/olivercode sync-hooks` (run from OliverCode). This is the automated part.
- Everything else: manually re-copy the managed files listed in
  `shared/project-bootstrap-manifest.json` from `core/templates/project/` into the target
  repo -- `strict` files get overwritten unconditionally; `presence` files are only copied
  in if missing (never overwrite existing repo-specific content).
- Workflow fail-safe is policy-driven: `shared/project-bootstrap-manifest.json`'s
  `githubActionsPolicy.mode` field controls whether managed repos are in `normal` mode or
  `manual_only` suspension.

3. Audit drift:
- `scripts/olivercode health` catches hook drift (compares each fleet repo's live hook
  against the template). It does not check other managed files.
- Other managed files: audit manually against `shared/project-structure-rules.json` and the
  managed-file list in `shared/project-bootstrap-manifest.json`.
- Drift is blocking for strict files and required paths.

4. Promotion and alignment:
- Update project tracks via the same sync source; branch roles are defined once in
  `shared/workflow-standards.md` ("Branch Lifecycle Standard").
- Verify branch status and ahead/behind after push.
- Never promote without a passing hygiene audit.

## Managed File Policy
- `strict`: file content must exactly match template.
- `presence`: file must exist; repo-specific content is allowed.

## Mandatory Repo Contract File

Each repo must keep `docs/repo-structure-contract.md` current with:
1. active backlog path
2. story catalog path
3. acceptance matrix path
4. story artifact roots

## Cadence
1. Run sync + audit before major releases.
2. Run sync + audit after adding any new project.
3. Run sync + audit when workflow templates change.
4. Run sync immediately after changing `githubActionsPolicy.mode`; this is the canonical way to suspend or restore mapped repo workflows.

## Incident Response
If a repo fails audit:
1. Run sync.
2. Re-run audit.
3. If still failing, patch repo-specific drift and commit with story/AC metadata.
4. Re-run audit until pass.

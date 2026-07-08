# Token Policy

## Where It Lives

The cross-repo token policy is defined in `local/repo-profiles.json` (gitignored, real fleet) or `shared/repo-profiles.example.json` (tracked placeholder). Each repo profile has three fields:

### ignoreGlobs
Glob patterns for directories and files that should be excluded from default AI/agent context loading. These are low-signal or generated paths that waste token budget when scanned.

Examples: `node_modules/**`, `runtime/manifests/**`, `*.log`, `coverage/**`

### docPriorityHints
Short list of high-signal docs that agents should read first when working in a repo. These are the current-state authorities for understanding the repo.

Examples for OliverCode: `README.md`, `ARCHITECTURE.md`, `docs/governance.md`, `core/contracts/FRAMEWORK_BASELINE.md`

### generatedArtifactDirs
Directories containing build output, generated reports, or runtime state that produce no useful context for agents. These should be excluded from agent file scans.

Examples: `runtime/manifests`, `node_modules`, `.next`, `__pycache__`

## Validation

`scripts/validate.sh` checks on every run that:
- Every repo profile has `ignoreGlobs` and `generatedArtifactDirs`
- No `ignoreGlobs` entry is the catch-all `**` (which would block everything)

## Enforcement

This policy is advisory for AI/agent context management. It does not affect gitignore or CI behavior.

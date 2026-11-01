# Token Policy

## Where It Lives

The cross-repo token policy is defined in `shared/repo-profiles.json` (tracked, real fleet).
Each repo profile carries a
`token_policy` object with three fields:

```json
"token_policy": {
  "ignore_globs": ["node_modules/**", "*.log", "coverage/**"],
  "doc_priority_hints": ["README.md", "CLAUDE.md", "docs/repo-structure-contract.md"],
  "generated_artifact_dirs": ["node_modules", ".next", "out", "coverage"]
}
```

### ignore_globs
Glob patterns for directories and files excluded from default AI/agent context loading.
Low-signal or generated paths that waste token budget when scanned.

### doc_priority_hints
Short list of high-signal docs an agent reads first when working in that repo — the
current-state authorities. For OliverCode itself: `README.md`, `ARCHITECTURE.md`,
`docs/GOVERNANCE.md`, `core/contracts/FRAMEWORK_BASELINE.md`.

### generated_artifact_dirs
Directories holding build output, generated reports, or runtime state that produce no
useful context. Excluded from agent file scans.

## Validation

Gate 8 of `.githooks/pre-commit` (`orchestration-gatekeeper.py --check-token-policy`) fails
the commit unless, for every repo profile:
- `ignore_globs` and `generated_artifact_dirs` are both present and non-empty
- no `ignore_globs` entry is the catch-all `**`, which would exclude everything


## Enforcement

The policy is advisory for AI/agent context management. It does not affect gitignore or CI
behavior — only Gate 8's validation of the declarations themselves is mechanical.

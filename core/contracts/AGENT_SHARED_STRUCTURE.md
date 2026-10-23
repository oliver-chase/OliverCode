# Agent Shared Structure

Shared contract for Claude Code, this machine's sole agent runtime. This file is the one
home for the canonical path map and the ownership rules that follow from it.
`core/contracts/AGENT_SYSTEM_MANIFEST.json` is the machine-readable mirror of the same map
(placeholder in git, real values in gitignored `local/`, per `docs/BACKLOG.md` G1).

## Canonical Paths

- Product repos: `<vault-root>/Oliver/Project Repos/*`
- Shared system root: `<vault-root>/Oliver/Project Repos/OliverCode`
- Claude runtime/orchestration: `~/.claude`
- Shared skills root: `<vault-root>/Oliver/Project Repos/OliverCode/skills`
- Shared manifest: `<vault-root>/Oliver/Project Repos/OliverCode/core/contracts/AGENT_SYSTEM_MANIFEST.json`
- Shared hygiene standard: `<vault-root>/Oliver/Project Repos/OliverCode/core/contracts/PROJECT_STRUCTURE_STANDARD.md`
- Workflow standards and trigger routing: `<vault-root>/Oliver/Project Repos/OliverCode/shared/workflow-standards.md`
- Workflow procedures: `<vault-root>/Oliver/Project Repos/OliverCode/core/workflows/`

## Ownership

- Product-specific implementation docs/workflows belong in each project repo.
- Cross-project orchestration standards belong in `<vault-root>/Oliver/Project Repos/OliverCode/shared/*`.
- Shared skills/tools belong in `<vault-root>/Oliver/Project Repos/OliverCode/skills/*`.
- Project hygiene and security rules belong in `<vault-root>/Oliver/Project Repos/OliverCode/core/contracts/PROJECT_STRUCTURE_STANDARD.md`.
- Runtime state in `~/.claude` is operational data, not product source code.
- Do not duplicate product workflow docs into runtime folders.

## Governance

- Policy: `docs/GOVERNANCE.md`
- Runner: `.githooks/pre-commit`

## Sync Contract

When workspace structure or cross-project standards change:
1. Update this file — the path map lives here and nowhere else.
2. Update `core/contracts/AGENT_SYSTEM_MANIFEST.json` if paths or roots changed, so the
   machine-readable mirror matches.
3. Keep the `~/.claude/CLAUDE.md` symlink pointing at this repo's `CLAUDE.md` (verified by
   `scripts/olivercode health`).

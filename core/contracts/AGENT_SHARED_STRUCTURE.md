# Agent Shared Structure

Shared contract for Claude Code, this machine's sole agent runtime.

## Canonical Paths

- Product repos: `<vault-root>/Oliver/Project Repos/*`
- Shared system root: `<vault-root>/Oliver/Project Repos/OliverCode`
- Claude runtime/orchestration: `~/.claude`
- Shared skills root: `<vault-root>/Oliver/Project Repos/OliverCode/skills`
- Shared orchestration persona: `<vault-root>/Oliver/Project Repos/OliverCode/core/personas/oliver/persona_soul.md`
- Shared orchestration core: `<vault-root>/Oliver/Project Repos/OliverCode/core/contracts/SHARED_ORCHESTRATION.md`
- Shared manifest: `<vault-root>/Oliver/Project Repos/OliverCode/core/contracts/AGENT_SYSTEM_MANIFEST.json`
- Shared hygiene standard: `<vault-root>/Oliver/Project Repos/OliverCode/core/contracts/PROJECT_HYGIENE_STANDARD.md`

## Ownership

- Product-specific implementation docs/workflows belong in each project repo.
- Cross-project orchestration standards belong in `<vault-root>/Oliver/Project Repos/OliverCode/shared/*`.
- Orchestration identity is `Oliver` and must remain present in shared persona routing.
- Shared skills/tools belong in `<vault-root>/Oliver/Project Repos/OliverCode/skills/*`.
- Project hygiene and security rules belong in `<vault-root>/Oliver/Project Repos/OliverCode/core/contracts/PROJECT_HYGIENE_STANDARD.md`.
- Runtime state in `.claude` is operational data, not product source code.

## Sync Contract

When workspace structure or cross-project standards change:
1. Update `<vault-root>/Oliver/Project Repos/OliverCode/core/contracts/AGENT_SHARED_STRUCTURE.md`.
2. Update `<vault-root>/Oliver/Project Repos/OliverCode/core/contracts/SHARED_ORCHESTRATION.md`.
3. Keep the `~/.claude/CLAUDE.md` symlink pointing at `<vault-root>/Oliver/Project Repos/OliverCode/CLAUDE.md` (verified by `scripts/olivercode health`).
4. Update `<vault-root>/Oliver/Project Repos/OliverCode/core/contracts/AGENT_SYSTEM_MANIFEST.json` if paths or roots changed.

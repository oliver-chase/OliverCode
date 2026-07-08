# Architecture

> One shared, git-tracked orchestration layer for Claude Code — skills, contracts, templates, and governance gates that load automatically in every session and every repo, so no agent ever works without the rules.

## Why This Exists

Working across many repos without a shared layer fails in consistent ways: the same engineering-method knowledge gets reinvented per repo, agent-rules files that aren't named exactly `CLAUDE.md` silently never load, skills accumulate in scattered unsynced locations, and docs drift from what code does. OliverCode fixes this by making the shared layer load automatically instead of requiring discovery.

## The Three Layers

**1. OliverCode (this repo — public, on GitHub).** Contracts, skills, templates, launcher, governance hooks. Clone-and-use standalone.

**2. Local machine state (gitignored, optional).** `runtime/control-plane/` holds private per-machine state and is never pushed. `local/` holds your real fleet registries (`repo-map.json`, `repo-profiles.json`); tracked `shared/*.example.json` files ship placeholders. OliverCode works without either present.

**3. Product repos (yours).** Sibling repos that inherit hooks, templates, and standards from OliverCode. Declared in `local/repo-map.json`. OliverCode is never a runtime dependency of a product repo — it defines standards, not implementations.

```
OliverCode (public)
├── CLAUDE.md          agent entry — symlinked to ~/.claude/CLAUDE.md, loads in every session
├── core/
│   ├── contracts/     structural standards all repos follow
│   ├── personas/      agent role definitions (one: oliver)
│   ├── templates/     project template — the single template home
│   └── workflows/     repeatable procedures
├── skills/            engineering-method + framework tooling skills (symlinked into ~/.claude/skills/)
├── shared/            bootstrap manifest, task policies, placeholder registries
├── scripts/           launcher (olivercode) + validation gates
├── .githooks/         pre-commit governance (secrets, emoji, PII, contracts)
├── local/             (gitignored) your real fleet config
└── runtime/control-plane/  (gitignored) private machine state
```

## How Activation Works

Nothing here depends on an agent choosing to look:

- `~/.claude/CLAUDE.md` symlinks to this repo's `CLAUDE.md` — rules present in every Claude Code session on the machine, any working directory.
- `~/.claude/skills/<name>` symlinks to `skills/<name>` — every skill discoverable from any repo.
- `.githooks/pre-commit` runs on every commit in every fleet repo — enforcement that works even when context doesn't.
- `scripts/olivercode health` verifies all of the above (symlinks, hooks, placement drift).

Anything that must always apply is enforced as a hook, not as an instruction an agent might not read.

## Operating Principles

- Claude Code is the sole runtime; Anthropic the sole model provider. By design, not as an interim state.
- Fail-closed before fail-open. No capability claim without a runnable verification.
- Sheet-of-truth rule for docs: one concept, one home; everything else points.
- Project-specific behavior lives in the owning project repo, never here.

## Dependency Direction

Product repos and local state depend on OliverCode. OliverCode depends on nothing — see `docs/FRAMEWORK_BOUNDARY.md`.

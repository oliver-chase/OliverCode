# Architecture

> One shared, git-tracked orchestration layer for Claude Code — skills, contracts, templates, and governance gates that load automatically in every session and every repo, so no agent ever works without the rules.

## Why This Exists

Working across many repos without a shared layer fails in consistent ways: the same engineering-method knowledge gets reinvented per repo, agent-rules files that aren't named exactly `CLAUDE.md` silently never load, skills accumulate in scattered unsynced locations, and docs drift from what code does. OliverCode fixes this by making the shared layer load automatically instead of requiring discovery.

## What You Actually Get

Five things, and it is worth being precise about which are mechanical and which are not:

| You get | How it reaches you | Actually enforced? |
|---|---|---|
| Pre-commit gates — nine in an adopted repo, eleven in OliverCode itself (`docs/GOVERNANCE.md` has the per-repo table) | `.githooks/pre-commit`, installed per repo by `olivercode sync-hooks` | **Yes** — fires on every `git commit`. Only `--no-verify` skips it, and the commit guard below refuses that inside Claude Code |
| Local validation | `bash scripts/validate.sh` — gates, doc/code consistency, reference integrity, tests | **Yes**, when run. Nothing auto-runs it |
| Contracts, templates, workflows | `core/` — inherited by every repo via the bootstrap manifest | No — instruction text an agent follows |
| Claude Code hooks (session check, commit guard, early-stop guard) | `~/.claude/settings.json`, written by `olivercode install` | **Yes**, inside Claude Code sessions. `core/contracts/EXECUTION_CONTRACT.md` "Session Hooks" |
| Skills | `~/.claude/skills/` symlinks, installed by `olivercode install` | No — the agent chooses to load them |

The honest summary: **the hooks are the only things that block you.** Everything else is a rule an agent follows because it is loaded, not because it is enforced. `CONTRIBUTING.md`'s "Enforcement Reality" section is the one home for that distinction.

**Hook enforcement fails open.** `docs/TROUBLESHOOTING.md` ("Commits are passing gates that should have blocked them") has the mechanism and the fix.

## The Two Layers

**1. OliverCode (this repo).** Contracts, skills, templates, launcher and governance hooks. The fleet registry (`shared/repo-profiles.json`) ships as an empty example. An operator's real registry lives in a private repo under `olivercode/`, named through `privateRepos` in `olivercode.local.json`, so a fork carries none of it.

**2. Product repos (yours).** Sibling repos that inherit hooks, templates, and standards from OliverCode. Declared in the registry's `repo-profiles.json`. OliverCode is never a runtime dependency of a product repo — it defines standards, not implementations.

`runtime/control-plane/` (gitignored, optional) holds private per-machine runtime state. OliverCode works without it.

```
OliverCode
├── CLAUDE.md          agent entry — symlinked to ~/.claude/CLAUDE.md, loads in every session
├── core/
│   ├── contracts/     structural standards all repos follow
│   ├── hooks/         the pre-commit gates, built into each hook by scripts/build-hooks.py
│   ├── templates/     project template — the single template home
│   └── workflows/     repeatable procedures
├── skills/            engineering-method + framework tooling skills (symlinked into ~/.claude/skills/)
├── shared/            bootstrap manifest, task policies, the empty example registry
├── scripts/           launcher (olivercode), validation, qa checkers, Claude Code hooks
├── docs/              current-state authority docs (one concept, one home)
├── tests/             tests for the gates, checkers, hooks and launcher
├── .githooks/         pre-commit and pre-push gates (docs/GOVERNANCE.md)
├── .claude-optimization/  standalone Claude OS memory/state (local layer)
└── runtime/control-plane/  (gitignored) private machine state
```

## How Activation Works

Nothing here depends on an agent choosing to look:

- `~/.claude/CLAUDE.md` symlinks to this repo's `CLAUDE.md` — rules present in every Claude Code session on the machine, any working directory.
- `~/.claude/skills/<name>` symlinks to `skills/<name>` — every skill discoverable from any repo.
- `.githooks/pre-commit` runs on every commit in every fleet repo — enforcement that works even when context doesn't.
- `olivercode install` creates both sets of symlinks. `olivercode health` verifies them (symlinks, hooks, placement drift).

Because the global `CLAUDE.md` loads in sessions whose working directory is almost never OliverCode, **it contains no repo-relative paths**. It resolves `$OC` from the symlink itself and says so explicitly. A bare path in it means the repo the agent is currently in. Getting that wrong is how a rules file becomes dead text agents silently fail to follow.

Anything that must always apply is enforced as a hook, not as an instruction an agent might not read.

## Getting Started

`docs/ADOPTING.md` is the onboarding path — clone, `install`, register your fleet, `sync-hooks`, verify with a probe that proves the gates actually block. The `olivercode-adoption` skill runs it as a guided, non-destructive audit.

## Operating Principles

- Claude Code is the sole runtime. Anthropic is the sole model provider. By design, not as an interim state.
- Fail-closed before fail-open. No capability claim without a runnable verification.
- Sheet-of-truth rule for docs: one concept, one home. Everything else points.
- Project-specific behavior lives in the owning project repo, never here.
- A rule without a gate regresses. When a finding class keeps recurring, it becomes a check.

## Dependency Direction

Product repos and local state depend on OliverCode. OliverCode depends on nothing — see `docs/FRAMEWORK-BOUNDARY.md`.

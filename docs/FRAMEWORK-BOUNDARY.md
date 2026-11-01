# Framework Boundary

## What OliverCode Is

OliverCode is the **shared orchestration framework**. It contains:
- Reusable contracts, policies, and standards (`core/contracts/`)
- Reusable skill definitions (`skills/`)
- Workflow procedures (`core/workflows/`)
- Shared project templates and manifests (`shared/`)
- Framework documentation (`docs/`)
- A thin launcher entrypoint (`scripts/olivercode`)
- Pre-commit governance hooks (`.githooks/`)

OliverCode can be cloned, inspected, and used standalone to read contracts, templates, and documentation without any runtime being installed.

## Canonical Paths and Ownership

Claude Code is this machine's sole agent runtime. `core/contracts/AGENT_SYSTEM_MANIFEST.json`
is the machine-readable mirror of the paths below -- tracked, with real values, since this
is a single operator's framework across that operator's own accounts.

- Product repos: `<fleet-root>/*`
- Shared system root: `OliverCode`
- Claude runtime/orchestration: `~/.claude`
- Shared skills root: `OliverCode/skills`
- Shared manifest: `OliverCode/core/contracts/AGENT_SYSTEM_MANIFEST.json`
- Shared structure and hygiene standard: `OliverCode/core/contracts/PROJECT_STRUCTURE_STANDARD.md`
- Workflow standards and trigger routing: `OliverCode/shared/workflow-standards.md`
- Workflow procedures: `OliverCode/core/workflows/`

Ownership follows from the map above:

- Product-specific implementation docs/workflows belong in each project repo.
- Cross-project orchestration standards belong in `shared/*`.
- Shared skills/tools belong in `skills/*`.
- Project structure and hygiene rules belong in `core/contracts/PROJECT_STRUCTURE_STANDARD.md`.
- Runtime state in `~/.claude` is operational data, not product source code.
- Do not duplicate product workflow docs into runtime folders.

When workspace structure or cross-project standards change: update this section (the path
map lives here and nowhere else), update `AGENT_SYSTEM_MANIFEST.json` if paths or roots
changed, and keep the `~/.claude/CLAUDE.md` and `~/.claude/VOICE.md` symlinks pointing at this repo's `CLAUDE.md` and `docs/VOICE.md`
(verified by `scripts/olivercode health`).

## What Lives Next To It (Not Inside It)

The `runtime/control-plane/` directory lives inside the OliverCode repo tree but is gitignored. It contains the runtime orchestration state that makes the framework actionable — session handoff, provider health, validation manifests. This is private per-machine state, never pushed to GitHub. See its README for details.

## What OliverCode Does NOT Contain

OliverCode deliberately does not include:
- Runtime-environment launcher and automation (the thin `scripts/olivercode` CLI is the only launcher surface the framework ships)
- Docker compose or container setup
- Runtime state, logs, telemetry, or handoff data
- Private restore checklists or project-specific credentials
- Generated runtime adapter files
- Runtime-specific validation scripts and automation tools

These belong in the runtime environment (`runtime/control-plane/`), not in the reusable framework.

## User-Global and Sibling-Agent State (Outside the Framework Entirely)

Two more layers exist on any machine running OliverCode, neither of which is framework material and neither of which OliverCode manages:

- **`~/.claude/` (user-global Claude Code settings, skills, agents).** Intentionally local and unmanaged by OliverCode — permissions, theme, and other harness settings live here per-machine by design. The skill/agent layer within it (cross-repo work skills: marketing, GEO, hiring, meeting notes) is real, durable content, not throwaway config. Its placement rules and durability ledger live in `docs/SKILLS-PLACEMENT.md`, not here. This doc's only job is to state the boundary: OliverCode neither reads from nor writes to `~/.claude/` directly.
- **Sibling agent state** (e.g. `.codex/`-class directories from other coding agents/tools). Out of scope for OliverCode entirely — not inventoried, not migrated, not a placement target. Delete on decommission of whatever tool created it. Do not fold its contents into any OliverCode-sanctioned location.

For "where does a new skill/agent file go," see `docs/SKILLS-PLACEMENT.md`'s decision tree — it covers every sanctioned location including the two user-global layers above. This doc and that one together should answer any placement question without asking the owner.

## One-Directional Dependency Rule

The dependency between OliverCode and the runtime environment is one-directional:

- **The runtime environment depends on OliverCode.** It reads contracts, templates, skills, and workflow definitions from OliverCode.
- **OliverCode does NOT depend on the runtime environment.** It can be used standalone. It must not reference runtime-specific paths, scripts, or configuration in its documentation or contracts.

Architectural descriptions may mention the runtime environment as a deployment concept, but must not depend on it for correctness or functionality.

## Standalone Mode

To use OliverCode without a runtime environment:

```
git clone https://github.com/oliver-chase/OliverCode.git
cd OliverCode
scripts/olivercode --help
.githooks/pre-commit
```

Standalone mode provides:
- Framework documentation and contracts
- Launcher surface (`scripts/olivercode`)
- Governance gates (`.githooks/pre-commit`)
- Reusable project templates and manifests

## Runtime Mode

When the local control plane is installed (`runtime/control-plane/`, gitignored), it adds per-machine state on top of OliverCode: the dependency declaration `health` reads, session/handoff state, and a bash shim at `runtime/control-plane/olivercode` that delegates to `scripts/olivercode` and carries no additional commands (`docs/OLIVERCODE-LAUNCHER.md`).

The control plane reads contracts, templates, skills, and workflow definitions from OliverCode. It does not maintain its own copies of these framework artifacts, and OliverCode stays fully usable without it.

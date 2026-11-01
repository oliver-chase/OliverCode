# Framework boundary

## What OliverCode is

OliverCode is the **shared orchestration framework**. It contains:
- Reusable contracts, policies, and standards (`core/contracts/`)
- Reusable skill definitions (`skills/`)
- Project templates (`core/templates/project/`) and shared manifests and registries (`shared/`)
- Framework documentation (`docs/`)
- A thin launcher entrypoint (`scripts/olivercode`)
- Pre-commit governance hooks (`.githooks/`)

OliverCode can be cloned, inspected, and used standalone to read contracts, templates, and documentation without any runtime being installed.

## Canonical paths and ownership

Claude Code is this machine's sole agent runtime.

- Product repos: `<fleet-root>/*`
- Shared system root: `OliverCode`
- Claude runtime/orchestration: `~/.claude`
- Shared skills root: `OliverCode/skills`
- Shared structure and hygiene standard: `OliverCode/core/contracts/PROJECT_STRUCTURE_STANDARD.md`

Ownership follows from the map above:

- Product-specific implementation docs/workflows belong in each project repo.
- Cross-project orchestration standards belong in `shared/*`.
- Shared skills/tools belong in `skills/*`.
- Project structure and hygiene rules belong in `core/contracts/PROJECT_STRUCTURE_STANDARD.md`.
- Runtime state in `~/.claude` is operational data, not product source code.
- Do not duplicate product workflow docs into runtime folders.

When workspace structure or cross-project standards change: update this section (the path
map lives here and nowhere else), and keep the `~/.claude/CLAUDE.md` and `~/.claude/VOICE.md` symlinks pointing at this repo's `CLAUDE.md` and `docs/VOICE.md`
(verified by `scripts/olivercode health`).

## What lives next to it (not inside it)

The `runtime/control-plane/` directory lives inside the OliverCode repo tree but is gitignored. It contains the runtime orchestration state that makes the framework actionable — session handoff, provider health, validation manifests. This is private per-machine state, never pushed to GitHub.

## What OliverCode does NOT contain

OliverCode deliberately does not include:
- Runtime-environment launcher and automation (the thin `scripts/olivercode` CLI is the only launcher surface the framework ships)
- Docker compose or container setup
- Runtime state, logs, telemetry, or handoff data
- Private restore checklists or project-specific credentials
- Generated runtime adapter files
- Runtime-specific validation scripts and automation tools

These belong in the runtime environment (`runtime/control-plane/`), not in the reusable framework.

## User-global and sibling-agent state (outside the framework entirely)

Two more layers exist on any machine running OliverCode, neither of which is framework material and neither of which OliverCode manages:

- **`~/.claude/` (user-global Claude Code settings, skills, agents).** Local and per-machine: permissions, theme, model and any hook the operator writes stay theirs. OliverCode writes these things here through `olivercode install`: the `CLAUDE.md` and `VOICE.md` links, a link per skill in its own `skills/`, its three hook entries in `settings.json`, the install record `.olivercode-install.json` that `uninstall` reads, and a `.pre-olivercode` backup of anything it replaced. `scripts/lib/claude_settings.py` merges those entries and leaves every other key as it was. The skill/agent layer within it (cross-repo work skills: marketing, GEO, hiring, meeting notes) is real, durable content, not throwaway config. Its placement rules and durability ledger live in `docs/SKILLS-PLACEMENT.md`, not here. OliverCode never edits anything else in `~/.claude/`.
- **Sibling agent state** (e.g. `.codex/`-class directories from other coding agents/tools). Out of scope for OliverCode entirely — not inventoried, not migrated, not a placement target. Delete on decommission of whatever tool created it. Do not fold its contents into any OliverCode-sanctioned location.

For "where does a new skill/agent file go," see `docs/SKILLS-PLACEMENT.md`'s decision tree — it covers every sanctioned location including the two user-global layers above. This doc and that one together should answer any placement question without asking the owner.

## One-directional dependency rule

The dependency between OliverCode and the runtime environment is one-directional:

- **The runtime environment depends on OliverCode.** It reads contracts, templates, skills, and workflow definitions from OliverCode.
- **OliverCode does NOT depend on the runtime environment.** It can be used standalone. It must not reference runtime-specific paths, scripts, or configuration in its documentation or contracts.

Architectural descriptions may mention the runtime environment as a deployment concept, but must not depend on it for correctness or functionality.

## Standalone mode

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

## Runtime mode

When the local control plane is installed (`runtime/control-plane/`, gitignored), it adds per-machine state on top of OliverCode: the dependency declaration `health` reads, session/handoff state, and a bash shim at `runtime/control-plane/olivercode` that delegates to `scripts/olivercode` and carries no additional commands (`docs/OLIVERCODE-LAUNCHER.md`).

The control plane reads contracts, templates, skills, and workflow definitions from OliverCode. It does not maintain its own copies of these framework artifacts, and OliverCode stays fully usable without it.

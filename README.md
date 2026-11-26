# OliverCode

**An autonomous engineering harness for Claude Code.**

OliverCode turns Claude Code into a system that can take responsibility for software work—from understanding a task through implementation, validation and delivery.

It runs Claude Code headlessly through your existing signed-in subscription, without an API key or separate per-token billing. Each execution runs in rounds, using the repository's own validation to catch failures and feed them back into the work.

You work with Claude Code normally when you want to think, explore or collaborate. When you delegate work, OliverCode manages the execution, coordination, quality checks, recovery and delivery.

## What it does

- **Executes work:** Runs Claude Code on tasks and delegated stories in isolated worktrees.
- **Coordinates work:** Plans execution, manages dependencies, prioritizes tasks and runs compatible work in parallel.
- **Validates changes:** Runs repository-specific checks and feeds failures back into subsequent rounds.
- **Recovers from failures:** Diagnoses problems and attempts bounded repairs when safe.
- **Delivers work:** Integrates validated changes, pushes completed work and reports blockers.
- **Maintains standards:** Installs shared instructions, skills, hooks and safeguards across governed repositories.
- **Supervises execution:** Tracks progress, decisions, validation, usage and machine health.

Each repository retains its own code, configuration and validation requirements.

## Install

Clone the repository or your fork, open it in Claude Code, and ask:

> Set this up for me.

The adoption skill guides Claude through installation, repository registration and verification.

Or install manually:

```bash
mkdir -p ~/Developer/Repos && cd ~/Developer/Repos
git clone <repo-url-or-fork-url> OliverCode
cd OliverCode
python3 scripts/olivercode install
```

Installation configures shared Claude Code instructions and skills, installs hooks and commit gates, and preserves backups of files it replaces. It is safe to run again.

See [docs/SETUP.md](docs/SETUP.md) for machine setup, restoration, removal and troubleshooting.

## Use it

Interactive Claude Code remains your normal workspace for conversation, exploration, planning and paired coding.

When you want work done independently, explicitly delegate it. Currently, delegated work is represented by a story on the repository's board, with scope and acceptance criteria.

From a project directory, register and configure your repository:

```bash
python3 /path/to/OliverCode/scripts/olivercode bootstrap .
python3 /path/to/OliverCode/scripts/olivercode discover \
  --root /path/to/your/repos --register
python3 /path/to/OliverCode/scripts/olivercode sync-hooks
```

Dispatch queued work:

```bash
olivercode dispatch
```

Preview the execution plan:

```bash
olivercode dispatch --plan
```

Work through a repository's open stories:

```bash
olivercode drain REPO

# Pause new stories; resume later
olivercode pause REPO
olivercode resume REPO

# Cancel one active story, preserving its handoff
olivercode cancel REPO 42
```

Check current work and system health:

```bash
olivercode status
olivercode health
olivercode conform
```

Dispatch and drain run isolated Claude Code sessions, validate changes and safely deliver completed work. Blocked or failed work is reported rather than treated as complete. Pause stops new claims while current builders finish; cancel stops one story after its current model session and preserves its worktree for handoff.

## Command reference

| Job | Commands |
| --- | --- |
| Install and update | `olivercode install` · `olivercode uninstall` · `olivercode update` · `olivercode bootstrap` · `olivercode sync-hooks` · `olivercode place` · `olivercode clean` · `olivercode worktree` · `olivercode commit-check` |
| Check a machine or a repo | `olivercode health` · `olivercode status` · `olivercode status digest` · `olivercode status page` · `olivercode status publish` · `olivercode conform` · `olivercode maintain` · `olivercode limits` |
| Run and land work | `olivercode run` · `olivercode dispatch` · `olivercode drain` · `olivercode pause` · `olivercode resume` · `olivercode cancel` · `olivercode land` · `olivercode wip` · `olivercode validated` · `olivercode queue` |
| Version and docs | `olivercode version-cut` · `olivercode docs-check` |
| Backlog and boards | `olivercode backlog-setup` · `olivercode board groom` · `olivercode board sync` · `olivercode story` · `olivercode candidates` · `olivercode gh-limit` · `olivercode gated` |
| Owner and decisions | `olivercode owner` · `olivercode decisions` |
| Fleet and policy | `olivercode discover` · `olivercode init-fleet` · `olivercode fleet-sync` · `olivercode policy` |
| Orientation | `olivercode guide` |

## How it works

Delegated work moves through a continuous execution cycle:

1. Understand the task and its requirements.
2. Investigate the repository and plan the work.
3. Select an execution strategy and manage dependencies.
4. Implement changes in an isolated environment.
5. Run the repository's validation.
6. Diagnose and repair failures when safe.
7. Integrate verified changes and report the outcome.

Recoverable failures should not require owner intervention. Unrelated work should continue when possible. Unsafe actions, consequential decisions and ambiguous requirements remain with the owner.

## Quality and safeguards

OliverCode surrounds execution with controls designed to prevent unsafe or incomplete work:

- Commit and push gates
- Secret scanning
- Repository-specific validation
- Shared policy and execution rules
- Isolated worktrees
- Bounded recovery and execution
- Fleet-wide safeguard checks
- Decision records and usage controls

Hooks enforce the rules that must block work. Instructions and skills guide the rest.

## Documentation

| Document | Purpose |
| --- | --- |
| [SETUP.md](docs/SETUP.md) | Installation and troubleshooting |
| [RULES.md](docs/RULES.md) | Operating rules and project lifecycle |
| [CONTRACT.md](docs/CONTRACT.md) | Repository requirements |
| [GATES.md](docs/GATES.md) | Quality gates and enforcement |
| [VERSIONING.md](docs/VERSIONING.md) | Version and release rules |
| [VOICE.md](docs/VOICE.md) | Writing standards |
| [DESIGN.md](docs/DESIGN.md) | Visual design standards |
| [skills/INDEX.md](skills/INDEX.md) | Available skills |

For all commands and options:

```bash
python3 scripts/olivercode --help
python3 scripts/olivercode guide
```

## Requirements

macOS or Linux. Git, Bash, Python 3 and Perl. GitHub CLI (`gh`) and `jq` are required for backlog tooling.

Run the full validation suite:

```bash
bash scripts/validate.sh
```

## License

MIT. See [LICENSE](LICENSE).

# OliverCode

> OliverCode gives every repo you work in the same commit gates, contracts, and skills, loaded automatically into each Claude Code session, so an agent never works without your rules.

## What This Is

A git-tracked framework holding the engineering rules you would otherwise re-explain in every
repo. It ships gates that scan for secrets, PII, and emoji before each commit, structural
contracts describing where code and docs belong, and a set of skills covering engineering
method. One command symlinks all of it into every Claude Code session on your machine, from
any working directory.

It exists because a shared layer an agent has to go looking for is a shared layer that
sometimes gets skipped. Here the rules load on their own, and the ones that must always hold
are wired into git hooks that fire whether or not anyone read the documentation. Scope is
security, token cost, folder structure, and development practice. Product logic stays in
product repos by contract (`docs/FRAMEWORK_BOUNDARY.md`), and OliverCode is never a runtime
dependency of the repos it governs.

One thing is worth knowing before you adopt it, because it sets how far to trust each layer:
the pre-commit hook is the part that blocks you. It fires on every `git commit` and refuses
the ones that trip a gate. Contracts, templates, and skills are text an agent loads and
follows, which is a weaker guarantee, and `CONTRIBUTING.md`'s "Enforcement Reality" section
is the one home for which is which. You work with the framework through a single command,
`scripts/olivercode`, and through gates firing on commits you were making anyway.

## The Four Things You Run

**`scripts/olivercode install`** activates a checkout. It symlinks `CLAUDE.md` and every skill
into `~/.claude`, which is what makes the rules load in sessions whose working directory is
somewhere else entirely. Run it once per machine. An existing `~/.claude/CLAUDE.md` is moved
to `CLAUDE.md.pre-olivercode` and the path is printed, because that file is usually your whole
accumulated ruleset. Bring nothing; the command reads what you already have.

**`scripts/olivercode sync-hooks`** installs the gates into each repo you have registered and
points `core.hooksPath` at them. Run it after you register a repo, and again whenever the hook
template changes. Bring a filled-in `local/repo-profiles.json`, which `scripts/olivercode init`
seeds for you. Read the per-repo lines it prints: a repo reported as skipped is a repo it did
not govern.

**`bash scripts/validate.sh`** is what you run before committing to OliverCode itself. It runs
the gates, checks that the docs and the code still agree, resolves every internal reference,
runs the tests, and reports which of your repos are governed. It fails closed on the first
four.

**`scripts/olivercode health`** answers the question the hook cannot: are the gates installed
at all. This matters more than it sounds. Hook enforcement fails open, so if `core.hooksPath`
is unset, points at a missing directory, or the hook is not executable, git runs no hooks and
prints nothing, and a commit carrying secrets succeeds. `health` is the only thing that detects
that state. Schedule it; a single run at setup goes stale the moment a repo's config changes.

## What You Get

**On every commit, in every registered repo**
Six gates: secrets, emoji and icons, PII, references to deleted repos, workflow push-auth, and
planning-doc governance. OliverCode runs two more on itself, contract integrity and token
policy, which validate framework-only files and have nothing to check in a product repo.
`docs/governance.md` holds the coverage table.

**Every Claude Code session, from any directory**
Your `CLAUDE.md` rules and the full skill set, loaded through `~/.claude` symlinks.

**On demand, when you run it**
Doc-versus-code consistency, internal reference integrity, the test suite, and a
fork-usability check that proves a stranger's clone works with no configuration.

**Once, when you stamp a new repo**
The project template: hooks, quality baseline, structure contract, and the supporting scripts
declared in `shared/project-bootstrap-manifest.json`.

## How to Get Started

**First time.** You need `python3`, `git`, `bash`, POSIX shell tools, and `perl`, which backs
the emoji gate and whose absence now blocks the commit. `gh` is needed only when you commit
files under `.github/workflows/`. There is nothing to install and
no language dependencies. Developed and tested on macOS against BSD userland and Bash 3.2, so
Linux should work and is untested; Windows needs WSL.

```bash
git clone <your-fork> OliverCode && cd OliverCode
python3 scripts/olivercode --help
bash scripts/validate.sh
scripts/olivercode health
```

All of that passes on a fresh clone with no setup, no `local/` config, and no surrounding
vault. A failure there is a bug in the fork rather than a problem with your machine, and
`bash scripts/qa/check-fork-usable.sh` verifies the whole property in a sandbox.

The fastest path from here is to let Claude do it: open the repo in Claude Code and say *"set
up OliverCode for my machine."* The `olivercode-adoption` skill ships project-level, so it is
available the moment you clone, before anything is installed. It inventories what you already
have, asks you the handful of decisions only you can make, and does the rest. Working through
it by hand instead is `docs/ADOPTING.md`.

**Optional tooling.** Several third-party plugins shape the token and verification posture
these rules were written against. All of them are optional and OliverCode runs standalone;
`docs/external-tooling.md` says what each is for.

**Coming back.** `scripts/olivercode health` tells you whether your fleet is still governed,
and `scripts/olivercode update` pulls this checkout's tracking branch and re-syncs the hooks.
Taking changes from the repo you forked is a deliberate, separate step, covered under "Staying
current with upstream" in `docs/ADOPTING.md`.

## If You Get Stuck

The `olivercode-adoption` skill handles repair as well as first setup, as a guided,
non-destructive audit; ask Claude Code to run it. For a specific failure,
[Troubleshooting](docs/troubleshooting.md) covers the common ones, starting with commits that
pass gates which should have blocked them. [Feature Map](docs/FEATURE_MAP.md) indexes every
capability this framework ships and names the one doc that owns each, which is the fastest way
to find the right page when you do not yet know what to call the thing you need.

Every document in the repo, by what you would go to it for:

**Orientation**
[Architecture](ARCHITECTURE.md) covers why the framework exists, the three layers, and how
activation works. [Adopting](docs/ADOPTING.md) is the full onboarding path from clone to a
governed fleet. [Framework Boundary](docs/FRAMEWORK_BOUNDARY.md) states what this deliberately
excludes. [Feature Map](docs/FEATURE_MAP.md) is the capability index.

**Enforcement**
[Governance](docs/governance.md) holds the gate list and the per-repo coverage table.
[Token Policy](docs/TOKEN_POLICY.md) is what Gate 8 validates.
[Contributing](CONTRIBUTING.md) carries the "Enforcement Reality" section separating what
blocks you from what merely loads. [Quality Baseline](QUALITY_BASELINE.md) is the standard a
governed repo is held to.

**Working in the repo**
[Agent Rules](CLAUDE.md) is what loads in every session. [CLI](docs/OLIVERCODE_LAUNCHER.md)
documents the `olivercode` command surface.
[Skills Placement](docs/skills-placement.md) decides where any new skill or agent file goes,
and [Skills Index](skills/INDEX.md) catalogs the ones that ship.
[Documentation Standard](docs/DOCUMENTATION_STANDARD.md) governs the docs themselves, and
[Backlog](docs/BACKLOG.md) is the live board of open work.

**Contracts**, all under `core/contracts/`:
[Framework Baseline](core/contracts/FRAMEWORK_BASELINE.md),
[Execution Contract](core/contracts/EXECUTION_CONTRACT.md),
[Project Structure](core/contracts/PROJECT_STRUCTURE_STANDARD.md),
[File Location](core/contracts/FILE_LOCATION_STANDARD.md),
[Agent Shared Structure](core/contracts/AGENT_SHARED_STRUCTURE.md),
[Project Hygiene](core/contracts/PROJECT_HYGIENE_STANDARD.md),
[Public/Private Repos](core/contracts/PUBLIC_PRIVATE_REPO_STANDARD.md),
[No Icons](core/contracts/NO_ICONS_STANDARD.md).

**Procedures**, all under `core/workflows/`:
[Workflows Index](core/workflows/README.md),
[OliverCode Sync](core/workflows/olivercode-sync.md),
[Project Standardization](core/workflows/project-standardization-lifecycle.md),
[Story Lifecycle](core/workflows/story-lifecycle-sop.md), plus
[Workflow Standards](shared/workflow-standards.md) for trigger routing and branch lifecycle.

**Also here**
[Keepalive Standard](docs/KEEPALIVE_STANDARD.md) for the Supabase and Cloudflare contract,
[External Tooling](docs/external-tooling.md) for the optional third-party plugins,
[Persona](core/personas/oliver/persona_soul.md) for the one orchestration role,
[Claude OS](.claude-optimization/README.md) for the standalone memory and state layer, and
[License](LICENSE), which is MIT.

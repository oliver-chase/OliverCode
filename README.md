# OliverCode

OliverCode is a harness for Claude Code. An agent is the model plus its harness. OliverCode drives Claude Code headless, through the owner's signed-in subscription, with no API key and no per-token billing, and wraps each run in rounds that run the repo's own validation and feed failures back. It adds the shared instructions, skills, commit gates, fleet checks and checks that direct and check every session.

Every project gets the same rules, skills, templates and repository checks, and keeps its own code and local configuration.

What the harness covers today:

- `olivercode run` and `olivercode dispatch`: Claude Code headless on a task or a board story, with the repo's own validation between rounds
- `olivercode drain` and `olivercode land`: a repo's open stories worked in priority order, each rebased, validated and pushed to main
- Shared instructions, voice and design standards, and skills that install into `~/.claude`
- Commit and push gates that refuse unsafe or incomplete work, with checks that the gates still run in every fleet repo
- Fleet checks for layout, boards, ledgers, tests, research and machine health, plus scheduled jobs that groom boards, and sync repos with no model call
- A GitHub budget and a validation queue that every session shares
- A decision ledger that keeps the owner's exact words for each decision

Also in place: regression evals that replay fixed scenarios through the real hooks, a check that policy cannot turn off silently, and a lessons log with a retro step. Fresh-clone portability, second-device sync, honest token counts and a check for each lesson are tracked on the backlog.

## Install

Clone the public repository, or fork it on GitHub and clone your fork. For a copy with no history, run `python3 scripts/qa/leak_scan.py --release DIR` and use the single-commit copy it writes. Open the folder in Claude Code and say what you want, for example `Set this up for me.` Claude installs OliverCode, registers your repos and checks that the gates block.

Manual install:

```bash
mkdir -p ~/Developer/Repos && cd ~/Developer/Repos
git clone <repo-url-or-fork-url> OliverCode
cd OliverCode
python3 scripts/olivercode install
```

The install command builds the commit hooks from `core/hooks/`, links `CLAUDE.md`, `VOICE.md`, `DESIGN.md` and skills into `~/.claude`, installs the Claude Code hooks, and preserves backups of files it replaces. It is safe to run again.

Install also links its `CLAUDE.md` into every Claude Code session on the machine, and the agents it governs build and merge a story's changes without asking. Read `CLAUDE.md` and `docs/RULES.md` before you install it.

Read [`docs/SETUP.md`](docs/SETUP.md) for machine setup, restoration, removal and troubleshooting.

## How work runs

You work in one thread, and you say what you want. Each request becomes a story on the repo's board. `olivercode dispatch N` or `olivercode drain REPO` builds a story in one fresh headless Claude session, in its own worktree. The builder commits and stops, and the runner validates the commit, lands it on main, logs the story and closes it. `olivercode status` shows what is open. You decide production deploys, payments, credentials and the rules files, and the runner leaves those to you.

## Dispatch planning

`olivercode dispatch --plan` reads each story's Files area, holds back stories that overlap and runs the rest in parallel, and sets the model by story size. A story with no Files area is refused until it gets one.

## Use it in a project

From a project directory:

```bash
python3 /path/to/OliverCode/scripts/olivercode bootstrap .
python3 /path/to/OliverCode/scripts/olivercode discover --root /path/to/your/repos --register
python3 /path/to/OliverCode/scripts/olivercode sync-hooks
```

`bootstrap` adds the managed project files, `discover --register` adds the repo to the fleet, and `sync-hooks` installs the current hooks in every registered repo and sets Git's `core.hooksPath`. The project declares its own validation command and keeps project-specific behavior in its own repository.

Check the installation and registered projects with:

```bash
python3 scripts/olivercode health
python3 scripts/olivercode conform
```

## Commands

`python3 scripts/olivercode --help` prints every command with its arguments, and `python3 scripts/olivercode guide` prints the same list with a plain-language overview. `docs/SETUP.md` ("Launcher commands") holds what the help line cannot say. The table below names each command once, by job.

| Job | Commands |
| --- | --- |
| Install and update | `olivercode install`, `olivercode uninstall`, `olivercode update`, `olivercode bootstrap`, `olivercode sync-hooks`, `olivercode place`, `olivercode clean`, `olivercode worktree`, `olivercode commit-check` |
| Check a machine or a repo | `olivercode health`, `olivercode status`, `olivercode status digest`, `olivercode conform`, `olivercode features`, `olivercode machines`, `olivercode ledger`, `olivercode audit-fleet`, `olivercode audit-mode`, `olivercode maintain`, `olivercode eval`, `olivercode report`, `olivercode cutlist`, `olivercode limits`, `olivercode usage` |
| Run and land work | `olivercode run`, `olivercode dispatch`, `olivercode drain`, `olivercode land`, `olivercode wip`, `olivercode validated`, `olivercode queue`, `olivercode batch` |
| Version and docs | `olivercode version-cut`, `olivercode docs-check` |
| Backlog and boards | `olivercode backlog-setup`, `olivercode board groom`, `olivercode gap-sweep`, `olivercode board sweep`, `olivercode board burndown`, `olivercode story`, `olivercode candidates`, `olivercode gh-limit` |
| Owner and decisions | `olivercode owner`, `olivercode push-blocked`, `olivercode decisions` |
| Learning | `olivercode lesson`, `olivercode retro` |
| Fleet and policy | `olivercode discover`, `olivercode init-fleet`, `olivercode fleet-sync`, `olivercode review`, `olivercode policy` |
| Orientation | `olivercode skills`, `olivercode guide` |

The scheduled jobs (`burndown`, `sweep`, `fleet-sync`, `review`, `retro`, `maintain`, `gh-limit`, `version-cut`) take `--schedule` to install a launchd job and `--unschedule` to remove it.

## Skills

Say what you want to Claude Code and the matching skill loads, for example "audit this". `python3 scripts/olivercode guide` lists every skill with the phrases that load it, and [`skills/INDEX.md`](skills/INDEX.md) is the catalog.

## What runs automatically

- Git runs the `.githooks` hooks on each commit while `core.hooksPath` points to it, and Claude Code runs the hooks `install` adds (`docs/RULES.md`, "Execution")
- `bash scripts/validate.sh` checks OliverCode's gates, documents, references and tests

Hooks enforce the rules that must block work. The standards and skills guide the rest. [`docs/GATES.md`](docs/GATES.md) lists each gate and its scope.

## Repository layout

| Path | Purpose |
| --- | --- |
| `CLAUDE.md` | Rules loaded in every Claude Code session |
| `core/hooks/` | Source for the generated repository hooks |
| `core/templates/project/` | Files copied into downstream projects |
| `skills/` | Reusable engineering and framework skills |
| `shared/` | Example registries and bootstrap data |
| `.githooks/` | OliverCode's own Git hooks |
| `.github/` | The framework CI workflow, paused while Actions billing is off |
| `.claude/` | The adoption skill link, so a fresh clone opened in Claude Code can set itself up |
| `.olivercode/` | This repo's permission policy (`olivercode policy init`) |
| `scripts/olivercode` | Command-line entry point |
| `scripts/lib/` | Command implementations and checks |
| `scripts/hooks/` | Claude Code hook implementations |
| `scripts/qa/` | Installation and gate rehearsals |
| `docs/` | Standards and reference documents, including `DESIGN.md` for visual work |
| `tests/` | Tests for the shipped checks and commands |
| `olivercode.local.example.json` | The example of this machine's `olivercode.local.json`, which is gitignored |
| `runtime/control-plane/` | Local control-plane state, gitignored and never pushed |
| `scratch/` | Local working files, gitignored. The board backups `backlog-setup` writes go to `backlog-backups/` in the repo's git directory |

## Using OliverCode in your own fork

Four things differ in a fork. This repository is public. Get the code by cloning it or by forking it on GitHub, then cloning your fork. `docs/backlog-config.json` names this repository's board and the `backlog` skill refuses it in any other checkout, so run `olivercode backlog-setup` to create your own. The README names this repository, so edit its issue links. Machine paths live in `olivercode.local.json`, which is gitignored: copy `olivercode.local.example.json` and fill it in. `bash scripts/qa/rehearse-install.sh` proves the install in a sandbox before you trust it.

## Documentation

| Document | Purpose |
| --- | --- |
| [`docs/SETUP.md`](docs/SETUP.md) | Setup, restoration, removal, commands and troubleshooting |
| [`docs/VERSIONING.md`](docs/VERSIONING.md) | What moves MAJOR, MINOR and PATCH, and the rules the daily version cut reads |
| [`docs/RULES.md`](docs/RULES.md) | Standing rules and project lifecycle |
| [`docs/CONTRACT.md`](docs/CONTRACT.md) | Required project shape and allowed differences |
| [`docs/GATES.md`](docs/GATES.md) | Gate list and enforcement scope |
| [`docs/VOICE.md`](docs/VOICE.md) | Writing rules loaded in every session |
| [`docs/DESIGN.md`](docs/DESIGN.md) | Design standard, read on visual work |
| [`docs/AUDIT-ACCEPTED.md`](docs/AUDIT-ACCEPTED.md) | Audit findings the owner accepted, each with its reason |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | Review marker for the live GitHub Project backlog |
| [`docs/SHARING.md`](docs/SHARING.md) | Whether the repository can be shared, and why |
| [`skills/INDEX.md`](skills/INDEX.md) | Included skill catalog |

## Status

`VERSION` holds the current version, MAJOR.MINOR.PATCH, cut once per day of activity as [`docs/VERSIONING.md`](docs/VERSIONING.md) describes, and `CHANGELOG.md` lists what each version changed. `olivercode health` still prints how many commits a checkout is behind upstream and what they are, and the `stable` tag marks the last commit the owner confirmed. It runs on macOS and Linux with `git`, `bash`, `python3` and `perl`, and `gh` with `jq` for the backlog scripts. `bash scripts/validate.sh` proves the gates, docs, references and tests in one run.

## License

MIT, in [`LICENSE`](LICENSE).

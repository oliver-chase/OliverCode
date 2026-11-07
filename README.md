# OliverCode

OliverCode gives Claude Code projects one set of instructions, skills, templates and Git checks.

It installs shared Claude configuration, links the included skills, and installs repository hooks that refuse unsafe or incomplete commits. Each project keeps its own code and local configuration; OliverCode supplies the reusable rules and checks.

## Install

Requirements: `git`, `bash`, `python3` and `perl`.

```bash
git clone https://github.com/oliver-chase/OliverCode.git
cd OliverCode
python3 scripts/olivercode install
```

The install command links `CLAUDE.md`, `VOICE.md` and the skills into `~/.claude`, installs the Claude Code hooks, and preserves backups of files it replaces. It is safe to run again. For guided setup, open the clone in Claude Code and say `Set this up for me.`

Read [`docs/SETUP.md`](docs/SETUP.md) for machine setup, restoration, removal and troubleshooting.

## Use it in a project

From a project directory:

```bash
python3 /path/to/OliverCode/scripts/olivercode bootstrap .
python3 /path/to/OliverCode/scripts/olivercode sync-hooks .
```

`bootstrap` adds the managed project files. `sync-hooks` installs the current hooks and sets Git's `core.hooksPath`. The project declares its own validation command and keeps project-specific behavior in its own repository.

Check the installation and registered projects with:

```bash
python3 scripts/olivercode health
python3 scripts/olivercode conform
```

## Commands

The launcher's command table (`COMMANDS` in `scripts/lib/cli.py`) is the home of this list. `python3 scripts/olivercode guide` prints an overview built from it, and `--help` prints the table itself.

| Command | Purpose |
| --- | --- |
| `olivercode install` | Link `CLAUDE.md`, `VOICE.md`, the skills and the Claude Code hooks into `~/.claude` |
| `olivercode uninstall` | Remove what `install` wrote and restore what it backed up |
| `olivercode update` | Pull this checkout, re-run `install`, then `sync-hooks` |
| `olivercode health` | Check this machine: hooks, skill links, voice copies, remotes, file sizes |
| `olivercode conform` | Check a repo, or every registered repo, against `docs/CONTRACT.md` |
| `olivercode bootstrap` | Stamp the project template into a repo (`--dry-run` shows the plan) |
| `olivercode sync-hooks` | Converge the hooks and `core.hooksPath` across the fleet |
| `olivercode discover` | Scan for git repos and report what governance they have |
| `olivercode backlog-setup` | Set up or repair a repo's GitHub Project board and backlog config |
| `olivercode size` | Print a repo's line count, baseline and headroom |
| `olivercode audit-fleet` | Run the audit skill's structure check on the skills folders |
| `olivercode skills` | List the skills, optionally filtered with `--grep` |
| `olivercode guide` | Print first steps, every command and every skill with its trigger phrases |

## Skills

Say what you want to Claude Code and the matching skill loads, for example "audit this". `python3 scripts/olivercode guide` lists every skill with the phrases that load it, and [`skills/INDEX.md`](skills/INDEX.md) is the catalog.

## What runs automatically

- Git runs `.githooks/pre-commit` on every commit while `core.hooksPath` points to it
- Claude Code runs the session, commit and early-stop hooks installed by `install`
- `bash scripts/validate.sh` checks OliverCode's gates, documents, references and tests

Hooks enforce the rules that must block work. The standards and skills guide the rest. [`docs/GATES.md`](docs/GATES.md) lists each gate and its scope.

## Verify OliverCode

```bash
bash scripts/validate.sh
bash scripts/validate.sh --tree
bash scripts/qa/rehearse-install.sh
```

The rehearsal uses disposable directories. It verifies a fresh install, managed links, hooks and refusal cases without changing the real machine.

## Repository layout

| Path | Purpose |
| --- | --- |
| `CLAUDE.md` | Rules loaded in every Claude Code session |
| `core/hooks/` | Source for the generated repository hooks |
| `core/templates/project/` | Files copied into downstream projects |
| `skills/` | Reusable engineering and framework skills |
| `shared/` | Example registries and bootstrap data |
| `.githooks/` | OliverCode's own Git hooks |
| `scripts/olivercode` | Command-line entry point |
| `scripts/lib/` | Command implementations and checks |
| `scripts/hooks/` | Claude Code hook implementations |
| `scripts/qa/` | Installation and gate rehearsals |
| `docs/` | Standards and reference documents |
| `tests/` | Tests for the shipped checks and commands |

## Documentation

| Document | Purpose |
| --- | --- |
| [`docs/SETUP.md`](docs/SETUP.md) | Setup, restoration, removal, commands and troubleshooting |
| [`docs/RULES.md`](docs/RULES.md) | Standing rules and project lifecycle |
| [`docs/CONTRACT.md`](docs/CONTRACT.md) | Required project shape and allowed differences |
| [`docs/GATES.md`](docs/GATES.md) | Gate list and enforcement scope |
| [`docs/VOICE.md`](docs/VOICE.md) | Writing rules loaded in every session |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Decisions that need more than a code comment |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | Review marker for the live GitHub Project backlog |
| [`skills/INDEX.md`](skills/INDEX.md) | Included skill catalog |

## Contributing

Read [`CLAUDE.md`](CLAUDE.md) and [`docs/RULES.md`](docs/RULES.md) before changing the framework. Run `bash scripts/validate.sh`, review the staged diff, then commit and push with the relevant story reference.

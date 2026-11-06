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

# OliverCode

OliverCode gives every code project you work on the same working rules and automatic safety checks — set up once, applied everywhere, without anyone having to remember them.

Two problems drive its design.

**An AI assistant only follows rules it can see.** Claude Code reads its instructions from one specific file name, `CLAUDE.md`. Rules saved under any other name are never read. Rules written for one project do not exist in the next one. Anything explained in a chat is forgotten when the session ends.

So everything here loads automatically. One install command links the same rules and skills into every session on your machine, and the rules that must never be broken are enforced by git itself — checks that run every time work is saved, whether or not anyone remembered them.

**Those git checks can silently vanish.** Git only runs them when a small piece of configuration points at them. If that configuration is missing or broken:

- git runs no checks
- git shows no warning
- a save containing a real password goes straight through

`scripts/olivercode health` is the command that catches this. Setup ends with a rehearsal: you try to save a fake password and watch the system refuse it, so you know the protection is real before you rely on it.

---

## Install

```bash
git clone <your-fork> OliverCode && cd OliverCode
bash scripts/validate.sh              # self-test: checks, docs, and tests all pass
scripts/olivercode install            # links the rules + skills into every session
scripts/olivercode init               # creates your private settings from templates
```

These three commands work on a brand-new download with zero setup. If one fails, the copy you downloaded is broken — nothing on your computer needs fixing.

You need `python3`, `git`, `bash`, and `perl`, which a Mac already has. Nothing gets installed, no accounts, no packages. Built and verified on macOS; Linux should work, untested; Windows needs WSL.

**The easier path:** open the downloaded folder in Claude Code and say *"set up OliverCode for my machine"*. A built-in setup skill walks the whole process, asks only the decisions that need you, and does the rest.

Nothing here destroys what you had:

- if you already have a `~/.claude/CLAUDE.md` rules file, `install` saves a backup copy first and prints where it put it
- `init` never overwrites a file that already exists
- both commands are safe to run twice

---

## How a project comes under protection

In order:

1. **Tell OliverCode about the project.** Add it to your private settings file, `local/repo-profiles.json` — `init` creates the file, and `scripts/olivercode discover` finds your projects and writes ready-to-paste entries. Projects can live anywhere on the machine.
2. **Run `scripts/olivercode sync-hooks`.** This installs the checks into each listed project. Read what it prints: a project marked "skipped" did not get protected.
3. **Rehearse a failure.** Put a fake password in a file and try to save it — the save must be refused. Step 2 saying "done" only means files were written; this step is what proves the protection works. The full setup guide ends on it.
4. **Run `scripts/olivercode health` regularly.** It is the only thing that notices when a project's checks have quietly stopped applying.

A protected project gets six checks on every save: real passwords and keys, emoji, personal information, references to deleted projects, unsafe automation files, and planning-document rules.

OliverCode runs two extra checks on itself that only make sense here — they validate the framework's own configuration files. `docs/GOVERNANCE.md` has the full table, plus the documented way to let one project run different checks on purpose.

---

## What you get

**Every time work is saved, in every protected project** — the checks run and can refuse the save. They work even when nobody has read any documentation.

**In every Claude Code session, from any folder** — your rules and the full skill set are already loaded.

**When you run `bash scripts/validate.sh`** — the framework tests itself: documentation still matches the code, every internal link still works, the test suite passes, and each of your projects is reported as protected or not.

**When you start a new project** — `scripts/olivercode bootstrap` copies the standard project files in. Run it with `--dry-run` first; that shows every file it would touch without touching anything.

---

## Three design decisions

### Only the git checks are trusted to enforce

Everything else — rules, templates, skills — is written guidance. The AI follows it because it is loaded, and that is weaker than a check that can refuse a save.

The framework keeps that distinction explicit. `CONTRIBUTING.md` lists which rules actually block and which merely instruct. When the same mistake keeps happening, the written rule gets turned into a check.

### Every check must be able to fail

The common defect in tooling like this is a check that says "PASS" without having examined anything — a scan that silently skips when a tool it needs is missing, a result printed over an empty list.

This framework hunts that defect in its own code with a dedicated detector, and its test suite proves each check the direct way: deliberately break the thing a check watches, then confirm the check catches it.

### Your private data never enters the shared code

Your real project names, file paths, and machine details live in files git is told to ignore, so they are never uploaded. The shared, uploadable files carry only placeholder examples.

A check enforces this: it reads your real project names from the private files and refuses any save that would put one of them into a shared file. A separate check proves the whole framework still works for a stranger who downloads it with none of your private files present.

---

## Checking the whole story yourself

```bash
bash scripts/qa/check-fork-usable.sh   # fast: a fresh download works and the protection blocks
bash scripts/qa/check-scenarios.sh     # thorough: 12 complete setup walkthroughs
bash scripts/qa/full-qa-pass.sh        # code quality, documentation health, size limits
```

The 12 walkthroughs each run in a disposable sandbox that cannot touch your real files: a brand-new machine, a machine with existing rules, projects scattered across folders, wrong settings, and a full uninstall.

Every claim they test is a sentence somewhere in this documentation, so a failure means the code or that sentence is wrong.

---

## Documentation

| | |
|---|---|
| **[ADOPTING.md](docs/ADOPTING.md)** | The full setup guide, step by step, ending in proof the protection works |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | How the pieces fit: the three layers, what loads where, what depends on what |
| **[GOVERNANCE.md](docs/GOVERNANCE.md)** | Every check, what it refuses, and which projects get which |
| **[FEATURE_MAP.md](docs/FEATURE_MAP.md)** | Every capability, mapped to the one document that owns it |
| **[OLIVERCODE_LAUNCHER.md](docs/OLIVERCODE_LAUNCHER.md)** | Every `olivercode` command |
| **[DOCUMENTATION_STANDARD.md](docs/DOCUMENTATION_STANDARD.md)** | The required structure and writing style for all documentation, here and in your projects |
| **[TOKEN_POLICY.md](docs/TOKEN_POLICY.md)** | The cost-control settings and the check that validates them |
| **[SKILLS-PLACEMENT.md](docs/SKILLS-PLACEMENT.md)** | Where any new skill file belongs |
| **[FRAMEWORK_BOUNDARY.md](docs/FRAMEWORK_BOUNDARY.md)** | What OliverCode deliberately does not do |
| **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** | Fixes by symptom, starting with saves that should have been refused |
| **[EXTERNAL-TOOLING.md](docs/EXTERNAL-TOOLING.md)** | Optional third-party plugins that pair well; none are required |
| **[KEEPALIVE_STANDARD.md](docs/KEEPALIVE_STANDARD.md)** | Keeping free-tier cloud services from going dormant |
| **[BACKLOG.md](docs/BACKLOG.md)** | Open work — read it before assuming a feature exists |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | Which rules block a save and which are guidance |
| **[QUALITY_BASELINE.md](QUALITY_BASELINE.md)** | The quality bar a protected project is held to |
| **[CLAUDE.md](CLAUDE.md)** | The rules the AI loads in every session |
| **[skills/INDEX.md](skills/INDEX.md)** | Every skill that ships, in one list |
| **[Contracts](core/contracts/)** | The standing standards: structure, execution, hygiene, intent, file locations |
| **[Workflows](core/workflows/)** | Repeatable procedures that span projects |
| **[Claude OS](.claude-optimization/README.md)** | The assistant's own memory and state files |

## Status

`python3 -m unittest discover tests` runs the test suite and reports its own count; the suite includes tests that break each check on purpose to confirm it notices.

8 checks run on saves to this repository;
a protected project receives six of those. Both numbers are verified against the actual check files on every self-test, so a change to either fails until this file is corrected.

`bash scripts/qa/check-scenarios.sh` runs the setup walkthroughs and prints its own tally. Plain `python3`, `bash`, and `perl` throughout — no packages to install. Built on macOS; automated cloud testing ships ready and is switched on per copy.

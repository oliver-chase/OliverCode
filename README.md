# OliverCode

OliverCode gives every code project you work on the same engineering rules, AI context, and automated safety checks — set up once, applied everywhere, without anyone having to remember them.

Two problems drive its design.

### Instructions are easy to lose

An AI assistant only follows rules it can see. Claude Code reads its instructions from one specific file name, `CLAUDE.md`. Rules saved under any other name are never read.

Rules written for one project do not exist in the next one, and anything explained in a chat is forgotten when the session ends.

So everything here loads automatically. One install command symlinks the same rules and skills into every session on your machine — a symlink is a pointer file, so every project reads one shared original.

### Guidance is not enforcement

Documentation can explain what should happen. It cannot guarantee that it does.

The rules that must never be broken are enforced as pre-commit hooks: checks git runs before accepting each commit, whether or not anyone remembered them.

Hook enforcement has one dangerous failure mode: git only runs pre-commit hooks when its `core.hooksPath` setting points at them. If that setting is missing or broken:

- git runs no hooks
- git shows no warning
- a commit containing a real password goes straight through

`scripts/olivercode health` is the command that catches this. Setup ends with a rehearsal: you try to commit a fake password and watch the hook refuse it, so you know enforcement is real before you rely on it.

---

## Install

```bash
git clone <your-fork> OliverCode && cd OliverCode
bash scripts/validate.sh              # self-test: gates, docs, and tests all pass
scripts/olivercode install            # symlinks the rules + skills into ~/.claude
scripts/olivercode init               # seeds your gitignored local/ config from templates
```

These three commands work on a fresh clone with zero setup — no config, no accounts. If one fails, the clone itself is broken; nothing on your machine needs fixing.

You need `python3`, `git`, `bash`, and `perl`, which a Mac already has. Nothing gets installed, no accounts, no packages. Built and verified on macOS; Linux should work, untested; Windows needs WSL.

**The easier path:** open the cloned folder in Claude Code and say *"set up OliverCode for my machine"*. A built-in setup skill walks the whole process, asks only the decisions that need you, and does the rest.

Nothing here destroys what you had:

- if you already have a `~/.claude/CLAUDE.md` rules file, `install` saves a backup copy first and prints where it put it
- `init` never overwrites a file that already exists
- both commands are safe to run twice

---

## How a repo becomes governed

In order:

1. **Register the repo** in `local/repo-profiles.json` — your fleet list, gitignored so it never uploads. `init` creates it, and `scripts/olivercode discover` finds your repos and writes ready-to-paste entries. Repos can live anywhere on the machine.
2. **Run `scripts/olivercode sync-hooks`.** This installs the hooks into each registered repo. Read what it prints: a repo marked "skipped" did not get governed.
3. **Rehearse a failure.** Put a fake password in a file and try to commit it — the commit must be refused. Step 2 saying "done" only means files were written; this rehearsal is what proves enforcement works. The full setup guide ends on it.
4. **Run `scripts/olivercode health` regularly.** It is the only thing that notices when a repo's hooks have quietly stopped applying.

A governed repo gets eight gates on every commit: secrets (passwords and keys), emoji, PII (personal information), references to deleted repos, unsafe workflow files, planning-document rules, comment length, and decision records.

OliverCode runs a further pair of gates on itself, ones that only make sense here — they validate the framework's own configuration files. `docs/GOVERNANCE.md` has the full table, plus the documented way to let one repo run different hooks on purpose.

---

## What you get

**On every commit, in every governed repo** — the gates run and can refuse the commit. They work even when nobody has read any documentation.

**In every Claude Code session, from any folder** — your rules and the full skill set are already loaded.

**When you run `bash scripts/validate.sh`** — the framework tests itself: documentation still matches the code, every internal reference resolves, the test suite passes, and each of your repos is reported as governed or not.

**When you start a new repo** — `scripts/olivercode bootstrap` stamps the standard project files in. Run it with `--dry-run` first; that shows every file it would touch without touching anything.

---

## Three design decisions

### Only the hooks are trusted to enforce

Everything else — contracts, templates, skills — is written guidance. The agent follows it because it is loaded, and that is weaker than a gate that can refuse a commit.

The framework keeps that distinction explicit. `CONTRIBUTING.md` lists which rules actually block and which merely instruct. When the same mistake keeps happening, the written rule gets turned into a gate.

### Every gate must be able to fail

The common defect in tooling like this is a check that says "PASS" without having examined anything — a scan that silently skips when a tool it needs is missing, a result printed over an empty list.

This framework hunts that defect in its own code with a dedicated detector, and its test suite proves each check the direct way: deliberately break the thing a check watches, then confirm the check catches it.

### Your private data never enters the tracked files

Your real repo names, file paths, and machine details live in gitignored files (`local/`, `runtime/`) — git never uploads them. The tracked files, the ones a fork receives, carry only placeholder examples.

A gate enforces this: it reads your real repo names from the gitignored config and refuses any commit that would put one of them into a tracked file. A separate check proves the whole framework still works for a stranger who clones it with none of your private files present.

---

## Checking the whole story yourself

```bash
bash scripts/qa/check-fork-usable.sh   # fast: a fresh clone works and the gates block
bash scripts/qa/check-scenarios.sh     # thorough: 12 complete setup walkthroughs
bash scripts/qa/full-qa-pass.sh        # code quality, documentation health, size limits
```

The 12 walkthroughs each run in a disposable sandbox that cannot touch your real files: a brand-new machine, a machine with existing rules, repos scattered across folders, wrong settings, and a full uninstall.

Every claim they test is a sentence somewhere in this documentation, so a failure means the code or that sentence is wrong.

---

## Documentation

| | |
|---|---|
| **[ADOPTING.md](docs/ADOPTING.md)** | The full setup guide, step by step, ending in proof the gates block |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | How the pieces fit: the three layers, what loads where, what depends on what |
| **[GOVERNANCE.md](docs/GOVERNANCE.md)** | Every gate, what it refuses, and which repos get which |
| **[FEATURE_MAP.md](docs/FEATURE_MAP.md)** | Every capability, mapped to the one document that owns it |
| **[OLIVERCODE_LAUNCHER.md](docs/OLIVERCODE_LAUNCHER.md)** | Every `olivercode` command |
| **[WRITING_PROCESS.md](docs/WRITING_PROCESS.md)** | How to think before writing a doc or a comment. Read before the standard below, which is QA |
| **[DOCUMENTATION_STANDARD.md](docs/DOCUMENTATION_STANDARD.md)** | The required structure and writing style for all documentation, here and in your projects |
| **[TOKEN_POLICY.md](docs/TOKEN_POLICY.md)** | The cost-control settings and the check that validates them |
| **[SKILLS-PLACEMENT.md](docs/SKILLS-PLACEMENT.md)** | Where any new skill file belongs |
| **[FRAMEWORK_BOUNDARY.md](docs/FRAMEWORK_BOUNDARY.md)** | What OliverCode deliberately does not do |
| **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** | Fixes by symptom, starting with commits that should have been refused |
| **[EXTERNAL-TOOLING.md](docs/EXTERNAL-TOOLING.md)** | Optional third-party plugins that pair well; none are required |
| **[KEEPALIVE_STANDARD.md](docs/KEEPALIVE_STANDARD.md)** | Keeping free-tier cloud services from going dormant |
| **[BACKLOG.md](docs/BACKLOG.md)** | Open work — read it before assuming a feature exists |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | Which rules block a save and which are guidance |
| **[QUALITY_BASELINE.md](QUALITY_BASELINE.md)** | The quality bar a governed repo is held to |
| **[CLAUDE.md](CLAUDE.md)** | The rules the AI loads in every session |
| **[skills/INDEX.md](skills/INDEX.md)** | Every skill that ships, in one list |
| **[Contracts](core/contracts/)** | The standing standards: structure, execution, hygiene, intent, file locations |
| **[Workflows](core/workflows/)** | Repeatable procedures that span projects |
| **[Claude OS](.claude-optimization/README.md)** | The assistant's own memory and state files |

## Status

`python3 -m unittest discover tests` runs the test suite and reports its own count; the suite includes tests that break each gate on purpose to confirm it notices.

10 gates run on commits to this repository;
a governed repo receives eight of those. Both numbers are verified against the actual hook files on every self-test, so a change to either fails until this file is corrected.

`bash scripts/qa/check-scenarios.sh` runs the setup walkthroughs and prints its own tally. Plain `python3`, `bash`, and `perl` throughout — no packages to install. Built on macOS; CI ships ready and is enabled per fork.

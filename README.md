# OliverCode

OliverCode is a shared set of **rules, skills, and automated checks for your code projects**.

Set it up once on your machine, and those standards apply across your projects:

* **Claude Code gets the same instructions and skills in every project.**
* **Your repositories get the same engineering and safety checks.**
* **Git can block a commit when a rule is broken.**
* **OliverCode checks that those protections are still working.**

The goal is simple: **set the engineering standards once and have them consistently applied everywhere.**

It solves two problems.

## Instructions are easy to lose

Claude Code only loads instructions from specific locations, including `CLAUDE.md`. Rules saved somewhere else can be missed, and anything explained in a chat disappears when the session ends.

OliverCode puts one shared set of rules and skills into `~/.claude` using symlinks. A symlink is a pointer to the original file, so every project uses the same source of truth.

### Guidance is not enforcement

Documentation can explain what should happen. It cannot stop someone from committing something that violates the rules.

OliverCode uses **Git pre-commit hooks** for rules that must be enforced. Git runs these checks before accepting a commit, and a failing check can refuse the commit.

There is one important failure mode: Git only runs the hooks when its `core.hooksPath` setting points to them. If that setting is missing or broken, Git gives no warning and a bad commit can pass.

`scripts/olivercode health` checks that the hooks are active.

Setup also includes a rehearsal: put a fake password in a file and try to commit it. The hook should refuse the commit. That proves the protection is actually working before you rely on it.

---

## Install

```bash
git clone <your-fork> OliverCode && cd OliverCode
bash scripts/validate.sh
scripts/olivercode install
scripts/olivercode init
```

These commands work from a fresh clone with no configuration, accounts, or packages.

You need:

* `python3`
* `git`
* `bash`
* `perl`

macOS already includes them. Nothing else is installed, and no accounts or packages are required.

OliverCode is built and verified on macOS. Linux should work but is untested. Windows requires WSL.

### The easier path

Open the cloned folder in Claude Code and say:

> **Set up OliverCode for my machine.**

The built-in setup skill walks through the process, asks only for decisions that require you, and handles the rest.

### Safe to run again

OliverCode preserves what you already have:

* If `~/.claude/CLAUDE.md` exists, `install` backs it up and tells you where the backup is.
* `init` never overwrites an existing file.
* Both commands are safe to run more than once.

---

## How OliverCode protects a repo

Once OliverCode is installed, connect each repo in four steps.

### 1. Register the repo

Add the repo to:

```text
local/repo-profiles.json
```

This is your local fleet list. It is gitignored, so your real repo names and machine-specific information never get uploaded.

`init` creates the file. You can also find your repos automatically:

```bash
scripts/olivercode discover
```

This generates ready-to-paste entries. Repos can live anywhere on your machine.

### 2. Install the hooks

Run:

```bash
scripts/olivercode sync-hooks
```

This installs the appropriate hooks into each registered repo.

**Read the output.** A repo marked `skipped` was not governed.

### 3. Prove the hooks work

Put a fake password in a file and try to commit it.

The commit must be refused.

A `sync-hooks` message saying `done` only confirms that the hook files were written. The rehearsal confirms that Git is actually running them.

The full setup guide ends with this test.

### 4. Check health

Run:

```bash
scripts/olivercode health
```

Run it regularly to catch repos whose hooks have stopped applying.

### The nine gates in a governed repo

Every governed repo runs nine checks on every commit:

1. **Secrets** — passwords, keys, and other credentials
2. **Emoji**
3. **PII** — personal information
4. **Deleted-repo references**
5. **Unsafe workflow files**
6. **Planning-document rules**
7. **Comment length**
8. **Decision records**
9. **Backlog hygiene** — including finished items incorrectly marked `DONE`

OliverCode itself runs a further pair of gates that validate the framework's own configuration files.

See [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) for the complete gate table and the documented process for intentionally giving a repo a different set of hooks.

---

## What happens automatically

### Every commit

The gates run automatically and can refuse the commit. They work even when nobody has read the documentation.

### Every Claude Code session

The shared rules and full skill set are already available, regardless of which project or folder you are working in.

### Every OliverCode self-test

Run:

```bash
bash scripts/validate.sh
```

OliverCode checks itself. It verifies that:

* documentation still matches the code
* internal references resolve
* the test suite passes
* registered repos are actually governed

### Every new repo

Run:

```bash
scripts/olivercode bootstrap
```

This adds the standard project files to a new repo.

Use `--dry-run` first to see exactly which files would be changed:

```bash
scripts/olivercode bootstrap --dry-run
```

---

## Three design decisions

### Enforcement is explicit

Contracts, templates, documentation, and skills provide guidance. **Hooks are the enforcement layer.**

`CONTRIBUTING.md` identifies which rules block commits and which are guidance. When the same mistake happens repeatedly, the written rule can become an automated gate.

### Every gate must actually fail

A check that reports `PASS` without actually checking anything is a defect. For example, a scan might silently skip itself when a required tool is missing.

OliverCode tests for this failure mode in its own code. The test suite also deliberately breaks every gate and confirms that the gate catches the failure.

### Private data stays private

Real repo names, file paths, and machine details live in gitignored `local/` and `runtime/` files. Tracked files contain only placeholder examples.

A gate prevents private repo names from entering tracked files. A separate test confirms that a fresh clone works without any of those private files.

---

## Verify the whole system

Run these checks when you want to verify the complete system:

```bash
bash scripts/qa/check-fork-usable.sh   # Fresh clone + enforcement
bash scripts/qa/check-scenarios.sh     # 12 complete setup scenarios
bash scripts/qa/full-qa-pass.sh        # Code, docs, and size checks
```

The 12 scenarios run in disposable sandboxes that cannot touch your real files.

They cover:

* a brand-new machine
* a machine with existing Claude rules
* repos stored in different folders
* incorrect settings
* a complete uninstall

Every scenario tests a claim made in the documentation. If one fails, the code or the corresponding documentation is wrong.

---

## Documentation

| Document | Purpose |
| --- | --- |
| [`ADOPTING.md`](docs/ADOPTING.md) | Complete setup and enforcement walkthrough |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | How the three layers fit together |
| [`GOVERNANCE.md`](docs/GOVERNANCE.md) | Every gate, what it blocks, and which repos receive which gates |
| [`FEATURE_MAP.md`](docs/FEATURE_MAP.md) | Every capability and its owning document |
| [`OLIVERCODE_LAUNCHER.md`](docs/OLIVERCODE_LAUNCHER.md) | Every `olivercode` command |
| [`WRITING_PROCESS.md`](docs/WRITING_PROCESS.md) | How to think before writing documentation or comments |
| [`DOCUMENTATION_STANDARD.md`](docs/DOCUMENTATION_STANDARD.md) | Required documentation structure and writing style |
| [`TOKEN_POLICY.md`](docs/TOKEN_POLICY.md) | Token-cost controls and validation |
| [`SKILLS-PLACEMENT.md`](docs/SKILLS-PLACEMENT.md) | Where new skill files belong |
| [`FRAMEWORK_BOUNDARY.md`](docs/FRAMEWORK_BOUNDARY.md) | What OliverCode deliberately does not do |
| [`TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Troubleshooting by symptom |
| [`EXTERNAL-TOOLING.md`](docs/EXTERNAL-TOOLING.md) | Optional third-party tooling |
| [`KEEPALIVE_STANDARD.md`](docs/KEEPALIVE_STANDARD.md) | Keeping free-tier cloud services from going dormant |
| [`BACKLOG.md`](docs/BACKLOG.md) | Open work and planned features |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Which rules block commits and which are guidance |
| [`QUALITY_BASELINE.md`](QUALITY_BASELINE.md) | Quality standard for governed repos |
| [`CLAUDE.md`](CLAUDE.md) | Rules Claude loads in every session |
| [`skills/INDEX.md`](skills/INDEX.md) | Every included skill |
| [**Contracts**](core/contracts/) | Standing standards for structure, execution, hygiene, intent, and file locations |
| [**Workflows**](core/workflows/) | Repeatable procedures across projects |
| [**Claude OS**](.claude-optimization/README.md) | Claude's memory and state files |

---

## Status

Run the test suite with:

```bash
python3 -m unittest discover tests
```

The suite reports its own test count and deliberately breaks each gate to verify that the gate catches the failure.

**OliverCode has 11 gates.**
A governed repo receives nine. Both counts are verified against the actual hook files during every self-test, so changing either number without updating the README causes the self-test to fail.

Run the complete setup scenarios with:

```bash
bash scripts/qa/check-scenarios.sh
```

The command reports its own scenario count.

OliverCode uses only `python3`, `bash`, and `perl`. No packages are required. It is built and verified on macOS; CI is included and can be enabled per fork.

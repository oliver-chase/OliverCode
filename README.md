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

Claude Code only loads instructions from specific locations, including `CLAUDE.md`. A rules file with any other name, such as `AGENTS.md`, never loads, skills pile up in scattered unsynced folders, and anything explained in a chat disappears when the session ends. Working across many repos without a shared layer also means each repo reinvents the same engineering-method knowledge, and its documents drift from what the code does.

OliverCode puts one shared set of rules and skills into `~/.claude` using symlinks. A symlink is a pointer to the original file, so every project uses the same source of truth.

### Guidance is not enforcement

Documentation can explain what should happen. It cannot stop someone from committing something that violates the rules.

OliverCode uses **Git pre-commit hooks** for rules that must be enforced. Git runs these checks before accepting a commit, and a failing check can refuse the commit.

There is one important failure mode: Git only runs the hooks when its `core.hooksPath` setting points to them. If that setting is missing or broken, Git gives no warning and a bad commit can pass.

`scripts/olivercode health` checks that the hooks are active.

OliverCode also installs three Claude Code hooks, which run in every session. At session start, Claude learns when the repo it opened has commit gates that git skips. Before a commit, Claude Code refuses one that would skip the gates. At the end of a turn, Claude goes back to work if it promised work it did not do. `docs/RULES.md` ("Execution") describes each one.

Setup also includes a rehearsal: write a fake API key into a file and try to commit it. The hook should refuse the commit. That proves the protection is actually working before you rely on it.

---

## Install

```bash
git clone <your-fork> OliverCode && cd OliverCode
bash scripts/validate.sh
scripts/olivercode install
```

These commands work from a fresh clone with no configuration, accounts, or packages. `docs/SETUP.md` continues from here: registering your repos, installing their hooks, proving the hooks work and backing out.

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
* `install` is safe to run more than once.

---

## How it works

### What you get

Five things, and it is worth being precise about which are mechanical and which are not:

| You get | How it reaches you | Actually enforced? |
|---|---|---|
| Pre-commit gates (`docs/GATES.md` has the per-repo table) | `.githooks/pre-commit`, installed per repo by `olivercode sync-hooks` | **Yes**, on every `git commit`. Only `--no-verify` skips it, and the commit guard below refuses that inside Claude Code |
| Local validation | `bash scripts/validate.sh`: gates, doc/code consistency, reference integrity, tests | **Yes**, when run. Nothing runs it automatically |
| Standards and templates | `docs/RULES.md` and `core/templates/project/`, inherited by every repo through the bootstrap manifest | No, they are instruction text an agent follows |
| Claude Code hooks (session check, commit guard, early-stop guard) | `~/.claude/settings.json`, written by `olivercode install` | **Yes**, inside Claude Code sessions |
| Skills | `~/.claude/skills/` symlinks, installed by `olivercode install` | No, the agent chooses to load them |

The hooks are the only things that block you. Everything else is a rule an agent follows because it is loaded and not because it is enforced.

### Two layers

1. **OliverCode (this repo).** Standards, skills, templates, the launcher and the governance hooks. The fleet registry (`shared/repo-profiles.json`) ships as an empty example. An operator's real registry lives in a private repo under `olivercode/`, named through `privateRepos` in `olivercode.local.json`, so a fork carries none of it
2. **Product repos (yours).** Sibling repos that inherit hooks, templates and standards from OliverCode and are declared in the registry's `repo-profiles.json`. OliverCode is never a runtime dependency of a product repo, because it defines standards and no implementations

`runtime/control-plane/` is gitignored, optional, and holds private per-machine runtime state. OliverCode works without it.

### How activation works

Nothing here depends on an agent choosing to look:

* `~/.claude/CLAUDE.md` symlinks to this repo's `CLAUDE.md`, so its rules are present in every Claude Code session on the machine, from any working directory
* `~/.claude/skills/<name>` symlinks to `skills/<name>`, so every skill is discoverable from any repo
* `.githooks/pre-commit` runs on every commit in every fleet repo, which enforces rules even when context does not
* `olivercode install` creates both sets of symlinks, and `olivercode health` verifies them along with the hooks and placement drift

The global `CLAUDE.md` loads in sessions whose working directory is almost never OliverCode, so it contains no repo-relative paths. It resolves `$OC` from the symlink itself and says so, and a bare path in it means the repo the agent is currently in. Getting that wrong turns a rules file into dead text that agents silently fail to follow. Anything that must always apply is enforced as a hook and never left to an instruction an agent might not read.

### How OliverCode protects a repo

Once OliverCode is installed, connect each repo in four steps.

**1. Register the repo.** Add it to your fleet list, the registry's `repo-profiles.json`:

```text
<private repo>/olivercode/repo-profiles.json   # when olivercode.local.json names private repos
shared/repo-profiles.json                      # otherwise, in your fork
```

`olivercode discover` prints the path this checkout reads. You can also find your repos automatically, passing `--root` once for each folder to search:

```bash
scripts/olivercode discover --root <folder-holding-your-repos>
```

This generates ready-to-paste entries. Repos can live anywhere on your machine.

**2. Install the hooks.**

```bash
scripts/olivercode sync-hooks
```

This installs the appropriate hooks into each registered repo. **Read the output.** A repo marked `skipped` was not governed.

**3. Prove the hooks work.**

```bash
cd <one of your repos>
bash "$OC/scripts/qa/probe-secret-gate.sh"
```

The probe writes a fake API key into a file and tries to commit it, and the commit must be refused. A `sync-hooks` message saying `done` only confirms that the hook files were written. The probe confirms that Git is actually running them. `docs/SETUP.md` Step 3 shows how to set `$OC`.

**4. Check health.**

```bash
scripts/olivercode health
```

Run it regularly to catch repos whose hooks have stopped applying.

Every governed repo checks each commit for secrets, personal data, unsafe workflow files and unclear agent instructions, among other things. `docs/GATES.md` lists every gate, which repos run which, and how to give a repo a different set of hooks.

### What happens automatically

**Every commit.** The gates run automatically and can refuse the commit. They work even when nobody has read the documentation.

**Every Claude Code session.** The shared rules and full skill set are already available, regardless of which project or folder you are working in.

**Every OliverCode self-test.** `bash scripts/validate.sh` checks OliverCode against itself. It verifies that:

* documentation still matches the code
* internal references resolve
* the test suite passes
* registered repos are actually governed

**Every new repo.** Run this to add the standard project files:

```bash
scripts/olivercode bootstrap <repo-path>
```

Use `--dry-run` first to see exactly which files would be changed:

```bash
scripts/olivercode bootstrap <repo-path> --dry-run
```

---

## Design decisions

### Enforcement is explicit

Standards, templates, documentation and skills provide guidance. **Hooks are the enforcement layer.** When the same mistake happens repeatedly, the written rule becomes an automated gate, because a rule without a gate regresses.

### Enforcement reality

Not every rule in this repo is machine-checked, so know which is which before assuming a rule is unbreakable.

**Hard-enforced:** the gates in `.githooks/pre-commit`, which fire on every `git commit` (`docs/GATES.md` lists them). Inside Claude Code, the commit guard also refuses a commit that would skip them.

**Soft, meaning instruction only:** "read the framework boundary before structural changes", the skill-placement requirements, the code, docs, audit, QA, gate, commit and push ordering, and running the install rehearsal at all (`rehearse-install.sh` is never auto-triggered). These are real rules worth following, and nothing blocks a commit that skips them. Being written in `CLAUDE.md` does not make a rule enforced, so check whether it is a hook or a sentence.

### Every gate must actually fail

A check that reports `PASS` without actually checking anything is a defect. For example, a scan might silently skip itself when a required tool is missing.

OliverCode tests for this failure mode in its own code. The test suite also deliberately breaks every gate and confirms that the gate catches the failure.

### Your data stays out of the harness

OliverCode ships its fleet registry (`shared/repo-profiles.json`) as an empty example. Your real registry lives in a private repo under `olivercode/`, named in `olivercode.local.json` under `privateRepos`, so every device that clones that private repo gets it and a fork of OliverCode gets none of it.

### Operating principles

* Claude Code is the sole runtime and Anthropic the sole model provider, by design
* Fail closed before failing open, and make no capability claim without a runnable verification
* One concept has one home, and everything else points to it
* Project-specific behavior lives in the owning project repo and never here
* OliverCode depends on nothing. Product repos and local state depend on OliverCode (`docs/RULES.md`, "Framework boundary")

---

## Contributing

Every tracked file has to justify itself as run, verify, ship or support (`docs/RULES.md`, "Framework baseline"). Anything that does none of those is deleted, merged or moved to the repo that owns it.

The mandatory rules are in `docs/RULES.md` ("Framework baseline"). Two of them apply to every commit: the documents change in the same change set as the behavior they describe, and `bash scripts/validate.sh` runs before the commit.

The workflow is the development lifecycle and execution process in `docs/RULES.md`, which ends in the gate mechanics in `docs/GATES.md`.

Review evidence required before a commit:

* `bash scripts/validate.sh` passes
* the launcher help surface still matches `docs/SETUP.md` ("Launcher commands")
* removed files have no surviving canonical references
* the git diff contains only intended current-state changes

Required commands:

```bash
bash scripts/validate.sh
scripts/olivercode --help
```

Safe push rules:

* Commit only after the governance gates pass and the staged files are reviewed
* Do not stage secrets, `.env*`, runtime state, private repo content, caches or generated local reports
* After a push, verify that `git status --short --branch` is clean and record the pushed short SHA

### Quality baseline

This repository is the canonical framework repo, so it defines the quality standards that every OliverCode project follows. All managed quality files originate here and are synced to consuming projects:

* `core/templates/project/.github/workflows/qa-hygiene.yml`
* `core/templates/project/.github/workflows/governance-secrets-gate.yml`
* `core/templates/project/.github/workflows/dependency-review.yml`
* `core/templates/project/.github/CODEOWNERS`
* `core/templates/project/.github/pull_request_template.md`
* `core/templates/project/QUALITY_BASELINE.md`
* `.githooks/pre-commit`, the pre-commit gate runner
* `core/templates/project/scripts/`, the template governance scripts

If a managed quality file changes in any project, the canonical file in this repo is changed first and then synced to all projects. OliverCode is the single source of truth. The commit sequence, the gate list, document voice and public-repo redaction each have one owner, and this section does not restate them: `docs/RULES.md`, `docs/GATES.md` and `docs/VOICE.md`.

### Optional tooling

None of these third-party tools ship here, and none are required, because OliverCode runs standalone. They are listed because OliverCode's verification rules were written on a machine that ran them, and a few of the rules read as arbitrary without that context.

| Tool | What it does | Install |
|---|---|---|
| [codeburn](https://github.com/getagentseal/codeburn) | Local token-usage, cost and health dashboard across AI coding tools. It reads session data from disk, with no proxy and no API keys | Per its repo README |
| [claude-code-ui-agents](https://github.com/mustafakendiguzel/claude-code-ui-agents) | Frontend prompt library in plain markdown, fetched per task when a UI request needs it | Reference only |
| [Ant Design](https://github.com/ant-design/ant-design) | Component-API and design-token sanity reference | Reference only |

---

## Verify the whole system

Run these checks when you want to verify the complete system:

```bash
bash scripts/validate.sh --tree          # Every gate over every tracked file, plus docs, bloat, code quality and tests
bash scripts/qa/rehearse-install.sh      # Fresh clone, real install and every setup scenario
```

The scenarios run in disposable sandboxes that cannot touch your real files.

They cover:

* a brand-new machine
* a machine with existing Claude rules
* repos stored in different folders
* incorrect settings
* a complete uninstall

Every scenario tests a claim made in the documentation. If one fails, the code or the corresponding documentation is wrong.

---

## Repository layout

| Path | What it holds |
| --- | --- |
| `CLAUDE.md` | The rules Claude loads in every session, linked into `~/.claude` by `install` |
| `core/hooks/` | The gate scripts that `scripts/build-hooks.py` assembles into each pre-commit and pre-push hook |
| `core/templates/project/` | The project template that `bootstrap` and `sync-hooks` copy into a repo, including the built hooks |
| `skills/` | The skills linked into `~/.claude/skills/`. `skills/INDEX.md` lists them |
| `shared/` | The bootstrap manifest and the example fleet registry |
| `.githooks/` | OliverCode's own pre-commit, commit-msg and pre-push hooks |
| `scripts/olivercode` | The launcher: `bootstrap`, `discover`, `install`, `uninstall`, `health`, `update`, `sync-hooks`, `audit-fleet`, `push-fleet` and `skills` |
| `scripts/validate.sh` | The single validation command, which runs the gates, the consistency checks, the reference check and the tests |
| `scripts/lib/` | The checkers and helpers behind the launcher and `validate.sh` |
| `scripts/hooks/` | The three Claude Code hooks: session check, commit guard and early-stop guard |
| `scripts/qa/` | The install rehearsal and the secret-gate probe |
| `scripts/local-scheduler/` | Unattended `audit-fleet` and `push-fleet` runs through `launchd` (`docs/SETUP.md`, "Scheduled runs") |
| `scripts/audit-staleness.py`, `scripts/find-spec.py`, `scripts/link-check.sh`, `scripts/run-governance-target.sh` | Staleness report, backlog ID lookup, reference check and the CI entrypoint for a downstream repo |
| `docs/` | One document per concept, listed below |
| `tests/` | Tests for the gates, checkers, hooks and launcher |
| `.claude-optimization/memory/` and `.claude-optimization/state/` | Optional memory and state files that `CLAUDE.md` reads when they exist. Memory holds the user profile and durable facts, state holds current targets and the decision log, and both are gitignored and created locally per user |
| `runtime/control-plane/` | Private machine state, gitignored and optional |

---

## Documentation

| Document | Purpose |
| --- | --- |
| [`CLAUDE.md`](CLAUDE.md) | Rules Claude loads in every session |
| [`docs/VOICE.md`](docs/VOICE.md) | How everything a person reads is written, loaded in every session |
| [`docs/SETUP.md`](docs/SETUP.md) | Setup and enforcement walkthrough, restoring a machine, every `olivercode` command and troubleshooting by symptom |
| [`docs/RULES.md`](docs/RULES.md) | Every standing rule: baseline, lifecycle, execution, structure, file locations, boundary, skill placement and documents |
| [`docs/GATES.md`](docs/GATES.md) | Every gate, what it blocks, and which repos receive which gates |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Design decisions whose reasoning is longer than a code comment should carry |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | The live tracker and its review marker. Open work is the `OliverCode` GitHub Project |
| [`skills/INDEX.md`](skills/INDEX.md) | Every included skill |

---

## Status

Run the test suite with:

```bash
python3 -m unittest discover tests
```

The suite reports its own test count and deliberately breaks each gate to verify that the gate catches the failure.

Run the install rehearsal with:

```bash
bash scripts/qa/rehearse-install.sh
```

The command reports its own case count. CI is included and can be enabled per fork.

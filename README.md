# OliverCode

OliverCode is a shared set of **rules, skills, and automated checks for your code projects**. Set it up once on your machine, and those standards apply across your projects:

* **Claude Code gets the same instructions and skills in every project.**
* **Your repositories get the same engineering and safety checks.**
* **Git can block a commit when a rule is broken.**
* **OliverCode checks that those protections are still working.**

## Start with a conversation

Clone the repo, or your fork of it:

```bash
git clone https://github.com/oliver-chase/OliverCode.git && cd OliverCode
```

Open the cloned folder in Claude Code and say one sentence, such as:

> **Set this up for me.**

The `olivercode-adoption` skill ships with the repo, so it is available on a fresh clone. It takes an inventory of your machine, asks only for the decisions that need you, installs the shared rules and hooks, and proves that a bad commit gets refused. `docs/SETUP.md` is the reference it works from, including how to clone the repo, how to restore a machine and how to back out.

You need `python3`, `git`, `bash` and `perl`. macOS includes them, and no accounts or packages are required. OliverCode is built and verified on macOS. Linux should work but is untested, and Windows requires WSL.

Setup keeps what you already have. `install` backs up an existing `~/.claude/CLAUDE.md`, tells you where the backup is, and is safe to run again.

## What problems it solves

### Instructions are easy to lose

Claude Code only loads instructions from specific locations, including `CLAUDE.md`. A rules file with any other name, such as `AGENTS.md`, never loads, skills pile up in scattered unsynced folders, and anything explained in a chat disappears when the session ends. OliverCode puts one shared set of rules and skills into `~/.claude` using symlinks, so every project uses the same source of truth.

### Guidance is not enforcement

Documentation can explain what should happen and cannot stop a commit that breaks the rules. OliverCode uses **Git pre-commit hooks** for rules that must be enforced, and a failing check refuses the commit.

Git runs those hooks only when its `core.hooksPath` setting points to them. If that setting is missing or broken, Git gives no warning and a bad commit can pass, so `scripts/olivercode conform` checks that the hooks are active. Setup also rehearses the protection by trying to commit a fake API key, which the hook must refuse.

OliverCode also installs three Claude Code hooks that run in every session. The session check tells Claude when the repo it opened has commit gates that git skips. The commit guard refuses a commit that would skip the gates. The early-stop guard sends Claude back to work when it promised work it did not do. `docs/RULES.md` ("Execution") describes each one.

## How it works

### What you get

| You get | How it reaches you | Actually enforced? |
|---|---|---|
| Pre-commit gates (`docs/GATES.md` has the per-repo table) | `.githooks/pre-commit`, installed per repo by `olivercode sync-hooks` | **Yes**, on every `git commit` while `core.hooksPath` points at it. `--no-verify` skips it, and the commit guard refuses that inside Claude Code |
| Local validation | `bash scripts/validate.sh`: gates, doc/code consistency, reference integrity, tests | **Yes**, when run. Nothing runs it automatically |
| Standards and templates | `docs/RULES.md` and `core/templates/project/`, inherited by every repo through the bootstrap manifest | No, they are instruction text an agent follows |
| Claude Code hooks (session check, commit guard, early-stop guard) | `~/.claude/settings.json`, written by `olivercode install` | **Yes**, inside Claude Code sessions |
| Skills | `~/.claude/skills/` symlinks, installed by `olivercode install` | No, the agent chooses to load them |

The hooks are the only things that block you. Everything else is a rule an agent follows because it is loaded.

### Two layers

1. **OliverCode (this repo).** Standards, skills, templates, the launcher and the governance hooks. The fleet registry ships as an empty example (`REGISTRY-PRIVATE-1` in `docs/DECISIONS.md` says where a working one lives)
2. **Product repos (yours).** Sibling repos that inherit hooks, templates and standards from OliverCode and are declared in the registry. OliverCode is never a runtime dependency of a product repo, because it defines standards and no implementations

`runtime/control-plane/` is gitignored, optional, and holds private per-machine runtime state. OliverCode works without it.

### How activation works

Nothing here depends on an agent choosing to look:

* `~/.claude/CLAUDE.md` symlinks to this repo's `CLAUDE.md`, so its rules are present in every Claude Code session on the machine, from any working directory
* `~/.claude/skills/<name>` symlinks to `skills/<name>`, so every skill is discoverable from any repo
* `.githooks/pre-commit` runs on every commit in every fleet repo, which enforces rules even when context does not
* `olivercode install` creates both sets of symlinks, and `olivercode health` verifies them, and `olivercode conform` checks each repo against `docs/CONTRACT.md`

Anything that must always apply is enforced as a hook and never left to an instruction an agent might not read.

### What happens automatically

* **Every commit** runs the gates, which can refuse it
* **Every Claude Code session** has the shared rules and the full skill set, whichever folder it opens
* **Every `bash scripts/validate.sh`** checks that documentation matches the code, internal references resolve, the tests pass and registered repos are governed
* **Every new repo** gets the standard project files from `olivercode bootstrap` (`docs/SETUP.md`, "Step 6b")

## Design decisions

### Enforcement is explicit

Standards, templates, documentation and skills provide guidance. **Hooks are the enforcement layer.** When the same mistake happens repeatedly, the written rule becomes an automated gate, because a rule without a gate regresses.

### Enforcement reality

Not every rule in this repo is machine-checked, so know which is which before assuming a rule is unbreakable.

**Hard-enforced:** the gates in `.githooks/pre-commit`, which fire on every `git commit` (`docs/GATES.md` lists them). Inside Claude Code, the commit guard also refuses a commit that would skip them.

**Soft, meaning instruction only:** "read the framework boundary before structural changes", the skill-placement requirements, the code, docs, audit, QA, gate, commit and push ordering, and running the install rehearsal at all (`rehearse-install.sh` is never auto-triggered). Being written in `CLAUDE.md` does not make a rule enforced, so check whether it is a hook or a sentence.

### Every gate must actually fail

A check that reports `PASS` without actually checking anything is a defect, such as a scan that silently skips itself when a required tool is missing. OliverCode tests for this in its own code, and the test suite deliberately breaks every gate and confirms that the gate catches the failure.

### Operating principles

* Claude Code is the sole runtime and Anthropic the sole model provider, by design
* Fail closed before failing open, and make no capability claim without a runnable verification
* One concept has one home, and everything else points to it
* Project-specific behavior lives in the owning project repo and never here
* OliverCode depends on nothing. Product repos and local state depend on OliverCode (`docs/RULES.md`, "Framework boundary")

## Contributing

Every tracked file has to justify itself as run, verify, ship or support (`docs/RULES.md`, "Framework baseline"). The commit sequence, the managed quality files, document voice and public-repo redaction each have one owner: `docs/RULES.md`, `docs/GATES.md` and `docs/VOICE.md`. `bash scripts/validate.sh` runs before every commit.

## Verify the whole system

```bash
bash scripts/validate.sh --tree          # Every gate over every tracked file, plus docs, bloat, code quality and tests
bash scripts/qa/rehearse-install.sh      # Fresh clone, real install and every setup scenario
bash scripts/validate.sh                 # The full test suite, including each skill's own tests
```

The rehearsal runs in disposable sandboxes that cannot touch your real files. Every scenario tests a claim made in the documentation, so a failure means the code or that claim is wrong. Both commands report their own counts.

## Repository layout

| Path | What it holds |
| --- | --- |
| `CLAUDE.md` | The rules Claude loads in every session, linked into `~/.claude` by `install` |
| `core/hooks/` | The gate scripts that `scripts/build-hooks.py` assembles into each pre-commit and pre-push hook |
| `core/templates/project/` | The project template that `bootstrap` and `sync-hooks` copy into a repo, including the built hooks |
| `skills/` | The skills linked into `~/.claude/skills/`. `skills/INDEX.md` lists them |
| `shared/` | The bootstrap manifest and the example fleet registry |
| `.githooks/` | OliverCode's own pre-commit, commit-msg and pre-push hooks |
| `scripts/olivercode` | The launcher. `python3 scripts/olivercode --help` lists its commands |
| `scripts/validate.sh` | The single validation command, which runs the gates, the consistency checks, the reference check and the tests |
| `scripts/lib/` | The checkers and helpers behind `validate.sh`, and the launcher command bodies in `cmd_*.py` |
| `scripts/hooks/` | The three Claude Code hooks: session check, commit guard and early-stop guard |
| `scripts/qa/` | The install rehearsal and the secret-gate probe |
| `scripts/link-check.sh`, `scripts/run-governance-target.sh` | The reference check and the CI entrypoint for a downstream repo |
| `docs/` | One document per concept, listed below |
| `tests/` | Tests for the gates, checkers, hooks and launcher |
| `.claude-optimization/memory/` and `.claude-optimization/state/` | Optional memory and state files that `CLAUDE.md` reads when they exist. Both are gitignored and created locally per user |
| `runtime/control-plane/` | Private machine state, gitignored and optional |

## Documentation

| Document | Purpose |
| --- | --- |
| [`docs/SETUP.md`](docs/SETUP.md) | Cloning, the setup steps, restoring a machine, backing out, how each launcher command behaves and troubleshooting by symptom |
| [`docs/RULES.md`](docs/RULES.md) | Every standing rule: baseline and managed files, lifecycle, execution, structure, file locations, boundary, skill placement and documents |
| [`docs/CONTRACT.md`](docs/CONTRACT.md) | What every repo must match, what may differ, and how an exception is recorded |
| [`docs/GATES.md`](docs/GATES.md) | Every gate, what it blocks, and which repos receive which gates |
| [`CLAUDE.md`](CLAUDE.md) | Rules Claude loads in every session |
| [`docs/VOICE.md`](docs/VOICE.md) | How everything a person reads is written, loaded in every session |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Design decisions whose reasoning is longer than a code comment should carry |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | The live tracker and its review marker. Open work is the `OliverCode` GitHub Project |
| [`skills/INDEX.md`](skills/INDEX.md) | Every included skill |

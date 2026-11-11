# Rules

Every standing rule OliverCode sets for itself and for the repos it governs lives in this file. Each rule has one home here, and every other document points to it by section name. Gates that enforce a rule are listed in `docs/GATES.md`. Words follow `docs/VOICE.md`.

## Framework baseline

OliverCode is the baseline framework for every downstream repo, so it stays small, current and reusable. Every tracked file in framework core justifies itself as exactly one of these, and a file that does none of them is deleted, merged or moved to the repo that owns it:

- Run: launcher and orchestration entrypoints (`scripts/olivercode`)
- Verify: gates that prove the framework works (`scripts/validate.sh`, `.githooks/pre-commit`, `tests/`)
- Ship: standards and templates that downstream repos inherit (`docs/RULES.md`, `core/templates/project/QUALITY_BASELINE.md`, `shared/project-bootstrap-manifest.json`)
- Support: current-state documents that explain the active surface (`README.md`, `docs/SETUP.md`, `docs/GATES.md`)

Removal rules decide what happens to a file that does none of those:

- A duplicate explainer is merged
- A roadmap, migration, status or history document is deleted, because git keeps the history, and none of them is active authority unless it is promoted into a current-state document
- A project-specific helper moves to the repo that owns it
- A generated report or cache is ignored and never tracked
- A validator that duplicates another validator's failure class is collapsed into it

A new file is allowed only when it reduces runtime complexity, replaces duplicated authority, tightens baseline verification or improves what downstream repos receive. Any other new file is rejected, and a new document replaces or merges with an older one so authority stays in one place.

Downstream managed repos inherit this baseline through the shared template and bootstrap path (`core/templates/project/QUALITY_BASELINE.md` and `shared/project-bootstrap-manifest.json`). They never reinterpret it locally. The requirements and the allowed differences are listed once in `docs/CONTRACT.md`, and any variance is explicit, temporary and recorded in the repo as that file describes.

Other framework rules:

- Claude Code is OliverCode's sole runtime and Anthropic its sole model provider. Multi-runtime or multi-provider framing returns only with a real implementation behind it
- Project-specific runtime logic lives in the owning project repo
- A rule without a gate regresses, so a finding class that keeps recurring becomes a check
- The governance runner stays small enough to understand in one read
- `core/templates/project/` is the single template home. CI workflows, documents, governance scripts and the built hooks all ship to downstream repos from there through the bootstrap manifest and `sync-hooks`, and a second template directory drifts from the masters
- The hooks are written in `core/hooks/` and built into `core/templates/project/` and `.githooks/` by `scripts/build-hooks.py`. Edit the gate files there and never a built hook
- `runtime/manifests/` does not exist as a tracked path. `.gitignore` reserves it for generated reports, inventory scans and status snapshots, so any manifest generation writes to an untracked location, and no validator consumes manifests
- Validation is `bash scripts/validate.sh` from the repo root, which wraps `.githooks/pre-commit` and the tests in `tests/`. OliverCode has no type checker or schema validator beyond its gates, because its main change risk is secret and PII leaks and document drift. Downstream repos declare their own validation command in the registry's `repo-profiles.json` (`REGISTRY-PRIVATE-1` in `docs/DECISIONS.md` says where that file lives)

## Development lifecycle

This sequence moves work from an idea to shipped code in every repo, without being asked. It applies to any non-trivial change, and a typo fix needs no spec. The other sections govern artifacts, and this one governs the order.

1. **Gap analysis before specs.** Measure first by counting what exists, running what runs and reading the live code. A gap analysis that cites no command is a guess. The output is a list of differences between what is claimed and what is true, each with the evidence that proves it
2. **Spec before build.** Every gap becomes a written spec before any code. A spec states the failure it prevents, what is in scope and what is explicitly out, and the watch-out, which is the way a plausible implementation gets it wrong. Specs live as issues in the repo's GitHub Project (see "Project structure"). Nothing is built that is not specced, and nothing is specced that cannot name its failure
3. **Prioritize by the cost of being wrong.** Rank by what breaking it costs: silent data loss first (wrong output that looks right), then a security boundary that can be bypassed, then a visible failure that is loud and recoverable, then cost and performance, then ergonomics. A defect that surfaces as worse results blamed on something else outranks one that throws, because an exception gets fixed and silently thinner data gets shipped
4. **Build, verify, commit, one loop per spec.** Write the failing test first, at a seam that reaches the real bug. Implement. Ablate by removing the guard, confirming the test goes red, then restoring it. Run the repo's own `check` or `validate` and read the exit code, never a grepped line, because a filtered log hides failing suites. Commit with the why, then push. One spec per commit, because a commit spanning two specs cannot be reverted cleanly
5. **QA, when the owner asks for it, is a separate pass by a separate reader.** The author cannot QA their own work and confirms what they intended. QA then runs as its own adversarial pass with a brief to find what is wrong. It verifies by running and never by reading, and its findings are fixed before the work is called done. A finding in the author's own recent edits is the most valuable kind
6. **Prefer boundary verification over volume.** A suite that grows without finding defects measures the wrong thing. Verify where the system meets reality (real networks, real files, real inputs), and say so when volume was not what found the bug
7. **Simplify as part of finishing.** A change is not done until you have asked what it made redundant: merge duplicated helpers, delete dead code, collapse a constructor that four call sites hand-rolled. Removal is a deliverable. Never remove functionality to reduce size, and reduce the number of places a behavior is expressed
8. **Consistency across repos is the point.** The same question gets the same answer in every repo: backlog policy, comment discipline, document shape, commit format and verification command name. A repo that deviates documents the deviation with its reason or removes it

For a rendered or executable artifact such as an HTML page, an SVG, a UI, a chart, a game or a script with observable output, running it means observing the actual render. A static check such as a linter, `node --check` or an XML parser confirms the file is well formed and does not confirm that it looks or behaves correctly. Render it in its real environment (a headless browser and screenshot for web artifacts, an SVG-to-PNG render, or executing the script and capturing its output), then look at what came back: read the screenshot and the console, and check the layout is intact and nothing is obscured. A screenshot that was produced and never looked at is not observation. Stop once you have looked and it is clean, and re-render only after a change.

Working rules that hold in every session:

- A broken, failing or slow system gets the `diagnosing-bugs` loop before any code changes, because a patch on a guess fixes only the symptom it guessed at
- A comment says what defect the code prevents or why it has this shape, and stays only when the code cannot say it
- Gate and lint findings get one pass: read the whole list, fix every finding, then re-run once
- Read a file before its first edit, and again whenever another session, a hook or a generator could have changed it. Grep for callers before changing a function signature
- A new top-level folder needs a reason in "Project structure"
- Before a commit, review the staged files and the diff: a removed file has no surviving canonical reference, and the diff holds only intended current-state changes. Never stage secrets, `.env*`, runtime state, private repo content, caches or generated local reports. After a push, `git status --short --branch` is clean and the pushed short SHA is recorded

Token efficiency applies to these rules too:

- Deterministic scripts beat model calls, because a gate that greps is cheaper, faster and more accurate than a model asked to check the same thing
- Targeted greps and line ranges beat whole-file reads

## Execution

Every change in any project follows this locked process, and no gate is skippable:

1. Code: implement the change fully
2. Docs: update every affected document to current state and audit related documents for stale references
3. Quick pass: read the diff for stale references, conflict markers and ordering hazards
4. Validate: verify the change end to end by running the repo's own validation command, which its `CLAUDE.md` names
5. Gate: pre-commit enforcement runs automatically, and a blocked commit is fixed before committing. How many gates run depends on the repo, and `docs/GATES.md` has the table
6. Commit: only on pass, with a descriptive message
7. Push: to the correct repo

When the owner asks for an audit, its reviewers run in parallel, one per area. Every other helper agent runs alone.

`.githooks/pre-commit` runs the gates on every commit git runs it for. Four things skip a gate: `--no-verify`, which the commit guard refuses inside Claude Code; an unset `core.hooksPath`, which `olivercode conform` reports; a `commit-msg.optout` file the owner creates in `.githooks`; and `ALLOW_FORCE_PUSH=1` on a force push. The gate list and what each one blocks live only in `docs/GATES.md`, so a hook change updates one table.

Four Claude Code hooks run inside every session, and `olivercode install` writes them into `~/.claude/settings.json`, each pointing at this checkout's script:

- `scripts/hooks/session_check.py` (`SessionStart`) tells the session once what would fail silently in the folder it opened: a repo whose gates git skips, a git repo with no gates, or a broken rules link. It prints nothing when all is well
- `scripts/hooks/commit_guard.py` (`PreToolUse` on Bash) refuses a `git commit` that would skip the repo's gates, whether gates are present while `core.hooksPath` does not run them, `--no-verify` is passed (including inside `bash -c` and `eval`), or `core.hooksPath` is overridden
- `scripts/hooks/placement_guard.py` (`PreToolUse` on Bash) refuses a `git clone` outside `repoRoot` and a `git worktree add` outside `<repoRoot>/_worktrees`, and names the right path. `session_check.py` and `olivercode health` name the repos, worktrees and backups already outside it, `olivercode place` lists the fix for each and `olivercode clean` removes merged, clean worktrees
- `scripts/hooks/early-stop-guard.py` (`Stop`, `EARLY-STOP-1` in `docs/DECISIONS.md`) sends a turn back to work when it ends by promising work it did not do

All four are deterministic and fail open, so a hook's own bug never blocks a commit or a session. `olivercode health` fails when one is missing on a machine where install linked this checkout.

Completion: run the repo's canonical validation before committing and stop on failure. A failing run never counts as completion. The mechanically enforced requirement is the pre-commit hook plus the repo's own `scripts/validate.sh`.

Authority hierarchy: the deploy platform must not be the first place a build or type error is discovered. Each repo profile declares a `canonicalValidationCommand` and a `finalAuthority`. Run the canonical command locally before the commit and treat the declared final authority, which is a full build and not a lint pass, as the check that decides whether the change is sound. Pre-commit gates catch secrets, structure and hygiene. They do not catch a block-scoped `const` referenced before its declaration, which only a full type-checking build surfaces.

Secrets stay out of git. Real credentials live in a gitignored `.secrets/` folder or in `.env.local`, `.env.example` is tracked and holds variable names without values, and `.githooks/pre-commit` is the enforcement gate.

Hooks are installed by the launcher from OliverCode with `scripts/olivercode sync-hooks`. It deploys `core/templates/project/pre-commit` (or the private variant for a private repo) to each repo's `.githooks/` and sets `core.hooksPath`.

## Project structure

These hygiene rules apply to every repo under `<fleet-root>/*`, whichever backlog paradigm the repo uses, so every agent follows the same read and write flow. OliverCode's own root is excluded from epic and commit hygiene and from the required base paths, because OliverCode is a framework and has no epics. The GitHub Project backlog model applies to OliverCode too: its open work lives in the `OliverCode` GitHub Project that `docs/backlog-config.json` names, `docs/DECISIONS.md` holds decision rationale, and `docs/BACKLOG.md` holds only the live tracker.

Every repo's backlog lives in a GitHub Project named by a `backlog-config.json` that the repo's own `CLAUDE.md` points to, and `skills/backlog/SKILL.md` governs it. No repo keeps a file-based story registry under `.github`.

Core invariants:

1. Every repo has exactly one active backlog source
2. Each repo keeps `docs/repo-structure-contract.md` current

Commit hygiene:

1. Every commit message carries a story reference such as `(#53)`, which the commit-msg hook enforces

Test hygiene:

1. Every behavior change updates or adds automated tests in the correct lane (contract, regression, visual or integration)
2. Every story has at least one negative-path assertion
3. Archived (not removed) features retain non-regression tests for data and telemetry paths

Discoverability:

1. Each repo's GitHub Project is the one place to list open stories, epics and unassigned entries, and the `backlog` skill's sweep covers it
2. Archive indexes for deferred functionality carry clear re-enable instructions

Shared quality baseline: managed files stay byte-identical across all repos where `shared/project-bootstrap-manifest.json` marks them strict. The managed files are `CODEOWNERS`, `QUALITY_BASELINE.md`, the hooks and the template governance scripts, all under `core/templates/project/`. A change to a managed file is made first in OliverCode and then synced to every project, because OliverCode is the single source of truth.

Required base paths in every repo:

1. `README.md`
2. `CLAUDE.md`, the only agent-rules file, because Claude Code is this framework's sole runtime and there is no separate `AGENTS.md` to keep in sync
3. `docs/repo-structure-contract.md`
4. A `backlog-config.json` file under `docs/` that names the repo's GitHub Project

Agent read order: `README.md`, then `CLAUDE.md`, then `docs/repo-structure-contract.md`, then the repo's GitHub Project.

Enforcement: the commit-msg hook requires a story reference, and pre-push blocks a history rewrite and a secret in any commit it sends (`docs/GATES.md`, "Pre-push gates"). Contract drift in `docs/repo-structure-contract.md` is a convention that `olivercode health` does not check.

## File locations

Every file type has one canonical home, which removes ambiguity about where plans, documents, credentials and runtime artifacts go.

| If it is a | Save to | Notes |
|---|---|---|
| Project plan or proposal | `<repo>/docs/plans/YYYY-MM-DD-<slug>.md` | Dated, one per plan |
| System or architecture document | `<repo>/docs/<TOPIC>.md` | Descriptive name in CAPS or kebab-case |
| Credential or secret | `.env.local` (gitignored) | Local only. `.env.example` shows variable names and placeholders |
| Voice and tone rules | `OliverCode/docs/VOICE.md`, linked to `~/.claude/VOICE.md` by `olivercode install` and imported by `CLAUDE.md` | One file for every repo. A self-contained suite ships its own copy as `docs/VOICE.md` |
| Agent skill | `OliverCode/skills/` | Engineering-method and framework-tooling skills only, per "Skill placement". Personal and business skills go to the personal skills folder (`skillsRoot` in `olivercode.local.json`). Anything else, such as product or vendor skills, is a real untracked directory directly under `~/.claude/skills/` |
| Runtime artifact or output | A gitignored output directory the repo declares in its own `docs/repo-structure-contract.md` | Generated by automation, never hand-edited, never tracked. Product-specific output paths belong to the owning repo |

These are the anti-patterns:

| Anti-pattern | Why it is wrong | Correct location |
|---|---|---|
| A plan inside an agent-OS directory such as `.claude-optimization` | Agent-OS directories hold that agent's own runtime internals and no project deliverables | `docs/plans/YYYY-MM-DD-<slug>.md` |
| `.env` committed | It leaks secrets to version control | `.env.local`, gitignored |
| A personal file such as `voice-notes.md` at the repo root | It pollutes the project structure, and voice rules are shared | `OliverCode/docs/VOICE.md` |
| Runtime output inside `docs/`, such as a generated report.json | Runtime output is not documentation | The repo's declared gitignored output directory |
| Skill files copied into each repo | Skills go stale, and each has one home | A symlink from `~/.claude/skills/<name>` to the skill's one real home |
| An undated plan file such as plan.md | Plan history and sequence cannot be tracked | `docs/plans/YYYY-MM-DD-<slug>.md` |

A file type missing from the map follows this process:

1. Classify it as a plan, a document, a credential, a runtime artifact or personal content
2. Check whether it fits an existing category
3. If it fits none, pick the closest category and propose the location
4. Add the new file type to the map in this section with its justification
5. Update `docs/repo-structure-contract.md` in every repo that uses the new file type

These paths are gitignored in every repo:

```
# Credentials and secrets
.env.local
.env
*.secret
*.pem
*.key
.secrets/*
!.secrets/README.md

# Runtime artifacts: add the repo's own generated-output directory here
# (whatever it declares in docs/repo-structure-contract.md)

# Agent runtime state (per-agent OS directory, e.g. .claude-optimization/)
.claude-optimization/memory/
.claude-optimization/state/

# OS files
.DS_Store
Thumbs.db
```

The private-overlay profile in "Public and private repos" honors that list in full with no per-repo exceptions.

Enforcement: pre-commit hooks block commits that violate location rules, such as PII in the wrong place or a committed credential. `docs/repo-structure-contract.md` in each repo lists that repo's active file locations, and a new repo includes this section's location map in its structure contract.

## No icons

Zero emojis, icons or pictographs appear anywhere, in code, comments, commits, documents, PRs, issues, chat, CLI output or config files. Output is plain text. Emphasis comes from structure (headings, lists, bold, italics) and never from icons. This applies to all projects, all channels and all contributors, with no exceptions and no override mechanism.

Instagram captions are posted copy and may hold emojis, so the caption ledgers under `data/` (`.csv`, `.json` and `.jsonl`) are not scanned. The icon and emoji gate in `docs/GATES.md` is the enforcement source of truth, including the exact blocked Unicode ranges, which are not restated here because a second copy would drift from the scanner.

## Public and private repos

This section applies to every downstream repo under `<fleet-root>/` that consumes OliverCode's templates, and not to OliverCode itself, which sets the standard and does not consume its own downstream template. OliverCode's equivalent surfaces are `docs/SETUP.md`, the README's install section and `runtime/control-plane/` for its own private machine state.

Every repo separates three surfaces: the public tracked contract surface, the local runtime surface and the private operator overlay surface. Any repo with the full split profile is the reference implementation, and other repos may use simpler profiles that keep the same boundary model.

1. Public repos own code, documents, templates, validators and bootstrap entrypoints
2. Private overlays own delegated tokens, `.runtime/`, per-agent OS state (`.claude-optimization/memory/` and `.claude-optimization/state/`), host scheduler wiring and machine-specific state. What goes in `.env.local` and `.secrets/*`, and what each tracked `.example` file shows, follows "File locations"

Repos may extend these baseline profiles and must support the vocabulary:

- `repo-contract-only`: tracked code, documents and contracts only
- `local-runtime`: a local runnable checkout using `.env.local`
- `private-overlay`: a machine-specific private runtime overlay

Canonical template files live in `OliverCode/core/templates/project/` and are applied manually. Hooks are converged by `scripts/olivercode sync-hooks`.

A public or shared repo describes the pattern and never your implementation. Never commit:

- Project names, which become `[project-name]` placeholders
- Host paths, which become `<workspace-root>` and `<fleet-root>` placeholders
- Personal identifiers, shell aliases and machine-specific configs
- An enumeration that matches your actual project count

`repo-profiles.json` ships one `_exampleProfile` and no real projects (`REGISTRY-PRIVATE-1` in `docs/DECISIONS.md`).

## Framework boundary

Read this section before any structural change to a repo. When workspace structure or cross-project standards change, update this section, because the path map lives here and nowhere else, and keep the `~/.claude/CLAUDE.md` and `~/.claude/VOICE.md` symlinks pointing at this repo's `CLAUDE.md` and `docs/VOICE.md` (`scripts/olivercode health` verifies them).

OliverCode is the shared orchestration framework. It contains:

- Reusable standards and policies (`docs/RULES.md`)
- Reusable skill definitions (`skills/`)
- Project templates (`core/templates/project/`) and shared manifests and registries (`shared/`)
- Framework documents (`docs/`)
- A thin launcher entrypoint (`scripts/olivercode`)
- Pre-commit governance hooks (`.githooks/`)

OliverCode can be cloned, inspected and used standalone without any runtime installed.

Claude Code is this machine's sole agent runtime. The canonical paths and their owners:

- Product repos: `<fleet-root>/*`
- Shared system root: `OliverCode`
- Claude runtime and orchestration: `~/.claude`
- Shared skills root: `OliverCode/skills`

Ownership follows from that map:

- Product-specific implementation documents and workflows belong in each project repo
- Cross-project orchestration standards belong in `shared/*`
- Shared skills and tools belong in `skills/*`
- Project structure and hygiene rules belong in "Project structure"
- Runtime state in `~/.claude` is operational data and not product source code
- Product workflow documents are never duplicated into runtime folders

`runtime/control-plane/` sits inside the OliverCode repo tree and is gitignored. It holds private per-machine runtime state such as session handoff, provider health and validation manifests, and it is never pushed to GitHub.

OliverCode deliberately does not contain:

- Runtime-environment launcher and automation (the thin `scripts/olivercode` CLI is the only launcher surface the framework ships)
- Docker compose or container setup
- Runtime state, logs, telemetry or handoff data
- Private restore checklists or project-specific credentials
- Generated runtime adapter files
- Runtime-specific validation scripts and automation tools

Those belong in the runtime environment (`runtime/control-plane/`).

Two more layers exist on any machine running OliverCode, and neither is framework material:

- **`~/.claude/` (user-global Claude Code settings, skills, agents).** Local and per machine: permissions, theme, model and any hook the operator writes stay theirs. `olivercode install` writes only the `CLAUDE.md` and `VOICE.md` links, a link per skill in `skills/`, its three hook entries in `settings.json`, the install record `.olivercode-install.json` that `uninstall` reads, and a `.pre-olivercode` backup of anything it replaced. `scripts/lib/claude_settings.py` merges those entries and leaves every other key as it was. The skill and agent layer within it, such as cross-repo work skills for marketing, hiring or meeting notes, is real durable content. OliverCode never edits anything else in `~/.claude/`
- **Sibling agent state**, such as `.codex/`-class directories from other coding agents. OliverCode leaves it alone: it is never inventoried, migrated or used as a placement target. Delete it when the tool that created it is decommissioned, and never fold its contents into an OliverCode location

The dependency is one-directional. The runtime environment depends on OliverCode and reads standards, templates, skills and workflow definitions from it. OliverCode does not depend on the runtime environment and cannot reference runtime-specific paths, scripts or configuration in its documents. Architectural descriptions may mention the runtime environment as a deployment concept and never depend on it for correctness.

Standalone mode needs only a clone:

```bash
git clone <your-fork> OliverCode
cd OliverCode
scripts/olivercode --help
.githooks/pre-commit
```

It provides the framework documents, the launcher surface, the governance gates and the reusable templates and manifests.

Runtime mode adds `runtime/control-plane/` (gitignored), which holds per-machine state on top of OliverCode: the dependency declaration `health` reads, session and handoff state, and a bash shim at `runtime/control-plane/olivercode` that delegates to `scripts/olivercode` and carries no additional commands. The control plane never keeps its own copies of framework artifacts, and OliverCode stays fully usable without it.

## Skill placement

Any agent installing, creating or moving a skill file consults this section first. OliverCode is orchestration, security and optimization only. The `skills/` folder holds engineering-method skills and the framework's own tooling (debugging, audits, planning, backlog) as real git-tracked content, indexed in `skills/INDEX.md`, which is the catalog. Anything else does not belong in this repo, whatever it is and wherever it should live instead, and a skill that shows up in `skills/` and is not engineering method or framework tooling is drift to remove.

Adding a skill takes three steps in the same session:

1. Create `skills/<name>/SKILL.md` with real tracked content
2. Add a row to `skills/INDEX.md` in the same change
3. Run `scripts/olivercode install`, which links every skill in `skills/` into `~/.claude/skills/`

An unlinked skill is invisible and an unindexed one is undiscoverable. Skills never live in a notes application's folders, because a skill's one home is a skill directory.

`.claude/skills/olivercode-adoption` is the one project-level pointer, a tracked symlink to `skills/olivercode-adoption`, and it is not a second home. It breaks a chicken-and-egg problem: the skill that walks someone through installing OliverCode was invocable only after `olivercode install` had linked it into `~/.claude/skills/`, which is the step it exists to guide. A project-level skill is available the moment the repo is cloned and opened. Do not add a second one without the same justification, because every other skill reaches the user through `~/.claude/skills/`.

Hooks are not skills and follow the same pattern: written once in `core/hooks/` (see "Framework baseline" above) and copied to every fleet and private repo by `sync-hooks`, with the public or private variant per `docs/GATES.md`, which also lists the dead-citation gate on staged skill and rule files.

When a repo-specific skill must win over a generic one: both can match the same task, for example a generic email-writing skill and a repo's own approval-gated outreach skill both matching "draft a cold email sequence". Matching is based on task phrasing and happens before any repo file is touched, so the generic skill can fire first even inside the repo the specific one was built for (`ACT-3` in `docs/DECISIONS.md`). No framework-level fix exists for that first mis-fire. The mitigation is a named, explicit directive in that repo's own `CLAUDE.md`, which loads for every session in that repo. It names the mandatory skill and the generic one to avoid, inside a section the agent reads early such as "Approval Boundaries". It catches the agent on its first repo-file touch and sends it back to the correct path even when it already invoked the wrong skill. If your repo has an approval-gated skill that a generic one could shadow, add this directive.

Drift check: `scripts/olivercode health` flags any of OliverCode's skills missing its symlink at `~/.claude/skills/<name>` and any symlink there that points somewhere other than `OliverCode/skills/<name>`. `scripts/olivercode conform` flags, for every fleet repo and private repo, any hook install state that makes git run no hooks, which means `core.hooksPath` unset, pointing at a missing directory, a hooks directory with no `pre-commit`, or a `pre-commit` that is not executable. It also flags a hook whose content diverges from the template. The first four make git skip hooks silently (`docs/SETUP.md` explains why), and `scripts/olivercode sync-hooks` repairs all five.

## Documents

Every README and document in OliverCode, in each repo it governs and in any fork follows this layout, and its words follow `docs/VOICE.md`. `bash scripts/validate.sh` checks internal references and document-to-code consistency and fails on any drift it finds.

### The README

A README serves a reader on their first day, who knows the business and none of the internals. Its sections come in this order:

1. The title is the repo name, followed by one sentence on what the repo does and what a reader can do with it
2. The driving problems take one to three short paragraphs, each naming a real problem, what it costs and the design choice that answers it
3. Install and first use give commands a reader can run at once, with realistic values
4. How it works explains the system in the reader's terms
5. What comes back shows the real fields, files or results, including what the reader receives when something fails
6. Design decisions state each decision as a claim and defend it with the failure it prevents
7. Task sections follow wherever the repo's surface needs them
8. Documentation is a two-column table that links every document in the repo with a one-line purpose, because a document missing from it is unreachable
9. Status gives the runtime requirements and the command that proves what works
10. License appears when the repo ships one and a reader needs to know it

A small tool gets a short README in the same order.

### Index READMEs

Some READMEs catalog a set of things, such as a skill suite, a monorepo or a folder of tools. They answer six questions in order, each under its own heading:

1. What is this, and who is it for?
2. How do I get it?
3. How is it organized? A directory tree answers this
4. How do the parts relate? A table answers this wherever the content forms a matrix
5. What is in each part? One table row per item describes it in its own terms
6. How do I keep it current?

Check every path, command and row against the repo before the README ships.

### Files and where they live

Documents live in `docs/` and use CAPS-KEBAB names such as `GATES.md`. The root holds only `README.md`, `CLAUDE.md`, `LICENSE` and a declared quality baseline. A repo with enough surface keeps this set:

| File | What it holds |
|---|---|
| `README.md` | The document a new reader starts from, including how the system is organized and how a change flows through it |
| A reference doc, one file or split by surface | Every option and field. OliverCode keeps its layout table in `README.md`, the launcher's command list in `olivercode --help` and each command's behavior in `docs/SETUP.md` |
| `docs/SETUP.md` | The steps a new user or a fork follows, each one verifiable, and the failures a user will hit, listed by symptom |
| `docs/DECISIONS.md` | Each design decision whose reasoning is longer than a code comment, cited by ID |
| `docs/BACKLOG.md` | The live tracker, or the open items for a repo without a GitHub Project |

Each concept has one home, and every other mention points to it by name. Every ID that a document or comment cites exists in `docs/DECISIONS.md`.

### Data files

A skill or script that records data keeps one file per kind of thing and adds rows to it. It never writes a file per day, week, month or run, and a new attribute of a thing is a column of its file. A reading taken over time rolls up inside the same file once the file passes 1,000 rows: rows older than 90 days become the last reading of each week, and nothing is copied to an archive. A log of decisions or of posted items stays whole. The skill names its data file, its roll-up point and what it deletes.

### Numbers in prose

A count that changes, such as tests, gates or coverage, never appears in a document. Give the command that produces it. A dated measurement goes in the backlog's live tracker once, with its date.

### The backlog

A repo whose `CLAUDE.md` names a `backlog-config.json` keeps its open work in that GitHub Project, which the `backlog` skill maintains. OliverCode works this way, and its `docs/BACKLOG.md` holds only the live tracker that the `audit` skill maintains. Every design decision, including each failure class a gate exists to stop, lives in `docs/DECISIONS.md`.

Every repo's Project runs the same kanban baseline, defined once in `shared/kanban-baseline.json`. The Status lanes are Backlog, Ready, In Progress, QA and Complete. The fields are Priority (P0 to P2), Size (XS to XL), Work type (Epic or Story) and Area, whose options come from the repo's own config. The board has no pull-request lane and no status that a pull request sets, so work reaches QA and Complete when a person or agent moves it and never when a pull request opens or merges.

Every owner request that changes files becomes a story before work starts, except a change to one file of 20 changed lines or fewer that adds no behavior, which commits with the number of the open epic it fits. `skills/backlog/references/story-template.md` defines the body: a user story sentence, Given/When/Then scenarios, an epic link, Priority, Size and Work type. A request that matches an open story is added to it, and a request that arrives mid-task is filed and queued without reordering the board unless the owner says "stop", "do this first" or "drop that". `skills/backlog/scripts/check_story_format.py` verifies a body, and the `backlog` skill's "Save every ask" holds the procedure. `CLAUDE.md` and the project template's `CLAUDE.md` each carry one line pointing here.

Every agent that commits or finishes work logs it on the story: its name, role (builder or QA), the commit, the files changed and the result. The lead logs a helper's result before reporting it. `.githooks/commit-msg` blocks a commit with no story reference, which is the part git enforces. The comment itself is procedure, because a hook cannot post to GitHub, and `docs/GATES.md` has the limit.

There is no QA phase and no pull request. After one quick pass and validation, the builder commits, pushes and merges to the default branch and closes the story on its logged evidence (the commit, the files and the validation result), unasked. Independent QA runs only when the owner requests it. Then a different agent checks each Gherkin scenario against the files, logs the verdict with role `qa`, and a failure returns the story to In Progress with the findings. `skills/backlog/scripts/complete_story.py` closes a story either way, and it checks the QA sign-off only when the story had a QA pass.

A scheduled job that commits data, such as a nightly sync, commits under one standing story that the repo names in `docs/backlog-config.json` as `nightlyStory`. That story carries Gherkin for what the job stages, and every sync commit cites it, so the story-reference gate passes and the history stays traceable. heyyounotes#6 and state-of-stoked#7 are the standing stories today. A sync commit stages only named data files and never a secret, and a refused commit is reported, never forced.

At the end of a story's work, merge its commits into the default branch and push, and open no pull request. A push sends every commit on the branch, so a checkout on a branch that carries unrelated commits merges only the story's commits, by cherry-pick in a separate worktree cut from the default branch. A repo whose `CLAUDE.md` says to ask before a push keeps that rule.

`olivercode backlog-setup [DIR] [--apply]` is the one command that creates or repairs a repo's Project to this baseline, writes its `backlog-config.json` and installs the commit-msg hook, and `olivercode conform` lists any repo whose board differs. A repair never loses an item's field values: the command saves every item's Status, Priority, Size and Work type before it changes a field, and it restores and verifies them afterward. `docs/SETUP.md` ("Launcher commands") documents the options.

A repo without a `backlog-config.json` keeps its open items in `docs/BACKLOG.md`, and finished work leaves the file because git keeps that history.

### Keeping documents current

A change to behavior, options, structure or file layout updates every document that states the old fact, in the same commit. The README's documentation table, its layout table and the backlog all count as documents. `scripts/validate.sh` catches the drift it can detect, and the rule still applies to the drift it cannot.

### CLAUDE.md

`CLAUDE.md` loads into every session, so every word in it is paid on every turn of every session. It holds only the rules a session must follow from any folder, each as a short paragraph or bullet that says what to do and when. The detail behind a rule lives in the document it names, which loads only when that rule fires. A new rule earns its place when a session would act wrongly without it, and it goes under the heading that already covers its kind of work. A repo's own `CLAUDE.md` holds only what is true of that repo.

### The GitHub about

Every repo has a filled-in About with a one-sentence description and topics that name its real technologies and problem areas. An empty About counts as missing documentation, and `olivercode conform` reports it wherever the `gh` CLI is available.

```bash
gh repo edit --description "..." --add-topic <topic>
```

### Where this applies

This section governs OliverCode, every repo it governs and any fork. A repo bootstrapped from `core/templates/project/` gets a quality baseline that points here. A self-contained suite that ships its own `docs/VOICE.md` follows its own documentation rules.

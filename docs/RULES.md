# Rules

Every standing rule OliverCode sets for itself and for the repos it governs lives in this file. Each rule has one home here, and every other document points to it by section name. Gates that enforce a rule are listed in `docs/GATES.md`. Words follow `docs/VOICE.md`.

## Framework baseline

OliverCode is the baseline framework for every downstream repo, so it stays small, current and reusable. Every tracked file in framework core is one of these, and a file that is none of them is deleted, merged or moved to the repo that owns it:

- Run: launcher and orchestration entrypoints (`scripts/olivercode`)
- Verify: gates that prove the framework works (`scripts/validate.sh`, `.githooks/pre-commit`, `tests/`)
- Ship: standards and templates that downstream repos inherit (`docs/RULES.md`, `core/templates/project/QUALITY_BASELINE.md`, `shared/project-bootstrap-manifest.json`)
- Support: documents that explain the active surface (`README.md`, `docs/SETUP.md`, `docs/GATES.md`)

A generated report or cache is ignored and never tracked. Downstream repos inherit the baseline through the template and bootstrap path. `docs/CONTRACT.md` lists the requirements and the allowed differences.

- Claude Code is the sole runtime and Anthropic the sole model provider
- `core/templates/project/` is the single template home. Documents, governance scripts and the built hooks ship to downstream repos from there through the bootstrap manifest and `sync-hooks`
- The hooks are written in `core/hooks/` and built into `core/templates/project/`, untracked, by `scripts/build-hooks.py`, which every command that reads them runs first. `.githooks/` links to the built files. Edit the gate files and never a built hook
- Validation is `bash scripts/validate.sh` from the repo root, which wraps `.githooks/pre-commit` and the tests in `tests/`. Downstream repos declare their own validation command in the registry's `repo-profiles.json`, which lives in the private repo that `olivercode discover` names

## Execution

Every non-trivial change follows the smallest-sufficient-change method in the `lean` skill. A typo fix needs no spec. Interactive work stays interactive; backlog and headless execution are explicit tools, not mandatory stages for every conversation.

1. **Measure the gap.** Count what exists, run what runs and read the live code
2. **Track deliberately.** File a board story when the owner delegates autonomous work, requests durable tracking, or the work needs cross-session coordination. Do not create a story for every interactive chat or ordinary coding exchange.
3. **Rank by the cost of being wrong.** Silent data loss first, then a bypassable security boundary, then a loud and recoverable failure, then cost, then ergonomics
4. **Build one spec at a time, test first.** Write the failing test, implement, then remove the guard to confirm the test goes red and restore it
5. **Update the documents** the change affects, and read the diff for stale references
6. **Validate** with the repo's own command and read its exit code. A failing run never counts as completion. Before the commit, run `olivercode commit-check FILE_OR_TEXT` on the draft message: it lists every blocking finding of the commit-msg gate and every voice warning at once
7. **Commit and push** with a message that gives the why
8. **Simplify.** Merge duplicated helpers and delete dead code the change made redundant. Never remove functionality to reduce size

Validation and review scale with risk as defined by the `lean` skill. An independent reader is conditional on risk, not a mandatory stage for every change. QA can be requested separately. For a rendered artifact (an HTML page, a UI, a chart), a linter confirms only that the file is well formed, so render it and look at the screenshot and the console.

Working rules that hold in every session:

- Every terminal command given to the owner starts with `cd` to the exact checkout that owns it; put the command on the next line. Do not imply repo-scoped commands work from an arbitrary folder.

- A broken, failing or slow system gets the `diagnosing-bugs` loop before any code changes
- A comment says what defect the code prevents or why it has this shape, and stays only when the code cannot say it
- Gate and lint findings get one pass: fix every finding, then re-run once
- Read a file before its first edit, and grep for callers before changing a function signature
- A deterministic script beats a model call, and a targeted grep or line range beats a whole-file read

`olivercode install` merges Claude Code hook entries into `~/.claude/settings.json`, each pointing at this checkout's script. Every entry is deterministic and fails open with a note on stderr, so a hook's own bug never blocks a commit or a session. `olivercode health` fails when one is missing.

- `session_check.py` (`SessionStart`) reports what would fail silently in the folder a session opened, such as gates git skips or a repo outside `repoRoot`
- `pretool_guard.py` (`PreToolUse`) runs the guards in one process, and a deny wins over an ask. They refuse a commit that skips the gates (`commit_guard.py`), a commit or push in an archived repo (`archived_guard.py`), a clone or worktree outside `repoRoot`, a clone of a repo that belongs to another device (`otherDeviceRepos` and `otherDeviceOwners` in `olivercode.local.json`) and a `gh repo create` for a folder with no origin (`placement_guard.py`) and an Agent call on a model other than Sonnet that the owner never named (`model_guard.py`) and a `git reset --hard` in a main checkout or a tree with uncommitted changes (`reset_guard.py`). `policy_guard.py` enforces `.olivercode/policy.json` and asks the owner at a push, a mass delete or a third failed gate, `gh_guard.py` keeps one shared GitHub budget, and `memory_guard.py` refuses a memory write that states a rule
- `gh_watch.py` (`PostToolUse`) records a GitHub rate limit seen in command output, and `owner_decision_capture.py` (`UserPromptSubmit`) keeps each owner message that names a story for that story's builder, and `error_paste.py` (`UserPromptSubmit`) prints nothing to the session, and file a pasted error as a story, and `status_hint.py` (`UserPromptSubmit`) answers a status question from the status digest with no tool call
- `early-stop-guard.py` and `wip_save.py` (`Stop`) send a turn back to work when it promises work it did not do, and snapshot uncommitted work into `refs/wip/` at most every 10 minutes (`olivercode wip list|restore`)

The owner may use as many interactive Claude Code conversations as useful. `olivercode dispatch N` and `olivercode drain REPO` are optional unattended execution modes for explicitly delegated stories, with Sonnet for building and Opus for design judgment and cold review, and the runner validates the commit and lands it. Each repo profile declares a `canonicalValidationCommand`, a full build that decides soundness. Run it before the commit, because the gates miss a build or type error.

### Prepared owner steps

A step only the owner can take (a sign-up, a payment, a key, a one-time code) is prepared to its final screen: the agent opens the page in the signed-in browser, fills every field that is not a secret or payment detail, stops where only the secret and submit remain and queues it with `olivercode owner add --tab URL --after TEXT`. When the owner says it is done, `olivercode owner done ID` prints the check to run and the work that waited on it. Agents never type a password, card number or code.

## Project structure

These rules apply to every repo under `<fleet-root>/*`, and `olivercode conform` checks them (`docs/CONTRACT.md`). Every repo has `README.md`, `CLAUDE.md` (the only agent-rules file), `docs/repo-structure-contract.md` and a `docs/backlog-config.json` that names its one GitHub Project, which `skills/backlog/SKILL.md` governs. Every commit message carries a story reference such as `(#53)`. Every behavior change updates or adds tests, and every story has at least one negative-path assertion.

Managed files stay byte-identical across repos where `shared/project-bootstrap-manifest.json` marks them strict (`QUALITY_BASELINE.md`, the hooks, the template's structure check and `duplication_check.py`). A change is made first in OliverCode and then synced.

## File locations

| If it is a | Save to |
|---|---|
| Project plan or proposal | `<repo>/docs/plans/YYYY-MM-DD-<slug>.md`, dated, one per plan |
| System or architecture document | `<repo>/docs/<TOPIC>.md` |
| Credential or secret | `.env.local` (gitignored). `.env.example` shows variable names and placeholders |
| Voice and tone rules | `OliverCode/docs/VOICE.md`, linked to `~/.claude/VOICE.md` by `olivercode install` and imported by `CLAUDE.md` |
| Agent skill | `OliverCode/skills/` for engineering-method and framework-tooling skills, per "Skill placement". Personal and business skills go to `skillsRoot` in `olivercode.local.json`, and product or vendor skills are real untracked directories under `~/.claude/skills/` |
| Runtime artifact or output | A gitignored directory the repo declares in its `docs/repo-structure-contract.md`. It is generated, never hand-edited and never tracked |

OliverCode's `.gitignore` names `.claude-optimization/memory/`, `.claude-optimization/state/`, `runtime/control-plane/`, `scratch/` and `olivercode.local.json`.

## No icons

Zero emojis, icons or pictographs appear in code, comments, commits, documents or chat. No hook enforces it, so review does.

## Public and private repos

Every repo separates the public tracked surface (code, documents, templates, validators) from the private operator overlay (tokens, `.runtime/`, `.claude-optimization/memory/` and `state/`, scheduler wiring and machine-specific state). A public or shared repo describes the pattern and never an implementation: no project names (use `[project-name]`), no host paths (use `<workspace-root>` and `<fleet-root>`), no personal identifiers or machine-specific configs.

## Framework boundary

OliverCode is the shared orchestration framework: standards (`docs/RULES.md`), skills (`skills/`), project templates (`core/templates/project/`), shared manifests (`shared/`), documents (`docs/`), a thin launcher (`scripts/olivercode`) and the commit hooks (`.githooks/`). A clone works standalone. Product repos live at `<fleet-root>/*`, and product-specific documents and workflows stay in each project repo. Per-machine state lives in `runtime/control-plane/`, which is gitignored and never pushed, and OliverCode holds no logs, telemetry, handoff data or project credentials.

`~/.claude/` is local and per machine. `olivercode install` writes only the `CLAUDE.md`, `VOICE.md` and `DESIGN.md` links, a link per skill, its hook entries in `settings.json`, the install record `.olivercode-install.json` that `uninstall` reads, a PATH block in `~/.zshenv`, `~/.bashrc` and the login profile, and a `.pre-olivercode` backup of anything it replaced.

## Skill placement

The `skills/` folder holds engineering-method skills and the framework's own tooling as git-tracked content, indexed in `skills/INDEX.md`. Any other skill there is drift to remove. To add one, create `skills/<name>/SKILL.md`, add its row to `skills/INDEX.md` in the same change and run `scripts/olivercode install`, which links it into `~/.claude/skills/`. `validate.sh` checks the index and `olivercode health` checks the links. `.claude/skills/olivercode-adoption` is the one project-level skill.

## Documents

Every README and document in OliverCode and in each repo it governs follows this layout. `bash scripts/validate.sh` checks internal references and document-to-code consistency.

### The README

A README opens with the repo name and one sentence on what the repo does, gives install commands a reader can run at once, explains how the system works and ends with a documentation table that links every document. `olivercode conform` checks the title and the section order, and the docs check checks the table.

### Files and where they live

Documents live in `docs/`. `olivercode --help` holds the command list, and `docs/SETUP.md` holds the setup steps and the failures a user will hit, listed by symptom. `docs/BACKLOG.md` is the tracker for a repo without a GitHub Project. Each concept has one home, and every other mention points to it by name.

### The backlog

A repo whose `CLAUDE.md` names a `backlog-config.json` keeps its open work in that GitHub Project, which the `backlog` skill maintains, and every repo's Project runs the kanban baseline in `shared/kanban-baseline.json`. The board has no pull-request lane. A repo without a config keeps its open items in `docs/BACKLOG.md`.

Priority is one written scale. P0 is security, data loss or a broken mainline; P1 is a correctness defect, blocked work or a reliability failure; P2 is an improvement, cost reduction or ergonomic change. The `Priority:` line in a story is the source of truth. Grooming may report a line that disagrees with the scale, but it does not rewrite the owner's choice. When Ready stories share a priority, the drain starts the story that unblocks the most open work first, then uses issue number as the remaining tie-breaker.

Every owner request that changes files becomes a story before work starts, except a change to one file of 20 changed lines or fewer that adds no behavior, which commits with the number of the open epic it fits. `skills/backlog/references/story-template.md` defines the body and `check_story_format.py` verifies it. A request that arrives mid-task is filed without reordering the board unless the owner says "stop", "do this first" or "drop that". Each agent that commits logs it on the story.

The runner builds each story in its own worktree under `_worktrees` in `repoRoot` (`~/Developer/Repos/_worktrees` with the default layout), on its own branch, in one fresh headless session. The builder commits and stops. The runner runs the repo's validation, lands the commit on the default branch with `olivercode land`, which merges and pushes it, logs the story with `log_action.py` and closes it on that evidence. Interactive sessions remain first-class and do not automatically create stories. The owner explicitly chooses when to file and delegate bounded work to `olivercode dispatch N` or `olivercode drain REPO`. Production deploys, payments, credentials and the owner's rules files stay with the owner. Nothing closes on a builder's own report, and there is no pull request. For a story in this repo, `complete_story.py` also confirms the installed checkout at `$OC` holds the commits and that the hook entry or launchd job the story changes is active.

Work ends landed or discarded and never parks on a branch. Before a session stops or reports, it lands what passes validation, fixes what fails, and discards what is superseded with its reason on the story. The pre-push hook and the policy guard refuse any other branch.

`olivercode backlog-setup` creates or repairs a repo's Project to the baseline and `olivercode conform` lists any repo whose board differs.

### CLAUDE.md

`CLAUDE.md` loads into every session, so every word in it is paid on every turn. It holds only the rules a session must follow from any folder, each as a short paragraph or bullet that says what to do and when. The detail behind a rule lives in the document it names. A repo's own `CLAUDE.md` holds only what is true of that repo.

In a `CLAUDE.md`, a bare path means the repo the session is in, and no machine path is hardcoded. The `audit` skill runs only when the owner names it.

The memory rule's detail is here. A fresh clone has no `$OC/.claude-optimization/memory/` folder and uses Claude Code's own memory. `scripts/hooks/memory_guard.py` refuses any write that puts a rule into the local memory folder, and it refuses every write to auto-memory under `~/.claude/projects/`.

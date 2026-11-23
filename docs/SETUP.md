# Setup

How to take a clone or fork of OliverCode and make it govern your own repos, how to restore that setup on a blank machine, what the `olivercode` commands do beyond their help line and what to do when something fails. The steps are written for the agent doing the work with a human approving.

Point existing rules at a shared home and keep them. Anything you cannot map to an OliverCode concept stays where it is.

For the plain-language picture of how the parts fit, read the README section "How it works, in plain terms" before this document.

You do not have to read this. Open the repo in Claude Code and say "Set this up for me". The `olivercode-adoption` skill ships project-level, so it is available on a fresh clone and drives every step below.

## Step 0: prove the clone is sound

You need Python 3.12 or newer, git, the GitHub CLI (`gh`) and the Claude Code CLI (`claude`), installed and signed in. `olivercode` in these docs stands for `python3 scripts/olivercode` run from the checkout, or `$OC/scripts/olivercode` from anywhere. Step 2's install links `olivercode` into `~/.local/bin` and adds that folder to the PATH of new zsh and bash shells, so a bare `olivercode` works after you open a new terminal.

Clone into `~/Developer/Repos`, outside `~/Documents`, `~/Desktop` and any iCloud Drive, Dropbox, OneDrive or Google Drive folder, because a sync service evicts working files when the disk fills.

```bash
mkdir -p ~/Developer/Repos && cd ~/Developer/Repos
git clone <your-fork> OliverCode && cd OliverCode
python3 scripts/olivercode --help
bash scripts/validate.sh
scripts/olivercode health
```

Each command must exit 0 on a clean clone with no configuration. If `validate.sh` fails here, the fork is broken and your setup is fine, so stop. `bash scripts/qa/rehearse-install.sh` rehearses the guide in a sandbox with a throwaway HOME.

## Step 1: inventory before you touch anything

```bash
ls ~/.claude/                                   # what already exists
cat ~/.claude/CLAUDE.md 2>/dev/null             # existing global rules, if any
ls -la ~/.claude/skills/ 2>/dev/null            # existing skills, real dirs vs symlinks
scripts/olivercode discover --root ~/dev --root ~/work   # read-only, one --root per folder
```

`discover` reports each repo's agent-rules file and hook state, inventories `~/.claude` and ends with a profile per repo. An existing setup usually surfaces three things:

- **Rules files not named `CLAUDE.md`.** `AGENTS.md` and `.cursorrules` do not auto-load in Claude Code, and Step 4 merges them in
- **Repos with `hooksPath=unset`.** They have no gates at all, silently
- **Real directories in `~/.claude/skills/`.** `install` never touches them and reports how many it left alone

## Step 2: back up, then install activation

`install` backs up an existing `~/.claude/CLAUDE.md` to `CLAUDE.md.pre-olivercode` itself and never deletes anything in `~/.claude/skills/`. Make your own restore point for that folder:

```bash
cp -R ~/.claude/skills ~/.claude/skills.pre-olivercode 2>/dev/null || true
scripts/olivercode install     # symlinks CLAUDE.md, VOICE.md, DESIGN.md + skills, merges the hook entries
scripts/olivercode health
```

`health` checks that every symlink resolves into this checkout. Keep the backups until everything is verified.

The first `install` on a machine ends with a short introduction to how work runs, the three first steps and the "Using it well" habits: register your repos, run `health`, file your first story. A repeat install prints one line that points to `olivercode guide`, which opens with the same explanation as the README's "How work runs" section. A status question in a session is answered from the status digest by `status_hint.py`, so it costs no tool call; `install` adds that hook, and `health` fails until it is in place.

Before the install step writes `permissions.allow`, run `scripts/olivercode install --show-allow` and show the user its output. Each line names one rule, whether it is already present, and what it permits. One yes from the user lets `install` write the missing ones beside their own rules, and `olivercode health` fails when any is missing later.

## Step 3: merge your global rules in

Sort your old `~/.claude/CLAUDE.md` into your fork's `CLAUDE.md` (machine-global rules), each repo's own `CLAUDE.md` (repo rules) and a skill (personal or business rules). Anything you cannot classify stays and is flagged for the human. Every path in the global file must resolve from anywhere, so use `$OC/...` for OliverCode's files.

## Step 4: rewrite each repo's CLAUDE.md

Start from `core/templates/project/CLAUDE.md`, keep only what is specific to the repo and verify every pointer with `ls`. Merge an `AGENTS.md`, `.cursorrules` or similar file into `CLAUDE.md`. If another tool still reads the original, keep it as a one-line pointer to `CLAUDE.md`, and otherwise delete it in the same commit. Never leave both files carrying live rules.

## Step 5: register your fleet

`install` makes your fleet folder a local git repo from the template and offers a private GitHub copy once. Run `scripts/olivercode init-fleet` to push that copy when you decline it at install, then run `scripts/olivercode discover --root <dir> --register` for each folder that holds the repos the user confirmed. It writes each new repo into the registry this checkout reads, with its `name`, `path` and the validation command the repo names. Remove any repo the user did not confirm, and set the command by hand for each repo it names as having none.

Your fleet's own stories, registry, owner-rule carriers and owner queue live in that private fleet repo and never in this one. File a story about one of your repos there, and keep this repo's issues to the engine.

```bash
scripts/olivercode conform --offline     # lists your repos by name; hook checks fail until Step 6
```

## Step 6: install enforcement

```bash
scripts/olivercode sync-hooks            # writes .githooks/ and sets core.hooksPath in every fleet repo
scripts/olivercode conform --offline     # hooks pass now; template checks stay FAIL until Step 6b
```

`sync-hooks` expects the fleet repos as siblings of the OliverCode checkout (see "Folder structure"). A repo reported as `[SKIP] not present on this machine` is one it did not govern, and the exit code does not show them, so read that list. `--commit --story REF` commits the hook files it changed and pushes nothing.

Give your OliverCode checkout its own board before the first commit. Run `gh auth login`, then `gh auth refresh -s project`, then `scripts/olivercode backlog-setup --apply`. The `docs/backlog-config.json` you received names the repo it came from, so the commit-msg gate skips story checks until this replaces it.

`docs/GATES.md` says when hook enforcement fails open. Run `scripts/olivercode conform` at setup and on a schedule to find it fleet-wide.

### Step 6b: stamp the project template into a repo

`bootstrap` stamps the full project template declared in `shared/project-bootstrap-manifest.json` (quality baseline, structure contract and supporting scripts), so a repo matches the standard on day one. Look before you write:

```bash
scripts/olivercode bootstrap <repo> --dry-run    # prints NEW/OVERWRITE per file, writes nothing
scripts/olivercode bootstrap <repo>
```

The manifest gives every file a mode: `presence` files are created only if absent, `strict` files are overwritten to stay byte-identical with the source, and `offered` files, such as `CODEOWNERS`, are written only when you ask. Read the OVERWRITE lines first, because that list is exactly what you agree to lose.

## Step 7: verify with evidence

```bash
bash scripts/validate.sh
scripts/olivercode conform --offline
scripts/olivercode skills
cd <one of your repos> && bash "$OC/scripts/qa/probe-secret-gate.sh"    # writes a fake secret, commits, expects a block
```

If the probe commit succeeds, your hooks are not installed, so go back to Step 6. A `sync-hooks` message saying `done` confirms only that the hook files were written, and the probe confirms that git runs them.

## Step 8: reconcile

Confirm anything you moved exists at its new home, tell the human what you could not classify and why, and remove the `.pre-olivercode` backups only after the human confirms.

## Keep the machine awake

Sessions stop when the Mac sleeps. `olivercode health` prints one warning when `pmset -g` shows a display or system sleep timer above zero, and `olivercode conform` reports the same line as the `sleep-setting` row. To clear it, open System Settings, then Battery or Energy, and turn off sleep on power adapter and display sleep, or run `caffeinate -dimsu` in a terminal before leaving.

## Staying current

A steady copy tracks the `stable` tag, which the owner moves by hand to the last commit proven in daily use: `git fetch --tags --force && git checkout stable`. `VERSION` holds the current version (`docs/VERSIONING.md`), and `olivercode health` prints how many commits the checkout is behind its upstream.

`olivercode update` pulls this checkout's tracking branch fast-forward only, re-runs install and re-syncs hooks. A change to a tracked file, a rebase in progress or a diverged checkout is refused before anything changes, and the refusal prints a fix that needs no push. An untracked or ignored file blocks it only when the release adds a file at the same path. On a fork the tracking branch is your own `origin`, so take upstream changes explicitly:

```bash
git remote add upstream <the repo you forked from>   # once
git fetch upstream && git merge upstream/main        # resolve conflicts deliberately
bash scripts/qa/rehearse-install.sh && scripts/olivercode sync-hooks
```

Your own state lives outside the tracked files, so an update never touches it. Settings such as the audit mode sit in the git-ignored `olivercode.local.json`, and a key you never set takes the default a release ships. Lessons and other state sit under `~/.olivercode`. Your own repo and Project go in `docs/backlog-config.local.json` and your fleet in `shared/repo-profiles.local.json`, both git-ignored, and each overrides the tracked example. When a release moves a state file, install moves your copy once and keeps a backup in `~/.olivercode/backups`.

### Installed checkout stays level with origin

The installed checkout only ever fast-forwards. A job or an owner step that makes a commit there makes it in a worktree of origin/main and lands it with `olivercode land WORKTREE STORY`. The daily version cut (`olivercode version-cut --commit`) works this way: it cuts the version in a worktree and hands the commit to `olivercode land` (#785). `olivercode version cut` runs the same cut on demand. The cut holds a lock while it lands, so a `land` for another story waits until the cut ends, and the land's retry loop repeats the fetch, rebase, validation and push while main moves, for up to ten minutes. A push the permission classifier denies reaches the owner queue once with the exact command (#789).

A checkout that already holds a commit origin lacks is named by `olivercode health`, by the SessionStart check, and by the refusals from `olivercode update` and `complete_story.py`. Each names the commits with their authors and prints one command, which moves those commits to a local branch and leaves the checkout level with origin/main. That command needs no write access to origin. `update` and `complete_story.py` change nothing until it has run, and a commit that belongs on origin/main goes there through `olivercode land`.

## Backing out

```bash
scripts/olivercode uninstall                          # removes what install wrote in ~/.claude and restores its backups
git -C <repo> config --unset core.hooksPath           # per governed repo; .githooks/ can stay or go
```

Then delete the checkout. `uninstall` keeps everything of yours in `~/.claude` and lists any backup it could not restore. OliverCode writes no system config and no shell profile, and files `bootstrap` stamped into a repo belong to that repo.

## Folder structure

`sync-hooks` and `conform` look for fleet repos as siblings of the OliverCode checkout.

A repo outside that layout gets an explicit `path` in the registry (absolute, `~`-relative or fleet-root-relative), which `discover` emits. When your repos share a parent that is not OliverCode's, pass `--root`:

```bash
scripts/olivercode sync-hooks --root /path/to/where/your/repos/live
scripts/olivercode health     --root /path/to/where/your/repos/live
```

Machine paths go in `olivercode.local.json` at the OliverCode root, which is gitignored. Copy `olivercode.local.example.json` and fill in:

- `fleetRegistry`: the path of the fleet registry file, `~/.olivercode/fleet/repo-profiles.json` when unset. With no registry at that path or under `privateRepos`, the fleet commands say no fleet is set and name `olivercode init-fleet`
- `privateRepos`: private repos that get the private hook variant and a hook check
- `skillsRoot`: the folder for personal skills, which the skill checks read
- `repoRoot`: the one folder that holds every repo, `~/Developer/Repos` in the example. Any folder outside the synced ones works. Worktrees go in `_worktrees` and backups in `_archive` under it. It must sit outside every synced folder
- `schedules.retiredNames`: names that a scheduled task must no longer mention, which `olivercode health` enforces
- `otherDeviceRepos` and `otherDeviceOwners`: repo names and GitHub accounts that belong to another of your devices. Every fleet walk skips the repos, `olivercode health` fails for a checkout of either under `repoRoot` and names the fix, and the clone guard refuses to clone them. No agent creates a GitHub repo for a folder that has no origin and reports the folder to the owner
- `watchRoots` and `allowOutside`: the folders `olivercode place` scans for strays, and checkouts allowed to stay elsewhere
- `repoPaths`: a repo outside the fleet folder
- `liveCopies`: each path a running bot reads, mapped to its agent copy. `install` and `conform` fail when OliverCode runs from a live path and name the agent copy to use
- `auditMode`: `full` or `gated`. Unset, the audit stops at its report and filed issues, and `olivercode audit-mode full|gated` stores the opt-in to fix them too
- `retroEpic`: the epic that `olivercode retro --file` names in each story it files, as a number, `#N` or `owner/repo#N`. Leave it unset or 0 and those stories carry no Epic line
- `voiceFile`: the owner's own voice file, which `install` links as `~/.claude/VOICE.md` in place of `docs/VOICE.md`
- `designFile`: your own design file, which `install` links as `~/.claude/DESIGN.md` in place of `docs/DESIGN.md`. `install` keeps a `~/.claude/VOICE.md` or `DESIGN.md` you already have and prints `[KEPT]`

`OLIVERCODE_SKILLS_ROOT` overrides `skillsRoot`. A layout the scripts cannot resolve degrades to WARN and skips, and a WARN is no coverage. If `sync-hooks` reports every repo as skipped, your `--root` is wrong.

## What a headless run costs

Every `claude -p` call that OliverCode starts runs with an empty strict MCP config, so no connector loads, and with Read, Edit, Write, Bash, Grep and Glob allowed. Each round of `run`, `dispatch` and `drain` appends one JSON line to `run-log.jsonl` in the OliverCode home folder with the story, round, model, input, output, cache read and cache write tokens, the cost when Claude Code reports it, the time the row was written, and the CLI's stop reason and stderr tail for a round that did not finish cleanly. The first round of a session also carries `start_tokens`, the context size of the session's first call: its input, cache read and cache write tokens, read from the first assistant line of the session transcript and no later line. The session total stays under `cache_write`, and no line writes a total under `start_tokens`. Sum that file by story to see what a story cost.

A story that is M or larger, or that changes a hook, gets one fresh reader after its validation passes. A finding sends the story back once: one short fix session gets the story, the diff and the finding, and the reader reads the commit again. A second finding holds the story. Nothing is pushed, the branch stays in its worktree, the story goes back to Ready and one comment on it holds the finding. A reader that cannot run holds nothing.

Claude Code has no flag that loads only the skills a story names. `--disable-slash-commands` drops every skill and saved only about 1,000 tokens of a 42,000-token start in a measured run, so the headless runner loads skills as an interactive session does. The start size is mostly the global rules files and tool definitions.

Set `OLIVERCODE_PROJECT_SETTINGS=1` to start each headless session with the project's settings only: `claude -p` then gets `--setting-sources project,local`, and the owner's `~/.claude/settings.json` contributes only OliverCode's own hook entries, so the commit gates and the pretool guards still run. The run refuses to start when those entries are missing. The default stays the current flags until one measured story shows the smaller start. To measure, run the same story once each way and compare `start_tokens` by the `settings` field of its run-log lines. Each headless session also skips the repo placement scan at start.

## Restoring on a new machine

Clone OliverCode and each fleet repo side by side, copy `olivercode.local.example.json` to `olivercode.local.json`, fill in this machine's paths and name the registry's repo under `privateRepos`. Then run Step 0, Step 2 for `install`, Step 6 for enforcement and Step 7 to prove a gate blocks. Steps 1, 3, 4 and 5 are done, because the rules and the registry come back with the clones. Marketplace plugins, application plugins and MCP server authorization need a person. A restore is finished when `health` is HEALTHY and a planted secret is refused by a real commit.

## Launcher commands

`python3 scripts/olivercode --help` prints every command and its arguments, and `olivercode guide` prints how work runs, the first steps and every command grouped by the job it does, one plain line each. `olivercode guide NAME` says what one command, gate, guard, scheduled job or skill does and where it lives.

In a repo with commit gates, a new interactive session refreshes `status-digest.md` through the session-start hook, with no model call, and prints three lines: the open count, the last story landed and the path to read before acting. A headless builder session gets none of them. The digest holds the open stories in priority order, the last five landed, what waits on the owner, the latest decisions and the run log, within 1,500 tokens. `--root DIR` overrides where fleet repos are looked for (the default is the parent of this checkout), and unknown arguments exit non-zero.

- `version-cut` reads the commits on main for one day, picks MAJOR, MINOR or PATCH from `docs/VERSIONING.md`, sets `VERSION` and writes that version's `CHANGELOG.md` section. `--commit` commits the two files with `OLIVERCODE_VERSION_CUT=1`, which the `version-files` gate requires
- `board sync` keeps each board in step with its issues, because GitHub has no API for the built-in "Item closed" and "Auto-add to project" workflows. It reads each board and its repo's issues through REST, moves the card of every closed issue to Status Complete and adds every open issue that has no card with Status Backlog, through `batch_project.py`, which queues the writes while GraphQL is on hold. `--dry-run` reports without writing, `--schedule` loads the `com.olivercode.board-sweep` launchd job that runs it every thirty minutes, and `olivercode conform` fails a board on a machine where that job is not loaded (#798)
- `docs-check` fails when a command in the launcher table is named in neither `README.md` nor this file, when the gates table in `docs/GATES.md` and `core/hooks/gates/` differ, when `skills/INDEX.md` and `skills/` differ, or when `README.md` and `docs/` do not link each other. `validate.sh` runs it, and `bootstrap` ships it to fleet repos
- `backlog-setup` works from `shared/kanban-baseline.json`: it reuses or creates the repo's Project, adds the missing Status lanes and fields, writes `docs/backlog-config.json`, creates the `owner-action` and `program` labels and installs the commit-msg hook. It saves every item's field values to `backlog-backups/` in the repo's git directory first, and exits non-zero when the counts per option differ afterwards
- `dispatch N` checks load and claim limits, posts the claim and builds the story in one fresh headless session, and the runner validates, lands and closes it through the same code `drain` uses. `drain REPO` works a repo's open stories in priority order the same way, one at a time. `drain REPO --parallel N` runs up to N builders at once, and only stories whose files areas do not overlap run together. Serial is the default because the validation queue serves one run at a time, so parallel builders invalidate each other's results. Parallel stays opt-in until a run with `--parallel 2` shows both stories landing with no rebase conflict and no repeated validation in the run log
- `land WORKTREE STORY` rebases the worktree on origin/main, runs `scripts/validate.sh` up to twice unless the runner already recorded a pass for the same tree (the log names the record it used, #910), pushes `HEAD:main` (retrying while main moves, see "A land resumes and retries"), fast-forwards a clean main checkout and deletes the worktree and its branches. Work that does not land stays in its worktree with a handover file at `~/.olivercode/land/handover-REPO-N.md`
- `limits check` prints the tracked line count against the one ceiling number in `docs/LIMITS.json` (tests are not counted) and exits 0 always. A count over the ceiling prints a warning and blocks nothing, and `validate.sh` and `land` never edit the file. Edit the number by hand to accept growth
- `board` (`groom` and `sync`), `fleet-sync`, `maintain` and `gh-limit` run without a model call, and each takes `--schedule` where `--help` shows it. `gh-limit clear` lifts the shared GitHub rate-limit hold
- `owner`, `decisions`, `lesson`, `retro`, `batch` and `story outbox` keep the owner's decisions, corrections and queued story requests in `~/.olivercode/`
- `push-blocked --session SID` answers a blocked OliverCode push. It reads the decision record `standing-push-olivercode` that the owner made with `decisions record ... --by owner`, names the one rule to allow and exits 0, and nobody asks the owner again. With no record it exits 1, leaves the push blocked and queues one owner line that asks once. It edits no settings file: the rule itself reaches `~/.claude/settings.json` through the installer's autoMode story
- `install` links `docs/VOICE.md` and `docs/DESIGN.md` into `~/.claude`, links each skill, merges the hook entries listed in `docs/RULES.md` ("Execution") into `~/.claude/settings.json` and sets `core.hooksPath` to `.githooks` here when unset. Any other file at a target path moves to `<name>.pre-olivercode` and is printed. `uninstall` reverses exactly that
- `validated record|check SHA` keeps the passing full validations that the pre-push hook requires before a push to main
- `queue show` lists the validation runs holding one of the slots that every `scripts/validate.sh` waits for. The slot count is `OLIVERCODE_VALIDATE_SLOTS`, which defaults to an eighth of this machine's cores (at least 1), so an 8-core laptop runs one validation at a time and a 16-core desktop runs two. A holder keeps its slot while its process lives and for up to 4 hours (`OLIVERCODE_VALIDATE_HARD_CAP`, in seconds), and a run waits up to an hour (`OLIVERCODE_VALIDATE_WAIT`, in seconds) before it goes ahead with a message that names why. A slot whose holder died, whose pid now belongs to another process or whose file is damaged is reclaimed with a line that names the repair The pretool guard routes `npm test`, `pytest` and the other commands in `QUEUED_COMMANDS` (`scripts/hooks/queue_guard.py`) through `queue run`

### The olivercode command on PATH

Install links `olivercode` into `~/.local/bin` and adds that folder to the PATH of new zsh and bash shells. `olivercode health` reports a missing link or a PATH that lacks the folder.

### A land resumes and retries

`olivercode land` can be run again after it was killed. When main moves on every one of the first four attempts it keeps rebasing, validating and pushing with a short pause for up to ten minutes, and a rebase conflict or a failed validation ends it earlier. A land that runs out of time reports `RESULT main-kept-moving`. A second land for a story that is already running refuses and names the running land's log. Each log is named `land-REPO-N.log`, so two repos landing the same story number never share one.

### Board workflows are set at install

Every board has two workflows that GitHub offers no API for, so an agent cannot switch them on. "Item closed" sets Status to Complete when an issue closes, and "Auto-add to project" adds each new issue that matches the filter `is:issue is:open`. A board with either one off drifts from the repo, with closed stories still open on the board and new stories missing from it. `olivercode backlog-setup --apply` prints both steps and the board's workflows page, `https://github.com/users/OWNER/projects/N/workflows`, after it makes or repairs a board. Open that page, pick each workflow in the left list, set the value, save and reload to check it. `olivercode conform` reads the workflow list and names the board and the workflow that is off. When GitHub does not return the list, conform says nothing about the workflows and the step stays on the owner's list. The `olivercode-adoption` skill walks a new user through the clicks.

### The deploy template

`core/templates/deploy/deploy.yml.tmpl` is the one reusable workflow for production deploys from CI. It sits outside `.github/workflows` and `bootstrap` does not stamp it, so it runs nowhere until the owner copies it into a repo as deploy.yml in its workflows folder, replaces the `__TOKEN__` placeholders (validation, deploy and rollback commands, live address, expected text, deploy secret name) and adds the deploy key as a secret of the repo's `production` environment. On each push to main it runs the repo's validation, deploys, checks the live address, and on a failed check runs the rollback and files a P0 issue. The owner approves each repo's workflow and key once, and a deploy by hand still needs the owner's message.

### Recurring jobs audit

`olivercode usage jobs --days N` (7 by default) lists every scheduled task and launchd job of this machine with its schedule, whether it starts a model, whether its text names a gate, its token spend over the period and whether it is a candidate to convert (it starts a model and names no gate). The list is ranked by spend, highest first. A scheduled task's spend is the usage in its run transcripts. A launchd job has no per-job transcript, so its spend shows as not measured. Run it before a conversion and again 7 days after, and the change is a number. The command reads files only and starts no model.

## How a headless builder finishes a story

`drain` and `dispatch N` share one finish, the same `work_story` code. The builder works in a worktree that `olivercode worktree add` prepares, so hooks and the virtualenv exist before its first commit. When the loop's validation passes, the story is landed with `olivercode land`, commented, closed and its card queued to Complete. Both commands send the builder the same brief: it commits by explicit path and stops, and it never validates, lands, logs or closes. A story counts as landed when a commit that names it is on origin's default branch, which the runner checks in the main checkout, so a story whose worktree is already gone is reported landed with exit 0. A story is closed only on that evidence. On any other outcome the story stays open, a comment names the reason, its card returns to Ready and the claim is released. A validation that runs past its hour fails the round and goes back to the model.

A story whose earlier session stopped keeps its branch story/N. A second `dispatch N` or `drain` reuses that branch: it attaches the worktree when it is missing, keeps the commits and uncommitted changes, rebases onto origin's default branch when that is clean (a conflict leaves the branch as it was) and tells the new session in its brief to read `git status` and `git log` first.

A session that stops on the turn cap (30 turns) or the 900-second round limit is resumed once on the same Claude Code session before the round counts as failed. Any other non-zero exit is reported with the CLI's own stop reason and the tail of its stderr, in the run log and in the story comment.

## Troubleshooting

### A denied job reaches the owner queue

When the permission classifier denies a command that loads a persistent job (a `launchctl bootstrap` or `olivercode retro --schedule`), the denial-watch hook writes one owner-queue line with the job label and the exact command to paste. The same denial again writes no second line. Run `olivercode owner list` to see the line and `olivercode owner done ID` once the job is loaded.

### Commits are passing gates that should have blocked them

Git runs hooks only when `core.hooksPath` resolves to a directory holding an executable `pre-commit`. If that config is unset, points at a missing directory or names a non-executable file, git runs no hooks and prints nothing, so every commit succeeds.

```bash
git config --get core.hooksPath      # expect: .githooks
scripts/olivercode conform --offline # FAILs with the exact reason if any repo is in that state
scripts/olivercode sync-hooks        # repairs it across the fleet and the private repos
```

Use the relative `.githooks` and never an absolute path, because an absolute one breaks silently when the repo moves.

### Fleet hooks report drift after a gate edit

`conform` compares each fleet repo's live hook against the templates built from `core/hooks/`, so every fleet repo diverges after a gate change until `scripts/olivercode sync-hooks` re-syncs it.

### `validate.sh` fails with "not a git repository"

`validate.sh` runs `.githooks/pre-commit`, which calls `git diff --cached`, so it needs a real `.git`. An extracted archive without `git init` fails this way, and that is expected.

### Conform batches its calls and fixes what it finds

`olivercode conform` reads delete-on-merge and admin rights for every registered repo in one GitHub query, calls `git ls-remote` once per repo and checks repos in parallel up to the CPU count. `sync-hooks --commit --story REF` and `backlog-setup --apply --commit --story REF` each land every change in one repo as one commit through the helper in `scripts/lib/gitfiles.py`, which never pushes and never skips the repo's hooks.

`olivercode conform --fix --story REF` runs each local fix (hooks with the queue block, managed files, the permission policy), commits them together per repo, sets delete-on-merge only on repos the signed-in owner administers, and puts every other failure on the owner queue with its exact command. A repo with uncommitted changes in a file a fix would touch is skipped with the reason. It then checks again and prints what still fails.

### `run-tests.sh` ends with an import error on a module name

`scripts/run-tests.sh` runs every test module in its own process through `scripts/lib/smoke_runner.py`, as `validate.sh` does, so two modules that share a name, such as `test_sweep` in `tests/` and in `skills/audit/scripts/`, no longer collide. `tests/test_run_tests_snapshot.py` covers it.

# Setup

How to take a clone or fork of OliverCode and make it govern your own repos, how to restore that setup on a blank machine, what every `olivercode` command does and what to do when something fails. The steps are written for the agent doing the work with a human approving.

The governing rule for the whole process is to optimize and never amputate. You point existing rules at a shared home and do not delete them. Anything you cannot map to an OliverCode concept stays exactly where it is, and a rule you do not understand is a rule you keep.

You do not have to read this. Open the repo in Claude Code and say "Set this up for me". The `olivercode-adoption` skill ships project-level, so it is available on a fresh clone, and it drives every step below and surfaces only the decisions that need you. This document is the reference it works from.

## What you are installing

| Layer | Where | Tracked | Owner |
|---|---|---|---|
| The framework | Your OliverCode fork | Yes | You |
| Your fleet's registry | The file `olivercode discover` names (`REGISTRY-PRIVATE-1` in `docs/DECISIONS.md`) | Yes, in that repo | You |
| Activation | `~/.claude/CLAUDE.md` and the `~/.claude/skills/*` symlinks | No, per machine | Your machine |

Your fleet's names and config live in one registry file, and no placeholder layer has to stay in sync with it.

## Step 0: prove the clone is sound

```bash
git clone <your-fork> OliverCode && cd OliverCode
python3 scripts/olivercode --help
bash scripts/validate.sh
scripts/olivercode health
```

Each command must exit 0 on a clean clone with no configuration. `health` notes that there is no control plane and `conform` reports that no fleet is registered, and both are correct. If `validate.sh` fails here, the fork is broken and your setup is fine, so stop.

One command rehearses the whole guide in a sandbox with a throwaway HOME and never touches your real `~/.claude`:

```bash
bash scripts/qa/rehearse-install.sh
```

It runs the real `install`, then walks fleet registration, `sync-hooks`, the secret probe, `health`, `update` and the backout. When it passes, every later failure is a setup problem. Run it after any change to the framework's plumbing.

Enable CI in your fork: `.github/workflows/framework-ci.yml` ships ready and is paused on the origin repo (`docs/GATES.md`, "Validation", says why). Where CI is off, `bash scripts/validate.sh` before you push is the whole enforcement layer.

## Step 1: inventory before you touch anything

Write the inventory to a scratch file, because you need it to prove nothing was lost.

```bash
ls ~/.claude/                                   # what already exists
cat ~/.claude/CLAUDE.md 2>/dev/null             # existing global rules, if any
ls -la ~/.claude/skills/ 2>/dev/null            # existing skills, real dirs vs symlinks

# Find your repos and what governance each already has. Read-only. Pass every
# directory your code lives under; they do not have to share a parent.
scripts/olivercode discover --root ~/dev --root ~/work
```

`discover` reports each repo's agent-rules file and hook state, inventories `~/.claude` and ends with a profile skeleton with explicit `path` values for the registry file the command names. An existing setup usually surfaces three things:

- **Rules files not named `CLAUDE.md`.** `AGENTS.md`, `.cursorrules` and similar files do not auto-load in Claude Code, so they are invisible in practice. Step 4 merges them in
- **Repos with `hooksPath=unset`.** They have no gates at all, silently
- **Real directories in `~/.claude/skills/`.** They exist in one place on one machine with no backup. Usually they are vendor skills, and anything else needs a decision on where it belongs. `install` never touches them and reports how many it left alone

Sort each existing rules file into three kinds. Machine-global rules belong in the OliverCode `CLAUDE.md`. Repo-specific rules stay in that repo's `CLAUDE.md`. Personal or business rules (voice, sales, hiring) belong in your own user-skills area and stay out of the framework (`docs/RULES.md`, "Skill placement"). Most existing files hold all three tangled together, and separating them is the adoption.

## Step 2: back up, then install activation

`install` backs up an existing `~/.claude/CLAUDE.md` to `CLAUDE.md.pre-olivercode` itself, so do not copy it first. It never deletes anything in `~/.claude/skills/`, and a restore point for that folder is yours to make:

```bash
cp -R ~/.claude/skills ~/.claude/skills.pre-olivercode 2>/dev/null || true

scripts/olivercode install     # symlinks CLAUDE.md, VOICE.md + skills, backing up what it replaces
scripts/olivercode health
```

`install` reports how many skills it linked and how many real directories it left alone, and `health` checks that every symlink resolves into this checkout. Keep the backups until everything is verified.

## Step 3: merge your global rules in

Your old `~/.claude/CLAUDE.md` content gets sorted in this order:

1. Machine-global rules go into your fork's `CLAUDE.md`, under its existing sections
2. Rules about one repo move to that repo's own `CLAUDE.md`
3. Personal or business rules become a skill, placed per `docs/RULES.md` ("Skill placement")
4. Anything you cannot classify stays in the global file and is flagged for the human

The global file loads in sessions whose working directory is almost never OliverCode, so every path in it must resolve from anywhere. Use `$OC/...` for OliverCode's own files, resolved and checked:

```bash
OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
[ -f "$OC/docs/RULES.md" ] || echo "OliverCode not installed"
```

A bare path such as `scripts/validate.sh` means the repo the agent is currently in, because every repo has its own. Say so explicitly, or the next reader assumes it means OliverCode's.

## Step 4: rewrite each repo's CLAUDE.md

For every repo, start from `core/templates/project/CLAUDE.md`. The file carries only what is specific to that repo, under a short block that says where the shared rules come from.

- Every pointer is relative to the reader's working directory. A path such as `Some/Vault/Path/OliverCode/CLAUDE.md` does not resolve from inside the repo, so verify each pointer with `ls`
- Repo-specific content stays even when it makes the file longer, and duplicated framework rules come out
- If a repo has an `AGENTS.md`, `.cursorrules` or a similar rules file, merge it into `CLAUDE.md`, because Claude Code auto-loads only `CLAUDE.md`. If another tool still reads the original (Cursor, Copilot, Codex), keep it with a one-line pointer to `CLAUDE.md` so the two cannot drift apart. If nothing reads it, delete it in the same commit, because git is the archive

Never leave both files carrying live rules, because that duplication is what this step exists to end.

## Step 5: register your fleet

Enforcement has to know which repos it governs before it can reach them, so registration comes first.

Edit the registry's `repo-profiles.json` with your real repo names and validation commands. `olivercode discover` prints which file this checkout reads (`REGISTRY-PRIVATE-1` in `docs/DECISIONS.md`). `_<field>_note` keys beside a worked example document the schema in place. `scripts/olivercode discover --root <dir>` emits a profile skeleton per repo with `name`, `path` and `canonicalValidationCommand`.

Confirm the fleet registered before continuing:

```bash
scripts/olivercode conform --offline     # must list your repos by name, not "no fleet registered"
```

## Step 6: install enforcement

```bash
scripts/olivercode sync-hooks     # writes .githooks/ + sets core.hooksPath in every fleet repo
scripts/olivercode conform --offline         # confirms each repo's hooks are installed and current
```

`sync-hooks` resolves your fleet from the registry file named in Step 5 and expects those repos as siblings of the OliverCode checkout. If your layout differs, see "Folder structure" below. Every repo reported as `[SKIP] not present on this machine` is one it did not govern, and the exit code does not show them, so read that list.

`docs/GATES.md` has the table of which gates each kind of repo runs.

Hook enforcement fails open when `core.hooksPath` is unset (`docs/RULES.md`, "Execution"). Run `scripts/olivercode conform` at setup and on a schedule to find it fleet-wide, and see "Commits are passing gates that should have blocked them" below to fix it.

### Step 6b: stamp the project template into a repo (optional)

`sync-hooks` already installs the gates, which is what governs a repo. `bootstrap` goes further and stamps the full project template declared in `shared/project-bootstrap-manifest.json` (quality baseline, structure contract and supporting scripts), so a new repo matches the standard on day one. For an existing repo, look before you write:

```bash
scripts/olivercode bootstrap <repo> --dry-run    # prints NEW/OVERWRITE per file, writes nothing
scripts/olivercode bootstrap <repo>
```

The manifest gives every file a mode. `presence` files are created only if absent and existing content is kept. `strict` files are overwritten because their contract is byte-identity with the template, which covers the hooks and the shared baseline. Read the OVERWRITE lines of the dry run first, because that list is exactly what you agree to lose.

## Step 7: verify with evidence

```bash
bash scripts/validate.sh          # gates, consistency, references, tests
scripts/olivercode conform --offline         # per-repo hook install state and the rest of the contract
scripts/olivercode skills         # every skill discoverable
```

Then prove enforcement fires:

```bash
cd <one of your repos>
bash "$OC/scripts/qa/probe-secret-gate.sh"    # writes a fake secret, commits, expects a block
```

`scripts/qa/probe-secret-gate.sh` is the one home for this probe, and its header explains why it writes straight into the repo and never stages through `/tmp`. If that commit succeeds, your hooks are not installed, so go back to Step 6. A `sync-hooks` message saying `done` confirms only that the hook files were written, and the probe confirms that git runs them.

## Step 8: reconcile

Make a last pass over what the Step 1 inventory found:

- Anything you moved: confirm it exists at its new home before you consider the old one gone
- Anything you could not classify: it stays, and you tell the human what and why
- Only after the human confirms: remove the `.pre-olivercode` backups

Write the result as a short report of what moved where, what stayed and what is still ambiguous.

## Staying current with upstream

`olivercode update` pulls this checkout's tracking branch, re-runs install so a new skill or Claude Code hook reaches this device, and re-syncs hooks. On a fork that tracking branch is your own `origin`, and it does not fetch the upstream framework. A fork carries local edits to `CLAUDE.md`, standards and templates, and auto-merging upstream over them would be destructive. To take upstream changes, do it explicitly:

```bash
git remote add upstream <the repo you forked from>   # once
git fetch upstream
git log --oneline HEAD..upstream/main                # read what you are about to take
git merge upstream/main                              # resolve conflicts deliberately
bash scripts/qa/rehearse-install.sh                  # prove the merge did not break the fork
scripts/olivercode sync-hooks                        # templates may have changed
```

Expect conflicts in `CLAUDE.md` and in anything under `core/` you customized, which are the files you were meant to change. Keep your version and take upstream's structural fixes.

## Backing out

Adopting this is not a one-way door. To remove it:

```bash
# 1. Remove what install wrote in ~/.claude and restore what it backed up
scripts/olivercode uninstall

# 2. Stop the hooks in each governed repo
git -C <repo> config --unset core.hooksPath          # per repo; .githooks/ can stay or go

# 3. The checkout itself is just a directory; delete it.
```

`uninstall` keeps everything of yours in `~/.claude` and lists any backup it could not restore, so merge those back by hand. These three steps cover everything OliverCode writes on a machine: the `~/.claude` entries `install` makes, the `.githooks/` folder and `core.hooksPath` key `sync-hooks` sets in each governed repo and `install` sets in this checkout. OliverCode writes no system config and no shell profile. Files `bootstrap` stamped into a repo belong to that repo once stamped, so they stay.

## Folder structure

`sync-hooks` and `conform` look for fleet repos as siblings of the OliverCode checkout, and nothing else depends on where anything sits.

```
<workspace-root>/
├── OliverCode/              the fork: framework, skills, standards, gates
│   └── runtime/control-plane/  (gitignored, optional) per-machine state
├── product-repo-a/          siblings of OliverCode
└── product-repo-b/
```

A repo outside that layout gets an explicit `path` in the registry file named in Step 5. `path` accepts absolute, `~`-relative or fleet-root-relative values, and `discover` emits it for you. Without it a repo is findable only at `<fleet-root>/<name>`. When your repos share a parent that is not OliverCode's, pass `--root`:

```bash
scripts/olivercode sync-hooks --root /path/to/where/your/repos/live
scripts/olivercode health     --root /path/to/where/your/repos/live
```

Machine paths go in `olivercode.local.json` at the OliverCode root, which is gitignored. Copy `olivercode.local.example.json` and fill in:

- `privateRepos`: private repos that get the private hook variant and a hook check
- `skillsRoot`: the skill checks
- `repoRoot`: the one folder that holds every repo (default the folder that holds OliverCode). Worktrees go in `_worktrees` and backups in `_archive` under it
- `watchRoots`: the folders `olivercode place` scans for strays (default `~/Developer`, `~/Desktop`, `~/Documents`), and `allowOutside` lists checkouts allowed to stay elsewhere, such as an Obsidian vault
- `repoPaths`: a repo outside the fleet folder

`OLIVERCODE_SKILLS_ROOT` overrides the file, and an unset value means this machine has none. A layout the scripts cannot resolve degrades to WARN and skips, and a WARN is no coverage. If `sync-hooks` reports every repo as skipped, your `--root` is wrong and your fleet is fine.

Inside each product repo, `docs/RULES.md` ("Project structure") is the structure contract.

## What a fork gets

Tracked and shared: standards, templates, skills, gates, the launcher, documents and tests. The fleet registry ships as an empty example. Never tracked and created per user: `runtime/control-plane/` (machine state), `.claude-optimization/memory/` and `state/` (your agent's memory) and the `~/.claude/` symlinks. The framework works without every one of them, and `scripts/validate.sh` passing on a clean clone is the test of it.

## Restoring on a new machine

A blank machine follows this order, and the steps above cover adopting OliverCode into a machine that already has work on it.

- OliverCode comes first, because its `CLAUDE.md` holds the rules every session loads
- The fleet registry returns with its repo's clone once `olivercode.local.json` names that repo under `privateRepos` (`REGISTRY-PRIVATE-1` in `docs/DECISIONS.md`)
- The private repos, the skills folder and any repo outside the fleet folder are per machine, so name them in `olivercode.local.json` before `sync-hooks` and `conform` run

Clone OliverCode and each fleet repo side by side, copy `olivercode.local.example.json` to `olivercode.local.json` and fill in this machine's paths. Then run Step 0 to prove the clone, Step 2 for `install`, Step 6 for enforcement and Step 7 to prove a gate blocks. Steps 1, 3, 4 and 5 are done, because the rules and the registry come back with the clones. `health` must end HEALTHY, and it lists a registered repo that is not cloned here once without failing.

Four things need a person, because no script restores them:

- **The other repos.** Each fleet repo is its own clone under `<fleet-root>/`, and `scripts/olivercode discover --root <dir>` finds what is present
- **Marketplace plugins.** They install through Claude Code and never through this repo
- **Application plugins.** An editor or notes app returns its plugin settings with the clone and not the compiled code, so reinstall each plugin from its store
- **MCP server authorization.** This is interactive OAuth per server, in a Claude Code session

Verify the restore:

```bash
scripts/olivercode health            # HEALTHY, and the topology checks pass
bash scripts/validate.sh             # gates, doc consistency, references, bloat, code quality, tests
bash scripts/qa/rehearse-install.sh  # the setup walkthroughs, in disposable sandboxes
```

A restore is finished when `health` is HEALTHY, a planted secret is refused by a real commit, and a skill from each plugin is invocable as `/<plugin>:<skill>`.

## Launcher commands

`python3 scripts/olivercode --help` prints every command and its arguments, and this section holds what the help line cannot say. The launcher invokes nothing outside this repo, hardcodes no paths and derives every path from `__file__`, so it runs the same from cron, a hook or a shell. It has no global alias. If a host adds its own alias or PATH entry, verify that separately and never commit host paths.

- `bootstrap` stamps the project template into a repo per `shared/project-bootstrap-manifest.json`. `strict` files are overwritten because byte-identity is their contract, and `presence` files are created only when missing. `--dry-run` writes nothing
- `backlog-setup` brings one repo to the board baseline in `shared/kanban-baseline.json` and prints the plan unless `--apply` is given. It reuses a Project that carries the repo's name or creates one, adds the missing Status lanes and the Priority, Size, Work type and Area fields, writes `docs/backlog-config.json` with the real IDs and installs the story-reference `commit-msg` hook. Before it touches a field it saves every item's values to `scratch/backlog-backups/`, restores any value that moved and exits non-zero when the counts per option differ from that file. An option outside the baseline stays on the board and the baseline check reports it. GitHub's API cannot switch off a board's built-in workflows, so the command lists them for you to turn off on the Project's Workflows page
- `discover` is a read-only scan for git repos under the given roots. It reports each repo's agent-rules file and hook state, inventories `~/.claude` and emits a `repo-profiles.json` skeleton. It excludes this checkout and is the mechanical form of Step 1
- `install` symlinks this checkout's `CLAUDE.md`, `docs/VOICE.md` (as `~/.claude/VOICE.md`) and every skill into `~/.claude`. It merges the seven hooks listed in `docs/RULES.md` ("Execution") into `~/.claude/settings.json` without touching other keys, and sets `core.hooksPath` to `.githooks` here when unset. It never destroys anything: any other file or link at a target path moves to `<name>.pre-olivercode` (then `.2`, `.3`) and is printed, because that file is usually the owner's existing ruleset (`BACKUP-COLLISION-1` in `docs/DECISIONS.md`). A link an earlier install wrote that now dangles because its checkout moved is replaced in place. It records its links in `~/.claude/.olivercode-install.json`, and a re-install of the same checkout reports ALREADY
- `uninstall` reverses `install`. It removes each link that points into this checkout and each dangling link the install record names, restores the newest `<name>.pre-olivercode` backup once its path is free, removes only hook entries in the exact form install writes and deletes a `settings.json` left empty (a symlinked one stays). Other links, real skill folders and every other key stay, `core.hooksPath` is untouched, and a second run changes nothing
- `conform [DIR]` checks one repo, or every registered repo, against `docs/CONTRACT.md`. `--offline` skips the board and GitHub About checks, the only ones that call GitHub
- `gh-limit [clear]` shows the shared GitHub rate-limit hold and until when, and `clear` lifts it early
- `place` lists every repo, worktree and backup outside `repoRoot` with the fix for each and exits non-zero on any stray
- `clean` lists merged, clean worktrees as reclaimable and says why it keeps each other one. `--apply` removes the reclaimable ones
- `policy init [DIR]` writes `.olivercode/policy.json`, the allowed commands and paths and the triggers that ask the owner
- `checkpoint [DIR]` records a repo's commit, uncommitted changes and untracked files before an unattended run
- `restore [DIR]` returns a repo to its checkpoint and lists the files it removed
- `context [DIR]` prints the words a session loads at start and exits non-zero over the `contextWords` budget
- `maintain` checks the machine, and `--fix` repairs what cannot lose work: it re-points a dangling `~/.claude` link, prunes a worktree whose folder is gone and downloads git files that iCloud evicted. Under a `repoRoot` inside iCloud Drive, Dropbox, OneDrive or Google Drive it moves each repo's `.git` to `.git.nosync` behind a symlink that sync services skip, and it restores a link a sync service renamed. It deletes an untracked `name 2.ext` that matches `name.ext`, archives an older differing copy in `_archive/stray-copies` and leaves a newer one. It reports and logs drifted hooks, a checkout outside `repoRoot`, a doc that trails a file it names by more than 60 days and a failing `health` check, then exits 1. `--schedule` installs a daily launchd job and `--unschedule` removes it
- `learn` reads `~/.olivercode/failures.log`. When one gate and reason appear three times it prints a proposed check or memory entry with the three lines as evidence, and otherwise `Nothing due`. `--reject KEY` and `--accept KEY` stop a proposal returning
- `report [--days N]` counts how often each gate blocked a commit in the last N days
- `eval list|run|compare` replays the tasks in `tasks/` (a starting state, a prompt and a shell check) against an agent command, records pass or fail, gate blocks and cost, and compares two results files
- `job REPO -- COMMAND` runs a scheduled agent job from a checkpoint in a repo whose hooks git runs, so the commit gates apply and a block lands in the failure log
- `health` checks this machine: dependencies, entrypoint and placement drift, the hook entries in `~/.claude/settings.json`, skill links, voice copies, remote reachability and tracked-file size against GitHub's 100MB limit. It compares `VERSION` with the `upstream` remote's and prints the changelog entries a fork is missing. What each repo must match is `conform`'s job
- `voiceFile` in `olivercode.local.json` names the owner's own voice file, which `install` links as `~/.claude/VOICE.md` in place of `docs/VOICE.md`
- `update` runs `git pull`, then `install`, then `sync-hooks`
- `sync-hooks` converges pre-commit hooks and `core.hooksPath` across the fleet and the private repos
- `audit-fleet` runs the `audit` skill's structure check against OliverCode's `skills/` and, when set, the skills folder (`skillsRoot`)
- `size [DIR]` prints a repo's total lines, its `docs/SIZE-BASELINE.json` baseline and the headroom
- `guide` prints first steps, every command and every skill with its trigger phrases from `skills/INDEX.md`
- `skills` lists the skills under `skills/` with the name and description from each `SKILL.md`

`--root DIR` overrides where fleet repos are looked for, and the default is the parent of this checkout. A fork whose repos live elsewhere needs it, and without it every repo reports as "not present on this machine". Unknown arguments exit non-zero, because ignoring one reports a success that did not happen.

Verify the launcher with:

```bash
python3 scripts/olivercode --help
python3 scripts/olivercode health
python3 scripts/olivercode bogus || true
```

`runtime/control-plane/olivercode`, present only when the local control plane is installed, is a shim that delegates to this CLI and adds no commands.

GitHub keeps an option's item values only when `updateProjectV2Field` receives that option's `id`, so `backlog-setup` sends the ids and verifies the counts. Run it against a throwaway Project after any change to `scripts/lib/backlog_setup.py`.

## Troubleshooting

Fixes for the failures a user hits, listed by symptom.

### Command not found

`scripts/olivercode` has no global alias and runs only from inside this checkout. `cd` into the OliverCode repo first, then run `scripts/olivercode --help`.

### Governance failure

Run the gates against every tracked file, staged or not:

```bash
bash scripts/validate.sh --tree
```

### A product command is not here

Product runtime authority lives in the owning project repo, which the registry's `repo-profiles.json` names. OliverCode ships standards and no product implementations, so use that repo's own scripts and documents.

### The workflow push auth gate blocks a staged workflow file

The gate checks the actual credential's scopes (`gh api user -i`) and not the remote URL scheme. Run `gh auth login --scopes workflow`, or `gh auth refresh -s workflow` if you are already logged in.

### Commits are passing gates that should have blocked them

Git runs hooks only when `core.hooksPath` resolves to a directory holding an executable `pre-commit`. If that config is unset, points at a missing directory or names a non-executable file, git runs no hooks and prints nothing, so every gate is absent and every commit succeeds. A commit containing an `sk-` key goes straight through.

```bash
git config --get core.hooksPath      # expect: .githooks
scripts/olivercode conform --offline            # FAILs with the exact reason if any repo is in that state
scripts/olivercode sync-hooks        # repairs it across the fleet and the private repos
```

Use the relative `.githooks` and never an absolute path, because an absolute one breaks silently the moment the repo moves.

### Fleet hooks report drift after a gate edit

The hooks check in `scripts/olivercode conform` compares each fleet repo's live hook against `core/templates/project/pre-commit` and `core/templates/project/pre-commit-private`. Those templates are built from `core/hooks/`, so a gate change is an edit there followed by a rebuild, and every fleet repo diverges until it is re-synced:

```bash
python3 scripts/build-hooks.py
scripts/olivercode sync-hooks
```

### `validate.sh` fails with "not a git repository"

`validate.sh` runs `.githooks/pre-commit`, which calls `git diff --cached`, so it needs a real `.git`. An extracted archive or tarball without `git init` fails this way, and that is expected.

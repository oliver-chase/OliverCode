# Setup

How to take a clone or fork of OliverCode and make it govern your own repos, how to restore that setup on a blank machine, what every `olivercode` command does and what to do when something fails. The steps are written for the agent doing the work with a human approving, and the `README.md` install section comes first.

The governing rule for the whole process is to optimize and never amputate. You point existing rules at a shared home and do not delete them. Anything you cannot map to an OliverCode concept stays exactly where it is, and a rule you do not understand is a rule you keep.

You do not have to read this. Open the repo in Claude Code and say "set up OliverCode for my machine". The `olivercode-adoption` skill ships project-level, so it is available on a fresh clone, and it drives every step below and surfaces only the decisions that need you. This document is the reference it works from.

## What you are installing

| Layer | Where | Tracked | Owner |
|---|---|---|---|
| The framework | Your OliverCode fork | Yes | You |
| Your fleet's real config | A private repo's `olivercode/repo-profiles.json`, or your fork's `shared/repo-profiles.json` | Yes, in that repo | You |
| Activation | `~/.claude/CLAUDE.md` and the `~/.claude/skills/*` symlinks | No, per machine | Your machine |

Your fleet's real names and config live in one registry file, and no placeholder layer has to stay in sync with it.

## Step 0: prove the clone is sound

```bash
git clone <your-fork> OliverCode && cd OliverCode
python3 scripts/olivercode --help
bash scripts/validate.sh
scripts/olivercode health
```

Each command must exit 0 on a clean clone with no configuration. `health` notes that there is no control plane and warns about an unregistered fleet, which is correct and still reports HEALTHY. If `validate.sh` fails here, the fork is broken and your setup is fine, so stop.

One command checks all of this in a sandbox with a throwaway HOME:

```bash
bash scripts/qa/rehearse-install.sh
```

It runs the real `olivercode install` against a throwaway HOME, then walks this guide's load-bearing steps (fleet registration, `sync-hooks`, the secret probe, `health`, `update` and the backout), so the instructions below are verified by running them. It never touches your real `~/.claude`. When it passes, every failure further on is a setup problem. Run it after any change to the framework's own plumbing.

Enable CI in your fork. `.github/workflows/framework-ci.yml` ships ready to run and is paused on the origin repo (`docs/GATES.md`, "Validation", says why). Where CI is off, the local commands are the entire enforcement layer, so run `bash scripts/validate.sh` before you push.

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

`discover` reports for each repo which agent-rules file it has, whether hooks are installed and which repos are ungoverned. It then inventories `~/.claude`, separating skills linked into this checkout from skills linked elsewhere, real untracked directories and broken links, and it ends with a profile skeleton with explicit `path` values, ready to paste into the registry file the command names.

An existing setup usually surfaces three things:

- **Rules files not named `CLAUDE.md`.** `AGENTS.md`, `.cursorrules` and similar files do not auto-load in Claude Code, so they are invisible in practice however good their content. Step 4 merges them in
- **Repos with `hooksPath=unset`.** They have no gates at all, silently
- **Real directories in `~/.claude/skills/`.** They are untracked content with no backup anywhere. Usually they are vendor skills, which is fine. Anything else exists in exactly one place on one machine, so decide where it belongs before it is lost. `install` never touches these and reports how many it left alone

Record for each existing rules file what it says and which of these it is:

- **Machine-global** (applies everywhere) belongs in the OliverCode `CLAUDE.md`
- **Repo-specific** (true for one product only) stays in that repo's `CLAUDE.md`
- **Personal or business** (voice, sales, hiring) belongs in your own user-skills area and stays out of the framework (`docs/RULES.md`, "Skill placement")

Most existing setups have all three tangled in one file, and separating them is the adoption.

## Step 2: back up, then install activation

`install` backs up an existing `~/.claude/CLAUDE.md` to `CLAUDE.md.pre-olivercode` itself, so do not copy it by hand first. It does not copy `~/.claude/skills/`, because it never deletes anything there. Back that folder up yourself if you want a restore point:

```bash
cp -R ~/.claude/skills ~/.claude/skills.pre-olivercode 2>/dev/null || true

scripts/olivercode install     # symlinks CLAUDE.md, VOICE.md + skills, backing up what it replaces
scripts/olivercode health
```

`install` reports how many skills it linked and how many real directories it left untouched. `health` then checks that every symlink resolves into this checkout. Keep the backups until the whole process is done and verified.

## Step 3: merge your global rules in

Your old `~/.claude/CLAUDE.md` content does not disappear. It gets sorted:

1. Rules that are machine-global go into your fork's `CLAUDE.md`, under its existing sections
2. Rules about one repo move to that repo's own `CLAUDE.md`
3. Personal or business rules become a skill, placed per `docs/RULES.md` ("Skill placement")
4. Anything you cannot classify stays in the global file and is flagged for the human

The one hard constraint on the global file is that it loads from `~/.claude/CLAUDE.md` in sessions whose working directory is almost never OliverCode. So every path in it must resolve from anywhere. Use `$OC/...` for OliverCode's own files, resolved and checked:

```bash
OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
[ -f "$OC/docs/RULES.md" ] || echo "OliverCode not installed"
```

A bare path such as `scripts/validate.sh` means the repo the agent is currently in. That is usually what you want, because every repo has its own, but say so explicitly or the next reader assumes it means OliverCode's.

## Step 4: rewrite each repo's CLAUDE.md

For every repo, start from `core/templates/project/CLAUDE.md`. The file carries only what is specific to that repo, under a short block that says where the shared rules come from.

- Every pointer is relative to the reader's working directory. A path such as `Some/Vault/Path/OliverCode/CLAUDE.md` does not resolve from inside the repo and is dead text, so verify each pointer with `ls` before you leave it in
- Repo-specific content stays even when it makes the file longer. Duplicated framework rules come out, and repo truth stays
- If a repo has an `AGENTS.md`, `.cursorrules` or a similarly named rules file, merge it into `CLAUDE.md`, because Claude Code auto-loads only `CLAUDE.md`. Then decide the original's fate explicitly and say which you chose. If another tool still reads it (Cursor, Copilot, Codex), keep it and replace its body with a one-line pointer to `CLAUDE.md` so the two cannot drift into disagreeing. If nothing reads it, delete it in the same commit as the merge, because git is the archive and a stale second rules file is what made the content invisible in the first place

Never leave both files carrying live rules, because that duplication is what this step exists to end.

## Step 5: register your fleet

Enforcement has to know which repos it governs before it can reach them, so registration comes first.

Edit the registry's `repo-profiles.json` with your real repo names and validation commands. It is a private repo's `olivercode/` copy when `olivercode.local.json` names one under `privateRepos`, and `shared/repo-profiles.json` otherwise. `_<field>_note` keys beside a worked example document the schema in place. `scripts/olivercode discover --root <dir>` prints the path this checkout reads and emits a profile skeleton per repo with `name`, `path` and `canonicalValidationCommand`.

Confirm the fleet registered before continuing:

```bash
scripts/olivercode health     # must list your repos by name, not "no fleet registered"
```

## Step 6: install enforcement

```bash
scripts/olivercode sync-hooks     # writes .githooks/ + sets core.hooksPath in every fleet repo
scripts/olivercode health         # confirms each repo's hooks are installed and current
```

`sync-hooks` resolves your fleet from the registry file named in Step 5 and expects those repos as siblings of the OliverCode checkout. If your layout differs, see "Folder structure" below. Every repo reported as `[SKIP] not present on this machine` is one it did not govern, and the exit code does not show them, so read that list.

An adopted repo runs every gate except contract integrity, which checks things only OliverCode has. `docs/GATES.md` has the coverage table.

Hook enforcement fails open. The troubleshooting entry "Commits are passing gates that should have blocked them" below explains why and how to fix it. `scripts/olivercode health` detects it fleet-wide, so run it on a schedule as well as at setup. The Claude Code session check also reports it for the repo a session opens.

### Step 6b: stamp the project template into a repo (optional)

This is not part of the required path. `sync-hooks` already installs the gates, which is what governs a repo. `bootstrap` goes further and stamps the full project template (the quality baseline, structure contract and supporting scripts declared in `shared/project-bootstrap-manifest.json`) so a repo matches the standard on day one.

Use it for a new repo. For an existing one, look before you write:

```bash
scripts/olivercode bootstrap <repo> --dry-run    # prints NEW/OVERWRITE per file, writes nothing
scripts/olivercode bootstrap <repo>
```

The manifest gives every file a mode, and the mode determines whether your existing content is safe:

- `presence` files are created only if absent. Existing content is never touched, and the run reports it as kept
- `strict` files are overwritten, because their contract is byte-identity with the template. The hooks and the shared baseline are strict, so a hand-edited version in the target repo is replaced

Always run `--dry-run` against an existing repo first and read the OVERWRITE lines, because that list is exactly what you are agreeing to lose.

## Step 7: verify with evidence

```bash
bash scripts/validate.sh          # gates, consistency, references, tests
scripts/olivercode health         # symlinks + per-repo hook install state
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

# 3. Remove the local scheduler, if you turned it on
bash scripts/local-scheduler/uninstall.sh

# 4. The checkout itself is just a directory; delete it.
```

`uninstall` keeps everything of yours in `~/.claude` and lists any backup it could not restore, so merge those back by hand. These four steps cover everything OliverCode writes on a machine: the `~/.claude` entries `install` makes, the `.githooks/` folder and `core.hooksPath` key `sync-hooks` sets in each governed repo, and the `launchd` agent the opt-in scheduler installs. OliverCode writes no system config and no shell profile. Files `bootstrap` stamped into a repo belong to that repo once stamped, so they stay. The scheduler's state and logs stay under `~/Library/Application Support/olivercode-scheduler` until you delete that folder.

## Folder structure

The framework assumes one layout: `sync-hooks` and `health` look for fleet repos as siblings of the OliverCode checkout. Nothing else depends on where anything sits.

```
<workspace-root>/
├── OliverCode/              the fork: framework, skills, standards, gates
│   └── runtime/control-plane/  (gitignored, optional) per-machine state
├── product-repo-a/          siblings of OliverCode
├── product-repo-b/
└── product-repo-c/
```

If your repos do not share a parent at all, which is the normal case when adopting into an existing setup, give each profile an explicit `path` in the registry file named in Step 5:

```json
"acme-api": { "name": "acme-api", "path": "~/work/clients/acme/api", ... }
```

`path` accepts absolute, `~`-relative or fleet-root-relative values, and `discover` emits it for you. Without it a repo is findable only at `<fleet-root>/<name>`, which makes a tidy sibling layout the easy path and leaves it optional. If your repos share a parent that is not OliverCode's, pass `--root`:

```bash
scripts/olivercode sync-hooks --root /path/to/where/your/repos/live
scripts/olivercode health     --root /path/to/where/your/repos/live
```

Machine paths go in `olivercode.local.json` at the OliverCode root, which is gitignored. Copy `olivercode.local.example.json` and fill in:

- `privateRepos`: private repos that get the private hook variant, a hook check and a push (a `vaultRoot` set before that list existed still counts as one entry named `vault`)
- `skillsRoot`: the skill checks
- `repoPaths`: a repo outside the fleet folder
- `pushRepos`: extra `push-fleet` targets

`OLIVERCODE_SKILLS_ROOT` overrides the file. An unset value means this machine has none, and nothing guesses it from the folder layout.

A layout the scripts cannot resolve degrades to WARN and skips. It never fails wrongly and it never checks anything, so a WARN is not coverage. If `sync-hooks` reports every repo as skipped, your `--root` is wrong and your fleet is fine.

Inside each product repo, `docs/RULES.md` ("Project structure") is the structure contract. The short version:

```
<product-repo>/
├── README.md
├── CLAUDE.md                       agent rules; the only filename Claude Code auto-loads
├── .githooks/                      installed by sync-hooks, activated by core.hooksPath
├── docs/
│   ├── repo-structure-contract.md  this repo's declared paths
│   ├── backlog-config.json         names this repo's GitHub Project
│   └── BACKLOG.md                  the live board, only if the repo has no backlog-config.json
└── scripts/validate.sh             this repo's canonical validation
```

A top-level directory needs a contract reason, because that rule keeps a fleet legible to an agent that has never seen it.

## What a fork gets

Tracked and shared: standards, templates, skills, gates, the launcher, documents and tests. The fleet registry ships as an empty example, and your real one lives in a private repo. Never tracked and created per user: `runtime/control-plane/` (machine state), `.claude-optimization/memory/` and `state/` (your agent's memory) and the `~/.claude/` symlinks. The framework works without every one of them, and `scripts/validate.sh` passing on a clean clone is the test of it.

## Restoring on a new machine

A blank machine restoring an existing setup from its remotes follows this order. The steps above cover adopting OliverCode into a machine that already has work on it.

- OliverCode comes first, because its `CLAUDE.md` holds the rules every session loads
- The fleet registry lives in a private repo under `olivercode/`, so it comes back with that repo's clone once `olivercode.local.json` names the repo under `privateRepos`
- The private repos, the skills folder and any repo outside the fleet folder are per machine, so name them in `olivercode.local.json` before `sync-hooks` and `health` run

Clone OliverCode and each fleet repo side by side in one folder, then copy `olivercode.local.example.json` to `olivercode.local.json` and fill in this machine's paths. The rest follows the steps above: Step 0 proves the clone, Step 2 runs `install`, Step 6 installs enforcement and Step 7 proves a gate blocks. Steps 1, 3, 4 and 5 are already done, because the rules and the registry come back with the clones. `health` is the checkpoint and it must end HEALTHY. A registered repo that is not cloned here is listed once and is not a failure.

Four things need a person, because no script restores them:

- **The other repos.** Each fleet repo is its own clone under `<fleet-root>/`. `scripts/olivercode discover --root <dir>` finds whatever is present and cannot clone what is absent. The private repo's `olivercode/repo-profiles.json` lists what should be there
- **Marketplace plugins.** Third-party plugins install through Claude Code and never through this repo. The README's "Optional tooling" section lists the ones this framework's rules assume
- **Application plugins.** An editor or notes app that tracks plugin settings in git gets those settings back with the clone, and the compiled plugin code does not return. Reinstall each plugin from its store
- **MCP server authorization.** This is interactive OAuth per server, in a Claude Code session

Verify the restore:

```bash
scripts/olivercode health            # HEALTHY, and the five topology checks pass
bash scripts/validate.sh             # gates, doc consistency, references, bloat, code quality, tests
bash scripts/qa/rehearse-install.sh  # the setup walkthroughs, in disposable sandboxes
```

A restore is finished when `health` is HEALTHY, a planted secret is refused by a real commit, and a skill from each plugin is invocable as `/<plugin>:<skill>`.

## Launcher commands

`scripts/olivercode` is the whole launcher surface. It invokes nothing outside this repo, contains no hardcoded vault, home or container paths, and derives every path from its own location (`__file__`), so it runs identically from cron, a hook or an interactive shell. It has no global alias and runs from inside the checkout. If a host sets up its own alias or PATH entry, verify that separately and never commit host-specific paths into this repo.

- `olivercode bootstrap <repo-path> [--dry-run]` stamps the project template into a repo per `shared/project-bootstrap-manifest.json` and creates its required directories. `strict` files are overwritten, because byte-identity is their contract, and `presence` files are created only when missing, so repo-specific content is never clobbered. `--dry-run` shows the plan and writes nothing
- `olivercode backlog-setup [DIR] [--apply]` brings one repo, new or existing, to the board baseline in `shared/kanban-baseline.json`, and without `--apply` it prints the plan and changes nothing. It creates the repo's GitHub Project when the backlog config names none, adds the missing Status lanes (QA included) and the Priority, Size, Work type and Area fields, and writes `docs/backlog-config.json` with the real field and option IDs. It also installs the story-reference `commit-msg` hook and the story rule in `CLAUDE.md`, and a second run changes nothing and says so. Before it touches a field it saves every item's Status, Priority, Size and Work type to `scratch/backlog-backups/`. Afterward it restores any value that moved and checks the count per option against that file, and it exits non-zero when they differ. `--map OLD=NEW` merges an option into a baseline option, such as a pull-request lane into QA. `--title`, `--area NAME` and `--no-link` set the Project title, the Area options and whether the Project links to the repo. GitHub's API cannot switch off a board's built-in workflows, so the command lists them for you to turn off on the Project's Workflows page. The live check below proves the behavior
- `olivercode discover --root DIR [--root DIR ...]` is a read-only scan for git repos under the given roots. It reports each one's agent-rules filename and hook state, inventories `~/.claude` (skills linked here, linked elsewhere, real directories and broken links) and emits a `repo-profiles.json` skeleton with explicit `path` values. It excludes the OliverCode checkout itself, because the framework governs the fleet and is not part of it. It is the mechanical form of Step 1
- `olivercode install` symlinks this checkout's `CLAUDE.md`, its `docs/VOICE.md` (as `~/.claude/VOICE.md`, which `CLAUDE.md` imports) and every skill into `~/.claude`, creating `~/.claude/` and `~/.claude/skills/` if absent. It also merges OliverCode's three Claude Code hooks into `~/.claude/settings.json`, creating the file if absent and leaving every other key alone (`docs/RULES.md`, "Execution"). It is never destructive. A real file or any other link at a target path, including a dangling one or one into another OliverCode checkout, is moved to `<name>.pre-olivercode` (then `.2`, `.3` on later collisions) and the path is printed, because that file is usually the operator's whole existing ruleset (`BACKUP-COLLISION-1` in `docs/DECISIONS.md`). Only a link an OliverCode install wrote that now dangles because its checkout moved is replaced in place. It records the links it wrote in `~/.claude/.olivercode-install.json`, and a re-install of the same checkout reports ALREADY and makes no backup
- `olivercode uninstall` is the reverse of `install` and step 1 of "Backing out". It removes each link in `~/.claude` that points into this checkout, and each dangling one an OliverCode install wrote, which the install record names. For an install made before the record existed, two or more of install's links must dangle into the same checkout-shaped folder, so a lone link to a drive that is not mounted stays, and a link into another live checkout stays too. It removes the record itself. It moves the newest `<name>.pre-olivercode` backup back once its path is free and lists older ones. It takes out only hook entries whose command is exactly the form install writes, so an operator hook that runs a script of the same name stays. A `settings.json` left empty is deleted, since Claude Code reads that the same as no file, unless it is a symlink, in which case it stays a link and keeps its file mode. Links pointing anywhere else, real skill folders, `~/.claude/` and `skills/` themselves and every other settings key stay. It leaves `core.hooksPath` alone, since `sync-hooks` sets that, and it is idempotent
- `olivercode health [--root DIR]` runs the dependency, entrypoint and placement-drift checks, plus the Claude Code hook entries in `~/.claude/settings.json` and the topology checks: skill links, the local scheduler's install and last runs, voice copies (each installed suite's `docs/VOICE.md` must match this repo's), remote reachability and tracked-file size against GitHub's 100MB limit. Its Backlog boards section reads each registered repo's Project once, compares it with the baseline, checks the `commit-msg` hook and lists `olivercode backlog-setup <repo> --apply` as the fix for any repo that differs. It falls back to the repo's config when GitHub is unreachable. A repo, private repo or control plane that is not on this machine is noted once and not counted
- `olivercode update` runs `git pull`, then `install` (so a new skill or Claude Code hook reaches this machine), then `sync-hooks`. Run it on each device to bring it current
- `olivercode sync-hooks [--root DIR]` converges pre-commit hooks and `core.hooksPath` across the fleet and the private repos. It also runs at the end of `update`
- `olivercode audit-fleet` runs the `audit` skill's three static checks (structure, MCP patterns, description length) against OliverCode's own `skills/` and, when this machine names one, the skills folder (`skillsRoot`). It is non-interactive, writes findings to a log and never fixes anything
- `olivercode push-fleet [--dry-run]` pushes already-committed work, unattended, for OliverCode, each repo in `privateRepos` and each repo named in `pushRepos`. It never commits, and it skips and reports a repo with uncommitted changes or no upstream tracking branch. Each repo's own pre-push hook is the real safety gate
- `olivercode skills [--grep TERM]` lists OliverCode's skills under `skills/` with name and description, read from each `SKILL.md`'s frontmatter and never from a hand-maintained copy. `--grep` filters by name or description

`--root DIR` overrides where fleet repos are looked for. The default is the parent of the OliverCode checkout, which is the sibling layout. A fork whose repos live elsewhere needs it, and without it every repo silently reports as "not present on this machine". Unknown arguments are rejected with a nonzero exit, because silently ignoring one is a wrong success: `sync-hooks --root /elsewhere` once ignored the flag, synced the default fleet and reported that it had worked.

The launcher is intentionally small, and the commands above are its entire surface. Verify it with:

```bash
python3 scripts/olivercode --help
python3 scripts/olivercode health
python3 scripts/olivercode bogus || true
```

The copy at `runtime/control-plane/olivercode`, present only when the local control plane is installed, is a thin shim that delegates to this same CLI and carries no additional commands.

### Verify backlog-setup against a live Project

The unit tests use a fake GitHub, so the real API gets a manual check whenever `scripts/lib/backlog_setup.py` changes. The check runs against a throwaway Project:

1. Create a Project named `oc-setup-test-<timestamp>` under your account, add the Priority and Size fields, and add three draft items with different Status, Priority and Size values
2. In a scratch git repo whose `origin` names any repo you own, write a `docs/backlog-config.json` that names the throwaway Project, then run `olivercode backlog-setup <scratch repo> --apply` twice. The first run must finish with "The board matches", the items must keep their values (compare `gh project item-list <number> --owner <owner> --format json` before and after) and the second run must print "Nothing to change"
3. Add an option named `In Review` to Status, put an item on it, and run again with `--map 'In Review=QA'`. The item must land on QA
4. Delete the throwaway Project with `gh project delete <number> --owner <owner>`

GitHub keeps an option's item values only when `updateProjectV2Field` receives that option's `id`. An update that omits the ids creates new options and clears every item value, which is why the command sends the ids and still verifies the counts. Run the command on a real Project only after this check passes.

### Scheduled runs

`scripts/local-scheduler/` runs `olivercode audit-fleet` and `olivercode push-fleet` unattended on a Mac through `launchd`. It is opt-in, and nothing installs it automatically. It uses one real scheduler, because two independent schedulers (`launchd` plus a separate `crontab` job) once ran the same work with no lock between them.

```bash
bash scripts/local-scheduler/install.sh
```

It needs `python3` on your `PATH`, so if `python3 scripts/olivercode --help` already works, this works. One `launchd` agent fires `tick.py` every 15 minutes and once immediately on load, which also covers a Mac that just woke up. `tick.py` decides what is due by checking marker files' elapsed time, so a tick missed during sleep means the next one catches up, where plain `cron` silently skips.

- `push-fleet` runs about every three hours (the `JOBS` list in `scripts/local-scheduler/tick.py` has the exact interval). It flushes already-committed work for OliverCode and the private repos and never commits
- `audit-fleet` runs weekly. It runs the `audit` skill's three static checks against the skills folder (`skillsRoot`) and OliverCode's own, and writes findings to a log

A failed job's marker is left untouched, so it stays due and the next tick retries without waiting a full interval. To move to a new Mac, clone this repo and any private repo `push-fleet` should cover, name them in `olivercode.local.json` and run `install.sh`. No machine-specific state migrates. To retire it, run `bash scripts/local-scheduler/uninstall.sh`, which removes the agent and leaves the state and logs under `~/Library/Application Support/olivercode-scheduler/` for you to delete. To check on it:

```bash
launchctl list | grep olivercode
tail -f ~/Library/Application\ Support/olivercode-scheduler/logs/scheduler.log
python3 scripts/local-scheduler/tick.py   # force a tick right now
```

## Troubleshooting

Fixes for the failures a user hits, listed by symptom.

### Command not found

`scripts/olivercode` has no global alias and runs only from inside this checkout. `cd` into the OliverCode repo first, then run `scripts/olivercode --help`.

### Governance failure

Run the gates against every tracked file, and not only the staged ones:

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
scripts/olivercode health            # FAILs with the exact reason if any repo is in that state
scripts/olivercode sync-hooks        # repairs it across the fleet and the private repos
```

Use the relative `.githooks` and never an absolute path, because an absolute one breaks silently the moment the repo moves.

### Fleet hooks report drift after a gate edit

The placement-drift check in `scripts/olivercode health` compares each fleet repo's live hook against `core/templates/project/pre-commit` and `core/templates/project/pre-commit-private`. Those templates are built from `core/hooks/`, so a gate change is an edit there followed by a rebuild, and every fleet repo diverges until it is re-synced:

```bash
python3 scripts/build-hooks.py
scripts/olivercode sync-hooks
```

### `validate.sh` fails with "not a git repository"

`validate.sh` runs `.githooks/pre-commit`, which calls `git diff --cached`, so it needs a real `.git`. An extracted archive or tarball without `git init` fails this way, and that is expected.

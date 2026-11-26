# Setup

OliverCode gives Claude Code shared rules, skills, commit gates, and a way to run work across your repositories. This guide gets it installed, moves your existing setup over safely, and verifies that the checks are actually working.

If you prefer, open OliverCode in Claude Code and ask it to set itself up. The `olivercode-adoption` skill follows this same process.

## 1. Get OliverCode running

You need Python 3.12+, Git, GitHub CLI (`gh`), and Claude Code (`claude`), installed and signed in.

Keep your repositories outside iCloud, Dropbox, OneDrive, or Google Drive. Sync folders can interfere with Git worktrees.

```bash
mkdir -p ~/Developer/Repos
cd ~/Developer/Repos
git clone <your-fork> OliverCode
cd OliverCode

python3 scripts/olivercode --help
bash scripts/validate.sh
scripts/olivercode health
```

Start from a clean clone. If validation fails, stop and fix it before installing. You can also rehearse the installation in a temporary environment:

```bash
bash scripts/qa/rehearse-install.sh
```

## 2. See what you already have

Before OliverCode changes your Claude setup, take inventory of the rules, skills, and hooks you already use.

```bash
ls -la ~/.claude
cat ~/.claude/CLAUDE.md 2>/dev/null
ls -la ~/.claude/skills/ 2>/dev/null

scripts/olivercode discover --root ~/Developer/Repos
```

Discovery is read-only. Use one `--root` for each parent folder containing repositories. Review what it finds and decide what belongs in OliverCode and what should stay. Keep anything you can't map; don't discard rules simply because they don't fit.

Back up your existing skills before installing:

```bash
cp -R ~/.claude/skills ~/.claude/skills.pre-olivercode 2>/dev/null || true
```

## 3. Install the shared setup

```bash
scripts/olivercode install
scripts/olivercode health
```

The installer links OliverCode's shared rules and skills into Claude's configuration, merges its hook entries, and adds the `olivercode` command to your PATH. Existing skill directories are left alone. Files it needs to replace are backed up first; keep those backups until you're satisfied everything works.

Review the permissions before allowing the installer to update them:

```bash
scripts/olivercode install --show-allow
```

This lists each permission and what it allows. Approve the changes before the allow list is written.

OliverCode defaults to one Claude model session at a time, a $6 recorded-spend ceiling and eight model invocations per story. You can raise or lower the session and story limits in `olivercode.local.json`; the session cap is still bounded by the machine's CPU and memory ceiling. `drain --parallel N` can narrow a run, but cannot exceed the configured account-wide cap.

## 4. Put your rules in the right place

Use the global `CLAUDE.md` for machine-wide rules, a repo's own `CLAUDE.md` for project rules, and skills for reusable workflows.

Merge existing `AGENTS.md`, `.cursorrules`, and similar files into the appropriate `CLAUDE.md`. If another tool still needs the old file, leave it a pointer rather than maintaining duplicate rules.

Start a repo's rules from the project template:

```bash
cp core/templates/project/CLAUDE.md <repo>/CLAUDE.md
```

Trim it to that repo, check referenced paths, and verify every migrated rule made it to its new home. Leave backups until you've checked.

## 5. Set up your fleet

OliverCode keeps the list of managed repos, their paths, and validation commands in a separate fleet registry. Stories, private rules, and owner decisions belong in your private fleet repo—not in OliverCode itself.

Initialize the fleet and register the repos you want it to manage:

```bash
scripts/olivercode init-fleet
scripts/olivercode discover --root ~/Developer/Repos --register
```

Review the registry. Confirm each repo, its path, and its validation command. Remove anything you don't want managed, and fill in any missing commands. Repos outside the shared folder can be given explicit paths.

Machine-specific settings go in the git-ignored `olivercode.local.json`; the example file shows the available options. Keep private fleet data outside this checkout. Updates won't overwrite either.

## 6. Turn on the gates

Install the hooks across your repos and check that they match OliverCode's current rules:

```bash
scripts/olivercode sync-hooks
scripts/olivercode conform --offline
```

Read the output carefully. Skipped repos haven't been checked or updated; they are not covered. If every repo is skipped, the root path is probably wrong. Hook enforcement can fail open in some circumstances—see [GATES.md](GATES.md) for what the gates check and when they can fail open.

Set up GitHub authentication and the board for this checkout:

```bash
gh auth login
gh auth refresh -s project
scripts/olivercode backlog-setup --apply
```

For an existing repo, preview the bootstrap changes before applying them:

```bash
scripts/olivercode bootstrap <repo> --dry-run
scripts/olivercode bootstrap <repo>
```

Read the overwrite list. Some template files are kept in sync, some are created only if missing, and optional files are written only when you ask.

## 7. Prove the checks work

Run the checks again, then test a commit gate in a managed repo:

```bash
bash scripts/validate.sh
scripts/olivercode conform --offline
scripts/olivercode guide
cd <repo>
bash "$OC/scripts/qa/probe-secret-gate.sh"
```

The probe attempts to commit a fake secret. Git should block it. If it doesn't, the hooks aren't enforcing the gate.

You're ready when health is healthy, your repos are registered, and the secret commit is blocked.

## How work runs

OliverCode's `run`, `dispatch`, and `drain` commands start headless Claude Code sessions in isolated worktrees. Builders work on stories; OliverCode itself handles validation, landing, and updating the board.

- `dispatch N` hands off a specific story.
- `drain REPO` works through a repo's open stories in priority order.
- `drain REPO --parallel N` is accepted for compatibility, but the temporary usage-protection mode still allows only one model session at a time.
- A stopped story can resume on its existing branch, retaining its commits and uncommitted changes.
- Validation is queued and runs one at a time. Each landing rebases onto what has already landed.
- Stories that don't pass or land stay open, with the reason recorded and the claim released.

Runs share a hard one-session cap during the usage audit. The runner records Claude usage and cost when available. A story stops at $3 in recorded spend or four model invocations; these caps cannot be raised through local settings while this temporary mode is active.

Use `olivercode guide` for a quick command overview or `olivercode guide NAME` for a command, gate, guard, scheduled job, or skill. `python3 scripts/olivercode --help` lists commands and options.

## Keep your Mac awake

Long runs stop when your Mac sleeps. Turn off sleep while plugged in, or start a session with:

```bash
caffeinate -dimsu
```

## Keep OliverCode up to date

Keep the checkout clean, then update:

```bash
olivercode update
```

Updates only fast-forward. If you're working from a fork, bring upstream changes in deliberately and resolve conflicts yourself. [VERSIONING.md](VERSIONING.md) explains version tracking.

## Set up another machine

Clone OliverCode and your fleet repos, restore that machine's local settings, then repeat installation, hook setup, and verification. Rules and the registry come with the repos; paths, authentication, permissions, and plugins are machine-specific and need to be set up again.

## Troubleshooting

**Commits aren't being blocked.** Git only runs hooks when `core.hooksPath` points to a directory with an executable `pre-commit`. Check it and repair the fleet:

```bash
git config --get core.hooksPath
scripts/olivercode conform --offline
scripts/olivercode sync-hooks
```

The configured path should be the relative `.githooks`. An absolute path can silently break when a repo moves.

**Hooks drift after a gate changes.** Run `scripts/olivercode sync-hooks` to bring the managed repos back in sync.

**Validation says “not a git repository.”** `validate.sh` uses Git's staged diff, so it needs a real checkout with a `.git` directory. An extracted archive won't work until initialized as a Git repo.

**A repo is skipped.** Skipped means it wasn't covered. Check the registry paths and the `--root` you passed, then rerun the command.

For deeper command behavior and configuration, use `olivercode guide`, command `--help`, and the relevant docs. The shipped templates are in `core/templates/`.

## Remove OliverCode

```bash
scripts/olivercode uninstall
git -C <repo> config --unset core.hooksPath
```

Run the second command in each managed repo. Then remove the checkout if you no longer need it.

Uninstall removes OliverCode's changes to your Claude configuration and restores backups where possible. It doesn't delete your rules, skills, repo files, or fleet data.

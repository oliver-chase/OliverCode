# Setup

OliverCode gives Claude Code shared rules, skills, and checks for working across your repositories. This guide gets it running without replacing anything you already have.

You can also open the repo in Claude Code and ask it to set everything up. The `olivercode-adoption` skill walks through the same process.

## Before you start

You need Python 3.12+, Git, GitHub CLI (`gh`), and Claude Code (`claude`), installed and signed in.

Clone OliverCode somewhere outside iCloud, Dropbox, OneDrive, or Google Drive. Sync services can interfere with worktrees.

```bash
mkdir -p ~/Developer/Repos
cd ~/Developer/Repos
git clone <your-fork> OliverCode
cd OliverCode

python3 scripts/olivercode --help
bash scripts/validate.sh
scripts/olivercode health
```

These checks should pass on a clean clone. If validation fails, stop and fix it before continuing. You can also run `bash scripts/qa/rehearse-install.sh` to test the installation in a temporary environment.

## Check what you already have

Look at your Claude setup and the repositories you want OliverCode to manage.

```bash
ls -la ~/.claude
cat ~/.claude/CLAUDE.md 2>/dev/null
ls -la ~/.claude/skills/ 2>/dev/null

scripts/olivercode discover --root ~/Developer/Repos
```

Use one `--root` for each folder that holds your repos. Discovery is read-only. It shows existing rules, skills, and hooks so you can decide what should move and what should stay.

Keep anything you can't map to an OliverCode concept. Nothing should be discarded just because it doesn't fit.

## Install

Back up your existing skills, then install the shared rules and hooks.

```bash
cp -R ~/.claude/skills ~/.claude/skills.pre-olivercode 2>/dev/null || true
scripts/olivercode install
scripts/olivercode health
```

Install links OliverCode's shared files and skills into Claude's configuration, merges its hook entries, and sets up the command on your PATH. Existing skills are left alone; files it replaces are backed up. Keep those backups until you've verified everything.

Before it changes your permissions, run:

```bash
scripts/olivercode install --show-allow
```

Review what each permission allows and approve it before the installer writes the allow list.

## Move your rules

Put machine-wide rules in the global `CLAUDE.md`, repo-specific rules in each repo's `CLAUDE.md`, and reusable instructions in skills.

Merge existing `AGENTS.md`, `.cursorrules`, or similar files into `CLAUDE.md`. If another tool still reads the old file, leave a pointer to the new one. Don't maintain two copies of the same live rules.

Start repo rules from the template:

```bash
cp core/templates/project/CLAUDE.md <repo>/CLAUDE.md
```

Keep only rules that belong to that repo, and check that every path you reference exists.

## Register your repos

OliverCode tracks the repos it manages in a separate fleet registry. Your stories, private rules, and owner decisions belong in that private fleet repo—not in OliverCode itself.

Set up the fleet and register the repositories you want managed:

```bash
scripts/olivercode init-fleet
scripts/olivercode discover --root ~/Developer/Repos --register
```

Review the registry. Confirm each repo, its path, and its validation command. Remove anything you don't want managed and fill in any missing commands.

## Enable the checks

Install the hooks and check your repos:

```bash
scripts/olivercode sync-hooks
scripts/olivercode conform --offline
```

Read the output. Anything skipped hasn't been checked or updated. Hook enforcement can fail open in some circumstances; `docs/GATES.md` explains when and what to watch for.

Set up GitHub authentication and the board for this OliverCode checkout:

```bash
gh auth login
gh auth refresh -s project
scripts/olivercode backlog-setup --apply
```

If you're bringing OliverCode into an existing repo, preview the template before applying it:

```bash
scripts/olivercode bootstrap <repo> --dry-run
scripts/olivercode bootstrap <repo>
```

Read the overwrite list before you approve it. Some template files are kept in sync with OliverCode, others are only created when missing, and optional files are written only when you ask.

## Verify it

Run the checks again, then test a commit gate in one of your managed repos:

```bash
bash scripts/validate.sh
scripts/olivercode conform --offline
scripts/olivercode guide
cd <repo>
bash "$OC/scripts/qa/probe-secret-gate.sh"
```

The probe tries to commit a fake secret. Git must block it. If it doesn't, the hooks aren't enforcing the gate.

You're ready when health passes, your repos are registered, and the secret commit is blocked.

## Keep the machine awake

Runs stop when your Mac sleeps. Turn off sleep while plugged in, or run `caffeinate -dimsu` before leaving a long session.

## Keep it current

Keep a clean checkout and update with:

```bash
olivercode update
```

Updates only fast-forward. If you work from a fork, bring upstream changes in deliberately and resolve conflicts yourself. See `docs/VERSIONING.md` for how releases are tracked.

Machine-specific settings belong in the git-ignored `olivercode.local.json`; private fleet data lives outside this repo. Updates won't overwrite either.

## Set up another machine

Clone OliverCode and your fleet repos, restore your local settings, and run the install, hook, and verification steps again. Rules and registry come back with the repos; machine paths, authentication, permissions, and plugins need to be set up on the new machine.

## More detail

The deeper configuration options, command behavior, runner internals, and troubleshooting notes are kept in [REFERENCE.md](REFERENCE.md) so this setup guide stays focused.

## Remove it

```bash
scripts/olivercode uninstall
git -C <repo> config --unset core.hooksPath
```

Run the second command in each managed repo to remove its hook setting. Then delete the OliverCode checkout if you no longer need it.

Uninstall removes the changes OliverCode made to your Claude configuration and restores backups where possible. It doesn't delete your rules, skills, repo files, or fleet data.

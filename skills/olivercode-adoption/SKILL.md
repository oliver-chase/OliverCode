---
name: olivercode-adoption
description: "Use when adopting OliverCode into a machine the user forked or cloned. Triggers: 'set up OliverCode', 'onboard my repos', 'point my CLAUDE.md files at OliverCode'. Also use when a fresh OliverCode checkout needs to get running. Walks the whole install: discover what exists, classify it, install activation, list the repos, install enforcement, prove the gates block. Works for a clean machine or a messy existing setup. Optimizes and points. Never amputates."
---

# OliverCode adoption

Drive the whole setup so the user does not have to read the documentation first. You read it.
They answer questions. `$OC/docs/SETUP.md` is the reference contract — consult it when you
need detail, but do not make the user read it.

## The rule that governs everything here

**Optimize, do not amputate.** You are pointing existing rules at a shared home and keeping
them. A rule you cannot classify is a rule you keep and flag. Never delete a user's config
because it looks redundant — redundancy is their call.

`install` backs up what it replaces. Keep each backup until the user confirms the result.

## Run this before anything else

```bash
OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
[ -f "$OC/docs/RULES.md" ] || OC="$(git -C "$(dirname "$(readlink -f ~/.claude/skills/olivercode-adoption/SKILL.md 2>/dev/null)" 2>/dev/null)" rev-parse --show-toplevel 2>/dev/null)"
[ -f "$OC/docs/RULES.md" ] || echo "Cannot find the OliverCode checkout. Ask the user where it is and set OC to that folder."
bash "$OC/scripts/qa/rehearse-install.sh"
```

If it fails, stop and report the fork as broken. Everything below assumes a sound checkout.

After install, point the user to "How work runs" in README.md and do not restate it. Then run `olivercode guide` and show the user its output, which says in plain sentences what each command, gate, job and skill does.

## The two decisions only a human can make

Bring the user exactly these two, each with your recommendation and its evidence. Never decide one silently, and keep the full inventory out of the question.

**1. For each existing rules file: global, repo-specific, or personal?**
The whole adoption. Most setups tangle all three in one file.
- *machine-global* (applies everywhere) → the fork's `CLAUDE.md`
- *repo-specific* (true of one product only) → that repo's `CLAUDE.md`
- *personal/business* (voice, GTM, hiring) → their own user-skills area, outside the framework
- *cannot classify* → leave it exactly where it is and say so
Present as a table with your proposed bucket per item. Get agreement before moving anything.

**2. Which repos are live?**
`discover` lists what exists. Only the user knows which repos are live, which they retired, and
which they do not want governed. Do not name a repo they did not confirm.

## What you discover and the user confirms

- **Each repo's validation command.** Read the repo: `scripts/validate.sh`, a `validate` or `check` script in `package.json`, or the command its `CLAUDE.md` names. Propose what you find, and ask only when you find none or several
- **A hook variant.** The default is none. Propose `hookVariant` in a repo's profile only when the repo already runs its own governance path or a gate whose checker lives only there, and show the file that proves it

## Procedure

Follow `docs/SETUP.md` Steps 0 to 8 in order, from the OliverCode checkout. It holds every command. At each step, an agent also does this:

- **Step 1, inventory.** Pass every root the user's code lives under to `discover`. Then tell the user two things they rarely know. A rules file named `AGENTS.md` or `.cursorrules` never auto-loads in Claude Code. A real directory in `~/.claude/skills/` has no backup anywhere. Any repo under `~/Documents`, `~/Desktop` or a cloud-sync folder moves to `~/Developer/Repos` by a fresh clone plus its untracked files, because sync services evict working files when the disk fills. Ask the user to confirm each move before you make it, and leave the original in place until they confirm the new clone Install nothing unasked
- **Step 2, install.** Run `olivercode install --show-allow` first and show the user the proposed allow rules with the one line each says it permits. Ask once: "Add these rules to your allow list?" On a yes, install writes them, and on a no, run install and tell the user that `olivercode health` will fail until they are added. Run it only after the user sees decision 1, because their existing `~/.claude/CLAUDE.md` is often their whole ruleset. `install` makes its own backup, so never copy one first
- **Step 3, merge rules.** Every path added to the fork's `CLAUDE.md` must resolve from any directory, so write OliverCode's own files as `$OC/...`
- **Step 4, repo `CLAUDE.md` files.** Run `ls` on every path you leave in the file, because an agent silently proceeds past a pointer that does not resolve. Never invent repo content: when a file has none left, say so and ask
- **Step 5, find the repos.** Run `olivercode discover --root DIR`, name each private repo in `privateRepos`, and note each repo's confirmed validation command
- **Step 6, enforcement.** Tell the user plainly when hook enforcement fails open (`docs/GATES.md`), and point at `docs/SETUP.md` ("Troubleshooting")
- **Step 6c, board sync.** A new board needs no web toggles. Filing a story adds its card, and closing it sets Status to Complete. Run `olivercode board sync --schedule` so the sweep keeps every board in step with its issues. On Linux it prints the crontab line to add and exits 1, because launchd needs macOS
- **Step 7, proof.** Quote the probe's actual output. A commit that succeeds means the hooks are not installed
- **Step 3b, sleep.** Apply the sleep line `olivercode health` prints, because a Mac that sleeps stops every session while the owner is away. Name the System Settings path or the `caffeinate -dimsu` command it gives
- **Step 8, reconcile.** Ask before deleting any backup

## Output

Report what moved (from where, to where, verified at the destination), what stayed and why, what you could not classify with the question they need to answer, the quoted enforcement probe, and where the backups are.

## Closing lines

As the last step, run `olivercode guide status` and show the user its output. It gives the steps to follow a run from a terminal, which cost no model turn, so the user never has to ask a thread for status.

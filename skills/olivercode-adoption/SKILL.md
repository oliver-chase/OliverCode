---
name: olivercode-adoption
description: "Use when adopting OliverCode into a machine the user forked or cloned. Triggers: 'set up OliverCode', 'Set up OliverCode City', 'Skip OliverCode City', 'onboard my repos', 'point my CLAUDE.md files at OliverCode'. Also use when a fresh OliverCode checkout needs to get running. Walks the whole install: discover what exists, classify it, install activation, register the fleet, install enforcement, prove the gates block. Works for a clean machine or a messy existing setup. Optimizes and points, and keeps what it cannot classify."
---

# OliverCode adoption

Drive the whole setup so the user does not have to read the documentation first. You read it. They answer questions, in their terms: say projects, folders and what a change does, never repo, fleet, registry or root, and do the navigation yourself, so the owner is never asked for a path or to run `cd`. `$OC/docs/SETUP.md` is the reference contract, so consult it when you need detail, but do not make the user read it.

## The rule that governs everything here

**Optimize and keep the owner's files.** You point existing rules at a shared home and keep them. A rule you cannot classify stays where it is and gets flagged. Never delete a user's config because it looks redundant: redundancy is their call. The shipped framework is the baseline and is never curated: use a setting or a skill override for a different behavior, and propose a core change only when neither can.

`install` backs up what it replaces. Keep each backup until the user confirms the result.

## Run this before anything else

```bash
OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
[ -f "$OC/docs/RULES.md" ] || OC="$(git -C "$(dirname "$(readlink -f ~/.claude/skills/olivercode-adoption/SKILL.md 2>/dev/null)" 2>/dev/null)" rev-parse --show-toplevel 2>/dev/null)"
[ -f "$OC/docs/RULES.md" ] || { echo "Cannot find the OliverCode folder. Ask the user in plain words where they saved or downloaded it, confirm the folder, then set OC to it."; exit 1; }
bash "$OC/scripts/qa/rehearse-install.sh"
```

Run it from inside the OliverCode checkout. If it fails, stop and report the fork as broken. Everything below assumes a sound checkout.

After install, point the user to "How work runs" in README.md and do not restate it. Then run `olivercode guide` and show the user its output, which says in plain sentences what each command, gate, job and skill does. Then ask "Want a walkthrough of how it all works?" and start "The walkthrough" below on a yes.

## The two decisions only a human can make

Bring the user exactly these two, each with your recommendation and its evidence. Never decide one silently, and keep the full inventory out of the question.

**1. For each existing rules file: global, repo-specific, or personal?**
The whole adoption. Most setups tangle all three in one file.
- *machine-global* (applies everywhere) → the fork's `CLAUDE.md`
- *repo-specific* (true of one product only) → that repo's `CLAUDE.md`
- *personal/business* (voice, GTM, hiring) → their own user-skills area, outside the framework
- *cannot classify* → leave it exactly where it is and say so
Present as a table with your proposed bucket per item. Get agreement before moving anything.

**2. Which repos are in the fleet?**
`discover` lists what exists. Only the user knows which repos are live, which they retired, and which they do not want governed. Do not register a repo they did not confirm.

## What you discover and the user confirms

- **Each repo's validation command.** Read the repo: `scripts/validate.sh`, a `validate` or `check` script in `package.json`, or the command its `CLAUDE.md` names. Propose what you find, and ask only when you find none or several
- **A hook variant.** The default is none. Propose `hookVariant` in a repo's profile only when the repo already runs its own governance path or a gate whose checker lives only there, and show the file that proves it

## Procedure

Follow `docs/SETUP.md` Steps 0 to 8 in order, from the OliverCode checkout. It holds every command. At each step, an agent also does this:

- **Step 1, inventory.** Find the folders holding the user's projects yourself: try `~/Developer`, `~/Projects`, `~/Documents`, `~/Desktop` and the folders recent Claude sessions used, confirm the list by asking where they keep what they have built or worked on with Claude, run `discover` on each, and show the projects by name with a recommendation each. Then tell the user two things they rarely know. A rules file named `AGENTS.md` or `.cursorrules` never auto-loads in Claude Code. A real directory in `~/.claude/skills/` has no backup anywhere. A repo under `~/Documents`, `~/Desktop` or a cloud-sync folder can move to `~/Developer/Repos` by a fresh clone plus its untracked files, because sync services evict working files when the disk fills. Offer that move for each such repo and let the user keep it where it is. Make a move only on the user's yes, and leave the original in place until they confirm the new clone. Install nothing unasked
- **Step 2, install.** Run `olivercode install --show-allow` first and show the user the proposed allow rules with the one line each says it permits. Ask once: "Add these rules to your allow list?" On a yes, install writes them, and on a no, run install and tell the user that `olivercode health` will fail until they are added. Run it only after the user sees decision 1, because their existing `~/.claude/CLAUDE.md` is often their whole ruleset. `install` makes its own backup, so never copy one first
- **Step 3, merge rules.** Every path added to the fork's `CLAUDE.md` must resolve from any directory, so write OliverCode's own files as `$OC/...`
- **Step 4, repo `CLAUDE.md` files.** Run `ls` on every path you leave in the file, because an agent silently proceeds past a pointer that does not resolve. Never invent repo content: when a file has none left, say so and ask
- **Step 5, register.** Run `olivercode init-fleet` first and tell the user the new private repo it reports, then add each repo's confirmed validation command
- **Step 6, enforcement.** Tell the user plainly when hook enforcement fails open (`docs/GATES.md`), and point at `docs/SETUP.md` ("Troubleshooting")
- **Step 6c, board sync.** A new board needs no web toggles. Filing a story adds its card, and closing it sets Status to Complete. Run `olivercode board sync --schedule` so the sweep keeps every board in step with its issues. On Linux it prints the crontab line to add and exits 1, because launchd needs macOS
- **Step 7, proof.** Quote the probe's actual output. A commit that succeeds means the hooks are not installed
- **Keep the machine awake** (`docs/SETUP.md`, "Keep the machine awake"). Apply the sleep line `olivercode health` prints, because a Mac that sleeps stops every session while the owner is away. Name the System Settings path or the `caffeinate -dimsu` command it gives
- **Step 8, reconcile.** Ask before deleting any backup

## Output

Report what moved (from where, to where, verified at the destination), what stayed and why, what you could not classify with the question they need to answer, the quoted enforcement probe, and where the backups are.

## The walkthrough

When the user asks to be walked through OliverCode, or after adoption when they say yes to "Want a walkthrough of how it all works?", teach it one part at a time. Run `olivercode guide NAME` for a part before you explain it, so your words match the checkout. Keep each part to a few sentences in plain language, and stop after each one with "Shall I continue to <next part>?" Never explain two parts in one turn.

For every automation, say three things in this order:
1. **What you do.** The one thing the user says or runs, or "nothing" when it runs alone
2. **What the harness does.** What runs, when it starts, and whether it spends a model turn
3. **How to check it is running.** The command whose output proves it, and what that output looks like when the part is healthy

Keep a list of the parts covered as you go. These are all the parts, in teaching order:

1. **Stories and the runner.** You say what you want and it becomes a story on the board. `olivercode dispatch N` or `olivercode drain REPO` builds it in a fresh session in its own worktree, then validates, lands and closes it. Check with `olivercode status`
2. **City and the phone.** You open the pinned City artifact. `olivercode status publish` refreshes it. Check that it opens on the phone
3. **Commit gates.** The hook blocks secrets, personal data, owner identifiers and version files on every commit. You change nothing. Check with `olivercode conform`, and read `docs/GATES.md` for the list
4. **Commit-message gate.** It requires a story reference and a test with code. Check a draft with `olivercode commit-check`
5. **Commit guard.** It refuses `--no-verify` and hook overrides inside Claude Code
6. **Validation queue.** `bash scripts/validate.sh` takes a turn in a shared queue so validations never pile up. Check with `olivercode queue`
7. **Board sweep job** (`olivercode board sync --schedule`). It moves closed stories to Complete and adds cards for open ones
8. **Fleet sync job** (`olivercode fleet-sync --schedule`). It brings each repo level with its remote
9. **Maintain job** (`olivercode maintain --schedule`). It repairs what is safe to repair on the machine
10. **GitHub limit job** (`olivercode gh-limit --schedule`). It lifts the shared rate-limit hold when GitHub has room
11. **Version cut job** (`olivercode version-cut --schedule`). It cuts a version from what landed on main
12. **Framework CI workflow** (`.github/workflows/framework-ci.yml`). It runs health, validation and the install rehearsal on push and pull request, and is paused while GitHub Actions billing is blocked
13. **Skills.** Say the phrase and the skill loads: `audit`, `backlog`, `diagnosing-bugs`, `plan` and `skill-creation`. The `audit` skill runs only when the user names it
14. **Owner steps and decisions.** `olivercode owner` keeps the steps only the user can take, `olivercode decisions` keeps their decisions in their words

The scheduled jobs start no model. Check any of them with `launchctl list | grep olivercode` on a Mac, and expect one line per installed job.

When the user asks what is left, list every part above that you have not yet covered, each with its one-line purpose, and offer the next one. Check the list against `olivercode guide` first, so a command, gate, job or skill added since this file was written is named too. When every part is covered, say so and point the user to `olivercode guide` for anything later.

## City on the desktop and the phone

Install prints the City step. In the Claude desktop app, do it. In a terminal with no desktop app, install has printed the local page path and `olivercode status publish`, so say nothing more. When the user says to skip City, set `cityDeclined` in `olivercode.local.json` to true and stop: health, status and the guide then stay quiet about City.

1. Read `cityArtifact` in `olivercode.local.json`. When it holds a URL, read that URL with the Artifact tool: if it opens, reuse it, make no second artifact and go to step 3, and if it cannot be read, treat City as missing.
2. Publish `~/.olivercode/status.html` with the Artifact tool as the artifact titled OliverCode City with `pin` set, save the URL it returns as `cityArtifact`, read that URL back and open it. Say "City set up" only after the read succeeds, and "pinned" only when the pin call succeeded. When publishing or the read fails, say "City incomplete", name what is missing and the one action that finishes it, and go on: install has succeeded and the local page works.
3. Walk the user through the phone steps from `olivercode guide`, naming each once: install the Claude app, sign in to the same account, open the pinned City artifact, and turn on Remote Control for desktop sessions. Ask "Turn Remote Control on for every desktop session?" and set the default only on a yes. Remote Control is a setting the user approves in the desktop app.
4. Ask the user to confirm City opened on the phone, and set `cityOnPhone` in `olivercode.local.json` to true on a yes, or false on a no.

## Closing lines

As the last step, tell the user how to begin: open the project in Claude and say the outcome in their own words, with no command to run. Then run `olivercode guide status` and show its output, the steps to follow a run from a terminal at no model cost.

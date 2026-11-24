---
name: olivercode-adoption
description: "Use when adopting OliverCode into a machine the user forked or cloned. Triggers: 'set up OliverCode', 'onboard my repos', 'point my CLAUDE.md files at OliverCode'. Also use when a fresh OliverCode checkout needs to get running. Walks the whole install: discover what exists, classify it, install activation, register the fleet, install enforcement, prove the gates block. Works for a clean machine or a messy existing setup. Optimizes and points, and keeps what it cannot classify."
---

# OliverCode adoption

Drive the whole setup so the user does not have to read the documentation first. You read it. They answer questions. `$OC/docs/SETUP.md` is the reference contract, so consult it when you need detail, but do not make the user read it.

## The rule that governs everything here

**Optimize and keep.** You point existing rules at a shared home and keep them. A rule you cannot classify stays where it is and gets flagged. Never delete a user's config because it looks redundant: redundancy is their call.

`install` backs up what it replaces. Keep each backup until the user confirms the result.

## Run this before anything else

```bash
OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
[ -f "$OC/docs/RULES.md" ] || OC="$(git -C "$(dirname "$(readlink -f ~/.claude/skills/olivercode-adoption/SKILL.md 2>/dev/null)" 2>/dev/null)" rev-parse --show-toplevel 2>/dev/null)"
[ -f "$OC/docs/RULES.md" ] || { echo "Cannot find the OliverCode checkout. Ask the user where it is and set OC to that folder."; exit 1; }
bash "$OC/scripts/qa/rehearse-install.sh"
```

Run it from inside the OliverCode checkout. If it fails, stop and report the fork as broken. Everything below assumes a sound checkout.

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

**2. Which repos are in the fleet?**
`discover` lists what exists. Only the user knows which repos are live, which they retired, and which they do not want governed. Do not register a repo they did not confirm.

## What you discover and the user confirms

- **Each repo's validation command.** Read the repo: `scripts/validate.sh`, a `validate` or `check` script in `package.json`, or the command its `CLAUDE.md` names. Propose what you find, and ask only when you find none or several
- **A hook variant.** The default is none. Propose `hookVariant` in a repo's profile only when the repo already runs its own governance path or a gate whose checker lives only there, and show the file that proves it

## Procedure

Follow `docs/SETUP.md` Steps 0 to 8 in order, from the OliverCode checkout. It holds every command. At each step, an agent also does this:

- **Step 1, inventory.** Pass every root the user's code lives under to `discover`. Then tell the user two things they rarely know. A rules file named `AGENTS.md` or `.cursorrules` never auto-loads in Claude Code. A real directory in `~/.claude/skills/` has no backup anywhere. A repo under `~/Documents`, `~/Desktop` or a cloud-sync folder can move to `~/Developer/Repos` by a fresh clone plus its untracked files, because sync services evict working files when the disk fills. Offer that move for each such repo and let the user keep it where it is. Make a move only on the user's yes, and leave the original in place until they confirm the new clone. Install nothing unasked
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

## City on the desktop and the phone

Install prints the City step. In the Claude desktop app, do it. In a terminal with no desktop app, install has printed the local page path and `olivercode status publish`, so say nothing more.

1. Read `cityArtifact` in `olivercode.local.json`. When it holds a URL, reuse it, make no second artifact, and go to step 3.
2. Publish `~/.olivercode/status.html` with the Artifact tool as the artifact titled OliverCode City, set `cityArtifact` in `olivercode.local.json` to its URL, pin it in the sidebar and open it.
3. Walk the user through the phone steps from `olivercode guide`, naming each once: install the Claude app, sign in to the same account, open the pinned City artifact, and turn on Remote Control for desktop sessions. Ask "Turn Remote Control on for every desktop session?" and set the default only on a yes. Remote Control is a setting the user approves in the desktop app.
4. Ask the user to confirm City opened on the phone, and set `cityOnPhone` in `olivercode.local.json` to true on a yes, or false on a no.

## Closing lines

As the last step, run `olivercode guide status` and show the user its output. It gives the steps to follow a run from a terminal, which cost no model turn, so the user never has to ask a thread for status.

---
name: olivercode-adoption
description: "Use when adopting OliverCode into a machine the user forked or cloned. Triggers: 'set this up', 'onboard my repos', 'point my CLAUDE.md files at OliverCode'. Also use when a fresh OliverCode checkout needs to get running. Walks the whole install: discover what exists, classify it, install activation, register the fleet, install enforcement, prove the gates block. Works for a clean machine or a messy existing setup. Optimizes and points. Never amputates."
---

# OliverCode adoption

Drive the whole setup so the user does not have to read the documentation first. You read it.
They answer questions. `$OC/docs/SETUP.md` is the reference contract — consult it when you
need detail, but do not make the user read it.

## The rule that governs everything here

**Optimize, do not amputate.** You are pointing existing rules at a shared home and keeping
them. A rule you cannot classify is a rule you keep and flag. Never delete a user's config
because it looks redundant — redundancy is their call.

Back up before the first mutation. Do not delete a backup until the user confirms the result.

## Run this before anything else

```bash
bash "$OC/scripts/qa/rehearse-install.sh"
```

If it fails, stop and report that the fork is broken and their machine is fine. Everything below assumes
a sound checkout.

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
`discover` lists what exists. Only the user knows which repos are live, which they retired, and
which they do not want governed. Do not register a repo they did not confirm.

## What you discover and the user confirms

- **Each repo's validation command.** Read the repo: `scripts/validate.sh`, a `validate` or `check` script in `package.json`, or the command its `CLAUDE.md` names. Propose what you find, and ask only when you find none or several
- **A hook variant.** The default is none. Propose `hookVariant` in a repo's profile only when the repo already runs its own governance path or a gate whose checker lives only there, and show the file that proves it

## Procedure

Follow `docs/SETUP.md` Steps 0 to 8 in order, from the OliverCode checkout. It holds every command. At each step, an agent also does this:

- **Step 1, inventory.** Pass every root the user's code lives under to `discover`. Then tell the user two things they rarely know. A rules file named `AGENTS.md` or `.cursorrules` never auto-loads in Claude Code. A real directory in `~/.claude/skills/` has no backup anywhere. Install nothing unasked
- **Step 2, install.** Run it only after the user sees decision 1, because their existing `~/.claude/CLAUDE.md` is often their whole ruleset. `install` makes its own backup, so never copy one first
- **Step 3, merge rules.** Every path added to the fork's `CLAUDE.md` must resolve from any directory, so write OliverCode's own files as `$OC/...`
- **Step 4, repo `CLAUDE.md` files.** Run `ls` on every path you leave in the file, because an agent silently proceeds past a pointer that does not resolve. Never invent repo content: when a file has none left, say so and ask
- **Step 5, register.** Add each repo's confirmed validation command
- **Step 6, enforcement.** Tell the user plainly that hook enforcement fails open, and point at `docs/SETUP.md` ("Troubleshooting")
- **Step 7, proof.** Quote the probe's actual output. A commit that succeeds means the hooks are not installed
- **Step 8, reconcile.** Ask before deleting any backup

## Output

- **Moved:** each rule, from where, to where, verified present at the destination
- **Kept in place:** what stayed and why
- **Ambiguous:** what you could not classify, with the question they need to answer
- **Enforcement:** the probe result, quoted
- **Backups:** where they are, and that they are still there

## Known traps

`docs/SETUP.md` holds them: the `$OC` guard in Step 3, the sibling layout and the `path` field in "Folder structure", a WARN that is not coverage, and "Troubleshooting".

---
name: olivercode-adoption
description: "Use when adopting OliverCode into a machine the user forked or cloned. Triggers: 'set this up', 'onboard my repos', 'point my CLAUDE.md files at OliverCode', 'audit my Claude config'. Also use when a fresh OliverCode checkout needs to get running. Walks the whole install: discover what exists, classify it, install activation, register the fleet, install enforcement, prove the gates block. Works for a clean machine or a messy existing setup. Optimizes and points. Never amputates."
---

# OliverCode adoption

Drive the whole setup so the user does not have to read the documentation first. You read it.
They answer questions. `$OC/docs/ADOPTING.md` is the reference contract — consult it when you
need detail, but do not make the user read it.

## The rule that governs everything here

**Optimize, do not amputate.** You are pointing existing rules at a shared home, not deleting
them. A rule you cannot classify is a rule you keep and flag. Never delete a user's config
because it looks redundant — redundancy is their call.

Back up before the first mutation. Do not delete a backup until the user confirms the result.

## Run this before anything else

```bash
bash scripts/qa/check-fork-usable.sh
```

If it fails, stop and report: the fork is broken, not their machine. Everything below assumes
a sound checkout.

## The four decisions only a human can make

Everything else is mechanical. Bring the user exactly these four, each with your recommendation and
its evidence. Never decide one silently, and keep the full inventory out of the question.

**1. For each existing rules file: global, repo-specific, or personal?**
The whole adoption. Most setups tangle all three in one file.
- *machine-global* (applies everywhere) → the fork's `CLAUDE.md`
- *repo-specific* (true of one product only) → that repo's `CLAUDE.md`
- *personal/business* (voice, GTM, hiring) → their own user-skills area, NOT the framework
- *cannot classify* → leave it exactly where it is and say so
Present as a table with your proposed bucket per item. Get agreement before moving anything.

**2. Which repos are in the fleet?**
`discover` lists what exists. Only the user knows which repos are live, which they retired, and
which they do not want governed. Do not register a repo they did not confirm.

**3. Any repo that genuinely needs a different hook?**
A repo can have a real reason to diverge, such as its own governance path or a gate whose checker
lives only there. Set `hookVariant` in its profile for that repo. Ask before assuming either way.

**4. What is each repo's canonical validation command?**
Only they know. `npm run build`, `pytest`, a repo script. This lands in the profile.

## Procedure

Follow `docs/ADOPTING.md` Steps 0 to 8 in order, from the OliverCode checkout. It holds every command. At each step, an agent also does this:

- **Step 1, inventory.** Pass every root the user's code lives under to `discover`. Then tell the user two things they rarely know. A rules file named `AGENTS.md` or `.cursorrules` never auto-loads in Claude Code. A real directory in `~/.claude/skills/` has no backup anywhere. Mention `docs/EXTERNAL-TOOLING.md` once as optional, and install nothing unasked
- **Step 2, install.** Run it only after the user sees decision 1, because their existing `~/.claude/CLAUDE.md` is often their whole ruleset. `install` makes its own backup, so never copy one first
- **Step 3, merge rules.** Every path added to the fork's `CLAUDE.md` must resolve from any directory, so write OliverCode's own files as `$OC/...`
- **Step 4, repo `CLAUDE.md` files.** Run `ls` on every path you leave in the file, because an agent silently proceeds past a pointer that does not resolve. Never invent repo content: when a file has none left, say so and ask
- **Step 5, register.** Add each repo's validation command (decision 4)
- **Step 6, enforcement.** Tell the user plainly that hook enforcement fails open, and point at `docs/TROUBLESHOOTING.md`
- **Step 7, proof.** Quote the probe's actual output. A commit that succeeds means the hooks are not installed
- **Step 8, reconcile.** Ask before deleting any backup

## Output

- **Moved:** each rule, from where, to where, verified present at the destination.
- **Kept in place:** what stayed and why.
- **Ambiguous:** what you could not classify, with the question they need to answer.
- **Enforcement:** the probe result, quoted.
- **Backups:** where they are, and that they are still there.

## Known traps

- A repo `CLAUDE.md` pointing at a workspace-root-relative path. Reads fine, resolves to
  nothing from inside the repo.
- `~/.claude/skills/` absent on a fresh machine — `install` handles it. A bare `ln -s` does not.
- An uninstalled symlink makes `dirname "$(readlink ~/.claude/CLAUDE.md)"` return `.`, silently
  resolving to whatever repo the agent is standing in. Always guard the resolution.
- A layout the scripts cannot resolve degrades to WARN and skips. **WARN is not coverage.**
- Registering a repo by name alone when it is not a sibling — it will never be found. Use `path`.

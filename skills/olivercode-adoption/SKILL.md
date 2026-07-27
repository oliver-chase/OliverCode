---
name: olivercode-adoption
description: "Use when adopting OliverCode into an existing setup — the user forked it, says 'set this up for my repos', 'point my CLAUDE.md files at OliverCode', 'audit my Claude config', or 'onboard my fleet'. Walks the non-destructive audit: inventory, classify, merge global rules, rewrite per-repo CLAUDE.md files, install enforcement, verify with a real block-probe. Optimizes and points; never amputates."
---

# OliverCode Adoption

Contract: `$OC/docs/ADOPTING.md`. Read it first — this skill is the execution procedure for
that document, not a second copy of it.

## The rule that governs every step

**Optimize, do not amputate.** You are pointing existing rules at a shared home, not deleting
them. A rule you cannot classify is a rule you keep and flag. Never delete a user's config
because it looks redundant — redundancy is the user's call, not yours.

Corollary: back up before the first mutation, and do not remove the backup until the user
confirms the result.

## Non-negotiables

1. **Inventory before mutation.** Write what exists to a scratch file first. You will be asked
   to prove nothing was lost, and memory is not proof.
2. **One gate per step.** Steps 2, 4, 5 and 8 change the user's machine or repos. Show the
   diff and get approval before each. Never batch them.
3. **Verify every pointer with `ls` before leaving it in a file.** A path that does not
   resolve from the reader's working directory is dead text, and dead text in a rules file is
   worse than no text — an agent tries to follow it and silently proceeds when it 404s.
4. **Prove enforcement, don't assume it.** Finish with the secret-probe in Step 7 of
   ADOPTING.md. Hooks fail open: unset or broken `core.hooksPath` means git runs nothing and
   says nothing.
5. **Never invent repo content.** If a repo's `CLAUDE.md` ends up with no repo-specific
   content, say so and ask what belongs there. Do not fabricate architecture claims.

## Procedure

Follow `$OC/docs/ADOPTING.md` steps 0-8 in order. Per step, what this skill adds:

### Step 0 — prove the clone
If `bash scripts/validate.sh` fails on the fresh clone, stop and report. That is a fork bug,
not a user setup problem, and continuing will bury it.

### Step 1 — inventory
Classify every existing rule into exactly one bucket: machine-global, repo-specific,
personal/business, or unclassifiable. Present the classification as a table and get agreement
BEFORE moving anything. Most setups tangle all three in one file; the separation is the whole
job, and getting it wrong silently relocates the user's rules.

### Step 2 — back up, then install activation
Back up `~/.claude/CLAUDE.md` and `~/.claude/skills/` first. If a `~/.claude/CLAUDE.md`
already exists, do NOT overwrite it before its content has been classified in Step 1 and
merged in Step 3 — that file is often the user's entire accumulated ruleset.

### Step 3 — merge global rules
Additive into the fork's `CLAUDE.md`. The one hard constraint: that file loads in sessions
whose cwd is almost never OliverCode, so every path in it must resolve from anywhere. Use the
guarded `$OC` resolution from ADOPTING.md; a bare path means the user's current repo, and if
you mean that, write that you mean it.

### Step 4 — rewrite per-repo CLAUDE.md
Framework rules out, repo truth stays. Merge any `AGENTS.md` INTO `CLAUDE.md` — Claude Code
auto-loads only that filename, so a differently-named rules file is invisible in practice.
After each rewrite, `ls` every path the file mentions.

### Step 5 — install enforcement
`scripts/olivercode sync-hooks`, then `scripts/olivercode health`. Report the fail-open
property explicitly to the user; they need to know detection is a scheduled check, not a
guarantee.

### Step 6 — register the fleet
`local/` copies only. If you are about to write a real repo name, path, or command into a
tracked file, stop — that is the boundary the fork's shareability depends on.

### Step 7 — verify with evidence
Run the three commands AND the secret-probe. Quote the actual output. "Should be blocked" is
not a result; a blocked commit is.

### Step 8 — reconcile
Report what moved where, what stayed, what is still ambiguous. Ask before deleting backups.

## Output

A short report:

- **Moved:** each rule, from where, to where, verified present at the destination.
- **Kept in place:** what stayed and why.
- **Ambiguous:** anything you could not classify, with the question the user needs to answer.
- **Enforcement:** the probe result, quoted.
- **Backups:** where they are, and that they are still there.

## Known traps

- A repo's `CLAUDE.md` pointing at a path relative to the workspace root instead of the repo
  root. Reads fine, resolves to nothing from inside the repo.
- `~/.claude/skills/` not existing yet on a fresh machine — `ln -s` into it fails with a bare
  "No such file or directory". `mkdir -p` first.
- An uninstalled symlink makes `dirname "$(readlink ~/.claude/CLAUDE.md)"` return `.`, which
  silently resolves to whatever repo the agent is standing in. Always guard the resolution.
- A layout the scripts cannot resolve degrades to WARN and skips. WARN is not coverage.

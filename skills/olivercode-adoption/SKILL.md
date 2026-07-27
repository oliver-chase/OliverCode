---
name: olivercode-adoption
description: "Use when adopting OliverCode into a machine — the user forked or cloned it and says 'set this up', 'onboard my repos', 'point my CLAUDE.md files at OliverCode', 'audit my Claude config', or opens a fresh OliverCode checkout wanting it running. Walks the whole install: discover what exists, classify it, install activation, register the fleet, install enforcement, prove the gates block. Works for a clean machine or a messy existing setup. Optimizes and points; never amputates."
---

# OliverCode Adoption

Drive the whole setup so the user does not have to read the documentation first. You read it;
they answer questions. `$OC/docs/ADOPTING.md` is the reference contract — consult it when you
need detail, but do not make the user read it.

## The rule that governs everything here

**Optimize, do not amputate.** You are pointing existing rules at a shared home, not deleting
them. A rule you cannot classify is a rule you keep and flag. Never delete a user's config
because it looks redundant — redundancy is their call.

Back up before the first mutation. Do not remove a backup until the user confirms the result.

## Run this before anything else

```bash
bash scripts/qa/check-fork-usable.sh
```

If it fails, stop and report: the fork is broken, not their machine. Everything below assumes
a sound checkout.

## The four decisions only a human can make

Everything else is mechanical. Bring the user exactly these, with your recommendation and the
evidence for it — do not decide them silently, and do not dump the whole inventory on them.

**1. For each existing rules file: global, repo-specific, or personal?**
This is the whole adoption. Most setups tangle all three in one file.
- *machine-global* (applies everywhere) → the fork's `CLAUDE.md`
- *repo-specific* (true of one product only) → that repo's `CLAUDE.md`
- *personal/business* (voice, GTM, hiring) → their own user-skills area, NOT the framework
- *cannot classify* → leave it exactly where it is and say so
Present as a table with your proposed bucket per item. Get agreement before moving anything.

**2. Which repos are in the fleet?**
`discover` lists what exists; only the user knows which are live, which are archived, and
which they do not want governed. Do not register a repo they did not confirm.

**3. Any repo that genuinely needs a different hook?**
If one has a real reason to diverge (its own governance path, a gate whose checker only lives
there), that is legitimate — set `hookVariant` in its profile rather than forcing the
template. Ask before assuming either way.

**4. What is each repo's canonical validation command?**
Only they know. `npm run build`, `pytest`, a repo script. This lands in the profile.

## Procedure

### 1. Discover — never assume you know where anything is

```bash
scripts/olivercode discover --root <each directory their code lives under>
```

Read-only. Pass every root; they do not have to share a parent. It reports per repo: the
agent-rules filename, hook state, ungoverned repos; then inventories `~/.claude`; then emits a
profile skeleton with `path` pre-filled.

Two things it surfaces that the user usually does not know:
- **Rules files not named `CLAUDE.md`** (`AGENTS.md`, `.cursorrules`) do not auto-load in
  Claude Code. Invisible in practice, however good the content. These get merged in step 4.
- **Real directories in `~/.claude/skills/`** are untracked content with no backup anywhere.

Then read what exists — `~/.claude/CLAUDE.md`, each repo's rules file — and build the
classification for decision 1.

### 2. Back up, then activate

```bash
scripts/olivercode install
```

That is the whole step. `install` does the backup itself: a real `~/.claude/CLAUDE.md` is
moved to `.pre-olivercode` and the path printed, foreign symlinks and real directories are
left alone and reported. Do not `cp` a backup first — you get two backups with confusing
names (`.pre-olivercode` and `.pre-olivercode.bak`) and no extra safety.

Do NOT run it before the user has seen decision 1 — that file is often their entire ruleset.

### 3. Merge the global rules in

Additive into the fork's `CLAUDE.md`, into its existing sections. The one hard constraint:
that file loads in sessions whose working directory is almost never OliverCode, so **every
path in it must resolve from anywhere**. Use `$OC/...` for OliverCode's own files:

```bash
OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
[ -f "$OC/core/contracts/FRAMEWORK_BASELINE.md" ] || echo "OliverCode not installed"
```

A bare path means the user's *current* repo. If you mean that, write that you mean it.

### 4. Rewrite each repo's CLAUDE.md

Framework rules out, repo truth stays. Header block and rules are in ADOPTING.md Step 4.
Merge any `AGENTS.md` INTO `CLAUDE.md` — only that filename auto-loads.

**`ls` every path you leave in the file.** A pointer that does not resolve from the reader's
cwd is dead text, and an agent will silently proceed when it 404s.

Never invent repo content. If a file ends up with no repo-specific content, say so and ask
what belongs there.

### 5. Register the fleet

```bash
scripts/olivercode init      # seeds local/, never overwrites
```

Paste `discover`'s skeleton into `local/repo-profiles.json`, keeping the `path` values for any
repo that is not a sibling. Add each repo's `canonicalValidationCommand` (decision 4) and a
`token_policy` block — without the latter, Gate 8 blocks their commits.

Real names go in `local/` only. If you are about to write a repo name into a tracked file,
stop: that boundary is what makes the fork shareable.

### 6. Install enforcement

```bash
scripts/olivercode sync-hooks
scripts/olivercode health
```

Tell them plainly: **hook enforcement fails open.** Unset or broken `core.hooksPath` means git
runs no hooks and prints nothing. `health` is the only detector; `validate.sh` now surfaces it
too.

### 7. Prove it, do not assume it

```bash
cd <one of their repos>
printf 'K="sk-%s"\\n' "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" > leak-probe.txt
git add leak-probe.txt && git commit -m probe    # MUST be blocked
git reset -q HEAD leak-probe.txt && rm -f leak-probe.txt
```

If that commit succeeds, the hooks are not installed. Quote the actual output — "should be
blocked" is not a result.

### 8. Reconcile

Report what moved where, what stayed, what is still ambiguous. Ask before deleting backups.

## Output

- **Moved:** each rule, from where, to where, verified present at the destination.
- **Kept in place:** what stayed and why.
- **Ambiguous:** what you could not classify, with the question they need to answer.
- **Enforcement:** the probe result, quoted.
- **Backups:** where they are, and that they are still there.

## Known traps

- A repo `CLAUDE.md` pointing at a workspace-root-relative path. Reads fine, resolves to
  nothing from inside the repo.
- `~/.claude/skills/` absent on a fresh machine — `install` handles it; a bare `ln -s` does not.
- An uninstalled symlink makes `dirname "$(readlink ~/.claude/CLAUDE.md)"` return `.`, silently
  resolving to whatever repo the agent is standing in. Always guard the resolution.
- A layout the scripts cannot resolve degrades to WARN and skips. **WARN is not coverage.**
- Registering a repo by name alone when it is not a sibling — it will never be found. Use `path`.

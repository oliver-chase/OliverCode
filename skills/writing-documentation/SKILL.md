---
name: writing-documentation
description: Use whenever writing or rewriting a README, architecture doc, reference doc, or repo documentation — this repo, a governed repo, or a fork. Applies the locked documentation structure: README outline, index README shape, CAPS-KEBAB naming, complete doc table, backlog policy, GitHub About. The structure lives in docs/DOCUMENTATION_STANDARD.md. How the words sound lives in docs/VOICE.md.
---

# Writing Documentation

This skill applies the documentation structure. `docs/VOICE.md` owns how every sentence sounds, and this skill adds no writing rules of its own.

## Procedure

1. **Read the contract and the voice.** `docs/DOCUMENTATION_STANDARD.md` holds the README outline, the index README shape, file naming, the backlog policy and the sync rule. `docs/VOICE.md` holds how the words sound. Both live in OliverCode, so resolve `$OC` from the `~/.claude/CLAUDE.md` symlink when you work in another repo. Read both files. Do not restate them from memory.
2. **Read what exists.** Read the repo's current README, its `docs/`, its tests and its entry points. Every claim must match the code as it is now. Get each number (test counts, gate counts, option lists) from a run or a count, never from an earlier doc.
3. **Write to the outline.** A README follows the standard's outline. A catalog README, such as a suite or a monorepo, follows its "Index READMEs" section. Before you deliver an index README, compare every path, command, count and table row against disk, and say what you compared.
4. **Name files to the convention.** Name files under `docs/` in CAPS-KEBAB. A rename sweeps every reference in the same commit, because the reference gate fails on stragglers.
5. **Sync in the same commit.** Fix anything the new text contradicts in the same change: the README's doc table, `docs/FEATURE_MAP.md` where present, and the backlog.
6. **Fill the GitHub About.** If the repo's About description or topics are empty or stale, set them with `gh repo edit --description "..." --add-topic <topic>`.
7. **Run `asd-ste100`** on `SKILL.md`, `CLAUDE.md` and other agent-read files, per the standard's "Sentence clarity" section. Skip it for READMEs and for company and client writing.
8. **Verify.** Run `bash scripts/validate.sh` in OliverCode, or the repo's own `scripts/validate.sh` elsewhere. The reference and consistency gates are the floor. Then read the result yourself for what they cannot check: ordering and completeness.

## Boundaries

- The standard governs documentation for people. `CLAUDE.md` files, skill files and other loaded-context files follow their own contracts.
- Code comments and company or client writing (marketing copy, decks, posts) follow `docs/VOICE.md` alone. This skill does not apply to them.
- Never add a document that restates a rule owned elsewhere. Point to the owning doc.
- A comment inside a skill folder that ships in a zip cites no ledger and no other file outside that folder.

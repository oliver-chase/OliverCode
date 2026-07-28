---
name: writing-documentation
description: Use whenever writing or rewriting a README, architecture doc, reference doc, or any repo documentation, or when asked to "document this" — in this repo, any governed repo, or a fork. Applies the locked documentation standard: problem-driven README outline, voice, CAPS-KEBAB naming, complete doc table, backlog policy, GitHub About. The standard itself lives in docs/DOCUMENTATION_STANDARD.md; this skill is how it gets applied.
---

# Writing Documentation

Every README and document produced under this framework follows one locked contract, so the
same request produces the same shape of document in every repo, for every user, on every
fork. This skill exists so an agent asked to "write a README" or "document X" lands on that
contract instead of a generic house style.

## Procedure

1. **Load the contract.** Read `docs/DOCUMENTATION_STANDARD.md` in the OliverCode checkout
   (resolve `$OC` from the `~/.claude/CLAUDE.md` symlink when working outside it). That file
   is the single home for the README outline, voice, formatting, file naming, backlog
   policy, and freshness rules. Do not restate its rules from memory — read it, then write.
2. **Read what exists.** The repo's current README, its `docs/`, its tests and entry points.
   Every claim you write must be checkable against the code as it is now; numbers (test
   counts, gate counts, option lists) come from running or counting, never from prior docs.
3. **Write to the locked README outline** — one-sentence identity, driving problems,
   install-with-runnable-example, how-it-works, what-comes-back, design decisions as claims,
   the COMPLETE documentation table, hard-numbers status, license. For a non-README
   document: `# Title`, one orientation sentence, then the standard's voice and formatting
   rules throughout.
4. **Name files to the convention.** CAPS-KEBAB names under `docs/`. Renaming an existing file means
   sweeping every reference in the same commit — the reference gate fails on stragglers.
5. **Same-commit sync.** Anything the new text contradicts elsewhere gets fixed in the same
   change: the README's doc table, `docs/FEATURE_MAP.md` where present, the backlog.
6. **GitHub About.** If the repo's About description or topics are empty or stale, set them
   (`gh repo edit --description "..." --add-topic <topic>`) in the README's register. An
   empty About is missing documentation.
7. **Verify.** `bash scripts/validate.sh` in OliverCode, or the repo's own
   `scripts/validate.sh` elsewhere — the reference and consistency gates are the floor; read
   the result yourself for what they cannot check (voice, ordering, completeness).

## Boundaries

- The standard governs documentation for humans. `CLAUDE.md` files, skill files, and other
  loaded-context artifacts follow their own contracts and compress accordingly.
- Client-facing brand content (marketing copy, decks, posts) follows the operator's own
  voice standards outside this framework — do not apply this skill to it.
- Never introduce a document that restates a rule owned elsewhere; point to the owning doc.

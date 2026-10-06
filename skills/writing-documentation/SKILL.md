---
name: writing-documentation
description: Use whenever writing or rewriting a README, architecture doc, reference doc, or repo documentation — this repo, a governed repo, or a fork. Also use for a non-trivial CODE COMMENT. Applies the locked documentation standard: README outline, index README shape, voice, CAPS-KEBAB naming, complete doc table, backlog policy, GitHub About. Its Voice, Readability, and Sentence clarity rules govern comment prose too. The standard itself lives in docs/DOCUMENTATION_STANDARD.md. This skill is how it gets applied.
---

# Writing Documentation

Every README and document produced under this framework follows one locked contract, so the
same request produces the same shape of document in every repo, for every user, on every
fork. This skill exists so an agent asked to "write a README" or "document X" lands on that
contract instead of a generic house style.

## Procedure

1. **Read the process, then the contract — in that order.** `docs/WRITING_PROCESS.md` first
   (resolve `$OC` from the `~/.claude/CLAUDE.md` symlink when working outside it): think,
   then write plainly, and treat every rule as QA on a draft that already exists.
   `docs/DOCUMENTATION_STANDARD.md` is that QA — the single home for the README outline,
   voice, formatting, file naming, backlog policy and freshness rules. Reading the standard
   first is what produces checklist-patched prose that passes every rule and still sounds
   like nobody. Do not restate either from memory — read them.
2. **Read what exists.** The repo's current README, its `docs/`, its tests and entry points.
   Every claim you write must be checkable against the code as it is now. Numbers (test
   counts, gate counts, option lists) come from running or counting, never from prior docs.
3. **Write to the locked README outline.** The parts, in order:
   - One-sentence identity, driving problems, install with a runnable example.
   - How it works, what comes back, design decisions as claims.
   - The COMPLETE documentation table, hard-numbers status, license.

   For a non-README document, write `# Title`, one orientation sentence, then follow the
   standard's voice and formatting rules throughout.

   A README that catalogs many things, such as a suite or a monorepo, follows the standard's
   "Index READMEs" section. Before you deliver one, compare every path, command, count and
   table row it names against disk. Say what you compared. Then read it as a stranger. Rewrite
   any paragraph over three sentences. Rewrite any internal term used before the text explains
   it. Rewrite any matrix written as a sentence.
4. **Name files to the convention.** CAPS-KEBAB names under `docs/`. Renaming an existing file means
   sweeping every reference in the same commit — the reference gate fails on stragglers.
5. **Same-commit sync.** Anything the new text contradicts elsewhere gets fixed in the same
   change: the README's doc table, `docs/FEATURE_MAP.md` where present, the backlog.
6. **GitHub About.** If the repo's About description or topics are empty or stale, set them
   (`gh repo edit --description "..." --add-topic <topic>`) in the README's register. An
   empty About is missing documentation.
7. **Run `asd-ste100`.** STE-flavored mode, `--disable long-sentence` — see
   `docs/DOCUMENTATION_STANDARD.md`'s "Sentence clarity" section for what it catches and the
   one rule this framework doesn't take from it. Skip this step for client-facing brand
   content. It's out of scope for both this skill and that skill.
8. **Verify.** `bash scripts/validate.sh` in OliverCode, or the repo's own
   `scripts/validate.sh` elsewhere — the reference and consistency gates are the floor. Read
   the result yourself for what they cannot verify (voice, ordering, completeness).

## Boundaries

- The standard governs documentation for humans. `CLAUDE.md` files, skill files, and other
  loaded-context artifacts follow their own contracts and compress accordingly.
- Client-facing brand content (marketing copy, decks, posts) follows the operator's own
  voice standards outside this framework — do not apply this skill to it.
- Never introduce a document that restates a rule owned elsewhere. Point to the owning doc.
- A comment inside a skill folder that ships in a zip is the exception to the decision-id rule.
  It says what the code does, carries no `AREA-TOPIC-N` id and no history, and points to no
  ledger. The reason for the rule lives in the commit or the issue.

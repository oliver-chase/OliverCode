---
name: backlog-management
description: >
  Owns a repo's GitHub Project as its live backlog, for any repo that names a backlog-config.json path in its own CLAUDE.md.
  Files a new Story or Epic (search first, never duplicate) and sets Status/Priority/Size every time.
  Closes an item with evidence.
  Runs an on-demand "what's due" triage check: stale Backlog, stale In Progress, unrevisited deferred items.
  Reads that repo's own config for the repo/Project/field IDs -- never hardcodes one repo's values.
  Trigger on "file this", "add a story", "add an epic", "close this out", "backlog status", "what needs triage", or "groom the backlog".
  Also trigger when a skill's own routing names "real new scope" that needs tracking before it gets built.
---

# Backlog Management

## Which repo, which config

This skill is repo-agnostic. It never hardcodes a repo name, a Project number, or a field ID. Every command reads them from that repo's own `backlog-config.json`, per `references/project-fields.md`'s exact command shape.

**Find the config, every time, before running anything**. Read the current repo's own `CLAUDE.md` for a line naming where `backlog-config.json` lives. This matches `plan`'s own "Plan File Location" convention for the same problem. Operations Vault's own `CLAUDE.md` names its copy today, at `01 - Skills/docs/backlog-config.json`. A repo's own `CLAUDE.md` may name no config file — that means it hasn't adopted this skill yet. Ask the user where one should live, write it there, and name it in that repo's `CLAUDE.md` in the same session. Never guess a path or silently skip this skill.

## File a Story or Epic

1. **Search first**. Use `references/project-fields.md`'s search command, loading the repo's config first. An existing open item wins. Extend it with a comment. Never create a duplicate.
2. **Classify the work**. A quick fix — a missing fallback, a stale word, a small config change with an obvious safe default — gets fixed inline. No Project item. Real new scope — a schema change, a new mechanism, a cross-family contract — gets filed before it gets built. Follow the repo's own quick-wins-only convention if it states one. Assume the same split if it doesn't.
3. **Create it**. `references/project-fields.md`'s exact create-and-add command shape.
4. **Set all 3 fields, every time**. Status: `Backlog` if something blocks the item or it needs a decision, `Ready` if the next action is already clear and unblocked. Priority and Size: per that repo's own prioritization doc, if it names one — Operations Vault's is `01 - Skills/docs/PRIORITIZATION.md`. Never leave a field blank because the judgment feels obvious — state it explicitly instead.
5. **Work Type**: `Epic` if the item spans multiple skills or families. `Story` otherwise.
6. **Filed from a plan doc? Delete the plan file once every Step/Story in it has a filed issue**. A plan doc (the `plan` skill's output, `<repo>/docs/plans/*.md`) is a drafting tool, not a second home for the same content. Once you transcribe its Steps into Epics/Stories with real Status/Priority/Size, the issue is the source of truth. A plan file sitting next to it is a duplicate that a no-duplication repo shouldn't keep. Delete it in the same pass that files the last issue from it. Git holds the history. Copy real reasoning (the "why," evidence, tradeoffs) into the issue body once, concisely. Don't leave the same explanation in both places. A plan may cover ground beyond what got filed, such as an open question or a deliberately deferred step. Keep that file until the rest is filed too, then delete it. Precedent: `Delete SPEC-90's plan file, content already in Issue #93`. That deletion happened once, ad hoc, before this rule existed. The same day this rule got written, 19 other closed-work plan docs still sat in one repo's `docs/plans/`. So the practice was not consistent. Never delete a plan doc for a still-open Story. Never delete one nobody has read yet just because a Story exists. Check the actual Status field, not the filename's date.

### Sizing an XL or L item for real completeness

XL or L almost always means the item touches N things across the fleet. That is the size where a memory-based "got them all" claim is most likely wrong. Seen live 2026-09-22 (vault issue `#186`): its own stated audit command was `.md`-only. It missed 2 real `.py` citations of the exact same string it meant to enumerate. The issue read as thorough because it named a real command. It still had a gap, because nobody re-ran that command against a wider net before filing.

1. **Audit first, as its own Story, before any fix Story exists**. The audit's output is a real, re-runnable command (a grep, a script) stated in the issue body — not a remembered list. Anyone should be able to run that exact command fresh and get the same count.
2. **Split the fix by the real boundary** — family, file type, whatever the actual seams are — one Story per boundary. Never one Story doing all N edits in a single unverified pass. This is the same Epic/Story split this skill already uses, applied inside one big change instead of across a whole initiative.
3. **Before-count and after-count, same command, every time**. Run the audit command and record N. Fix. Re-run the identical command and read the real number left. That number is 0 or a real, expected residual, named explicitly, never silent. The close-out evidence comment states both numbers. "Fixed them all" with no number attached is not evidence.
4. **A wider-than-expected audit result is itself a finding**. The real command may turn up a file type, a family, or a count the drafting session didn't expect. Comment that the same way you comment a correction. Don't quietly narrow scope to match what the draft assumed.

## Close a Story or Epic

1. Move Status to `Complete`.
2. Comment the evidence — files touched, what actually shipped. One comment per real change. Never rewrite the issue body to reflect the final state. The comment trail is the record.
3. **Check for a parent Epic. If one exists, update it too — this is not optional**. GitHub's `Status` field never updates on its own from sub-issue completion. `Sub-issues progress` tracks the count automatically. `Status` does not follow it. Query `subIssuesSummary` (GraphQL) for the parent's real completed/total count. All complete: move the parent to `Complete`, unless a sub-issue was deliberately deferred and stays open on purpose. Then the parent stays `In Progress`, never `Complete`, and the comment says why. Some complete, none deferred: move the parent to `In Progress` if it was still `Backlog` or `Ready`. Comment the parent with the real count either way.

## "What's due" — on-demand triage check

Trigger: "backlog status," "what needs triage," "groom the backlog." Also run this first, silently, whenever this skill gets invoked for any other reason. Read-only. Reports. Never silently reprioritizes anything.

`references/project-fields.md`'s list command, then check:

1. **Stale Backlog** — a `P0` or `P1` item sitting in `Backlog` with no comment in 14 days. This threshold has no real data behind it yet. Revise it once a real complaint says it's wrong, not before.
2. **Stale In Progress** — an item sitting in `In Progress` with no comment in 7 days.
3. **Unrevisited deferred** — a `deferred` label, no comment in 30 days.

Report one grouped digest. Say "Nothing due" if genuinely clean.

## The gap-analysis reflex

A repo that adopts this skill names it, in its own `CLAUDE.md`, as the mechanism for gap-analysis-before-build. Real new scope gets filed here before it gets built, not on request. Operations Vault's own copy already does this. A calling skill states this once in its own text ("file via `backlog-management`") rather than repeating this skill's procedure inline.

## Boundaries

**Will:**

- Read the calling repo's own config before running any command — never hardcode a repo, Project, or field ID.
- Search the Project before creating anything.
- Set Status, Priority, and Size on every item this skill files, no exceptions.
- Size an XL or L item with a real, re-runnable audit command. Split it into boundary-scoped sub-Stories with a before/after count. Never file it as one flat mega-item.
- Report triage findings without changing anything on its own.
- Delete a plan doc once every Step/Story in it has a filed issue — the issue becomes the record, not a second copy.

**Will not:**

- Assume a config path. Ask, if the repo's `CLAUDE.md` doesn't name one.
- Create a duplicate item without first searching for an existing one.
- Decide Priority or Size from a template — each one is a real per-item judgment call.
- File a quick fix as a Story.
- Rewrite an issue's body to hide its history. Evidence goes in comments, appended, not overwritten.

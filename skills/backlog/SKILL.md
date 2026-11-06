---
name: backlog
description: >
  Owns a repo's GitHub Project as its live backlog, for any repo whose CLAUDE.md names a backlog-config.json.
  Files a Story or Epic (search first, never duplicate) with Status, Priority and Size set, closes an item with evidence, and sweeps the board for field gaps, status drift, duplicates and missing QA sign-off.
  Trigger on "file this", "add a story", "add an epic", "close this out", "backlog status", "what needs triage", "groom the backlog", or "board hygiene".
  Also trigger when a skill names real new scope that needs tracking before it gets built.
---

# Backlog

Every script below runs from this skill's folder, and command shapes live in `references/project-fields.md`.

## Which repo, which config

Before running anything, read the current repo's `CLAUDE.md` for the line that names its `backlog-config.json`. Never ask the owner for the path when that line exists, and never guess one. A `CLAUDE.md` with no such line means the repo has not adopted this skill. The config lives at `docs/backlog-config.json`: run `olivercode backlog-setup` (add `--apply` to create the Project and write the file) and name the file in `CLAUDE.md` in the same session.

Verify it with `python3 scripts/check_board_hygiene.py --config CONFIG --verify-config`. It stops a config that holds the example's placeholders and a config whose repo is not the git origin of its folder, which is a fork that inherited the owner's config. On a stop, file, comment and edit nothing, and run `olivercode backlog-setup --apply` for the fork's own repo, which creates its Project and writes the config. Never hardcode a repo, Project or field ID.

## Check the board against the baseline

Run `python3 scripts/check_board_hygiene.py --config CONFIG --verify-baseline`. It compares the Project's fields with `shared/kanban-baseline.json` (`docs/RULES.md`, "The backlog"), prints each difference with its fix and never edits a board. `references/project-fields.md` ("Baseline check") has the offline option and the repair path.

## Save every ask

Every owner request that changes files becomes a story before any work starts, so nothing the owner asks for is lost or done untracked. The exception is a small change (`docs/RULES.md`, "The backlog"): it runs the repo's validation and commits with the number of the open epic whose goal fits. The rule lives in `docs/RULES.md` ("The backlog") and the body format in `references/story-template.md`.

1. **Search the open stories first** (command in `references/project-fields.md`). A request that duplicates an open story is added to it as a comment.
2. **Write the body** from the template, and pick the open epic whose goal the request serves. When none fits, file an epic first with `Work type: Epic`: the container whose body lists its stories and carries no `Epic:` line.
3. **Check the body** with `python3 scripts/check_story_format.py BODY_FILE` and fix every part it prints.
4. **File it** as below. A request the owner wants now goes in `Ready`, and the session starts it after filing.
5. **A mid-task request is filed and queued.** The order changes only on "stop", "do this first" or "drop that".

## Work an item

Take items one at a time. Before building, run `git fetch origin main` and list the branches and recent commits that name the story, since another session may have built it already. Read the story in full, restate the ask in your own words and check it against the current code, tests and docs, since a story written weeks ago may describe a state that has moved. When they conflict, show the owner the exact differences and wait for a decision before overwriting, updating or skipping. A matching story goes ahead without a pause. When the code has moved, rewrite the story with accurate Gherkin criteria, file any prerequisite or follow-on stories through "Save every ask", and confirm the backlog changes before the build starts.

## Log every action

After each commit or finished piece of work, and before a lead reports a helper's result, run `python3 scripts/log_action.py --config CONFIG --story N --agent NAME --role builder|qa --commit HASH --files COUNT --result "one line"`. It posts one comment through `gh api`, and `--dry-run` posts nothing. Commit messages carry `(#N)`.

## File a story or epic

1. **Search first** and extend an existing open item with a comment.
2. **Classify the work.** An owner request is filed ("Save every ask") unless it meets that section's small-change exception. A quick fix the session finds on its own, such as a missing fallback or a stale word, is fixed inline with no Project item. Real new scope is filed before it is built. A repo's own quick-wins convention wins.
3. **Answer the fit check in the body.** Adding to what exists is the default, so the body names what it extends (a new file states why no home fits), whether it is core or an add-on, what it replaces and its effect on size and always-loaded tokens, and whether it passes `$OC/skills/audit/references/lenses.md`.
4. **Create it and add it to the board yourself** with the create-and-add command in `references/project-fields.md`. Nothing adds an issue to the Project automatically, so an issue made any other way (the web, a script, `gh api`) is not on the board until `gh project item-add` runs. Check with the item list afterwards that the new number appears with every field set
5. **Set Status, Priority, Size and Work type every time.** Status is `Backlog` when something blocks the item or it needs a decision, and `Ready` when the next action is clear and unblocked. Priority and Size are a per-item judgment under the repo's prioritization doc, never copied from a template or left blank.
6. **An XL or L item** gets an audit Story first, with a re-runnable command and a before and after count, then one fix Story per boundary. `references/story-template.md` ("Sizing an XL or L item") has the procedure.
7. **Filed from a plan doc?** Copy its reasoning into the issue body once, and delete the plan file in the same pass that files its last Step. Keep it while any Step or open question is unfiled or deferred.

## Close a story or epic

1. **QA first.** The builder moves the story to `QA` and stops. A different agent that built no part of the story checks each Gherkin scenario against the files without seeing the builder's conclusion. One agent covers every story of a branch and ends its report with one line per story, as in `Story 12: PASS; confirmed: Work is finished; Work fails`. Log the whole report with `log_action.py --role qa --from-report FILE`, and a note may follow the last scenario name. A story whose body has the line `QA: mechanical` changes no behavior (a wording, whitespace or duplicate-removal edit), needs no QA agent, and closes when the builder logs a result that says `validate.sh exits 0` and quotes the counts it changed. The check looks for the phrase only, so the lead reads the counts.
2. **Complete it** with `python3 scripts/complete_story.py --story N --config CONFIG --evidence "files touched and what shipped"`. It runs `check_qa_signoff.py` first, and only on a pass moves Status to `Complete`, posts the evidence and closes the issue. On a refusal it changes nothing, and the story returns to `In Progress` with the findings in a comment. The check exits 0 on an independent PASS that confirms every scenario by its whole name when the story also has a builder comment, or on the mechanical proof above. A story another session built but never logged needs its builder logged first with `log_action.py --role builder --agent-from-commit --commit HASH`. The issue body is never rewritten, so the comment trail stays the record.
3. **Update the parent epic.** Status does not follow sub-issue progress, so query `subIssuesSummary` (`references/project-fields.md`). All complete: move the parent to `Complete`. A sub-issue deliberately deferred: the parent stays `In Progress` and the comment says why. Some complete, none deferred: move a `Backlog` or `Ready` parent to `In Progress`. Comment the real count either way.

## Sweep the board

The sweep is read-only and changes nothing until the owner approves a fix. A stopped read (a reached limit, a failed call, a GraphQL rate limit) means it did not run, so say so and never report clean.

**After every filing**, run only the required-fields and duplicate dimensions: `python3 scripts/check_board_hygiene.py --config CONFIG --dimension fields --dimension duplicates`. The full five-dimension sweep runs when the owner asks for it, when a person raises the backlog ("backlog status", "what needs triage", "groom the backlog", "board hygiene").

When the owner asks for a sweep, read the config path from the repo's `CLAUDE.md` and check all five dimensions unless the owner names one. Open with this message, word for word, with no other opening line and no closing recap.

> A tidy board shows at a glance what to work on next and where each item stands.
>
> I read your live GitHub Project board and report anything out of order across five dimensions. We go through each finding together, and I change nothing until you approve a fix.

| Dimension | Checks |
|---|---|
| Required fields (`fields`) | Priority and Size on every open item, plus Work Type and Area where defined |
| Status drift (`drift`) | Board Status matches issue state, and every open issue is on the board |
| Duplicate cards (`duplicates`) | One card per issue |
| QA sign-off (`qa-signoff`) | Every Complete item from `qaRequiredFromIssue` has an independent sign-off |
| Grooming (`groom`) | Built work left in Backlog or Ready, epics whose Status lags their sub-issues, and open stories whose titles overlap |

`references/project-fields.md` ("Sweep dimensions") holds each rule in full.

The script is `python3 scripts/check_board_hygiene.py --config CONFIG`, with `--dimension` (repeatable).

Every finding is mechanical. Report them as one grouped list, or "Nothing due" when clean.

### Clear the findings

Clear each required-fields and status-drift finding with `gh project item-edit` or `gh api graphql`. A closed issue that shows open means the board and the issue were edited separately: close the issue and set Status `Complete` together, then re-run `drift`.

A calling skill says "file via `backlog`" once and does not repeat this procedure.

Finishing a whole backlog with several agents (file groups, briefs, QA that names every scenario, merging): `references/delegating-a-backlog.md`.

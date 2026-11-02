---
name: backlog
description: >
  Owns a repo's GitHub Project as its live backlog, for any repo that names a backlog-config.json path in its own CLAUDE.md.
  Files a new Story or Epic (search first, never duplicate) and sets Status/Priority/Size every time.
  Closes an item with evidence.
  Sweeps the whole board across 7 dimensions: required-field gaps, Status that disagrees with issue state, duplicate cards, an empty Ready column, stale Area options, ranked Ready candidates and stale items.
  Reads that repo's own config for the repo/Project/field IDs -- never hardcodes one repo's values, and refuses a fork that carries the owner's config.
  Trigger on "file this", "add a story", "add an epic", "close this out", "backlog status", "what needs triage", "groom the backlog", "board hygiene", "is the backlog properly prioritized", "check the project board" or "what should go in Ready".
  Also trigger when a skill's own routing names "real new scope" that needs tracking before it gets built.
---

# Backlog

This skill files an item, closes it and sweeps the whole board. Filing and closing set the fields on one item. The sweep checks every open item at once.

## Which repo, which config

**Find the config, every time, before running anything**. Read the current repo's own `CLAUDE.md` for a line naming where `backlog-config.json` lives. This matches `plan`'s own "Plan file location" convention for the same problem. A repo's own `CLAUDE.md` may name no config file. That means it hasn't adopted this skill yet. Ask the user where one should live, write it there from `$OC/shared/backlog-config.example.json`, and name it in that repo's `CLAUDE.md` in the same session. Never guess a path or silently skip this skill.

**Then verify it**: `python3 scripts/check_board_hygiene.py --config CONFIG --verify-config`, run from this skill's folder. The check stops a config that still holds the example's placeholders, and a config whose repo is not the git origin of the folder it sits in. The second case is a fork that inherited the owner's `docs/backlog-config.json`. On a stop, file nothing, comment on nothing and edit no field. Tell the owner of the fork to copy `shared/backlog-config.example.json`, fill in their own Project and pass that path. The example holds placeholders only, so nothing runs against it, and no fallback reaches the owner's Project.

## Check the board against the baseline

Run `python3 scripts/check_board_hygiene.py --config CONFIG --verify-baseline` from this skill's folder. It reads the Project's field list from `gh` and compares it with `shared/kanban-baseline.json`, which `docs/RULES.md` ("The backlog") describes. Add `--fields-file FILE` to compare a saved `gh project field-list --format json` output with no network call. Each difference prints with its fix, and the exit status is 1 when any exist. A config with no option ID for a baseline lane, such as QA, is still valid. Add the lane to the Project, then copy its option ID from the field list into the config. The check reads fields and never edits a board. Built-in workflows do not appear in the field list, so a pull-request workflow on the Project is turned off by hand.

## Save every ask

Every owner request, however small, becomes a story before any work starts. This is how nothing the owner asks for is lost or done untracked. The format lives in `references/story-template.md`, and the rule's home is `docs/RULES.md` ("The backlog").

1. **Search the open stories first**, with `references/project-fields.md`'s search command. A request that duplicates an open story is added to it as a comment. File nothing new.
2. **Write the body** from `references/story-template.md`: the user story sentence, Given/When/Then scenarios, the epic link, then Priority, Size and Work type.
3. **Pick the epic**. Use the open epic whose goal the request serves. When none fits, file an epic first with the same template and `Work type: Epic`.
4. **Check the body**: `python3 scripts/check_story_format.py BODY_FILE`, run from this skill's folder. Fix every part it prints before filing.
5. **File it** with "File a story or epic" below, setting Status, Priority, Size and Work type. A request the owner asks for now goes in `Ready`, and the session starts it after filing.
6. **A request that arrives mid-task is filed and queued**. The current story keeps its order. Reorder only when the owner says "stop", "do this first" or "drop that".

## Log every action

Run `python3 scripts/log_action.py --config CONFIG --story N --agent NAME --role builder|qa --commit HASH --files COUNT --result "one line"` from this skill's folder after each commit or finished piece of work, and before a lead reports a helper's result. It posts one comment on the story through `gh api`, and `--dry-run` prints the comment and posts nothing. The commit message carries `(#N)`, which the commit-msg hook requires.

## File a story or epic

1. **Search first**. Use `references/project-fields.md`'s search command, loading the repo's config first. An existing open item wins. Extend it with a comment. Never create a duplicate.
2. **Classify the work**. An owner request is never a quick fix to skip filing: it follows "Save every ask" above. A quick fix — a missing fallback, a stale word, a small config change with an obvious safe default — gets fixed inline. No Project item. Real new scope — a schema change, a new mechanism, a cross-family contract — gets filed before it gets built. Follow the repo's own quick-wins-only convention if it states one. Assume the same split if it doesn't.
3. **Check the fit, in the issue body**. Adding to what exists is the default, so the body answers:
   - What existing skill, reference, script or config this extends. A new skill or file states why no existing home fits
   - Whether it belongs to the target's core or to an add-on, where the target names that split
   - What it replaces or removes, and its expected effect on size and on always-loaded tokens
   - Whether it still passes the lenses in `$OC/skills/audit/references/lenses.md`: a user reaches it by talking, it runs on its own, each concept keeps one home, and it adds no unused part
4. **Create it**. `references/project-fields.md`'s exact create-and-add command shape.
5. **Set all 3 fields, every time**. Status: `Backlog` if something blocks the item or it needs a decision, `Ready` if the next action is already clear and unblocked. Priority and Size: per that repo's own prioritization doc, if it names one. Never leave a field blank because the judgment feels obvious — state it explicitly instead.
6. **Work Type**: `Epic` if the item spans multiple skills or families. `Story` otherwise.
7. **Filed from a plan doc? Delete the plan file once every Step/Story in it has a filed issue**. A plan doc (the `plan` skill's output file) is a drafting tool, not a second home for the same content. Once you transcribe its Steps into Epics/Stories with real Status/Priority/Size, the issue is the source of truth. Delete it in the same pass that files the last issue from it. Git holds the history. Copy real reasoning (the "why," evidence, tradeoffs) into the issue body once, concisely. A plan may cover ground beyond what got filed, such as an open question or a deliberately deferred step. Keep that file until you file the rest too. Never delete a plan doc for a still-open Story, or one nobody has read yet just because a Story exists. Check the actual Status field, not the filename's date. See `references/plan-doc-deletion.md` for why this rule exists.

### Sizing an XL or L item for real completeness

XL or L almost always means the item touches N things across the fleet. That is the size where a memory-based "got them all" claim is most likely wrong. Seen live 2026-09-22: its own stated audit command was `.md`-only. It missed 2 real `.py` citations of the exact same string it meant to enumerate. The issue read as thorough because it named a real command. It still had a gap, because nobody re-ran that command against a wider net before filing.

1. **Audit first, as its own Story, before any fix Story exists**. The audit's output is a real, re-runnable command (a grep, a script) stated in the issue body — not a remembered list. Anyone should be able to run that exact command fresh and get the same count.
2. **Split the fix by the real boundary** — family, file type, whatever the actual seams are — one Story per boundary. Never one Story doing all N edits in a single unverified pass. This is the same Epic/Story split this skill already uses, applied inside one big change.
3. **Before-count and after-count, same command, every time**. Run the audit command and record N. Fix. Re-run the identical command and read the real number left. That number is 0 or a real, expected residual, named explicitly, never silent. The close-out evidence comment states both numbers. "Fixed them all" with no number attached is not evidence.
4. **A wider-than-expected audit result is itself a finding**. The real command may turn up a file type, a family, or a count the drafting session didn't expect. Comment that the same way you comment a correction. Don't quietly narrow scope to match what the draft assumed.

## Close a story or epic

0. **QA comes first**. The builder moves the story to `QA` and stops. A different agent, one that is a builder on no part of the story, re-reads the files and runs the checks against each Gherkin scenario without being shown the builder's conclusion. It logs its verdict with `log_action.py --role qa`, and its `--result` starts with `PASS` or `FAIL` and names every scenario it confirmed, as in `PASS; confirmed: Work is finished; Work fails`. Run `python3 scripts/check_qa_signoff.py --story N --config CONFIG` from this skill's folder. It exits 0 on an independent PASS that confirms every scenario, and the story moves on. On `FAIL`, or when the checker refuses, the story returns to `In Progress` with the findings in a comment.
1. Move Status to `Complete`.
2. Comment the evidence — files touched, what actually shipped. One comment per real change. Never rewrite the issue body to reflect the final state. The comment trail is the record.
3. **Check for a parent Epic. If one exists, update it too — this is not optional**. GitHub's `Status` field never updates on its own from sub-issue completion. `Sub-issues progress` tracks the count automatically. `Status` does not follow it. Query `subIssuesSummary` (GraphQL) for the parent's real completed/total count. All complete: move the parent to `Complete`, unless a sub-issue was deliberately deferred and stays open on purpose. Then the parent stays `In Progress`, never `Complete`, and the comment says why. Some complete, none deferred: move the parent to `In Progress` if it was still `Backlog` or `Ready`. Comment the parent with the real count either way.

## Sweep the board

Trigger: "backlog status", "what needs triage", "groom the backlog", "board hygiene", "is the backlog properly prioritized". Run it after every item you file, and whenever a person mentions the backlog. Read-only. It reports and changes nothing until the owner approves a fix.

A request that names its config path skips the opening message. Otherwise send this first, in one turn, exactly as written, with no other opening line and no closing recap.

> A tidy board shows at a glance what to work on next and where each item stands.
>
> I read your live GitHub Project board and report anything out of order across 7 dimensions. We go through each finding together, and I change nothing until you approve a fix.
>
> The config path is all I need to start, and naming a dimension you already suspect lets me go straight to it. I also need `gh` installed and signed in.
>
> You can answer in any of these ways:
> 1. Send the path to the repo's `docs/backlog-config.json`, and I will check all 7 dimensions.
> 2. Send that path with one dimension by name: fields, drift, duplicates, ready, area, suggest or stale. I will check only that one.
> 3. Send that path with a skills folder, and I will compare the Area options with its folders.

| Dimension | Checks |
|---|---|
| Required fields | Every open item has Priority and Size, plus Work Type and Area where the config defines them |
| Status drift | Board Status matches the issue state: the finished column, such as `Complete` or `Done`, holds only closed issues, and no open column holds one. The board's own column names decide. Every open issue of the config's own repo is on the board |
| Duplicate cards | No issue has more than one card on the board, counted per repo and number (the same number in two repos is two issues) |
| Ready occupancy | The `Ready` column holds at least one item whenever Backlog holds one |
| Area freshness | Every Area option matches a folder directly under the skills root you pass, or one of the retired, parked or catch-all options the config's `areaPolicy` lists. Every such folder has a matching option |
| Ready candidates | Fires only with an empty Ready column and a non-empty Backlog. Ranks Backlog items by Priority then Size, skips any that a keyword scan reads as blocked, and lists up to 5 |
| Stale | A `P0` or `P1` item in `Backlog` with no comment in 14 days, an item in `In Progress` with none in 7, and an item labelled `deferred` with none in 30. An item with no comment counts from its filing date. The 14-day threshold has no real data behind it yet. Revise it once a real complaint says it is wrong |

Run `python3 scripts/check_board_hygiene.py --config path/to/backlog-config.json` from this skill's folder. Add `--dimension fields|drift|duplicates|ready|area|suggest|stale` to run one. Add `--skills-root path/to/skills` to run Area freshness against that folder's direct sub-folders. Without it, Area reports a skip and the other six run. The script needs `gh` on the path, signed in. Without `--config`, or with a path that holds no file, it stops with one line that says so and names the example config a fork starts from.

The board list, the issue lists and the comment history are read with explicit limits and pagination. A read that reaches its limit or fails stops the run with a message. A stop means the sweep did not run, so say so and never report clean. A GraphQL rate-limit error is the same case.

Required fields, status drift, duplicate cards and Area freshness are mechanical. A missing field, a status that contradicts the issue, or an orphaned option is never a judgment call. Ready occupancy, Ready candidates and stale are advisory. An empty Ready column can be right when nothing is unblocked, a suggested candidate can still be blocked in a way no keyword names, and a quiet item can be waiting on something real. Read each advisory finding in context before you act, and report one grouped digest. Say "Nothing due" when every dimension is clean.

### Clear the findings

1. A closed issue that shows open means someone edited the board and the issue separately. Close the issue and set Status `Complete` together, then re-run `drift`.
2. Clear each `required-fields`, `status-drift` and `area-freshness` finding directly with `gh project item-edit` or `gh api graphql`.
3. For `ready-occupancy`, read the open Backlog items and use `ready-candidates` as the shortlist. Pick the unblocked item with the highest priority by `<repo>/docs/PRIORITIZATION.md`, in the repo whose board you check, and read its body before you promote it to `Ready`. An item whose body names an open design question, or leaves design calls to the builder, is not Ready. It needs a `plan` pass first.
4. For `stale`, ask the owner per item whether to comment, reprioritize or close it. Never move one silently.

## The gap-analysis reflex

A repo that adopts this skill names it, in its own `CLAUDE.md`, as the mechanism for gap-analysis-before-build. Real new scope gets filed here before it gets built, not on request. A calling skill states this once in its own text ("file via `backlog`") and does not repeat this skill's procedure inline.

## Boundaries

**Will:**

- Read the calling repo's own config before running any command, and verify it first. Never hardcode a repo, Project, or field ID.
- Search the Project before creating anything.
- Set Status, Priority, and Size on every item this skill files, no exceptions.
- Size an XL or L item with a real, re-runnable audit command. Split it into boundary-scoped sub-Stories with a before/after count. Never file it as one flat mega-item.
- Report sweep findings without changing anything on its own.
- Read the retired, parked and catch-all Area options from the config's `areaPolicy`.
- Delete a plan doc once every Step/Story in it has a filed issue — the issue becomes the record, not a second copy.

**Will not:**

- Assume a config path. Ask, if the repo's `CLAUDE.md` doesn't name one.
- File an item that the repo's prioritization doc lists under "What never gets filed". Read that section before step 1 of filing.
- Finish a filing or answer a backlog question without running the sweep. The sweep is the baseline: run it whenever a person mentions the backlog and after every item you file.
- Write to a Project the checkout does not own. A fork that inherited the owner's config stops at the verify step.
- Start work on an owner request before its story exists.
- Create a duplicate item without first searching for an existing one.
- Decide Priority or Size from a template — each one is a real per-item judgment call.
- File a quick fix as a Story.
- Rewrite an issue's body to hide its history. Evidence goes in comments, appended, not overwritten.

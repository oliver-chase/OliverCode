---
name: backlog
description: >
  Owns the GitHub Project of a repo whose CLAUDE.md names a backlog-config.json. Files a Story or Epic,
  closes an item with evidence and sweeps the board for gaps, drift and duplicates. Trigger on "file this",
  "add a story", "add an epic", "close this out", "backlog status", "groom the backlog", "board hygiene",
  or new scope a skill names that needs tracking.
---

# Backlog

Every script below runs from this skill's folder, and command shapes live in `references/project-fields.md`.

## Which repo, which config

Before running anything, read the current repo's `CLAUDE.md` for the line that names its `backlog-config.json`. Never ask the owner for the path when that line exists, and never guess one. A `CLAUDE.md` with no such line means the repo has not adopted this skill. The config lives at `docs/backlog-config.json`: run `olivercode backlog-setup` (add `--apply` to create the Project and write the file) and name the file in `CLAUDE.md` in the same session.

Verify it with `python3 scripts/check_board_hygiene.py --config CONFIG --verify-config`. It stops a config that holds the example's placeholders and a config whose repo is not the git origin of its folder, which is a fork that inherited the owner's config. On a stop, file, comment and edit nothing, and run `olivercode backlog-setup --apply` for the fork's own repo, which creates its Project and writes the config. Never hardcode a repo, Project or field ID.

## Check the board against the baseline

Run `python3 scripts/check_board_hygiene.py --config CONFIG --verify-baseline`. It compares the Project's fields with `shared/kanban-baseline.json` (`docs/RULES.md`, "The backlog"), prints each difference with its fix and never edits a board. `references/project-fields.md` ("Baseline check") has the offline option and the repair path.

## Save every ask

The rule is in `docs/RULES.md`, "The backlog": every owner request that changes files becomes a story before work starts, and the procedure is "File a story or epic" below. A calling skill says "file via `backlog`" and does not repeat that procedure.

A mid-task request is filed and queued. The order changes only when the owner says "stop", "do this first" or "drop that".

## File a story or epic

1. **Search first.** Search the open stories (command in `references/project-fields.md`, "Search before creating"). A request that duplicates an open story is added to it as a comment. Then search the closed ones for an idea the owner already rejected:
   `gh api -X GET search/issues -f q="repo:$REPO is:issue is:closed reason:\"not planned\" <topic>" --jq '.items[] | "\(.number) \(.title)"'`
   A match is shown to the owner with its number, title and the closing comment that gives the reason. File nothing until the owner decides whether the new request overturns it. Record what you searched and found on the story's `Existing coverage checked:` line.
2. **Classify the work.** A quick fix the session finds on its own, such as a missing fallback or a stale word, is fixed inline with no Project item, and a repo's own quick-wins convention wins. Real new scope is filed before it is built. One request is one story, split only when it would name more than five files. A story that cuts code names a behavior a reader can check, such as one helper with every caller using it and every test still passing, and never a line count, because a builder cannot meet a line target without cutting test protections.
3. **Get a second opinion before the body is written.** When the request changes a repo's files and is not a small change, start one fresh read-only agent (`subagent_type: Explore`) with the owner's request, the repo path and the files to read. Never send it the session's answer, and never fork the session, since a fork inherits that answer. When the two answers differ on fit, size, overlap or approach, name each difference to the owner, recommend one with the reason, and write the story only after the owner picks. When they agree, record `second opinion agreed` on the `Existing coverage checked:` line. A small change starts no second agent.
4. **Write the body** from `references/story-template.md`. Pick the open epic whose goal the request serves. When none fits, file an epic first with `Work type: Epic`: the container whose body lists its stories and carries no `Epic:` line. Answer the fit check in the body: adding to what exists is the default, so the body names what it extends (a new file states why no home fits), whether it is core or an add-on, what it replaces, its effect on size and always-loaded tokens, and whether it passes `$OC/skills/audit/references/lenses.md`.
5. **Check the body** with `python3 scripts/check_story_format.py BODY_FILE --title "TITLE"` and fix every part it prints. A story needs a `Files area:` line, and the check lists each open story that names one of the same files. Add the new scenarios to that story, or name its number in `Existing coverage checked:` and say why the work is separate. `--offline` is for a scan with no network only. In OliverCode, also run `python3 scripts/lib/repo_name_guard.py --text-file BODY_FILE` before any post.
6. **Check its fit, then file it.** Run `olivercode board fit BODY_FILE --title TITLE --config CONFIG` (#1004). It adds one `Related:` line for each open story whose Files area shares a file or folder with this one, and prints each Files area path that is not on main and that no `Creates:` line names. Fix a printed path, or add a `Creates:` line for a new file, and file the story either way. It calls no model. Then create it with the batch command in `references/project-fields.md`.
7. **Set Status, Priority, Size and Work type every time.** Status is `Backlog` when something blocks the item or it needs a decision, and `Ready` when the next action is clear and unblocked. A request the owner wants now goes in `Ready`, and the session starts it after filing. Priority is the audit's scale (P0 to P2, `skills/audit/SKILL.md`, "Priorities"). Priority and Size are a per-item judgment, never copied from a template or left blank. The queue coalesces these writes and accepts them during a hold.
8. **An XL or L item** gets an audit Story first, with a re-runnable command and a before and after count, then one fix Story per boundary (`references/story-template.md`, "Sizing an XL or L item").
9. **Filed from a plan doc?** Copy its reasoning into the issue body once, and delete the plan file in the same pass that files its last Step. Keep it while any Step or open question is unfiled or deferred.

## Work an item

Take items one at a time. Before building, run `git fetch origin main` and list the branches and commits that name the story, since another session may have built it. Read the story in full and check it against the current code, tests and docs, since it may describe a state that has moved. On a conflict, show the owner the differences and wait for a decision. A match goes ahead. When the code has moved, rewrite the story with accurate Gherkin criteria, file prerequisite or follow-on stories through "File a story or epic", and confirm before building.

Run `log_action.py --config CONFIG --story N --check-claim` and skip a story "claimed by" another session. Before editing, set it In Progress and replace `--check-claim` with `--agent SESSION --role claim`.

Read and comment over REST, and spend GraphQL only as `references/project-fields.md` ("Spend GraphQL sparingly") states.

## Log every action

After each commit or finished piece of work, run `python3 scripts/log_action.py --config CONFIG --story N --agent NAME --role builder --commit HASH --files COUNT --result "one line"`. It posts one comment through `gh api`, and `--dry-run` posts nothing. Commit messages carry `(#N)`. Post a "landed in HASH" comment only after `git log -1` confirms the commit, never chained in the same command as the commit.

## Close a story or epic

1. **Complete it** with `python3 scripts/complete_story.py --story N --config CONFIG --evidence "files touched and what shipped"`. It needs a builder entry on the story, and every commit the builder entries name must already be on origin/main, or on the owner's `engineBranch` for an OliverCode checkout (push first; `log_action.py --role builder` refuses an unpushed commit too). A story in the OliverCode repo closes only when the installed checkout at `$OC` holds its commits: a checkout that is behind is updated once with `olivercode update` and checked again, and a story that changes a hook needs that hook entry in `~/.claude/settings.json`. A story whose files define or schedule a launchd job (a `launchd.job` or `launchd.schedule` call, or a plist `Label`) needs that job loaded, and a label listed only as data, such as in the feature register, is not demanded. A story at or above the config's `closeGateFromIssue` also needs `--evidence` to hold a line `Run output:` followed by the output of a live run of the story's own Gherkin scenario, and the comment ends with `Closed by complete_story.py.`, which the sweep's `close-gate` dimension reads. Only then does it post the evidence and close the issue through REST, then set Status to `Complete` and archive the card. The comment ends with a `Live:` line naming the installed commit and each hook entry or job label that proves the fix is active. A refused check changes nothing; a failed write names what landed. A story another session built but never logged needs its builder logged first with `log_action.py --role builder --agent-from-commit --commit HASH`. The issue body is never rewritten, so the comment trail stays the record.
2. **An owner action stays open.** A story only the owner can do (an account sign-in, a device in hand, a purchase) carries the `owner-action` label and a comment with the exact steps. The audit's done check names it for the owner and counts every other open issue as unfinished.
3. **Update the parent epic.** Status does not follow sub-issue progress, so query `subIssuesSummary` (`references/project-fields.md`). All complete: move the parent to `Complete`. A sub-issue deliberately deferred: the parent stays `In Progress` and the comment says why. Some complete, none deferred: move a `Backlog` or `Ready` parent to `In Progress`. Comment the real count either way.

## Sweep the board

The sweep is read-only and changes nothing until the owner approves a fix. A stopped read (a reached limit, a failed call, a GraphQL rate limit) means it did not run, so say so and never report clean.

**After the last filing of a batch**, run only the required-fields and duplicate dimensions once: `python3 scripts/check_board_hygiene.py --config CONFIG --dimension fields --dimension duplicates --no-cache`. The full five-dimension sweep runs when the owner asks for it, when a person raises the backlog ("backlog status", "what needs triage", "groom the backlog", "board hygiene").

When the owner asks for a sweep, read the config path from the repo's `CLAUDE.md` and check all five dimensions unless the owner names one. Open with this message, word for word, with no other opening line and no closing recap.

> A tidy board shows at a glance what to work on next and where each item stands.
>
> I read your live GitHub Project board and report anything out of order across five dimensions. We go through each finding together, and I change nothing until you approve a fix.

`references/project-fields.md` ("Sweep dimensions") holds each rule in full.

Report every finding as one grouped list, or "Nothing due" when clean.

### Clear the findings

Clear required-fields and drift findings through `batch_project.py`, never a per-item edit loop. For a closed issue shown open, close it and queue Status `Complete`, then re-run `drift`.

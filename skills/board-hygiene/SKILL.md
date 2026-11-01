---
name: board-hygiene
description: "Checks the live GitHub Project board across 6 hygiene dimensions together. The six are required-field gaps, Status that disagrees with issue state and more than one card for an issue. They also cover an empty Ready column, stale Area options and ranked Ready candidates. Trigger on \"board hygiene\", \"is the backlog properly prioritized\", \"check the project board\" or \"what should go in Ready\". Name one dimension to scope to it."
---

# Board Hygiene

"Is the backlog properly organized" means all 6 dimensions below, run together. This skill sweeps every open item at once. `backlog-management` sets the fields on the one item it files or closes.

## Opening message

Send this first, in one turn, exactly as written, with no other opening line and no closing recap. A request that names its config path skips the message.

> A tidy board shows at a glance what to work on next and where each item stands.
>
> I read your live GitHub Project board and report anything out of order across 6 dimensions. We go through each finding together, and I change nothing until you approve a fix.
>
> The config path is all I need to start, and naming a dimension you already suspect lets me go straight to it. I also need `gh` installed and signed in.
>
> You can answer in any of these ways:
> 1. Send the path to the repo's `docs/backlog-config.json`, and I will check all 6 dimensions.
> 2. Send that path with one dimension by name: fields, drift, duplicates, ready, area or suggest. I will check only that one.
> 3. Send that path with a skills folder, and I will compare the Area options with its folders.

## The 6 Dimensions

| Dimension | Checks |
|---|---|
| Required fields | Every open item has Priority and Size, plus Work Type and Area where the config defines them |
| Status drift | Board Status matches the issue state: the finished column, such as `Complete` or `Done`, holds only closed issues, and no open column holds one. The board's own column names decide. Every open issue of the config's own repo is on the board |
| Duplicate cards | No issue has more than one card on the board, counted per repo and number (the same number in two repos is two issues) |
| Ready occupancy | The `Ready` column holds at least one item whenever Backlog holds one |
| Area freshness | Every Area option matches a folder directly under the skills root you pass, a reviewed retired label, a parked family, or the `fleet-wide` catch-all. Every such folder has a matching option |
| Ready candidates | Fires only with an empty Ready column and a non-empty Backlog. Ranks Backlog items by Priority then Size, skips any that a keyword scan reads as blocked, and lists up to 5. |

Run `python3 scripts/check_board_hygiene.py --config path/to/backlog-config.json` from this skill's folder. The config is `docs/backlog-config.json` in the repo whose board you check. It holds the project and repo identity and the field IDs. Without `--config`, or with a path that holds no file, the script stops with one line that says so. Add `--dimension fields|drift|duplicates|ready|area|suggest` to run one. Add `--skills-root path/to/skills` to run Area freshness against that folder's direct sub-folders. Without it, Area reports a skip and the other five run. The script needs `gh` on the path, signed in.

Required fields, status drift, duplicate cards and Area freshness are mechanical. A missing field, a status that contradicts the issue, or an orphaned option is never a judgment call. The other two are advisory. An empty Ready column can be right when nothing is unblocked. A suggested candidate can still be blocked in a way no keyword names. Read each advisory finding in context before you act.

## Process

1. Run all 6 dimensions. A closed issue that shows open means someone edited the board and the issue separately. Close the issue and set Status `Complete` together, then re-run `drift`. A GraphQL rate-limit error means the sweep did not run. Say so, never report clean. Ask for one by name to scope to it.
2. Clear each `required-fields`, `status-drift` and `area-freshness` finding directly with `gh project item-edit` or `gh api graphql`.
3. For `ready-occupancy`, read the open Backlog items. Use `ready-candidates` as the shortlist. Pick the unblocked item with the highest priority by `<repo>/docs/PRIORITIZATION.md`, in the repo whose board you check, and read its body before you promote it to `Ready`. An item whose body names an open design question, or leaves design calls to the builder, is not Ready. It needs a `plan` pass first.

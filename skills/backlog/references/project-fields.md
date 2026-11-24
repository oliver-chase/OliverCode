# Command shapes

`CONFIG` below is the path this repo's own `CLAUDE.md` names, per `SKILL.md`'s "Which repo, which config" section. Load it once, at the start of a run.

## Config shape

A new repo and every fork start from `$OC/shared/backlog-config.example.json`, whose `_comment` explains each key. A fork never uses the owner's `docs/backlog-config.json`: the sweep script's `--verify-config` check refuses it.

If a field or option is missing, re-fetch with `gh project field-list <number> --owner <owner> --format json` and update that repo's own config in the same session. Never guess an ID or skip setting a field because the ID isn't there yet.

## Load

```bash
REPO="$(jq -r '.repoOwner' "$CONFIG")/$(jq -r '.repoName' "$CONFIG")"
```

## Create + add + set (queue fields, then one batch)

Filing a story goes through `olivercode board file BODY_FILE --title TITLE --config CONFIG` (#1107), which runs the format check first and creates nothing on a failed check. The commands below are what it runs, for a case it does not cover.

```bash
number=$(gh api -X POST "repos/$REPO/issues" -f title="<title>" -F body=@BODY_FILE --jq .number)
jq -n --argjson n "$number" '{issues: [{number: $n, fields: {status: "Backlog", priority: "P2", size: "S", workType: "Story"}}]}' |
  python3 "$OC/skills/backlog/scripts/batch_project.py" --config "$CONFIG" --input -
```

Create every issue first, then send one batch.

`batch_project.py` validates config options, coalesces requests, adds missing cards, and updates up to
15 fields per mutation. A hold only queues work in `~/.olivercode/gh-project-queue.json`; rerun it
after the hold. Do not loop `gh project item-edit`.

## Search before creating

```bash
gh api -X GET search/issues -f q="repo:$REPO is:issue <topic>" --jq '.items[] | "\(.number) \(.state) \(.title)"'
```

## Spend GraphQL sparingly

`gh project`, `gh issue` and `gh api graphql` share one 5,000-point hourly GraphQL budget across every agent on the machine, and the REST commands above use the core budget. Read an issue, its comments and post a comment through `gh api repos/$REPO/issues/N` (and `.../comments`), and set a story's Status, Priority, Size and Work type in one `batch_project.py` run per story. `olivercode gh-limit report` prints the hour's GraphQL points and REST requests as separate lines, then each by session and command. `gh api rate_limit` costs nothing. `check_board_hygiene.py` reuses a board list under 10 minutes old (`--no-cache` reads live) and stops below 500 points.

## Check a parent Epic's real completion before closing

Status never follows this automatically.

```bash
gh api graphql -f query="{ repository(owner: \"$(jq -r '.repoOwner' "$CONFIG")\", name: \"$(jq -r '.repoName' "$CONFIG")\") { issue(number: <parent>) { subIssuesSummary { total completed } } } }"
```

## List items with fields, for the sweep

```bash
gh project item-list "$(jq -r '.projectNumber' "$CONFIG")" --owner "$(jq -r '.projectOwner' "$CONFIG")" --format json --limit 1000
```

The command stops silently at `--limit`. Compare `jq '.items|length'` with the Project's own total. A count equal to the limit means the list is cut.

## Find one issue's board item

Use this query to read the item ID for one known issue. It costs one GraphQL call. A list of the board costs one call per 100 items. Every session and tool on the account spends the same hourly GraphQL limit. A board of several hundred items spends several calls on each list.

```bash
gh api graphql -f query="{ repository(owner: \"$(jq -r '.repoOwner' "$CONFIG")\", name: \"$(jq -r '.repoName' "$CONFIG")\") { issue(number: <n>) { projectItems(first: 5) { nodes { id project { number } } } } } }"
```

Pick the node whose `project.number` equals `projectNumber` in the config. Read an issue, post a comment and close an issue through the REST API (`gh api repos/<owner>/<repo>/issues/<n>`). REST has its own limit and keeps working when GraphQL runs out.

## Baseline check

`python3 scripts/check_board_hygiene.py --config CONFIG --verify-baseline` reads the Project's field list from `gh`. `--fields-file FILE` compares a saved `gh project field-list --format json` output with no network call. A config with no option ID for a baseline lane such as QA stays valid: add the lane to the Project, then copy its option ID from the field list into the config. `olivercode backlog-setup DIR --apply` makes the changes the check asks for and keeps every item's field values. Built-in workflows do not appear in the field list, so a pull-request workflow on the Project is turned off by hand.

## Sweep dimensions

Each dimension's `--dimension` name is in brackets.

- **Required fields** (`fields`): every open item has Priority and Size, plus Work Type and Area where the config defines them
- **Status drift** (`drift`): the finished column, such as `Complete` or `Done`, holds only closed issues, and no open column holds one. The board's own column names decide. Every open issue of the config's own repo is on the board
- **Duplicate cards** (`duplicates`): no issue has more than one card on the board, counted per repo and number, so the same number in two repos is two issues
- **Close gate** (`close-gate`): every Complete item numbered at or above the config's `closeGateFromIssue` has a comment ending in `Closed by complete_story.py.`, which only `complete_story.py` writes. A story closed through the API, `gh issue close` or the web has none and is listed with the fix: reopen it and run `complete_story.py`. A null or absent key switches the dimension off
- **Grooming** (`groom`): a Backlog or Ready item with a builder entry belongs in QA. An epic whose sub-issues are all closed belongs in the finished column, and one with some closed belongs in In Progress. A Ready epic moves to Backlog, since an epic is never built directly; grooming moves each epic with its stories and comments on it (#1105). Two open stories sharing three or more title words, most of the shorter title, may duplicate each other

The board list, issue lists and comment history are read with explicit limits and pagination. Without `--config`, or with a path that holds no file, the script stops with one line that names the example config a fork starts from.

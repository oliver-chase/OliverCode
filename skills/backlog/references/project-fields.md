# Command shapes

`CONFIG` below is the path this repo's own `CLAUDE.md` names, per `SKILL.md`'s "Which repo, which config" section. Load it once, at the start of a run.

## Config shape

A new repo adopting this skill, and every fork, copies `$OC/shared/backlog-config.example.json` (tracked,
placeholder values) as its starting point. A fork never uses the owner's `docs/backlog-config.json`: the sweep script's `--verify-config` check refuses it. Every `backlog-config.json` this skill reads has
this shape:

```json
{
  "repoOwner": "...",
  "repoName": "...",
  "projectOwner": "...",
  "projectNumber": 1,
  "projectId": "PVT_...",
  "fields": {
    "status": {"id": "...", "options": {"Backlog": "...", "Ready": "...", "In Progress": "...", "QA": "...", "Complete": "..."}},
    "priority": {"id": "...", "options": {"P0": "...", "P1": "...", "P2": "..."}},
    "size": {"id": "...", "options": {"XS": "...", "S": "...", "M": "...", "L": "...", "XL": "..."}},
    "workType": {"id": "...", "options": {"Epic": "...", "Story": "..."}}
  },
  "qaRequiredFromIssue": null,
  "areaPolicy": {"parked": [], "catchAll": []}
}
```

`qaRequiredFromIssue` is optional: set it to an issue number and the `qa-signoff` sweep flags every Complete item at or above that number that lacks an accepted independent QA sign-off, while null or an absent key switches the check off.

`areaPolicy` is optional. It lists the Area options that match no skill folder: `parked` for a family with no folder in the repo, `catchAll` for cross-family work.

If a field or option is missing, re-fetch with `gh project field-list <number> --owner <owner> --format json` and update that repo's own config in the same session. Never guess an ID or skip setting a field because the ID isn't there yet.

## Load

```bash
PROJECT_ID=$(jq -r '.projectId' "$CONFIG")
REPO="$(jq -r '.repoOwner' "$CONFIG")/$(jq -r '.repoName' "$CONFIG")"
STATUS_ID=$(jq -r '.fields.status.id' "$CONFIG")
```

## Create + add + set (one field, repeat per field)

```bash
url=$(gh issue create --repo "$REPO" --title "<title>" --body "<body>")
item_id=$(gh project item-add "$(jq -r '.projectNumber' "$CONFIG")" --owner "$(jq -r '.projectOwner' "$CONFIG")" --url "$url" --format json | jq -r .id)
gh project item-edit --id "$item_id" --project-id "$PROJECT_ID" \
  --field-id "$STATUS_ID" --single-select-option-id "$(jq -r '.fields.status.options.Backlog' "$CONFIG")"
```

## Search before creating

```bash
gh issue list --repo "$REPO" --search "<topic>" --state all
```

## Comment on close

```bash
gh issue comment <number> --repo "$REPO" --body "<evidence>"
gh issue close <number> --repo "$REPO" --reason completed
```

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

- **Required fields**: every open item has Priority and Size, plus Work Type and Area where the config defines them
- **Status drift**: the finished column, such as `Complete` or `Done`, holds only closed issues, and no open column holds one. The board's own column names decide. Every open issue of the config's own repo is on the board
- **Duplicate cards**: no issue has more than one card on the board, counted per repo and number, so the same number in two repos is two issues
- **QA sign-off**: every Complete item numbered at or above the config's `qaRequiredFromIssue` has an accepted independent sign-off, as `check_qa_signoff.py` defines it. A null or absent key switches the dimension off

The board list, issue lists and comment history are read with explicit limits and pagination. Without `--config`, or with a path that holds no file, the script stops with one line that names the example config a fork starts from.

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
  "areaPolicy": {"retired": [], "parked": [], "catchAll": []}
}
```

`areaPolicy` is optional. It lists the Area options that match no skill folder: `retired` for frozen labels on Complete items, `parked` for a family with no folder in the repo, `catchAll` for cross-family work.

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

# Command shapes

`CONFIG` below is the path this repo's own `CLAUDE.md` names, per `SKILL.md`'s "Which repo, which config" section. Load it once, at the start of a run.

## Config shape

Every `backlog-config.json` this skill reads has this shape:

```json
{
  "repoOwner": "...",
  "repoName": "...",
  "projectOwner": "...",
  "projectNumber": 1,
  "projectId": "PVT_...",
  "fields": {
    "status": {"id": "...", "options": {"Backlog": "...", "Ready": "...", "In Progress": "...", "Complete": "..."}},
    "priority": {"id": "...", "options": {"P0": "...", "P1": "...", "P2": "..."}},
    "size": {"id": "...", "options": {"XS": "...", "S": "...", "M": "...", "L": "...", "XL": "..."}},
    "workType": {"id": "...", "options": {"Epic": "...", "Story": "..."}}
  }
}
```

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

## List items with fields, for the triage check

```bash
gh project item-list "$(jq -r '.projectNumber' "$CONFIG")" --owner "$(jq -r '.projectOwner' "$CONFIG")" --format json --limit 200
```

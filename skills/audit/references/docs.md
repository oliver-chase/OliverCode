# Docs

Every document in scope, checked against what it describes. A doc is a claim about the system, and the code decides. Trust in this order: live code and config, tool output, git history, a configured GitHub Project's live state, then docs. A doc that looks authoritative, with dates, status labels or line numbers, is no more likely to be right.

## Steps

1. **Find the likeliest drift.** List every doc with its last change, and compare it with recent commits in the area it describes. A doc untouched while its area changed often is read first:

```bash
git ls-files '*.md' | while read f; do printf "%s %s\n" "$(git log -1 --format=%ad --date=short -- "$f")" "$f"; done | sort
git log --oneline -20
```

2. **Read every doc in full**, and list its checkable claims: paths, commands, flags, env vars, counts, routes, schedules, status labels and "required files" lists
3. **Check each claim** against its source:

| Claim | Check against |
|---|---|
| A command or flag | The CLI's `--help`, `package.json` scripts, or the script's argument parser |
| A path or required file | The file tree |
| A count, such as gates, tests or migrations | The command that counts it, never the doc's number |
| An env var | The example env file and the code that reads it |
| A schedule | The scheduler config itself, including its comments |
| A CI or deploy step | The workflow file |
| An issue or ticket ID | The issue itself |
| A status ("active", "done") | The code and the backlog |

4. **Find contradictions.** Grep each key fact across all docs. The same fact in two files is a finding even when both agree today, since one goes wrong at the next change
5. **Check the backlog** where the repo names one: its open items against what the docs say is open or done
6. **Plan the structure.** Each fact gets one home, and every other file points to it by name. Before merging or removing a doc, grep code, scripts, CI and templates for its path, so the change updates every reference

## Leave alone

- A dated log or evidence entry is a record, so fix only live links in it
- An example, fixture or template may break a content rule on purpose
- A feature the doc describes may no longer matter. Check whether it is used before polishing its description, since the right fix may be to cut it

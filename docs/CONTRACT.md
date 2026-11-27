# Contract

A conforming repo matches every requirement below, and nothing else about it is constrained. Each requirement guards a failure that can lose work, leak data or break a gate, and has one entry with its check and the command that fixes a miss. Words follow `docs/VOICE.md`, and `docs/RULES.md` holds the reasoning behind each requirement.

No command checks these requirements across repos any more. `olivercode health` checks the `hooks` requirement for OliverCode and each repo in `privateRepos`, and validation checks `engine-only`. The owner reviews the rest.

## What must match

| Id | Requirement | Check | Fix |
|---|---|---|---|
| `ignore` | The repo's `.gitignore` makes git ignore an env file, a `.pem`, a `.key` and a `.secrets` file, by whatever pattern | a manual check | Add the missing lines |
| `validation` | One validation command, `bash scripts/validate.sh` from the repo root (or `npm run validate` or `npm run check`), named in the repo's `CLAUDE.md` ("Execution" in `docs/RULES.md`) | a manual check | Add `scripts/validate.sh` and name it in the repo's `CLAUDE.md` |
| `engine-only` | An engine checkout (a repo that ships `scripts/lib/engine_only.py`) holds no personal file: no machine config, filled-in registry, memory, story, queue item or file naming a fleet repo is tracked or sitting untracked and unignored | a manual check, which runs the engine-only check on the checkout | Move the listed file to the private fleet repo |
| `fleet-private` | The private fleet repo found through the configured fleet path is private and has no collaborator beyond its owner; the check runs once, on the engine checkout, and skips offline | a manual check, which asks GitHub for the repo's visibility and collaborators | `gh repo edit <owner>/<repo> --visibility private --accept-visibility-change-consequences`, and remove each collaborator in the repo settings |
| `sleep-setting` | No `pmset -g` system sleep timer would stop a session on this Mac; the check runs once, on the engine checkout, and skips off macOS | a manual check, which reads `pmset -g` | In System Settings, open Battery or Energy and turn off sleep on power adapter and display sleep, or run `caffeinate -dimsu` before leaving |
| `board` | The board runs the kanban baseline in `shared/kanban-baseline.json`, and every request is a story with Gherkin criteria under an epic ("The backlog" in `docs/RULES.md`) | a manual check | `olivercode backlog-setup <repo> --apply` |
| `issues` | No open issue of the OliverCode repo names a fleet repo in its title or body, so the public board never leaks one; the check reads open issues over REST, runs on the OliverCode checkout and skips offline | a manual check, which reads the open issues through `gh api` | Reword the title and body of each named issue so it says another repo, then read the issue again |
| `hooks` | The commit gates in `docs/GATES.md` run on every commit, with `core.hooksPath` set to `.githooks` | a manual check | `olivercode sync-hooks` |
| `permission-policy` | The repo has `.olivercode/policy.json`, the list of what a session may do without asking | a manual check | `olivercode policy init <repo>` |
| `unfinished-work-snapshot` | The Claude settings on this machine run `wip_save.py`, which saves work not yet landed; the check runs once, on the engine checkout | a manual check, which reads `~/.claude/settings.json` | `olivercode install` |
| `managed-files` | Managed files stay byte-identical to the templates the bootstrap manifest marks strict ("Project structure" in `docs/RULES.md`) | a manual check | `olivercode bootstrap <repo>` |
| `tests` | A repo with code has at least one tracked test file | a manual check | Add a test for the code that matters most |
| `branches` | origin holds only its default branch, so a stray branch is found within a day ("The backlog" in `docs/RULES.md`) | a manual check, which reads origin with `git ls-remote` and skips offline | `olivercode clean --apply` for the merged branches, and delete the rest |
| `delete-on-merge` | GitHub deletes a pull request's branch when it merges | a manual check, which reads the repo's GitHub setting and skips offline | `gh repo edit OWNER/REPO --delete-branch-on-merge` |

## What may differ

- Language and toolchain, because the validation command wraps whatever the repo uses
- The product itself, including its code, its runtime files and its README
- The gate count, as `docs/GATES.md` sets for adopted, private and OliverCode repos

## Exceptions

A repo that must differ from a requirement records the exception in its own `docs/repo-structure-contract.md`, under the heading "Contract exceptions". Each entry is one line, `- <id>: <reason>. Expires YYYY-MM-DD`, where `<id>` is a requirement id from the table. An entry with no reason or a past expiry is a failure.

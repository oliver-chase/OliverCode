# Contract

A conforming repo matches every requirement below, and nothing else about it is constrained. Each requirement has one entry with its check and the command that fixes a miss. Words follow `docs/VOICE.md`, and `docs/RULES.md` holds the reasoning behind each requirement.

`olivercode conform [DIR]` runs every check below on one repo, or on every registered repo when it gets no directory. It prints pass, fail, exception, manual or skip per requirement with the fix command, and it exits non-zero on any fail. `--offline` skips the checks that call GitHub.

## What must match

| Id | Requirement | Check | Fix |
|---|---|---|---|
| `layout` | Layout: `README.md`, `CLAUDE.md`, `docs/repo-structure-contract.md` and a `docs/backlog-config.json`, with every other document in `docs/` ("Project structure" in `docs/RULES.md`) | olivercode conform | `olivercode bootstrap <repo>` |
| `validation` | One validation command, `bash scripts/validate.sh` from the repo root, named in the repo's `CLAUDE.md` ("Execution" in `docs/RULES.md`) | olivercode conform | Add `scripts/validate.sh` and name it in the repo's `CLAUDE.md` |
| `board` | The board runs the kanban baseline in `shared/kanban-baseline.json`, and every request is a story with Gherkin criteria under an epic ("The backlog" in `docs/RULES.md`) | olivercode conform | `olivercode backlog-setup <repo> --apply` |
| `hooks` | The commit gates in `docs/GATES.md` run on every commit, with `core.hooksPath` set to `.githooks` | olivercode conform | `olivercode sync-hooks` |
| `managed-files` | Managed files stay byte-identical to the templates the bootstrap manifest marks strict ("Project structure" in `docs/RULES.md`) | olivercode conform | `olivercode bootstrap <repo>` |
| `size` | The size baseline in `docs/SIZE-BASELINE.json`, with the counter the ratchet gate runs ("Size ratchet" in `docs/GATES.md`) | olivercode conform | `olivercode bootstrap <repo>`, then `olivercode size <repo> --lower` |
| `tests` | Tests per 100 lines of code, measured by `skills/audit/scripts/size.sh`. The minimum is not yet set, because no fleet-wide ratio is measured | conform prints it as manual: `bash skills/audit/scripts/size.sh <repo>` measures the ratio | Add tests in the story that changes the code |
| `docs` | The doc set and README order ("Documents" in `docs/RULES.md`) and a filled-in GitHub About | olivercode conform checks the GitHub About, and `bash scripts/validate.sh` checks references | `gh repo edit --description ... --add-topic ...` |
| `audit` | The audit and cleanup routine: the `audit` skill runs on the commits of a multi-commit session and keeps the live tracker current | Manual: conform lists it and runs nothing | The `audit` skill |

## What may differ

- Absolute size, because the ratchet compares a repo with its own baseline and never with another repo
- Language and toolchain, because the validation command wraps whatever the repo uses
- The product itself, including its code, its runtime files and its README sections beyond the required order
- The gate count, as `docs/GATES.md` sets for adopted, private and OliverCode repos

## Exceptions

A repo that must differ from a requirement records the exception in its own `docs/repo-structure-contract.md`, under the heading "Contract exceptions". Each entry is one line, `- <id>: <reason>. Expires YYYY-MM-DD`, where `<id>` is a requirement id from the table. The conformance check reports an exception as an exception, and reports an entry with no reason or a past expiry as a failure.

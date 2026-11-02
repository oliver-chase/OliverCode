# Contract

A conforming repo matches every requirement below, and nothing else about it is constrained. Each requirement has one entry with its check and the command that fixes a miss. Words follow `docs/VOICE.md`, and `docs/RULES.md` holds the reasoning behind each requirement.

A check or fix marked "pending" has no command yet. Story #108 builds the one conformance command that runs every check and reports each repo pass or fail per item with its fix, and it replaces the pending marks with real commands.

## What must match

| Requirement | Check | Fix |
|---|---|---|
| Layout: `README.md`, `CLAUDE.md`, `docs/repo-structure-contract.md` and a `docs/backlog-config.json`, with every other document in `docs/` ("Project structure" in `docs/RULES.md`) | Pending | `olivercode bootstrap <repo>` |
| One validation command, `bash scripts/validate.sh` from the repo root, named in the repo's `CLAUDE.md` ("Execution" in `docs/RULES.md`) | Pending | Pending |
| The board runs the kanban baseline in `shared/kanban-baseline.json`, and every request is a story with Gherkin criteria under an epic ("The backlog" in `docs/RULES.md`) | `olivercode health`, Backlog boards section | `olivercode backlog-setup <repo> --apply` |
| The commit gates in `docs/GATES.md` run on every commit, with `core.hooksPath` set to `.githooks` | `olivercode health --hooks-only` | `olivercode sync-hooks` |
| Managed files stay byte-identical to the templates the bootstrap manifest marks strict ("Project structure" in `docs/RULES.md`) | `olivercode health` | `olivercode bootstrap <repo>` |
| The size baseline in `docs/SIZE-BASELINE.json`, with the counter the ratchet gate runs ("Size ratchet" in `docs/GATES.md`) | `olivercode size <repo>` | `olivercode bootstrap <repo>`, then `olivercode size <repo> --lower` |
| Tests per 100 lines of code, measured by `skills/audit/scripts/size.sh`. The minimum is not yet set, and #108 sets it from the fleet's measured ratios | `bash skills/audit/scripts/size.sh <repo>` | Add tests in the story that changes the code |
| The doc set and README order ("Documents" in `docs/RULES.md`) and a filled-in GitHub About | `olivercode health` for the About, `bash scripts/validate.sh` for references. The rest is pending | Pending |
| The audit and cleanup routine: the `audit` skill runs on the commits of a multi-commit session and keeps the live tracker current | Pending | `audit` skill |

## What may differ

- Absolute size, because the ratchet compares a repo with its own baseline and never with another repo
- Language and toolchain, because the validation command wraps whatever the repo uses
- The product itself, including its code, its runtime files and its README sections beyond the required order
- The gate count, as `docs/GATES.md` sets for adopted, private and OliverCode repos

## Exceptions

A repo that must differ from a requirement records the exception in its own `docs/repo-structure-contract.md`, under the heading "Contract exceptions". Each entry names the requirement, gives the reason and gives an expiry date. The conformance check reports an exception as an exception, and reports an entry with no reason or a past expiry as a failure.

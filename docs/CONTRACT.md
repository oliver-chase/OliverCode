# Contract

A conforming repo matches every requirement below, and nothing else about it is constrained. Each requirement has one entry with its check and the command that fixes a miss. Words follow `docs/VOICE.md`, and `docs/RULES.md` holds the reasoning behind each requirement.

`olivercode conform [DIR]` runs every check below on one repo, or on every registered repo when it gets no directory. It prints pass, fail, exception, manual or skip per requirement with the fix command, and it exits non-zero on any fail. `--offline` skips the checks that call GitHub.

## What must match

| Id | Requirement | Check | Fix |
|---|---|---|---|
| `layout` | Layout: `README.md`, `CLAUDE.md`, `docs/repo-structure-contract.md` and a `docs/backlog-config.json`, with every other document in `docs/` ("Project structure" in `docs/RULES.md`) | olivercode conform | `olivercode bootstrap <repo>` |
| `ignore` | The repo's `.gitignore` makes git ignore an env file, a `.pem`, a `.key` and a `.secrets` file, by whatever pattern | olivercode conform | Add the missing lines |
| `readme` | README.md opens with a title and keeps its Install, Documentation, Status and License sections in that order | olivercode conform | Reorder the sections |
| `folders` | Every top-level folder besides `docs/` and `scripts/` is named in the repo's `docs/repo-structure-contract.md` | olivercode conform | List the folder with its purpose under "Required structure" |
| `validation` | One validation command, `bash scripts/validate.sh` from the repo root (or `npm run validate` or `npm run check`), named in the repo's `CLAUDE.md` ("Execution" in `docs/RULES.md`) | olivercode conform | Add `scripts/validate.sh` and name it in the repo's `CLAUDE.md` |
| `queue-bypass` | Validation runs through the one queued entry point: the repo has no tracked script that starts its tests or `validate.sh` around the queue, `scripts/validate.sh` holds the queue block, and a repo that ships `scripts/lib/queue_bypass.py` still runs it from `scripts/validate.sh` | olivercode conform, which runs the queue bypass check on the repo | `olivercode sync-hooks` for a missing queue block, and `bash scripts/validate.sh` for every other start |
| `engine-only` | An engine checkout (a repo that ships `scripts/lib/engine_only.py`) holds no personal file: no machine config, filled-in registry, memory, story, queue item or file naming a fleet repo is tracked or sitting untracked and unignored | olivercode conform, which runs the engine-only check on the checkout | Move the listed file to the private olivercode-fleet repo |
| `fleet-private` | The private fleet repo found through the configured fleet path is private and has no collaborator beyond its owner; the check runs once, on the engine checkout, and skips offline | olivercode conform, which asks GitHub for the repo's visibility and collaborators | `gh repo edit <owner>/<repo> --visibility private --accept-visibility-change-consequences`, and remove each collaborator in the repo settings |
| `sleep-setting` | No `pmset -g` display or system sleep timer would stop a session on this Mac; the check runs once, on the engine checkout, and skips off macOS | olivercode conform, which reads `pmset -g` | In System Settings, open Battery or Energy and turn off sleep on power adapter and display sleep, or run `caffeinate -dimsu` before leaving |
| `board` | The board runs the kanban baseline in `shared/kanban-baseline.json`, and every request is a story with Gherkin criteria under an epic ("The backlog" in `docs/RULES.md`) | olivercode conform | `olivercode backlog-setup <repo> --apply` |
| `hooks` | The commit gates in `docs/GATES.md` run on every commit, with `core.hooksPath` set to `.githooks` | olivercode conform | `olivercode sync-hooks` |
| `managed-files` | Managed files stay byte-identical to the templates the bootstrap manifest marks strict ("Project structure" in `docs/RULES.md`) | olivercode conform | `olivercode bootstrap <repo>` |
| `dead-selftest` | No `ste-lint-joined.py` in the repo's hooks folder, the selftest of the retired STE gates | olivercode conform | `git rm` the file |
| `tests` | A repo with code has at least one tracked test file | olivercode conform | Add a test for the code that matters most |
| `docs` | The doc set and README order ("Documents" in `docs/RULES.md`) and a filled-in GitHub About | olivercode conform checks the GitHub About, and `bash scripts/validate.sh` checks references | `gh repo edit --description ... --add-topic ...` |
| `learning` | A self-learning loop: the repo's structure contract answers the five steps under "Learning loop" | olivercode conform | Fill in the section, or record an exception when the repo has no results to read |
| `research` | Each file in a repo's research folder (docs/research) has an `applied:` line naming the file in code, data or a skill that carries its findings, or `applied: none, because <reason>` | olivercode conform | Build the finding into code or data, then add the line |
| `audit` | The audit and cleanup routine: the `audit` skill runs when the owner asks for it and keeps the live tracker current | olivercode conform passes when `docs/AUDITED.txt` has content and lists it as manual otherwise | The `audit` skill |
| `automation` | Each script a launchd job or scheduled task runs from the repo is tracked by the repo's git, so a local automation ships inside a repo | olivercode conform | `git add` the script and commit it |
| `live-launcher` | OliverCode does not run from a path `liveCopies` in `olivercode.local.json` lists as live, so an update never writes into a running bot | olivercode conform, which `install` also runs first | Run olivercode from the agent copy the failure names |
| `branches` | origin holds only its default branch, so a stray branch is found within a day ("The backlog" in `docs/RULES.md`) | olivercode conform, which reads origin with `git ls-remote` and skips offline | `olivercode clean --apply` for the merged branches, and delete the rest |
| `delete-on-merge` | GitHub deletes a pull request's branch when it merges | olivercode conform, which reads the repo's GitHub setting and skips offline | `gh repo edit OWNER/REPO --delete-branch-on-merge` |
| `features` | Every feature in `docs/STANDARDS.json` that is not owner-only is on for the repo: board baseline, story template, Area label, commit gates, permission policy, owner queue, burndown, decision records, lessons and retro, nightly sweep, groom schedule, the daily maintenance job, headless builders, worktree cleanup, the unfinished-work snapshot, gap sweep, fleet sync, GitHub write replay and version cut | `olivercode features --repo NAME`, which `conform` reads and which fails naming each enable command. A scheduled job whose last run failed or is older than twice its interval counts as off, shown failing or stale. A feature retired with `--retire NAME --reason TEXT` passes and is listed with its reason | The enable command each off row prints |
| `machines` | Every machine that recorded itself in `.olivercode/machines/` runs the newest OliverCode version and has the commit gates and the permission policy, so every machine that works on a repo follows the same protocol | `olivercode machines show`, which `conform` reads and which fails naming each machine that differs | `olivercode update`, `olivercode sync-hooks` and `olivercode policy init` on the named machine, then `olivercode machines record` |

## Learning loop

A repo that acts and can read what happened keeps the loop a shop runs, where decisions are logged, judged on a review day and kept or reverted. `docs/repo-structure-contract.md` holds a "Learning loop" section with one line per step, each naming the file or script that does it:

- Record: each action the repo takes on its own, with the date, the reason and the metric it should move, in a file the repo owns
- Read: the result on the review day, over a window before the change and the same window after it
- Compare: the result against a market or peer signal, so a rise everyone had does not count as a win
- Decide: keep the change or revert it, and log the verdict with its reason. Only the owner may keep a change that made the metric worse
- Thin data: report "no trend yet" when fewer than seven days of readings or too little volume back a window, and decide nothing
- Lessons: each incident goes in the repo's lesson log, which stays on this device under `~/.olivercode/lessons` and never in the checkout, with what happened, why and the rule that holds now, and `olivercode retro` adds a candidate for every lesson with no check and marks it covered, and the owner promotes a candidate to the board with `olivercode candidates promote`

A repo with nothing to measure, such as a static site with no analytics, records that as a `learning` exception.

## What may differ

- Language and toolchain, because the validation command wraps whatever the repo uses
- The product itself, including its code, its runtime files and its README sections beyond the required order
- The gate count, as `docs/GATES.md` sets for adopted, private and OliverCode repos

## Exceptions

A repo that must differ from a requirement records the exception in its own `docs/repo-structure-contract.md`, under the heading "Contract exceptions". Each entry is one line, `- <id>: <reason>. Expires YYYY-MM-DD`, where `<id>` is a requirement id from the table. The conformance check reports an exception as an exception, and reports an entry with no reason or a past expiry as a failure.

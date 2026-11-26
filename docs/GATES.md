# Gates

This file lists every check that can block a commit or a push, what each blocks and which repos run it. A failed gate blocks the commit.

The gates guard against honest mistakes and careless agents. A commit that rewrites the hooks in the same commit is out of scope, because git runs the hook from the working tree, and `olivercode conform` catches a changed hook afterwards.

## Validation

`bash scripts/validate.sh` runs every active check from the repo root:

- With no argument it runs the pre-commit gates, the fleet name check, reference integrity (`scripts/link-check.sh`), the docs check, the size warning (`olivercode limits check`, which never fails the run), the bloat and code quality checks, the queue bypass check, and the tests
- `--tree` is the same as no argument, because the pre-commit gates always scan every tracked file; any other unknown option exits 2 and records nothing
- `--check-consistency` runs the fleet name check only
- `--rehearse` rehearses the install in sandboxes (`scripts/qa/rehearse-install.sh`)
- `bash scripts/run-tests.sh` runs the test suite from a clean clone of HEAD under a temporary HOME, inside one validation queue slot

### Throughput and the one entry point

Every validation waits in the per-user queue, so at most a few run at once however many builders, landings and hooks ask. `bash scripts/validate.sh` is the one entry point: its managed block takes a slot before any gate starts, and `olivercode land`, the builders, `fleet-sync`, the audit's done check and conform all start validation through it.

- The gates that share no state (pre-commit, fleet names, bloat, code quality, references, docs, size limits, queue bypass, smoke tests and hook state) run in parallel inside the run's one slot, at most `OLIVERCODE_VALIDATE_GATES` at once (default: the core count). A `=== validate: gate ... ===` line prints as each gate starts and as it finishes with its seconds, and `olivercode land` shows the same lines while its full log fills. Their output replays in the order above with the same `=== validate: ... ===` lines, and any failing gate fails the run with that gate's exit code. The smoke tests run one process per test module, `OLIVERCODE_VALIDATE_JOBS` at a time (default: the core count)
- The slot count is `OLIVERCODE_VALIDATE_SLOTS`, default an eighth of the machine's cores and at least 1, so an 8-core machine runs one validation at a time. A slot is reclaimed when its holder is gone or its pid belongs to another process, and a slot held for more than 4 hours is reaped even when its holder lives. A run that has waited an hour goes ahead and says so on stderr. Missing, old and damaged state is repaired with a line that names the repair
- A run keeps a time budget of `OLIVERCODE_VALIDATE_TIMEOUT` seconds (default 5 minutes, set from measured runs with headroom and scaled up to twice by the machine's load per core). Past it, the run stops the gates still running and fails with exit 124 and a line that names each one, its seconds and the load, with the command that reruns that gate alone
- The queue bypass gate (`scripts/lib/queue_bypass.py`) fails when a tracked `scripts/validate.sh` has no queue block, when a script starts the test suite (`python3 -m unittest`, `pytest`, `npm test`, `run-tests.sh`) outside the queue, or when a script starts `validate.sh` with its queue variables replaced. The finding names the script and line and the entry point to use. Tests, docs and Markdown may name these commands. `olivercode conform` runs the same check on every registered repo and fails a repo whose `validate.sh` no longer runs it, and the docs check fails when a gate script this file names has no script or hook that runs it

Hook drift fails validation: OliverCode's hook, the public template and the private template run the same gates, each gate's body lives once in `core/hooks/gates/`, and `scripts/build-hooks.py` assembles the four hooks (two pre-commit templates, pre-push and commit-msg) from one ordered gate list. The built hooks are untracked, and install, bootstrap, sync-hooks, conform and `validate.sh` build them before reading them.

`validate.sh` also reports fleet hook state through `olivercode conform --offline --hooks-only`. That report is advisory, because hook enforcement fails open: a repo with an unset or broken `core.hooksPath` runs no gates and prints nothing.

`.github/workflows/framework-ci.yml` runs health, `validate.sh` and the install rehearsal on push and pull request. It is paused on the origin repo while GitHub Actions billing is blocked, so the local commands are the enforcement.

## Commit gates

Each row gives the gate's number in OliverCode's hook, in an adopted repo's hook and in the private variant, and a dash where that hook does not run it.

| Gate | What it blocks | OliverCode | Adopted repo | Private variant |
|------|---------------|:---:|:---:|:---:|
| Secrets | API keys, tokens, JWTs and private keys in any staged file. A placeholder passes by its value, such as `EXAMPLE` or a run of `x`, or on a line that carries `secret-scan: allow` | 1 | 1 | 1 |
| PII | Host paths, email addresses and personal data in staged code and config. Tests and files named as mocks, `*.env.example`, `.gitignore`, `docs/PII-GATE.json` and `.githooks/*` are skipped, and a repo lists files that must hold a pattern under `exempt` in `docs/PII-GATE.json`, each with a reason | 2 | 2 | — |
| Owner identifiers | A staged file that names an identifier the gate derives from git and config, described below. Markdown and tests are scanned. It names the file and line, and skips where nothing can be derived | 3 | 3 | 2 |
| Version files | A staged `VERSION` or `CHANGELOG.md`. The daily cut (`olivercode version-cut`) sets `OLIVERCODE_VERSION_CUT=1` for its own commit, and `validate.sh --tree` skips the gate because it stages nothing (`docs/VERSIONING.md`) | after 3 | after 3 | after 2 |

`sync-hooks` deploys `core/templates/project/pre-commit` to every fleet repo, and `core/templates/project/pre-commit-private` to every repo in `privateRepos` in `olivercode.local.json` and every fleet repo whose profile sets `"private": true`. A repo with its own hook declares `hookVariant: "<reason>"` in its profile (`shared/repo-profiles.json`), which makes `sync-hooks` skip it and `conform` pass it with a note.

The private variant drops the PII gate because a private repo holds personal data by design. `build-hooks.py` generates OliverCode's own hook and the two templates and never a variant repo's hook.

A gate reads its config (`docs/PII-GATE.json`, `docs/IDENTIFIER-GATE.json`) from HEAD, so a commit that edits the config does not exempt itself. Bootstrap writes the public variant, which runs the PII gate, when it cannot read a repo's visibility.

### Owner identifiers

The gate builds its identifiers from `git log` authors (the full author name as one phrase, plus each email local part), from the owner segment of the `origin` remote, and from the string values of account, shop, store, handle, username, owner, brand and seller keys in the files that `configGlobs` lists. Noreply addresses, bots, Claude, GitHub and Anthropic are ignored. Matching is lowercase on whole words, for identifiers of 5 characters or more.

`docs/IDENTIFIER-GATE.json` holds two lists. `configGlobs` names config files to read and ships empty. `localData` names files that may hold an identifier, each with a reason under `localDataReasons`. Built in as local data are `.secrets/`, `scratch/`, `.githooks/`, `docs/backlog-config.json` and the config file itself.

### Repo-local hook

A repo adds its own blocking checks in an executable `pre-commit.local` file beside the hook in `.githooks/`. `sync-hooks` never writes or overwrites that file. The private hook runs it after its numbered gates with the staged file list on stdin, and a non-zero exit blocks the commit.

A repo can also list checks in `docs/SUITE-CHECKS.json`, as `{"checks": [{"name", "files": [globs], "command"}]}`. Every variant runs each check on the staged files that match its globs.

### Commit guard limits

Inside Claude Code, `scripts/hooks/commit_guard.py` refuses `--no-verify` and `-n` in any form git accepts, a `core.hooksPath` override, a commit wrapped in `bash -c` or `eval`, and a `git -c alias.NAME=...` alias that commits with a hook skip. It cannot see a commit run through a shell function, a variable, command substitution, a shell alias, a configured git alias or a pipe into `sh`, where the pre-push secret scan still applies.

## Commit-message gate

Git shows a commit message only to the `commit-msg` hook, so these checks are a hook of their own. The hook runs every check, prints every blocking finding together with a count and refuses once at the end. `olivercode commit-check FILE_OR_TEXT` runs the same checks on a draft message in the current repo, commits nothing, queues no card and logs no refusal, so a builder sees every finding before committing. Every repo that `sync-hooks`, `olivercode bootstrap` or `olivercode backlog-setup` manages gets the same one, and `conform` fails a repo whose `commit-msg` copy is missing or differs from the template.

| Gate | What it blocks |
|------|---------------|
| Story reference | A commit whose message has no `#<number>`, such as `(#53)`. A `fixup!`, `squash!`, `amend!` or revert message that names an existing commit is exempt, as is a merge that stages no code and a repo's first commit. The hook blocks when it cannot read the message file |
| Story exists | A reference to a story absent from its repo: `#N` is checked in the repo that `docs/backlog-config.json` names and `owner/repo#N` in the repo it spells out, through `gh api`. It fails open with a warning when `gh` or GitHub is unavailable, and a repo without the config skips it |
| Test with code | A commit that changes any file outside a test path except documentation and data (such as `.md`, `.json`, `.csv`, `.html` and `LICENSE`) and changes no test, unless the message has a line `No test: <reason>` |
| Co-author form | A `Co-Authored-By` line in any other form than `Co-Authored-By: Name <email>`, or a Claude co-author without Anthropic's noreply address. A commit with no co-author line passes |
| Other repo names | In an OliverCode checkout only, a message that names a repo from the local registry. The hook says to write "another repo" instead. `log_action.py` and `complete_story.py` refuse the same text before they post, and `python3 scripts/lib/repo_name_guard.py --scan-issues` lists the issues that already name one |
| Closes card | A message with `closes #N` or `resolves #N` queues Status Complete for that card through `batch_project.py`, and refuses the commit with the fix when the config or the backlog scripts are missing or the queue rejects the request. A bare `(#N)` queues nothing |
| Voice (warning) | In a repo that ships `docs/VOICE.md`, a bullet that ends in a period or a contrast phrase such as "rather than" or "instead of" prints a warning. It never blocks and is not counted as a finding |

A repo opts out only when its owner commits a file named `commit-msg.optout` in the folder git reads hooks from. The file counts once HEAD holds it, and every commit it lets through prints that the check is off.

## Pre-push gates

Every repo that `sync-hooks` manages gets one pre-push hook, the same for every variant.

| Gate | What it blocks |
|------|---------------|
| History rewrite | A push that would rewrite an existing remote branch. `ALLOW_FORCE_PUSH=1` allows a deliberate one |
| Secrets | A secret in any commit the push sends, including a merge resolution and a secret added and removed again inside the range |
| WIP subject | A push that sends a commit whose subject starts with WIP. Reword the commit after validating, or save the work with `olivercode wip` |
| Validated on record | A push to `main` or `master` whose tree has no passing full validation under 7 days old (`olivercode validated check`). `OLIVERCODE_ALLOW_UNVALIDATED_PUSH=1` overrides it |

The secret patterns live once in `core/hooks/secret-patterns.sh`, and `scripts/build-hooks.py` builds them into both the commit gate and the push hook. The pre-push hook also refuses a push of any branch other than the default (`ALLOW_BRANCH_PUSH=1` overrides one command).

## Repeated blockers

The daily `olivercode board groom --all`, which `maintain --fix` runs, reads the failure log with no model call. A gate and reason that appear 3 or more times file one story, "Prevent the repeated block: ...", naming the blocker and its occurrences. An open story for the same blocker gets each new occurrence as a comment, and a blocker seen twice files nothing.

## Engine-only check

The engine-only check, `scripts/lib/engine_only.py`, keeps an OliverCode clone free of personal files. The commit gate runs it through `docs/SUITE-CHECKS.json` and refuses a staged config, filled-in registry, memory file, story, queue item or file that names a fleet repo, with a message that points at the private olivercode-fleet repo. `olivercode conform` runs the same check on the whole checkout and fails with the file and the fix

## Rename check

A rename story carries a line `Renames: OLD -> NEW` in its body. `complete_story.py` refuses to close it while OLD still appears in a tracked line of scripts, docs, tests, launchd plists or the feature register, and it lists each file and line. A line that says "alias", "formerly" or "renamed from", and any history file, are skipped. `olivercode board groom` tells the owner about an open rename story that has no `Renames:` line. The check lives in `scripts/lib/rename_check.py`.

## Name check

`olivercode board groom` compares each command, job label and file name in a tracked README with the heading it sits under, and tells the owner about every pair that reads differently, with the fix: use one name in both. A heading and an identifier belong together when the heading's section names exactly one identifier, or when the identifier is followed by the heading's name in brackets. No model runs. The check lives in `scripts/lib/name_drift.py`.

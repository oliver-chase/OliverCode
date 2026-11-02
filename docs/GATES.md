# Gates

Every check that can block a commit or a push, what it blocks and which repos run it. A failed gate blocks the commit, and no bypass mode exists.

## Validation

`bash scripts/validate.sh` runs every active check from the repo root:

- `bash scripts/validate.sh` runs the pre-commit gates, doc and code consistency, reference integrity, documentation duplication and the tests
- `bash scripts/validate.sh --tree` runs the same checks with the gates over every tracked file, since a commit otherwise checks only what it stages
- `bash scripts/validate.sh --check-consistency` runs doc and code consistency only
- `bash scripts/run-tests.sh` runs the test suite from a clean clone of HEAD under a temporary HOME and prints the commit it tested, so uncommitted edits in another session cannot change the result

Beyond the commit hook, `validate.sh` fails closed on these classes, each of which used to drift silently:

- **Document and code consistency** (`scripts/lib/consistency_check.py`): skills index parity and gate-count claims
- **Internal reference integrity** (`scripts/link-check.sh`): markdown links and backtick repo paths
- **Documentation duplication** (`scripts/lib/duplication_check.py`, `GATE-DUPLICATION-1` in `docs/DECISIONS.md`)
- **Unfalsifiable checks**, meaning a gate or script that cannot fail whatever the input (`scripts/lib/falsifiability_check.py`, `GATE-FALSIFIABILITY-1` in `docs/DECISIONS.md`)
- **Hook drift**: OliverCode's hook, the public template and the private template run the same gates, each gate's body lives once in `core/hooks/gates/`, and `scripts/build-hooks.py` assembles the three hooks from one ordered gate list. `validate.sh` fails when a committed hook differs from the build

`validate.sh` also reports fleet hook state on every run, through `olivercode conform --offline`, which reads local files and makes no network call. That report is advisory and never fatal, because hook enforcement fails open: a repo with an unset or broken `core.hooksPath` is silently ungoverned. Surfacing it where agents already look replaced a weekly log nobody read. A repo that must diverge from the template declares `hookVariant` in its profile, which `shared/repo-profiles.json` documents.

OliverCode ships `.github/workflows/framework-ci.yml`, which runs health, `validate.sh` and the install rehearsal as gating steps on push and pull request. The workflow is paused on the origin repo while GitHub Actions billing is blocked. That is policy and not drift, and the same pause applies to managed repos. Do not re-enable it as a fix. Enable it in your own fork, where your billing applies.

While CI is paused the local commands are the enforcement. `bash scripts/validate.sh` is the one entry point and also runs the bloat and code quality checks (`CI-STRICT-1` in `docs/DECISIONS.md`). `bash scripts/qa/rehearse-install.sh` rehearses the install in sandboxes, and `validate.sh --rehearse` runs it. Nothing runs the rehearsal automatically, so it is advisory. A governance CI workflow template for downstream repos exists at `core/templates/project/.github/workflows/olivercode-governance.yml`.

## Commit gates

Gate coverage differs by repo. This table is the one home for that, and anywhere else that names a count points here (`GATE-COUNT-1` in `docs/DECISIONS.md`).

* OliverCode runs nine gates on itself.
* An adopted repo runs the same nine.
* A repo deployed with the private variant runs seven.

| Gate | What it blocks | OliverCode | Adopted repo | Private variant |
|------|---------------|:---:|:---:|:---:|
| Secrets | API keys, tokens, JWTs and private keys in staged files | 1 | 1 | 1 |
| Icons and emoji | Unicode emoji and icon characters | 2 | 2 | 2 |
| PII | Host paths, email addresses and personal data in staged code and config. Markdown, tests, mocks and hook sources are skipped | 3 | 3 | — |
| Workflow push auth | Staged `.github/workflows/` files without a workflow-scoped credential, checked through `gh api user -i` and not the remote URL scheme | 4 | 4 | — |
| Archived content | A staged path under a directory named `Archive`, `legacy`, `deprecated`, `outdated`, `backup` or `old`, or a file suffixed `.bak`, `-old`, `-backup`, `-deprecated` or `-superseded`. A repo holds current state only and git is the archive, so a superseded file is deleted or replaced and never parked. A repo can exempt a path through its optional `pre-commit.local` hook, described below | 5 | 5 | 3 |
| Skill citations | A staged `SKILL.md`, `CLAUDE.md` or `references/*.md` that cites an issue number that does not exist (`GATE-CITATION-1` and `GATE-SCOPE-1` in `docs/DECISIONS.md`). Conditional: it runs where `gh` is installed and authenticated, and reports no finding where either is missing | 6 | 6 | 4 |
| Size ratchet | A commit that leaves the repo's total lines more than the allowance above `lines` in `docs/SIZE-BASELINE.json`. It counts through `skills/audit/scripts/size.sh --total --staged`, names the three files that grew most, and skips where the baseline file is missing or its `lines` is `null`. See "Size ratchet" below | 7 | 7 | 5 |
| Owner identifiers | A staged file that names an identifier the gate derives from git: the names and email local parts of `git log` authors, the owner of the origin remote, and the account and shop values in the config files that `configGlobs` lists in `docs/IDENTIFIER-GATE.json`. Matching is lowercase on whole words, for identifiers of 4 characters or more. Markdown and tests are scanned. It names the file and line, and skips where nothing can be derived. See "Owner identifiers" below | 8 | 8 | 6 |
| Duplicate text | A staged markdown file that shares a passage of 15 words or more with another tracked markdown file, in docs, skills, references, core templates or the repo root. It runs the shared check over the staged markdown files against the tracked tree, names both files, and skips where the script or python3 is missing. See "Duplicate text" below | 9 | 9 | 7 |
| **Total** | | **9** | **9** | **7** |

The numbers are each gate's position in that hook's run order, so the same gate can carry a different number in different hooks. Read the column and not the number.

### Verdicts on judged gates

Each gate stays only while it names a defect it blocks and a test that triggers it (`GATE-PRUNE-1` in `docs/DECISIONS.md`).

| Gate | Verdict | Defect it blocks | Test that triggers it |
|------|---------|------------------|-----------------------|
| Icons and emoji | Stays | An emoji or icon character committed into a file, which `docs/RULES.md` ("No icons") forbids | `TestGate2Emoji.test_emoji_blocks` in `tests/test_precommit_gates.py` |
| Archived content | Stays | A superseded file parked under an archive-named folder or beside its replacement as `-old`, so the reader cannot tell which copy is live. Its first run flagged more than 30 live files, which is why the suffix list leaves out `copy` | `TestGateArchivedContent` in `tests/test_precommit_gates.py` stages an `Archive/` path and an `-old` file and expects a block |
| Planning doc governance | Removed | None it still prevents. It ran only where `scripts/check-planning-doc-governance.py` exists, and only two repos carry that file (`gh issue view 111`), each of which calls the checker from its own `package.json`. The file-based backlog it governed moved to GitHub Projects | None. The tests went with the gate |

The checker and its contract file still ship in the bootstrap manifest until story #111 confirms with the two repos that carry them, so a repo that uses them keeps working.

Which hook a repo receives:

| Source | Deployed to | Selected by |
|---|---|---|
| `core/templates/project/pre-commit` | Every fleet repo | The default for `olivercode sync-hooks` |
| `core/templates/project/pre-commit-private` | Every repo in `privateRepos` in `olivercode.local.json`, plus any fleet repo whose profile sets `"private": true` | Each repo declares itself, so `sync-hooks` maintains it like any other target |
| A repo's own hook | That repo | The profile declares `hookVariant: "<reason>"`, which makes `sync-hooks` skip it and `conform` pass it with a note |

The private variant drops the PII gate on purpose. A private repo holds personal data by design, and a gate that blocks host paths and email addresses would block every legitimate commit in it. It is deployed as a file literally named `pre-commit`, because git invokes that name and no other. `sync-hooks` writes no second copy beside it and deletes a leftover `pre-commit-private` from an earlier sync.

`hookVariant` carries a real cost, set out with the incident that proved it in `_hookVariant_note` in `shared/repo-profiles.json`. `scripts/build-hooks.py` generates OliverCode's own hook and the two templates and never a variant repo's hook. When a third repo declares a variant, give `build-hooks.py` an entry for each variant repo, using the template's gate list plus that repo's own gates, so its hook is generated too.

### Size ratchet

`docs/SIZE-BASELINE.json` holds `lines` (the repo's total), `allowancePercent` (5) and `updated`. The gate counts the staged tree with `size.sh --total --staged`, the one line counter, and blocks a commit that leaves the total more than `allowancePercent` above `lines`. `olivercode bootstrap` adds the file with `lines: null`, which skips the gate until the repo records its total, and adds a copy of the counter to the repo's scripts folder, which the gate runs. A baseline set without a counter blocks.

* `olivercode size` prints the total, the baseline and the headroom
* `olivercode size --lower` rewrites `lines` to the current total after a cleanup. It sets a `null` baseline and accepts an equal total, and exits non-zero without writing when the total is higher
* A story that must grow the repo raises `lines` by editing the file in the same commit, with the story number in the message

The raise rule is procedure plus a reference and not a hard limit. A pre-commit gate cannot read the commit message, so when `docs/SIZE-BASELINE.json` is staged the gate trusts the `lines` it holds, and the commit-msg gate below is what requires a story number on that commit. Nothing checks that the raise belongs to the story named.

### Owner identifiers

The gate keeps a repo free of the people and accounts behind it, with no name list to maintain. It builds its identifiers from `git log` authors (names split into words, plus each email local part), from the owner segment of the `origin` remote, and from the string values of account, shop, store, handle, username, owner, brand and seller keys in the files matched by `configGlobs`. Noreply addresses, bots, Claude, GitHub and Anthropic are ignored.

`docs/IDENTIFIER-GATE.json` holds two lists. `configGlobs` names config files to read, and ships empty. `localData` names files that may hold an identifier, each with a line in `localDataReasons`. Built in as local data are `.secrets/`, `scratch/`, `.githooks/`, `docs/backlog-config.json` and the config file itself. `docs/DECISIONS.md` is scanned like any other file. The PII gate still skips markdown and tests, and this gate scans them.

### Duplicate text

One check serves every repo: `scripts/lib/duplication_check.py` here, shipped by bootstrap into an adopted repo's `scripts/` folder, so no repo keeps a private copy. It slides a 15-word window across every tracked markdown file and fails on a window two files share, unless `DECLARED_MARKERS` lists it with a reason. The commit gate passes it the staged markdown files and judges each against the whole tracked tree, so a commit is blocked only for a passage it adds or edits. `validate.sh` runs the same check over every pair, which reports an old duplicate between two untouched files.

### Repo-local hook

A repo adds its own blocking checks in an executable `pre-commit.local` file beside the hook in `.githooks/` (`GATE-LOCAL-1` in `docs/DECISIONS.md`). `sync-hooks` never writes or overwrites that file. The private hook runs it after its numbered gates with the staged file list on stdin, and a non-zero exit blocks the commit.

Every variant's archived-content gate also asks this file about a path it is about to block. It runs `pre-commit.local archive-exempt <path>` with empty stdin, and the exit status 10 exempts that path. Any other status leaves the block in place, so a local hook that does not know the argument cannot exempt anything by accident. A repo with permanent records in an archive-named folder, such as a weekly-task archive, declares them in its own `pre-commit.local`, and the framework carries no repo-specific exemption.

## Commit-message gate

Git shows a commit message only to the `commit-msg` hook, so this check is a hook of its own and the commit gate tables above leave it out. Every repo that `sync-hooks`, `olivercode bootstrap` or `olivercode backlog-setup` manages gets the same one, and `conform` fails a repo whose board or `commit-msg` copy is missing or differs from the template and lists the `backlog-setup` command that fixes it.

| Gate | What it blocks |
|------|---------------|
| Story reference | A commit whose message has no `#<number>`, such as `(#53)` or `Story: #53`. Merge, revert and `fixup!`, `squash!` and `amend!` messages are exempt, and so is a repo's first commit. A reference inside a `#` comment line does not count, and the hook blocks when it cannot read the message file |

A repo opts out only when its owner creates a file named `commit-msg.optout` in the repo's `.githooks` folder. The hook and `sync-hooks` never create or remove that file, and every commit it lets through prints that the check is off.

The hook enforces the reference and nothing more. Posting the log comment on the story (`skills/backlog/scripts/log_action.py`) is a procedure that the `backlog` skill and `docs/RULES.md` assign to each agent, and no hook can force a comment on GitHub.

## Pre-push gates

Every repo that `sync-hooks` manages also gets one pre-push hook, the same for every variant, because what is safe to push does not depend on which commit gates a repo runs.

| Gate | What it blocks |
|------|---------------|
| History rewrite | A push that would rewrite an existing remote branch. `ALLOW_FORCE_PUSH=1` allows a deliberate one |
| Secrets | A secret in any commit the push sends, including a merge resolution and a secret added and removed again inside the range. A new branch is checked against every commit the destination remote does not have yet |

The secret patterns live once in `core/hooks/secret-patterns.sh`, and `scripts/build-hooks.py` builds them into both the commit gate and the push hook.

## Cross-project standardization

OliverCode is the source baseline for downstream repos. The reusable baseline lives in `docs/RULES.md` ("Framework baseline"), `core/templates/project/QUALITY_BASELINE.md` and `shared/project-bootstrap-manifest.json`. Enforcement for downstream repos is each repo's own `.githooks/pre-commit` and its declared `canonicalValidationCommand` in the registry's `repo-profiles.json` (`REGISTRY-PRIVATE-1` in `docs/DECISIONS.md` places it).

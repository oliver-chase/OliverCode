# Gates

Every check that can block a commit or a push, what it blocks and which repos run it. A failed gate blocks the commit.

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
- **Budget** (`docs/BUDGET.json`): `testCount`, `docWords` and `skillWords` are measured by `skills/audit/scripts/fleet_check.py` and fail when over
- **Hook drift**: OliverCode's hook, the public template and the private template run the same gates, each gate's body lives once in `core/hooks/gates/`, and `scripts/build-hooks.py` assembles the three hooks from one ordered gate list. `validate.sh` fails when a committed hook differs from the build

`validate.sh` also reports fleet hook state on every run, through `olivercode conform --offline`, which reads local files and makes no network call. That report is advisory and never fatal, because hook enforcement fails open: a repo with an unset or broken `core.hooksPath` is silently ungoverned. A repo that must diverge from the template declares `hookVariant` in its profile, which `shared/repo-profiles.json` documents.

OliverCode ships `.github/workflows/framework-ci.yml`, which runs health, `validate.sh` and the install rehearsal as gating steps on push and pull request. The workflow is paused on the origin repo and on managed repos while GitHub Actions billing is blocked. Enable it in your own fork, where your billing applies.

While CI is paused the local commands are the enforcement. `bash scripts/validate.sh` also runs the bloat and code quality checks (`CI-STRICT-1` in `docs/DECISIONS.md`). `validate.sh --rehearse` rehearses the install in sandboxes (`scripts/qa/rehearse-install.sh`), and nothing runs it automatically, so it is advisory.

## Commit gates

Gate coverage differs by repo, and this list is the one home for the counts.

* OliverCode runs nine gates on itself
* An adopted repo runs the same nine
* A repo deployed with the private variant runs seven

| Gate | What it blocks | OliverCode | Adopted repo | Private variant |
|------|---------------|:---:|:---:|:---:|
| Secrets | API keys, tokens, JWTs and private keys in any staged file. A placeholder passes by its value, such as `EXAMPLE` or a run of `x`, or on a line that carries `secret-scan: allow` | 1 | 1 | 1 |
| Icons and emoji | Unicode emoji and icon characters | 2 | 2 | 2 |
| PII | Host paths, email addresses and personal data in staged code and config. Markdown, tests and mocks are skipped, and a repo lists files that must hold a pattern under `exempt` in `docs/PII-GATE.json`, each with a reason | 3 | 3 | — |
| Workflow push auth | Staged `.github/workflows/` files without a workflow-scoped credential, checked through `gh api user -i` and not the remote URL scheme | 4 | 4 | — |
| Archived content | A staged path under a directory named `Archive`, `legacy`, `deprecated`, `outdated`, `backup` or `old`, or a file suffixed `.bak`, `-old`, `-backup`, `-deprecated` or `-superseded`. A repo holds current state only and git is the archive, so a superseded file is deleted or replaced and never parked. A repo can exempt a path through its optional `pre-commit.local` hook, described below | 5 | 5 | 3 |
| Skill citations | A staged `SKILL.md`, `CLAUDE.md` or `references/*.md` that cites an issue number that does not exist (`GATE-CITATION-1` and `GATE-SCOPE-1` in `docs/DECISIONS.md`). Conditional: it runs where `gh` is installed and authenticated, and reports no finding where either is missing | 6 | 6 | 4 |
| Size ratchet | A commit that leaves the repo's total lines more than the allowance above `lines` in `docs/SIZE-BASELINE.json`. It counts through `skills/audit/scripts/size.sh --total --staged`, names the three files that grew most, and skips where the baseline file is missing or its `lines` is `null`. See "Size ratchet" below | 7 | 7 | 5 |
| Owner identifiers | A staged file that names an identifier the gate derives from git: the names and email local parts of `git log` authors, the owner of the origin remote, and the account and shop values in the config files that `configGlobs` lists in `docs/IDENTIFIER-GATE.json`. Matching is lowercase on whole words, for identifiers of 4 characters or more. Markdown and tests are scanned. It names the file and line, and skips where nothing can be derived. See "Owner identifiers" below | 8 | 8 | 6 |
| Duplicate text | A staged markdown file that shares a passage of 15 words or more with another tracked markdown file, in docs, skills, references, core templates or the repo root. It runs the shared check over the staged markdown files against the tracked tree, names both files, and skips where the script or python3 is missing. See "Duplicate text" below | 9 | 9 | 7 |
| **Total** | | **9** | **9** | **7** |

The numbers are each gate's position in that hook's run order, so read the column.

### Verdicts on judged gates

Each gate stays only while it names a defect it blocks and a test that triggers it (`GATE-PRUNE-1` in `docs/DECISIONS.md`).

| Gate | Verdict | Defect it blocks | Test that triggers it |
|------|---------|------------------|-----------------------|
| Icons and emoji | Stays | An emoji or icon character committed into a file, which `docs/RULES.md` ("No icons") forbids | `TestGate2Emoji.test_emoji_blocks` in `tests/test_gate_content.py` |
| Archived content | Stays | A superseded file parked under an archive-named folder or beside its replacement as `-old`, so the reader cannot tell which copy is live. The suffix list leaves out `copy`, which matched live files | `TestGateArchivedContent` in `tests/test_gate_content.py` stages an `Archive/` path and an `-old` file and expects a block |

Which hook a repo receives:

| Source | Deployed to | Selected by |
|---|---|---|
| `core/templates/project/pre-commit` | Every fleet repo | The default for `olivercode sync-hooks` |
| `core/templates/project/pre-commit-private` | Every repo in `privateRepos` in `olivercode.local.json`, plus any fleet repo whose profile sets `"private": true` | Each repo declares itself, so `sync-hooks` maintains it like any other target |
| A repo's own hook | That repo | The profile declares `hookVariant: "<reason>"`, which makes `sync-hooks` skip it and `conform` pass it with a note |

The private variant drops the PII gate on purpose, because a private repo holds personal data by design and the gate would block every legitimate commit. It is deployed as a file named `pre-commit`, the only name git invokes. `sync-hooks` writes no second copy and deletes a leftover `pre-commit-private`.

`hookVariant` has a real cost, set out in `_hookVariant_note` in `shared/repo-profiles.json`. `scripts/build-hooks.py` generates OliverCode's own hook and the two templates, never a variant repo's. When a third repo declares a variant, give `build-hooks.py` an entry for it, using the template's gate list plus that repo's own gates.

### Size ratchet

`docs/SIZE-BASELINE.json` holds `lines` (the repo's total), `allowancePercent` (5) and `updated`. The gate counts the staged tree with `size.sh --total --staged`, the one line counter, and blocks a commit that leaves the total more than `allowancePercent` above `lines`. `olivercode bootstrap` adds the file with `lines: null`, which skips the gate until the repo records its total, and adds a copy of the counter to the repo's scripts folder, which the gate runs. A baseline set without a counter blocks.

* `olivercode size` prints the total, the baseline and the headroom
* `olivercode size --lower` rewrites `lines` to the current total after a cleanup. It sets a `null` baseline and accepts an equal total, and exits non-zero without writing when the total is higher
* A story that must grow the repo raises `lines` to the counted total in the same commit, with the story number in the message. The gate refuses any other figure
* A repo that keeps its own size_baseline script under scripts gets that command named in the block message. The script counts the files and writes `lines`, so a merge of two branches reruns it and never picks between two hand-edited numbers. The gate and the raise cap read the file the same way

A raise is capped. `raiseCapPercent` in the baseline file (default 2) limits how far one commit may raise `lines` above the committed value. The hook reads the cap from the committed file, so the same commit cannot change it, and merge, revert and fixup messages get the same check. The size gate prints the raise and passes it, because a pre-commit gate cannot read the commit message. The commit-msg hook then refuses a raise over the cap unless the message carries a line `Size: L` or `Size: XL`, copied from the Size field of the story that needs the growth. A story of size M or smaller splits its work so each commit stays inside the cap, or lowers the total elsewhere in the same commit. The reviewer confirms the raise belongs to the story named. A repo that opts out of the commit-msg hook loses this check with it.

### Icons and emoji

`docs/EMOJI-GATE.json` lists exempt globs and a reason for each.

### Owner identifiers

The gate keeps a repo free of the people and accounts behind it, with no name list to maintain. It builds its identifiers from `git log` authors (names split into words, plus each email local part), from the owner segment of the `origin` remote, and from the string values of account, shop, store, handle, username, owner, brand and seller keys in the files matched by `configGlobs`. Noreply addresses, bots, Claude, GitHub and Anthropic are ignored.

`docs/IDENTIFIER-GATE.json` holds two lists. `configGlobs` names config files to read, and ships empty. `localData` names files that may hold an identifier, each with a line in `localDataReasons`. Built in as local data are `.secrets/`, `scratch/`, `.githooks/`, `docs/backlog-config.json` and the config file itself. `docs/DECISIONS.md` is scanned like any other file. The PII gate still skips markdown and tests, and this gate scans them.

### Duplicate text

One check serves every repo: `scripts/lib/duplication_check.py` here, shipped by bootstrap into an adopted repo's `scripts/` folder, so no repo keeps a private copy. It slides a 15-word window across every tracked markdown file and fails on a window two files share, unless `DECLARED_MARKERS` lists it with a reason, or the repo's own `DUPLICATION-ALLOW.json` in its docs folder does (a `markers` object of lowercase passage words to the reason it repeats, where an entry with no reason counts for nothing). The commit gate passes it the staged markdown files and judges each against the whole tracked tree, so a commit is blocked only for a passage it adds or edits. `validate.sh` runs the same check over every pair, which reports an old duplicate between two untouched files.

### Repo-local hook

A repo adds its own blocking checks in an executable `pre-commit.local` file beside the hook in `.githooks/` (`GATE-LOCAL-1` in `docs/DECISIONS.md`). `sync-hooks` never writes or overwrites that file. The private hook runs it after its numbered gates with the staged file list on stdin, and a non-zero exit blocks the commit.

Every variant's archived-content gate also asks this file about a path it is about to block, by running `pre-commit.local archive-exempt <path>` with empty stdin. Exit status 10 exempts the path and any other status leaves the block in place. A repo declares its permanent archive records in its own `pre-commit.local`.

### Commit guard limits

Inside Claude Code, `scripts/hooks/commit_guard.py` refuses `--no-verify` and `-n` in any form git accepts, a `core.hooksPath` override, a commit wrapped in `bash -c` or `eval`, and a `git -c alias.NAME=...` alias that commits with a hook skip, including a chained alias, a `!` shell alias and one whose body is a shell function. It cannot see a commit run through a shell function, a variable, command substitution, a shell alias, a configured git alias or a pipe into `sh`, where the pre-push secret scan and CI still apply.

## Commit-message gate

Git shows a commit message only to the `commit-msg` hook, so these checks are a hook of their own and the commit gate tables above leave it out. Every repo that `sync-hooks`, `olivercode bootstrap` or `olivercode backlog-setup` manages gets the same one, and `conform` fails a repo whose board or `commit-msg` copy is missing or differs from the template and lists the `backlog-setup` command that fixes it.

| Gate | What it blocks |
|------|---------------|
| Story reference | A commit whose message has no `#<number>`, such as `(#53)` or `Story: #53`. Merge, revert and `fixup!`, `squash!` and `amend!` messages are exempt, and so is a repo's first commit. A reference inside a `#` comment line does not count, and the hook blocks when it cannot read the message file |
| Story exists | A reference to a story absent from its repo: `#N` is checked in the repo that `docs/backlog-config.json` names and `owner/repo#N` in the repo it spells out, through `gh api`. Yes answers are cached in `.git/story-exists-cache`. The check fails open with a warning when `gh` or GitHub is unavailable, and a repo without the config skips it |
| Test with code | A commit that adds or changes a `.py`, `.sh`, `.js`, `.mjs`, `.ts` or `.tsx` file outside a test path and changes no test, unless the message has a line `No test: <reason>` |
| Co-author form | A `Co-Authored-By` line in any other form than `Co-Authored-By: Name <email>`, or a Claude co-author without `<noreply@anthropic.com>`. Merges and cherry-picks are checked too, and a commit with no co-author line passes |
| Size raise | A commit that raises `lines` in `docs/SIZE-BASELINE.json` by more than `raiseCapPercent` (default 2) of the committed value, without a `Size: L` or `Size: XL` line in the message. See "Size ratchet" above |

A repo opts out only when its owner creates a file named `commit-msg.optout` in the repo's `.githooks` folder. The hook and `sync-hooks` never create or remove that file, and every commit it lets through prints that the check is off.

No hook can force the log comment on the story (`skills/backlog/scripts/log_action.py`), so each agent posts it as the `backlog` skill directs.

## Pre-push gates

Every repo that `sync-hooks` manages also gets one pre-push hook, the same for every variant, because what is safe to push does not depend on which commit gates a repo runs.

| Gate | What it blocks |
|------|---------------|
| History rewrite | A push that would rewrite an existing remote branch. `ALLOW_FORCE_PUSH=1` allows a deliberate one |
| Secrets | A secret in any commit the push sends, including a merge resolution and a secret added and removed again inside the range. A new branch is checked against every commit the destination remote does not have yet |

The secret patterns live once in `core/hooks/secret-patterns.sh`, and `scripts/build-hooks.py` builds them into both the commit gate and the push hook.

## Cross-project standardization

OliverCode is the source baseline for downstream repos. The reusable baseline lives in `docs/RULES.md` ("Framework baseline"), `core/templates/project/QUALITY_BASELINE.md` and `shared/project-bootstrap-manifest.json`. Enforcement for downstream repos is each repo's own `.githooks/pre-commit` and its declared `canonicalValidationCommand` in the registry's `repo-profiles.json` (`REGISTRY-PRIVATE-1` in `docs/DECISIONS.md` places it).

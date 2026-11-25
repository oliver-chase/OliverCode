# Cut list

The second cut list (#1054): what was checked for removal, what was removed and what stays, each with the evidence. It replaces the earlier fixed line-count target. Size is an outcome to measure here, and no number is a goal.

## Method

- A definition counts as unused when its name appears nowhere else in the tracked files outside its own definition, including tests, docs, templates and string dispatch. A name that only tests mention is listed apart
- A module counts as unused when no product file, doc or launcher entry names it
- A removal runs the modules that touch the code, then the full validation
- A test goes only with the function it tested, and only when that function had no product caller
- Findings come from `main` at 1685c37, and the scan covers 1,455 top-level functions and classes in `scripts/` and `skills/`

## The candidates the story named

| Candidate | Verdict | Evidence |
|-----------|---------|----------|
| `cmd_rule`, `push_approval`, `live_copy` | Already removed | The only mention is `test_removed_jobs`, which asserts they stay gone |
| iCloud hygiene steps | Keep | Read by `placement.py` and the audit's `portability.py`, and tested in both |
| gh cost log | Already removed | No code names it |
| Duplicate finder and owner-rule mapping | Already removed | Only a health comment names owner rules |
| Migrated state code | Already removed | No code names a migration |
| Dead health and retro code | Nothing found | The scan finds no unused function in either. `retroFilesPerRun` is a live limit that `intake.prevention` reads |
| Large modules | No change | No dead code was found in them, and the story forbids splitting to meet a number |

## Removed

| Item | Why it was safe | Tests |
|------|-----------------|-------|
| `usage_sessions.app_records` | Defined and never called | None |
| `lesson_cover.write_request` | Defined and never called | None |
| `repo_profiles.load_local_profiles` | Defined and never called | None |
| `policy_parse._simple_commands` | Defined and never called | None |
| `maintain._agent_path` | Defined and never called | None |
| `backlog_setup.workflow_problems` | Only its own two tests called it | Two removed |
| `usage_sessions.period_usage` | Only its own test called it | One removed |
| `limits.inbound` | Only its own test called it | One removed |
| `lesson_cover.own_backlog` | Nothing called it, and one test patched it | Patch removed |
| `cmd_groom.unblocks_of`, `cmd_groom.impact` and the groom's `impact` record | The drain ranks by the GitHub dependency count in `open_issues`. `unblocks_of` was the only reader of the record, so the record was written each groom and never read | Three removed |
| `board_api.read_workflows` and `WORKFLOWS_QUERY` | `workflow_problems` was their only caller, so they became unused when it went. A second scan found them | None |
| `lesson_cover.SECTION`, three imports and two stale docstring lines | Left behind by the cuts above | None |

Seven tests were removed, and each tested a function with no product caller. Every other behavior keeps its test.

## Kept after review

| Item | Reason |
|------|--------|
| The standalone `main` in `archived_guard.py`, `placement_guard.py` and `reset_guard.py` | Removed in #1199 after the three names joined `RETIRED` in `claude_settings.py`, so install and update drop an older standalone hook entry. The modules stay as the checks `pretool_guard.py` calls |
| `repo_state.forget_said` | Tests use it to reset a cache. It is a test hook in a product module, so it stays until the tests carry their own reset |
| The seven commands with one product reference (`cmd_version`, `cmd_fleetsync`, `cmd_lesson`, `cmd_board`, `cmd_commit_check`, `cmd_run`, `cmd_limits`) | Each is wired in `scripts/olivercode`, which is how a command runs |
| Duplicate private helpers (`_git` in 14 modules, `_run`, `_read`, `_save`, `_locked`, `_write`) | They differ in what they catch or return. Merging them would change behavior and is out of scope until a caller needs one |
| Test modules with overlapping onboarding text | Merging belongs to the test audit's rewrite list (`TEST-AUDIT.md`), one module at a time |

## Measured change

| Measure | Before | After |
|---------|--------|-------|
| Lines in tracked Python files | 51,755 | 51,561 |
| Tests | 2,197 | 2,190 |
| Functions with no product caller | 12 | 1 (`repo_state.forget_said`, a test reset hook, kept) |
| Full validation | passes | passes |

Removing a function can leave its helper unused, so the scan ran again after each round of cuts until it found nothing. The change is 194 net lines removed across 14 files. Validation time did not change by a measurable amount, because the removed code ran no work of its own, and this list claims no saving there.

# BACKLOG — OliverCode

Forward-looking framework improvements only. Historical audit worklogs live outside this
repo (they are operator-specific session records, not framework material — per this
framework's own removal rule: history/status docs are not active authority).

Status values: OPEN, IN-PROGRESS, FIXED, WONT-FIX (with reason).
Severity: HIGH (gate silently broken / wrong result), MEDIUM (wrong on real inputs or
misleading), LOW (polish, drift).

---

## Design decisions (stable rationale — referenced from code and docs by ID)

These IDs are cited from `.gitignore`, `scripts/validate.sh`, `scripts/bot-system-reality-check.js`,
contract JSON `_note` fields, and several docs. They are settled decisions, not open items.

- **G1 — Example-config + local-overlay pattern.** Tracked files ship placeholder-only
  registries (`shared/*.example.json`, placeholder `shared/repo-map.json` etc.); the real
  fleet lives in gitignored `local/` copies. Loaders try the local overlay first and fall
  back to the tracked example with a WARN. Personal data never enters tracked files.
- **D1 — No bot-specific guard logic in the framework.** Product guards live in the owning
  product repo under `scripts/guards/`; `bot-system-reality-check.js` discovers them by
  convention from the fleet registry, never from a hardcoded table.
- **D2 — No repo-specific enforcement in the framework.** `validate.sh --target-repo <root>`
  execs the target's own `scripts/validate-repo.sh` if present, else skips cleanly.
  Delegated suites (e.g. SDR) resolve via a profile flag (`"suites": ["sdr"]`), never a
  hardcoded repo name.
- **ACT-3 — Skill precedence gap (known, unmitigatable at mechanism level).** A generic
  skill and a repo-specific approval-gated skill can both match the same task, and nothing
  biases selection toward the gated one before a repo file is touched. Mitigation: a named,
  explicit directive in the repo's own `CLAUDE.md`. See `docs/skills-placement.md`.

---

## Open items

### OC-1. `security-review` skill name collides with a built-in Claude Code skill — LOW — FIXED 2026-07-08
- Renamed to `skills/code-security-review` (frontmatter, INDEX row, `~/.claude/skills/`
  symlink, cross-references in repo-audit-with-execution-batches). Verified live: both
  skills now appear as distinct entries in the harness's own skill list.

### OC-2. Token-efficiency pass over the contract/doc layer — MEDIUM — FIXED 2026-07-08

All 4 known duplications collapsed to one home each, verified by re-grep (exactly one file
states the full rule, all others point):

1. Doc-sync trigger-paths rule (was in `CONTRIBUTING.md` x2 + `docs/DOCUMENTATION_STANDARD.md`
   + `CLAUDE.md`) -> home is `docs/DOCUMENTATION_STANDARD.md` "Requirement" (folded in the
   precise trigger-path list `scripts/`, `skills/`, `core/personas/`, `shared/`,
   `core/contracts/` that only `CONTRIBUTING.md` used to carry).
2. History/roadmap-not-authority rule (was in `CONTRIBUTING.md` + `FRAMEWORK_BASELINE.md` +
   `docs/governance.md`) -> home is `FRAMEWORK_BASELINE.md` "Removal Rules".
3. run/verify/ship/support file-justification rule (was in `CONTRIBUTING.md` +
   `FRAMEWORK_BASELINE.md`, near-verbatim) -> home is `FRAMEWORK_BASELINE.md` "Purpose".
4. Source-of-truth doc lists (was in `CONTRIBUTING.md` x2 sections + `FRAMEWORK_BASELINE.md`
   "Support") -> home is `FRAMEWORK_BASELINE.md`'s "Support"/"Ship" lists; `CONTRIBUTING.md`'s
   redundant "Baseline Contract" section deleted outright (not a required header per
   `docs/DOCUMENTATION_STANDARD.md`'s "Required Document Structures").

**Found 2 more duplications while executing (not in the original 4, same pattern):**
`docs/governance.md`'s "Locked Baseline Rules" also restated "project-specific automation
belongs in the owning repo" (duplicate of `CONTRIBUTING.md` Rule 2) and "new docs
merge/replace old authority" (duplicate of Rule 5) — both collapsed to pointers at
`CONTRIBUTING.md`.

**Also fixed while reading these files (real bugs, not duplication):** `docs/governance.md`
claimed "OliverCode itself runs no CI workflows" — false as of this same session
(`.github/workflows/framework-ci.yml`, confirmed running green). Corrected.

`README.md`'s "Key Docs" table deliberately kept un-collapsed — different audience
(external/newcomer readers who won't dig into contract files), matches
`docs-reality-audit`'s own "don't merge docs serving different audiences" rule.

Verified: `wc -w` total went 11966 -> 11936 words (net lower, as required — OC-11's
legitimate new content in the same file set partially offset the cut); `bash
scripts/validate.sh` and `bash scripts/link-check.sh` both green throughout, one commit
per collapsed duplication group.

### OC-3. Prompt Library value audit — LOW — FIXED 2026-07-08

**Remainder executed.** Read all 18 content files in `prompts/` in full (14 QA + REF-01 +
RM-01 + WF-01 + WF-02), checked each against `core/workflows/*.md` and `skills/INDEX.md`
for overlap.

**Verdict: 18 KEEP, 0 MERGE, 0 RETIRE.** Every QA-01..QA-14 prompt carries executable
mechanical specificity (exact file paths, exact commit messages, exact ID formats, exact
status values) that the corresponding `core/workflows/*.md` bullets don't have at that
granularity — the workflow docs are principles, these are the executable scripts-in-English
that implement them. REF-01/WF-01/WF-02/RM-01 serve a genuinely distinct purpose: portable
copy-paste bootstrap material for pasting into a DIFFERENT repo's `CLAUDE.md` (repos that
don't have OliverCode cloned alongside them can't reference `core/workflows/*.md` directly).

**Real bugs found and fixed while reading (not just classification):**
- All 18 files' parent links still pointed at the pre-rename `Oliver/Prompt Library/_Prompt
  Library` path (dangling since OC-8's `Prompt Library/` -> `prompts/` rename, missed then).
  Fixed to `prompts/README`.
- All 18 files listed `AI: Codex (Claude Code)` — contradicts `CONTRIBUTING.md` Rule 1
  (Claude Code sole runtime). Fixed to `Claude Code`.
- `REF-01`: two dangling references — `_Post-Implementation QA Orchestration.md` (deleted
  earlier this session when QA-15/16/17/ALL were retired) and a stale "Prompt Library"
  location reference. Both fixed.
- **`RM-01`'s "Fill In Before Running" example values were not generic placeholders — they
  were tesknota's actual product spec**: a real commit hash, a real per-folder LOC
  breakdown (`components/ui-design-system: 7,545`, etc.), and a real feature list
  ("Fragrance library", "Compliment tracking", "Perfume identity block: perfume name, house
  underneath, small concentration pill"). This is exactly the personal/product-identifying
  content the owner's "NO personal info" directive targets, and well beyond the framework's
  own two-examples allowance — genericized every value to `<placeholder>` form.

Verified: `prompts/README.md`'s index table matches all 18 files exactly (no drift);
`scripts/validate.sh` and `scripts/link-check.sh` both green.


### OC-4. `olivercode health` fleet checks assume the vault layout — LOW — FIXED 2026-07-08 (`OLIVERCODE_VAULT_ROOT` env override added; convention walk-up kept as fallback)
- The hook-drift section resolves the vault root by walking up from OC_ROOT
  (`oc_root.parent.parent.parent`) — correct for this operator's layout, silently wrong for
  a fork living elsewhere. It WARN-skips when nothing is found (safe), but the layout
  assumption should be explicit config (env var or local/ setting), not a hardcoded walk.

### OC-5. Development-practice defaults in CLAUDE.md — MEDIUM — FIXED 2026-07-08
- Owner directive: working sessions should diagnose bugs and simplify continuously (not
  only when asked), keep project-repo folder structures clean and minimal, keep
  documentation robust but manageable. Added as a `## Development Practice` section in
  `CLAUDE.md` (loads in every session via the `~/.claude/CLAUDE.md` symlink), pointing at
  the `diagnosing-bugs` skill, `/simplify`, `/code-review`, and the structure contracts.

### OC-6. Stranger-fork CI — LOW — FIXED 2026-07-08

**Original blocker was wrong, and revealed a real Gate 5 bug.** The spec assumed the
owner had SSH configured; they didn't (`~/.ssh/` has no keypair). Verified instead: `gh
auth status` showed the active HTTPS credential already carries `workflow` scope
(`gh auth login`, not legacy git credential caching) -- Gate 5 blocked based on remote URL
scheme alone, which is the wrong signal. There is no SSH switch needed; there never was.

**Fixed Gate 5** (`.githooks/pre-commit` and `core/templates/project/pre-commit`, kept
identical): checks the actual credential's scopes via `gh api user -i` /
`X-OAuth-Scopes` header instead of the remote URL. Blocks only when no workflow-scoped
credential is actually present; message now says `gh auth login --scopes workflow`.
Verified live: staged `.github/workflows/framework-ci.yml`, Gate 5 passed with
`[OK] gh credential has workflow scope`.

**Added `.github/workflows/framework-ci.yml`**: checkout, `python3 scripts/olivercode
health`, `bash scripts/validate.sh`, `bash scripts/link-check.sh`, `bash
scripts/qa/full-qa-pass.sh`. Rehearsed in a fresh `local/`-free checkout with a real `.git`
(matching what `actions/checkout` produces) before committing -- all 4 steps green,
health reports the correct not-installed-checkout WARN path (not FAIL).

### OC-10. Framework smoke tests — MEDIUM — FIXED 2026-07-08

`tests/repo-profiles.test.mjs` (node:test) + `tests/test_frontmatter_parser.py`
(unittest) added. Both read only the tracked `shared/repo-profiles.example.json` via a
scratch tempdir copy -- never `local/`. Wired into `scripts/validate.sh`'s default mode
as `run_smoke_tests()`, WARN-skips when `tests/` is absent or a runtime is missing.

Node quirk found while verifying: this Node install (v26.0.0) doesn't discover bare
`node --test tests/` or `node --test ./tests` -- both throw `MODULE_NOT_FOUND` on the
directory itself. Explicit glob (`node --test tests/*.mjs`) works reliably; used that
form in validate.sh and here rather than the bare-directory form the original spec named.

Verified: `python3 -m unittest discover tests` 3/3 pass; `node --test tests/*.mjs` 3/3
pass; deliberately zeroing out `shared/repo-profiles.example.json`'s profiles made the
suite-injection test throw (confirmed real signal, not a no-op), restored byte-identical
after; full stranger-clone rehearsal (fresh `git init`, no `local/`) -- health 9/9,
`validate.sh` runs and passes both suites identically to the real checkout.

### OC-11. Docs-reality audit of the remaining docs/ surface — MEDIUM — FIXED 2026-07-08

Ran the `docs-reality-audit` skill against the full scoped list (9 `docs/` files, all 7
`core/workflows/*.md`, all 11 `core/contracts/*`). 25 files read in full; every path,
command, gate count, and referenced-skill/script claim verified against live code before
trusting it (never against a doc's own claim about itself).

**Findings (file, claim, verified fact, fix):**

| File | Stale/wrong claim | Verified fact | Fix |
|---|---|---|---|
| `docs/KEEPALIVE_STANDARD.md` | "this doc previously carried a duplicate markdown table" | Current-State Wording bans "previously" phrasing | Reworded to state the current rule, dropped the history reference |
| `docs/bots-gateway.md` | `bash scripts/validate-all.sh --sdr-only` listed as a bare command | `validate-all.sh` does not exist in OliverCode -- it's the repo declaring the `sdr` suite's own script | Rewrote to `node scripts/bots-gateway.mjs test:sdr` + a comment explaining the delegation |
| `docs/troubleshooting.md` | "full governance suite expects `jq` and `rg`" | Zero uses of `jq`/`rg` anywhere in the gates/QA scripts (grepped) | Removed the section |
| `docs/troubleshooting.md` | `scripts/olivercode providers` documented as a real command | Zero hits in `scripts/olivercode`'s `COMMANDS` list -- fabricated, remnant of the retired multi-provider vision | Removed the section; added 3 real current-state sections (Gate 5 credential fix, hook-drift resync, validate.sh-needs-real-git) |
| `docs/OLIVERCODE_LAUNCHER.md` | "Runtime commands are available from the runtime launcher" | Verified `runtime/control-plane/olivercode`'s actual content: a 17-line shim that `exec`s the same 4-command Python CLI, zero extra commands | Corrected to state the shim carries no additional commands |
| `docs/FEATURE_MAP.md` | Enforcement table omitted Gate 8, `tests/`, and CI entirely | Gate 8 added 2026-07-08 (this session); `tests/` and `.github/workflows/framework-ci.yml` added same session | Added rows for both; reworded "Historical Note" (banned "Previous versions... listed" phrasing) to a forward-looking rule |
| `docs/DOCUMENTATION_STANDARD.md` | Required `README.md` header list (`Start Here`/`Core Commands`/etc.) | The real, actively-maintained README (rewritten this session per owner's own explicit ask) uses different section names entirely -- `What It Keeps`, `Quick Start`, `Where Things Live`, etc. | Rewrote the requirement as required CONTENTS (scope statement, Quick Start, Where Things Live table, Key Docs index) rather than exact header text -- the doc was stale, not the README |
| `docs/DOCUMENTATION_STANDARD.md` | "`CHANGELOG.md` is the only file for version history" | `CHANGELOG.md` does not exist anywhere in the repo | Corrected to state git log is the version history, no separate file required |
| `docs/DOCUMENTATION_STANDARD.md` | Gate list omitted token policy | 8 gates exist, not 7 | Added "token policy" to the list |
| `core/workflows/story-lifecycle-sop.md` | Cited `story-lifecycle-gate` as a "supporting gate skill" | Zero matches anywhere in `skills/` or `~/.claude/skills/` -- confirmed non-existent (matches AUD-F6's earlier finding in the pre-squash history) | Removed the reference |
| `core/workflows/project-standardization-lifecycle.md` | `.githooks/pre-commit` described as syncing strict/presence template files, with an `OVERWRITE_NON_STRICT=1` env-var toggle | Grepped the entire pre-commit hook: zero knowledge of strict/presence files, the bootstrap manifest, or any sync behavior -- it is purely the 8-gate scanner. `OVERWRITE_NON_STRICT` has zero implementation anywhere. | Rewrote "Sync existing projects" and "Audit drift" steps honestly: no automated sync script ships; `scripts/olivercode sync-hooks` is the one part that IS automated (hooks only) |
| `core/contracts/PROJECT_STRUCTURE_STANDARD.md` | "Agent Read Order" step 2 = `AGENTS.md` | Same document's own line 23 states "CLAUDE.md — the only agent-rules file... no separate AGENTS.md" -- direct internal self-contradiction | Removed `AGENTS.md` from the read order, renumbered |
| `core/contracts/PROJECT_STRUCTURE_STANDARD.md` | "Required Base Paths" numbered 1,2,3,4,5,7 (skips 6) | Numbering defect, not a content error | Renumbered |
| `core/contracts/PROJECT_HYGIENE_STANDARD.md` | "Contract source: `contracts/PROJECT_STRUCTURE_STANDARD.md`" | Bare path -- real location is `core/contracts/PROJECT_STRUCTURE_STANDARD.md` (same stale-path bug class the pre-squash SK-3 sweep fixed elsewhere, missed here) | Added the `core/` prefix |
| `core/contracts/NO_ICONS_STANDARD.md` | "CI gates — GitHub Actions governance-secrets-gate includes emoji scanning" | Read `governance-secrets-gate.yml` in full: secret-filename gating and nested-agent-folder blocking only, zero emoji logic | Corrected; noted OliverCode's own `framework-ci.yml` covers emoji via Gate 2 |
| `core/contracts/FILE_LOCATION_STANDARD.md` | "OliverCode/skills/ ... the one tracked home for non-personal skills" | Contradicts `docs/skills-placement.md`: OliverCode/skills/ is engineering-method/framework-tooling ONLY; personal/business skills live in the vault's user-skills/, everything else (product/GTM/vendor) is untracked directly under `~/.claude/skills/` | Corrected to the real 3-way split |
| `core/contracts/SHARED_ORCHESTRATION.md` | Pointed to the runtime environment's `ORCHESTRATION_SOURCE_OF_TRUTH.md` | Confirmed deleted in the 2026-07-08 control-plane audit (176-file prune) | Removed the dangling reference |
| `core/contracts/FRAMEWORK_BASELINE.md` | "There is no CI pipeline" | `.github/workflows/framework-ci.yml` added this same session, confirmed running green on GitHub (2 runs, both success) | Corrected -- direct same-day contradiction with this session's own work |
| `core/contracts/FRAMEWORK_BASELINE.md` | "`runtime/manifests/` contains 77 tracked files (796KB)" | `runtime/manifests/` does not exist as a path at all; 0 tracked files (`git ls-files` empty) | Corrected to state the path doesn't exist, `.gitignore` reserves it preemptively |
| `core/contracts/code-size-policy.json` | (implicit: tracked = active) | Zero consumers anywhere (`grep -rl` across every script), zero doc references it as active | **Deleted** -- confirmed dead, not just stale text |
| `core/contracts/EXECUTION_CONTRACT.md` | Gate table listed 6 fictional gate categories (".env files", "Legacy language", "Credentials" as separate filename-match gates) | None of these exist in `.githooks/pre-commit` -- grepped for `.env`/`auth.json`/`credentials.json`/"legacy language" patterns, zero hits beyond an `.env.example` skip-pattern | Replaced with the real 8-gate table |

**Needs owner review (Phase 7 — business judgment, not resolved silently):**
- `core/contracts/PUBLIC_PRIVATE_REPO_STANDARD.md` requires "each repo" (scope explicitly
  includes OliverCode itself) to provide `docs/SETUP_MODES.md`, `docs/MANUAL_SETUP.md`,
  `scripts/bootstrap-profile.sh`, `scripts/run-profile-checks.sh`. OliverCode's own root has
  none of these (only template copies under `core/templates/project/`, stamped into
  downstream repos) -- `docs/SETUP_MODES.md`/`MANUAL_SETUP.md` were deliberately deleted
  from OliverCode's own `docs/` in an earlier pass this session as duplicative of
  `INSTALL.md`. Two ways to resolve, need a decision: (a) narrow this contract's scope to
  exclude the framework repo itself (it's the template source, not a downstream consumer),
  or (b) restore the 4 files to OliverCode's own root for self-consistency. Not resolved
  either way -- flagged here, not guessed.

Verified after all fixes: `bash scripts/validate.sh` (8 gates + smoke tests), `bash
scripts/link-check.sh`, `scripts/olivercode health` (14/14) -- all green.

### OC-12. `core/workflows/` vs `prompts/` overlap consolidation — LOW — FIXED 2026-07-08 (no action needed)

OC-3's remainder verdicts are this item's input: all 18 prompts came back KEEP, zero
MERGE/RETIRE candidates. There is no procedure duplicated in both a workflow doc and a
prompt — the two libraries operate at different altitudes by design (workflow docs =
principles, prompts = executable session scripts), confirmed by direct read rather than
assumed from the original suspicion. No consolidation needed.
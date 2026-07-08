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

### OC-2. Token-efficiency pass over the contract/doc layer — MEDIUM — OPEN

**Why:** authority docs load into agent context; every duplicated rule is paid for twice
per session and drifts independently. Target: one home per rule, pointers elsewhere.

**Preconditions:** read `docs/DOCUMENTATION_STANDARD.md` ("one capability, one authority
doc") and CONTRIBUTING.md's "Enforcement Reality" section first. Run
`wc -w core/contracts/*.md docs/*.md CONTRIBUTING.md CLAUDE.md` and record the total as
the before-number.

**Known duplications to collapse (verified by read, not guessed):**
1. Doc-sync-in-same-change-set rule stated 4x: CONTRIBUTING.md (Mandatory Rule 3 + Rule 5
   + "Documentation Sync Requirement" section), docs/DOCUMENTATION_STANDARD.md
   ("Requirement" section), docs/FEATURE_MAP.md ("Non-Drift Rule"), CLAUDE.md
   (Development Practice bullet). Home: DOCUMENTATION_STANDARD. Others become one-line
   pointers.
2. History/roadmap-docs-are-not-authority rule stated 3x: CONTRIBUTING.md Rule 7,
   core/contracts/FRAMEWORK_BASELINE.md ("Removal Rules"), docs/governance.md ("Locked
   Baseline Rules"). Home: FRAMEWORK_BASELINE.
3. run/verify/ship/support file-justification rule stated 2x verbatim: CONTRIBUTING.md
   ("Locked Framework Rule") and FRAMEWORK_BASELINE.md ("Purpose"). Home: FRAMEWORK_BASELINE.
4. Source-of-truth doc lists stated 3x with drift risk: CONTRIBUTING.md
   ("Source-of-Truth Documents" + "Baseline Contract"), FRAMEWORK_BASELINE.md ("Support"),
   README.md ("Key Docs"). Home: FRAMEWORK_BASELINE's Support list; others point.

**Procedure (per duplication):** pick the home listed above; replace every other
occurrence with `See <home-file> "<section>"`; never delete a rule without confirming the
home copy states it at least as strictly.

**Acceptance criteria:** (a) `bash scripts/validate.sh` green; (b) `bash
scripts/link-check.sh` green; (c) re-run the `wc -w` total — must be lower; (d) for each
of the 4 duplications, `git grep` the rule's key phrase returns exactly ONE file with the
full rule text (pointers don't count); (e) no rule weakened — diff review confirms
deletions are restatements only.

**Guardrails:** do NOT touch `.githooks/pre-commit` or any script. Doc/contract text only.
One commit per duplication collapsed, gates run before each commit.

### OC-3. Prompt Library value audit — LOW — PARTIALLY FIXED 2026-07-08
- Retired the 4 prompts `full-qa-pass.sh`'s own header named as its LLM equivalents
  (QA-15/16/17/ALL) plus their orchestration guide; updated REF-01 and the QA scripts'
  pointers to the script paths. Remaining ~19 prompts (story-lifecycle QA series, WF, RM)
  have no script equivalent — kept pending a content-level value audit.

**Remainder spec (the content-level audit):**
- **Scope:** every file in `prompts/` except README.md (~19 files: QA-01..QA-14, REF-01,
  RM-01, WF-01, WF-02).
- **Per-file procedure:** (1) read the prompt fully; (2) check overlap against
  `core/workflows/*.md` (story-lifecycle-sop, backlog-workflow, qa-process, full-qa-audit
  cover the same territory) and `skills/INDEX.md`; (3) classify: KEEP (unique procedure
  not in any workflow/skill/script), MERGE (fold unique content into the overlapping
  workflow doc, delete prompt), or RETIRE (fully covered elsewhere).
- **Known suspects:** QA-01..QA-14 parallel `core/workflows/story-lifecycle-sop.md` +
  `qa-process.md` step-by-step; WF-01/WF-02 parallel `core/workflows/backlog-workflow.md`.
  Verify by reading, don't assume.
- **Acceptance criteria:** every prompt has a recorded verdict here with one-line evidence;
  `prompts/README.md` table matches the surviving set exactly; link-check green.
- **Guardrails:** never delete a prompt whose procedure exists nowhere else — MERGE first.

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

### OC-11. Docs-reality audit of the remaining docs/ surface — MEDIUM — OPEN

**Why:** this pass verified README, ARCHITECTURE, governance, FEATURE_MAP, BACKLOG. Not
re-verified since heavy restructuring: `docs/TOKEN_POLICY.md`,
`docs/write-mode-enforcement-protocol.md`, `docs/KEEPALIVE_STANDARD.md`,
`docs/bots-gateway.md`, `docs/troubleshooting.md`, `docs/OLIVERCODE_LAUNCHER.md`,
`docs/FEATURE_MAP.md` (row-level), `docs/DOCUMENTATION_STANDARD.md`,
`docs/skills-placement.md`, plus `core/workflows/*.md` (7 files) and
`core/contracts/*.md` not touched today.

**Procedure:** run the `docs-reality-audit` skill against this repo, scoped to the list
above. For every factual claim (a path, a command, a count, a gate number), verify against
the live file/script per the skill's Phase 3 table. Fix stale claims in place; log
contradictions between two docs as findings here before choosing the home.

**Acceptance criteria:** every doc in scope carries zero claims that fail verification;
gates + link-check green; findings and fixes appended to this item with file:claim pairs.

**Guardrails:** current-state wording rules apply (no "previously/no longer" phrasing —
see DOCUMENTATION_STANDARD "Current-State Wording"). Don't rewrite style, only truth.

### OC-12. `core/workflows/` vs `prompts/` overlap consolidation — LOW — OPEN (depends on OC-3 remainder)

**Why:** two parallel procedure libraries cover the story/QA/backlog lifecycle. Suspected
near-duplicates: `qa-process.md`+`full-qa-audit.md` vs prompts QA-01..QA-14;
`backlog-workflow.md` vs WF-01/WF-02. Same one-home rule as OC-2.

**Procedure:** execute OC-3's remainder first (its verdicts are this item's input). Then
for each MERGE verdict, fold the prompt's unique content into the owning workflow doc and
delete the prompt; for workflow docs left with no unique content, point them at the
surviving home.

**Acceptance criteria:** no procedure step exists in both a workflow doc and a prompt;
`prompts/README.md` and `core/workflows/README.md` both accurate; gates + link-check green.

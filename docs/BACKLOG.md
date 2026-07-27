# BACKLOG — OliverCode

Forward-looking framework improvements only. Historical audit worklogs live outside this
repo (they are operator-specific session records, not framework material — per this
framework's own removal rule: history/status docs are not active authority).

Status values: OPEN, IN-PROGRESS, FIXED, WONT-FIX (with reason).
Severity: HIGH (gate silently broken / wrong result), MEDIUM (wrong on real inputs or
misleading), LOW (polish, drift).

---

## Design decisions (stable rationale — referenced from code and docs by ID)

These IDs are cited from `.gitignore`, `scripts/validate.sh`, contract JSON `_note` fields,
and several docs. They are settled decisions, not open items.

- **G1 — Example-config + local-overlay pattern.** Tracked files ship placeholder-only
  registries (`shared/*.example.json`, placeholder `shared/repo-map.json` etc.); the real
  fleet lives in gitignored `local/` copies. Loaders try the local overlay first and fall
  back to the tracked example with a WARN. Personal data never enters tracked files.
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

Specs are written context-free: a future agent with no session memory should be able to
execute each one from what is written here.

### A1 — Reference-integrity gate for backtick paths (HIGH)

`scripts/link-check.sh` only matches inline markdown links whose target ends in `.md`. On
this repo that is 9 links; the repo's actual cross-references are backtick-quoted repo paths,
of which there are hundreds. Every stale path found in the full-file audit survived through
this hole.

Build: extend `link-check.sh` (or add a sibling checker wired into it) to extract
backtick-quoted tokens starting with a tracked top-level dir (`scripts/`, `core/`, `docs/`,
`shared/`, `skills/`, `tests/`, `.githooks/`, `.github/`, `.claude-optimization/`) and assert
each resolves on disk. Required exclusions, all verified as legitimate today:
- files under `core/templates/` — their paths are relative to the DOWNSTREAM repo, not here
- `docs/repo-structure-contract.md`, `.github/user-stories/*`, `scripts/validate-repo.sh` —
  same reason, they describe target repos
- tokens containing `<`, `>`, `*`, `|`, `$` (placeholders)
- the deliberate anti-pattern examples in `core/contracts/FILE_LOCATION_STANDARD.md`

Wire into `scripts/validate.sh` and `.github/workflows/framework-ci.yml`. Fail closed.

### A2 — INDEX/directory parity check for skills (MEDIUM)

`skills/INDEX.md`'s table and the `skills/*/SKILL.md` directories can drift in both
directions, and the check is documented as manual in INDEX.md's own Validation section.
Build a check that asserts set equality between the table's skill names and the directory
listing, and wire it into `validate.sh`. Frontmatter `name:` must also match its directory
name — `scripts/olivercode skills` reads frontmatter while humans read the table.

### A3 — Gate-count consistency check (MEDIUM)

The pre-commit gate count is restated in several docs and has drifted before
(`QUALITY_BASELINE.md` said 6 while the hook had 8). Build a check that derives the real
count from `.githooks/pre-commit` (`grep -c 'Gate [0-9]/'`) and greps tracked docs for a
contradicting "N gates" claim. Prefer this over hand-auditing on each hook change.

### A4 — Make CI fail on QA findings (MEDIUM)

`framework-ci.yml` runs `full-qa-pass.sh`, but every phase is advisory, so a finding cannot
fail the build. Decide the strict set (`check-bloat.sh --strict` at minimum) and make CI
honor it. Confirm the current baseline is clean first so the switch does not land red.

### A5 — Tests for the enforcement surfaces (HIGH)

`tests/` covers a frontmatter parser and a profiles loader. Neither is a gate. There are zero
tests for the 8 pre-commit gates and zero for `validate_evidence()` in
`scripts/orchestration-gatekeeper.py` — the one function whose silent failure means a false
completion claim passes. Add fixture-driven tests: for each gate, one staged input that must
block and one that must pass; for `validate_evidence()`, one case per required-evidence field
covering both the missing and the malformed shape.

### A7 — model-routing remains a declared scope exception (LOW)

`skills/model-routing/` is built on `LLM_PROVIDER_ORDER` and cheapest-vs-capable provider
tiers, while `CONTRIBUTING.md` mandatory rule 1 names Anthropic the sole model provider and
forbids multi-provider framing without an implementation behind it. Kept deliberately
(owner decision, 2026-07-27) as a pattern contract rather than a claim about this
framework's runtime. Do not re-raise as drift; if it is ever removed, tear down
`~/.claude/skills/model-routing` in the same session or `olivercode health` reports a broken
symlink.

---

## Live tracker — current state for the next agent

### Where things stand (2026-07-27)

- Full read-every-file audit of all tracked files completed and executed: defect fixes,
  legacy-reference strip, doc consolidation, and both owner decisions applied.
- Removed: the conflicting `install-enforcement.sh`/`pre-commit-gate.sh` hook installer, a
  no-op QA phase, orphaned docs/configs, four micro-workflows folded into canonical homes.
- Doc duplication collapsed: trigger routing, testing baseline, backlog procedure, gate
  table, branch lifecycle, quality baseline, and the skills catalog each have one home.
- Every file under `core/templates/project/` is now declared in the bootstrap manifest —
  `templatedFiles` for the unconditional ones, `conditionalFiles` for the keepalive set,
  which syncs only where a repo's `keepalive` profile block enables it.
- Open work is A1-A5 above: all five are new gates/tests, deliberately specced not built.

### Coverage

Reviewed through: `9c87a91` (2026-07-27, full-file audit)

### Deliberately kept (validated decisions — do not redo)

- `core/templates/project/pre-commit` intentionally differs from `.githooks/pre-commit`:
  the OliverCode copy adds Gate 6 (contract integrity) and Gate 8 (token policy); the
  template carries the anon-key meta-tag allowlist. Both are correct; do not converge them.
- `scripts/qa/check-code-quality.sh` is TypeScript-leaning and several of its sections are
  low-yield on this repo. It earns its place on the Next.js fleet repos, which are its real
  target. Not a cleanup candidate here.
- `core/contracts/AGENT_SYSTEM_MANIFEST.json` looks like a duplicate of
  `AGENT_SHARED_STRUCTURE.md` but is the tracked half of the G1 example/overlay pair and has
  a real `local/` counterpart. Keep both.
- `skills/model-routing/` — see A7.
- The keepalive surface — in scope by owner decision, not an orphan.

### Activity log (append here, newest last)

- 2026-07-27 [audit] Defect fixes + orphan removal, commit `ed1e4d1`.
- 2026-07-27 [audit] Legacy-reference strip, doc consolidation, specs written, `e773ff1`.
- 2026-07-27 [audit] Path map / baseline rules to one home, `67bc6ff`.
- 2026-07-27 [audit] FEATURE_MAP made a real index, `8e19b17`.
- 2026-07-27 [audit] Product paths out of the location contract, lib imports unified, `9c87a91`.
- 2026-07-27 [audit] Owner decisions applied: keepalive brought into scope via
  `conditionalFiles`; `vault-content-parsing` moved to the vault's `.olivercode/user-skills/`
  with its symlink repointed and the ledger updated; `model-routing` kept as a declared
  exception. A6 and A8 resolved, A7 reduced to a keep-note.

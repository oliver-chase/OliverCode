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

### OC-1. `security-review` skill name collides with a built-in Claude Code skill — LOW — OPEN
- This repo's `skills/security-review` and Claude Code's built-in `security-review` share an
  exact name. Which one wins at invocation time is untested. Test; rename ours (e.g.
  `code-security-review`) if the built-in shadows it.

### OC-2. Token-efficiency pass over the contract/doc layer — MEDIUM — OPEN
- `core/contracts/` + `docs/` load into agent context on demand; several contracts restate
  each other's rules at length (FRAMEWORK_BASELINE vs CONTRIBUTING vs DOCUMENTATION_STANDARD
  overlap on doc-sync rules). One home per rule, pointers elsewhere — measured target:
  reduce total tracked authority-doc token count without losing a single enforceable rule.

### OC-3. Prompt Library value audit — LOW — OPEN
- 27 tracked fill-in-the-blank session prompts predate the skills system. Several (QA-15/16/17)
  duplicate what `scripts/qa/*.sh` now does deterministically. Audit each: still adds value
  over a skill/script, or retire.

### OC-4. `olivercode health` fleet checks assume the vault layout — LOW — OPEN
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

### OC-6. Stranger-fork CI — LOW — OPEN
- G4's stranger-clone rehearsal is manual. A minimal GitHub Actions workflow running
  `scripts/olivercode health` + `bash scripts/validate.sh` + `scripts/link-check.sh` on
  push would catch fresh-clone regressions automatically. (This repo currently ships no CI
  by design — revisit whether that ruling still holds now that the repo is public-facing.)

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

None open. Closed audit items (OC-1..OC-12, resolved 2026-07-08) are archived in the vault history file `.olivercode/olivercode-backlog-history.md` — per this file's own rule that history is not active authority.

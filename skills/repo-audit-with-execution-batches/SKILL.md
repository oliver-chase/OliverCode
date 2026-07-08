---
name: repo-audit-with-execution-batches
description: "Run a structured 7-part repo audit that discovers FIX/PATCH/TODO/HACK/FIXME markers, structural gaps, doc staleness, and code-quality issues."
---

# Repo Audit with Execution Batches

## The 7-Part Audit

Run in order. Each batch produces a report section. Don't batch all at once — audit reveals issues that change subsequent batch findings.

### Batch 1 — Surface Scan

Same first step as `repo-discovery` — reuse that skill's Surface Scan/Entry Points steps instead of re-deriving them here. Identify: language, framework, build system, test runner, CI config.

### Batch 2 — Marker Hunt

Search for: `FIX`, `PATCH`, `TODO`, `FIXME`, `HACK`, `XXX`, `BUG`, `WORKAROUND`, `temp`, `temporary`, `hack`

```bash
grep -rn "FIX\|TODO\|HACK\|FIXME\|BUG\|WORKAROUND" --include="*.js" --include="*.ts" --include="*.py" <dirs>
```

Report counts per category, not every occurrence.

### Batch 3 — Doc Freshness

Presence check only — does `README.md`/`AGENTS.md`/`CLAUDE.md`/`ARCHITECTURE.md`/`docs/` exist and look current at a glance? For a real claim-by-claim verification of docs against live code (routes, migration counts, design tokens, cron schedules, story IDs) plus no-duplication consolidation, that's a distinct pass — use `docs-reality-audit`, don't improvise it inline here.

### Batch 4 — Structural Validation

Against `PROJECT_STRUCTURE_STANDARD.md` (from OliverCode contracts):
- Does the layout match conventions?
- Are there files at wrong paths?
- Are there orphaned files?

### Batch 5 — Config Drift

- `package.json` vs lockfile — in sync?
- `.env.example`/`.env.local.example` vs actual env vars used in code
- CI config vs actual build/test commands

### Batch 6 — Security Surface

Presence check only — hardcoded secrets (API keys, tokens, passwords), `.gitignore`
coverage, public exposure risk. For the real vulnerability-class walkthrough (injection,
auth bypass, IDOR, SSRF, path traversal, XSS, insecure deserialization), that's a distinct
pass — use `code-security-review`, don't improvise it inline here.

### Batch 7 — Summary + Priority

Produce a ranked list by impact × fix difficulty. Each finding: file:line, category, proposed fix.

## Complementary Skills — Hand Off, Don't Improvise Inline

This audit finds and categorizes issues; it doesn't fix them in depth. When a batch turns up something that has its own dedicated skill, hand off to it rather than doing a lighter version here:

- Batch 2 (markers) surfaces an actual bug → `/code-review`
- Batch 6 (security) surfaces something worth a real vulnerability-class walkthrough → `code-security-review`
- Batch 2 or Batch 4 surfaces real duplication/dead code (not just a marker comment) → `/simplify`
- Any batch surfaces something actually broken, not just messy → `diagnosing-bugs` for root cause, before proposing a fix
- The repo has a UI and the audit is part of a broader project review → `/ux-ui` as a separate pass
- The ask is a FULL functionality audit of a live product (does everything actually work end to end, fix quick wins inline, crash-safe incremental findings) → `functionality-audit`, not this skill

## Output Format

```markdown
## Batch N — <name>
Depth: CHARACTER-LEVEL / SAMPLED

| File | Issue | Priority |
|------|-------|----------|
| path/to/file.js:42 | TODO left in production code | Medium |
```

---

> Authored 2026-06-12.

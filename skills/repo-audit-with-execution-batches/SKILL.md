---
name: repo-audit-with-execution-batches
description: "Run a structured 7-part repo audit that discovers FIX/PATCH/TODO/HACK/FIXME markers, structural gaps, doc staleness, and code-quality issues."
---

# Repo Audit with Execution Batches

## The 7-Part Audit

Run in order. Each batch produces a report section. Don't batch all at once — audit reveals issues that change subsequent batch findings.

### Batch 1 — Surface Scan

Read-only. Identify: language, framework, build system, test runner, CI config.

### Batch 2 — Marker Hunt

Search for: `FIX`, `PATCH`, `TODO`, `FIXME`, `HACK`, `XXX`, `BUG`, `WORKAROUND`, `temp`, `temporary`, `hack`

```bash
grep -rn "FIX\|TODO\|HACK\|FIXME\|BUG\|WORKAROUND" --include="*.js" --include="*.ts" --include="*.py" <dirs>
```

Report counts per category, not every occurrence.

### Batch 3 — Doc Freshness

Presence check only — does `README.md`/`AGENTS.md`/`CLAUDE.md`/`ARCHITECTURE.md`/`docs/` exist and look current at a glance. A real claim-by-claim verification of docs against live code (routes, migration counts, design tokens, cron schedules, story IDs) plus no-duplication consolidation is a distinct pass — see "Complementary Skills" below.

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
coverage, public exposure risk. A real vulnerability-class walkthrough (injection, auth
bypass, SSRF, XSS) is a distinct pass — see "Complementary Skills" below.

### Batch 7 — Summary + Priority

Produce a ranked list by impact × fix difficulty. Each finding: file:line, category, proposed fix.

## Complementary Skills — Hand Off, Don't Improvise Inline

This audit finds and categorizes issues. It doesn't fix them in depth. When a batch turns up something that has its own dedicated skill, hand off to it rather than doing a lighter version here:

- Batch 2 (markers) surfaces an actual bug → `/code-review`
- Batch 6 (security) surfaces something worth a real vulnerability-class walkthrough → `/security-review`
- Batch 2 or Batch 4 surfaces real duplication/dead code (not just a marker comment) → `/simplify`
- Any batch surfaces something actually broken, not just messy → `diagnosing-bugs` for root cause, before proposing a fix
- The repo has a UI and the audit is part of a broader project review → hand off to whichever frontend/design skill the machine has installed (OliverCode ships none — see `docs/EXTERNAL-TOOLING.md`), as a separate pass

## Output Format

```markdown
## Batch N — <name>
Depth: CHARACTER-LEVEL / SAMPLED

| File | Issue | Priority |
|------|-------|----------|
| path/to/file.js:42 | TODO left in production code | Medium |
```

# File Location Standard

Status: Active
Effective Date: 2026-05-22
Scope: All Oliver projects, public and private

## Purpose

Define exactly where every file type belongs across ALL Oliver projects. This eliminates ambiguity about where to save plans, docs, credentials, personal files, and runtime artifacts. Every agent and every human contributor follows the same location rules.

## Canonical Location Map

| If it is a... | Save to... | Notes |
|---|---|---|
| Project plan / proposal | `<repo>/docs/plans/YYYY-MM-DD-<slug>.md` | Dated, one per plan. Plans are operating system docs. |
| System / architecture doc | `<repo>/docs/<TOPIC>.md` | Descriptive filename in ALL_CAPS or kebab-case. |
| Credential / secret | `.env.local` (gitignored, never committed) | Local only. `.env.example` shows variable names + placeholders only. |
| Personal file / voice content | `private-runtime/voice/` | Gitignored. Contains persona data, tone samples, personal notes. |
| Agent skill reference | `OliverCode/skills/` | The one tracked home for non-personal skills — see `docs/skills-placement.md`. |
| Runtime artifact / output | `_Automation/latest/` | Generated files from automation runs. Not hand-edited. |
| Outreach / SDR output | `<repo>/sdr/outreach/latest/` | If repo has SDR subdirectory. |
| Content production output | `_Automation/latest/content-production/` | Draft content waiting for approval. |
| Lead research output | `_Automation/latest/lead-research-<date>.json` | Dated, one per research batch. |

## Anti-Patterns — NEVER Do These

| Anti-pattern | Wrong location | Why it is wrong | Correct location |
|---|---|---|---|
| Plans in an agent-OS dir | `.claude-optimization/plans/my-plan.md` | Agent-OS directories (e.g. `.claude-optimization/`) are for that agent's own runtime internals, not project deliverables. | `docs/plans/YYYY-MM-DD-my-plan.md` |
| Credentials committed | `.env` in git | Leaks secrets to version control. | `.env.local` (gitignored) |
| Personal files in repo root | `voice-notes.md` at repo root | Pollutes project structure with personal data. | `private-runtime/voice/` |
| Runtime artifacts in docs | `docs/output/report.json` | Runtime output is not documentation. | `_Automation/latest/report.json` |
| Agent skills duplicated | Copying skill files into each repo | Skills go stale; single source of truth is OliverCode. | `.<agent-os>/skills/` with pointer to OliverCode |
| Plans undated in root | `docs/plan.md` | Cannot track plan history or sequence. | `docs/plans/YYYY-MM-DD-<slug>.md` |

## Discovery Process for New File Types

When you encounter a file type that does not appear in the canonical map:

1. **Classify the file** — Is it a plan? A doc? A credential? A runtime artifact? Personal content?
2. **Check the map** — Does it fit an existing category?
3. **If no match** — Determine the closest category and propose the location.
4. **Update this standard** — Add the new file type to the canonical map with justification.
5. **Sync all repos** — Update `docs/repo-structure-contract.md` in every repo that uses the new file type.

## Gitignore Rules

These paths must be gitignored in ALL repos:

```
# Credentials and secrets
.env.local
.env
*.secret
*.pem
*.key

# Personal / voice files
private-runtime/

# Runtime artifacts
_Automation/

# Agent runtime state (per-agent OS directory, e.g. .claude-optimization/)
.claude-optimization/memory/
.claude-optimization/state/

# OS files
.DS_Store
Thumbs.db
```

## Enforcement

1. Pre-commit hooks block commits that violate location rules (PII in wrong locations, credentials committed).
2. `docs/repo-structure-contract.md` in each repo must list the active file locations for that repo.
3. Cross-repo audit: pre-commit gates check for location violations in staged files.
4. New repos must include this standard's location map in their structure contract.

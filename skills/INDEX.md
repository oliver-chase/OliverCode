# skills/ — OliverCode Skill Index

> OliverCode ships orchestration/security/optimization skills only — engineering method and
> the framework's own tooling. Load by name when you encounter the domain. This is the
> source of truth — add or edit skills directly here, and update this table in the same
> change. See `docs/SKILLS-PLACEMENT.md` for how to add a new one.

## Method and orchestration skills

| Skill | Domain | Load When |
|-------|--------|-----------|
| `diagnosing-bugs` | Tight-feedback-loop bug diagnosis (6 phases) | Hard bugs, regressions, "debug this" |
| `docs-reality-audit` | Docs-vs-code truth check + no-duplication consolidation | Simplifying/updating docs, or docs claim things that look stale |
| `repo-audit-with-execution-batches` | Structured repo audit — surface scan, marker hunt, report | Quick scan-and-report audit of a repo |
| `deep-review` | Post-build review loop — single review agent over a commit range, simplify pass, remove-don't-archive cleanup, live re-verification, session tracker | Before closing any multi-commit build session ("review tonight's work") |
| `automation-first-agent-design` | Agent workflow design | Designing agent workflows |
| `olivercode-adoption` | Onboarding a fork into an existing setup | "Set this up for my repos", pointing existing CLAUDE.md files at OliverCode |
| `plan` | Markdown planning | Planning a task before executing |
| `backlog-management` | Config-driven GitHub Project backlog ops | Filing, closing, or triaging backlog work in a repo that names a backlog-config.json in its own CLAUDE.md |
| `board-hygiene` | Live GitHub Project board check across 6 dimensions: required fields, status drift, duplicate cards, Ready occupancy, Area freshness, Ready candidates | After filing or closing backlog items, or "is the backlog properly organized" |
| `plan-pressure-test` | Adversarial check of a plan doc against live system state before it runs | "Pressure test this plan", or before executing a plan doc from `plan` |
| `skill-creation` | Intake for a new skill: overlap check first, then the baseline every new skill meets | "New skill", "build a skill for X", "should this be a new skill" |

## Rules

- Keep only orchestration/security/optimization skills in `skills/<name>/SKILL.md`. Anything
  that isn't an engineering-method skill or the framework's own tooling doesn't belong here —
  no exceptions. A skill that only makes sense inside one product repo belongs in that repo's
  own `.claude/skills/`. Personal/business skills belong in the personal skills folder
  (`skillsRoot` in `olivercode.local.json`).
- Update this table in the same change when a skill is added or removed. This index is the
  only catalog — do not create a second copy of the skill list anywhere.
- Remove references to retired skills instead of keeping dead aliases alive.
- Adding one: `docs/SKILLS-PLACEMENT.md` has the full contract (real content, index row, and
  the `~/.claude/skills/<name>` symlink — all three in the same session).

## Validation

Mechanical: `bash scripts/validate.sh` fails if a row here has no matching
`skills/<name>/SKILL.md`, if a skill directory has no row, or if a `SKILL.md`'s frontmatter
`name:` disagrees with its directory name (the launcher lists by frontmatter, humans read
this table). See `scripts/lib/consistency_check.py`.

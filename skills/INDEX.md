# skills/ — OliverCode skill index

> OliverCode ships orchestration/security/optimization skills only — engineering method and
> the framework's own tooling. Load by name when you encounter the domain. This is the
> source of truth — add or edit skills directly here, and update this table in the same
> change. See `docs/RULES.md` ("Skill placement") for how to add a new one.

## Method and orchestration skills

| Skill | Domain | Load When |
|-------|--------|-----------|
| `diagnosing-bugs` | Tight-feedback-loop bug diagnosis (6 phases) | Hard bugs, regressions, "debug this" |
| `audit` | The one audit, with a router: a whole repo or suite, a skill or family, the docs, a commit range or a plan. Reads every line, checks seven lenses, files fixes as one epic | "Audit this", "QA this", "review tonight's work", "are the docs accurate", "audit my skills", "pressure test this plan", and before closing a multi-commit session |
| `olivercode-adoption` | Onboarding a fork into an existing setup | "Set this up for my repos", pointing existing CLAUDE.md files at OliverCode |
| `plan` | Markdown planning | Planning a task before executing |
| `backlog` | Config-driven GitHub Project backlog: files, closes and sweeps the board across 8 dimensions (required fields, status drift, duplicate cards, Ready occupancy, Area freshness, Ready candidates, stale items, QA sign-off) | Filing, closing or sweeping backlog work in a repo that names a backlog-config.json in its own CLAUDE.md; "board hygiene", "is the backlog properly organized" |
| `skill-creation` | Intake for a new skill: overlap check first, then the baseline every new skill meets | "New skill", "build a skill for X", "should this be a new skill" |

## Rules

- Keep only orchestration/security/optimization skills in `skills/<name>/SKILL.md`. Anything
  that isn't an engineering-method skill or the framework's own tooling doesn't belong here —
  no exceptions. A skill that only makes sense inside one product repo belongs in that repo's
  own `.claude/skills/`. Personal/business skills belong in the personal skills folder
  (`skillsRoot` in `olivercode.local.json`).
- Update this table in the same change when a skill is added or removed. This index is the
  only catalog — do not create a second copy of the skill list anywhere.
- Remove references to retired skills, and keep no dead aliases.
- Adding one: `docs/RULES.md` ("Skill placement") has the full contract (real content, index row, and
  the `~/.claude/skills/<name>` symlink — all three in the same session).

## Validation

Mechanical: `bash scripts/validate.sh` fails if a row here has no matching
`skills/<name>/SKILL.md`, if a skill directory has no row, or if a `SKILL.md`'s frontmatter
`name:` disagrees with its directory name (the launcher lists by frontmatter, humans read
this table). See `scripts/lib/consistency_check.py`.

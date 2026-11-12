# skills/ — OliverCode skill index

> OliverCode ships orchestration/security/optimization skills only — engineering method and
> the framework's own tooling. Load by name when you encounter the domain. This is the
> source of truth. Add or edit skills here, and update this table in the same change. See `docs/RULES.md` ("Skill placement") for how to add a new one.

## Method and orchestration skills

| Skill | Domain |
|-------|--------|
| `diagnosing-bugs` | Bug diagnosis through a tight feedback loop |
| `audit` | The one audit: a whole repo to done, a skill or family, the docs, a commit range or a plan |
| `olivercode-adoption` | Onboarding a fork into an existing setup |
| `plan` | Markdown planning before work starts |
| `backlog` | A repo's GitHub Project backlog: file, close and sweep the board |
| `skill-creation` | Intake for a new skill, with the overlap check first |

## Rules

- Keep only orchestration/security/optimization skills in `skills/<name>/SKILL.md`. Anything
  that isn't an engineering-method skill or the framework's own tooling doesn't belong here —
  no exceptions. A skill that only makes sense inside one product repo belongs in that repo's
  own `.claude/skills/`. Personal/business skills belong in the personal skills folder
  (`skillsRoot` in `olivercode.local.json`).
- Update this table in the same change when a skill is added or removed. This index is the
  hand-written list of skills. `docs/CATALOG.md` is generated from the code by the audit skill's `catalog.py`, so never edit it.
- Remove references to retired skills, and keep no dead aliases
- Adding one: `docs/RULES.md` ("Skill placement") has the full contract (real content, index row, and
  the `~/.claude/skills/<name>` symlink — all three in the same session).

## Validation

Mechanical: `bash scripts/validate.sh` fails if a row here has no matching
`skills/<name>/SKILL.md`, if a skill directory has no row, or if a `SKILL.md`'s frontmatter
`name:` disagrees with its directory name (the launcher lists by frontmatter, humans read
this table). See `scripts/lib/consistency_check.py`.

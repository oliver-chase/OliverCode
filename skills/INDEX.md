# skills/ — OliverCode skill index

> OliverCode ships orchestration/security/optimization skills only — engineering method and
> the framework's own tooling. Load by name when you encounter the domain. This is the
> source of truth. Add or edit skills here, and update this table in the same change. See `docs/RULES.md` ("Skill placement") for how to add a new one.

## Method and orchestration skills

| Skill | Domain |
|-------|--------|
| `diagnosing-bugs` | Bug diagnosis through a tight feedback loop |
| `audit` | The one audit: a whole repo to a report and filed issues, a skill or family, the docs, a commit range or a plan |
| `olivercode-adoption` | Onboarding a fork into an existing setup |
| `plan` | Markdown planning before work starts |
| `backlog` | A repo's GitHub Project backlog: file, close and sweep the board |
| `skill-creation` | Intake for a new skill, with the overlap check first |

## Rules

Add, move or retire a skill per `docs/RULES.md` ("Skill placement") and update this table in the same change. `bash scripts/validate.sh` checks the table against each `skills/<name>/SKILL.md` and its `name:`. Remove references to retired skills, and keep no dead aliases.

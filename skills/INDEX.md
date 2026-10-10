# skills/ — OliverCode Skill Index

> OliverCode ships orchestration/security/optimization skills only — engineering method and
> the framework's own tooling. Load by name when you encounter the domain. This is the
> source of truth — add or edit skills directly here, and update this table in the same
> change. See `docs/SKILLS-PLACEMENT.md` for how to add a new one.

## Method and orchestration skills

| Skill | Domain | Load When |
|-------|--------|-----------|
| `never-guess` | Data-first approach | When tempted to estimate instead of measure |
| `diagnosing-bugs` | Tight-feedback-loop bug diagnosis (6 phases) | Hard bugs, regressions, "debug this" |
| `tdd` | Test-driven development — tracer-bullet vertical slices | Building features test-first, red-green-refactor |
| `docs-reality-audit` | Docs-vs-code truth check + no-duplication consolidation | Simplifying/updating docs, or docs claim things that look stale |
| `repo-discovery` | Read-only repo exploration | Entering an unfamiliar repo |
| `repo-audit-with-execution-batches` | Structured repo audit — surface scan, marker hunt, report | Quick scan-and-report audit of a repo |
| `functionality-audit` | Full product functionality audit — crash-safe incremental, quick wins inline, context-free specs, RLS/tooltips/revert/complete-but-isn't | Full audit of a live product ("audit everything", "what's broken/missing/fake-done") |
| `code-security-review` | Vulnerability-class review — injection, auth bypass, IDOR, SSRF, path traversal, XSS, insecure deserialization | Security review, or touching auth/input-parsing/file-paths/external-requests/serialization |
| `deep-review` | Post-build review loop — single review agent over a commit range, simplify pass, remove-don't-archive cleanup, live re-verification, session tracker | Before closing any multi-commit build session ("review tonight's work") |
| `automation-first-agent-design` | Agent workflow design | Designing agent workflows |
| `olivercode-cli` | OliverCode CLI launcher | Modifying CLI, command routing, help surface |
| `olivercode-adoption` | Onboarding a fork into an existing setup | "Set this up for my repos", pointing existing CLAUDE.md files at OliverCode |
| `plan` | Markdown planning | Planning a task before executing |
| `backlog-management` | Config-driven GitHub Project backlog ops | Filing, closing, or triaging backlog work in a repo that names a backlog-config.json in its own CLAUDE.md |
| `model-routing` | Model tier selection strategy (cheap vs capable) | Choosing which model tier handles a task |
| `writing-documentation` | Write any README/doc to the locked documentation standard (outline, voice, naming, About) — docs/DOCUMENTATION_STANDARD.md is the one home |

## Personas (not skills, kept in `core/personas/`)

- `oliver` -> `core/personas/oliver/persona_soul.md`

No team template.

## Rules

- Keep only orchestration/security/optimization skills in `skills/<name>/SKILL.md`. Anything
  that isn't an engineering-method skill or the framework's own tooling doesn't belong here —
  no exceptions. A skill that only makes sense inside one product repo belongs in that repo's
  own `.claude/skills/`. Personal/business skills belong in the vault's
  `Operations Vault/01 - Skills/`.
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

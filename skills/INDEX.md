# skills/ — OliverCode Skill Index

> OliverCode ships orchestration/security/optimization skills only — engineering method and
> the framework's own tooling. Load by name when you encounter the domain. This is the
> source of truth — add or edit skills directly here, and update this table in the same
> change. See `docs/skills-placement.md` for how to add a new one.

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
| `repo-structural-cleanup` | File moves, renames, deletes | Restructuring a repo |
| `structured-code-removal` | Safe feature/module removal | Removing a feature safely |
| `behavior-preserving-module-extraction` | Refactoring patterns | Extracting a module from a monolith |
| `validator-consolidation` | Merge validate scripts | Consolidating overlapping validators |
| `automation-first-agent-design` | Agent workflow design | Designing agent workflows |
| `agent-os-parallel-structure` | Agent OS design | Building a parallel agent OS for a secondary agent |
| `vault-content-parsing` | Vault conventions | Parsing vault content, building vault tooling |
| `olivercode-cli` | OliverCode CLI launcher | Modifying CLI, command routing, docker guards |
| `plan` | Markdown planning | Planning a task before executing |
| `model-routing` | Model tier selection strategy (cheap vs capable) | Choosing which model tier handles a task |

`frontend-ui-references` moved to the vault's `.olivercode/user-skills/` -- design/UI reference
routing doesn't fit OliverCode's scope (security, token optimization, dev practices, folder
structure).

## Personas (not skills, kept in `core/personas/`)

- `oliver` -> `core/personas/oliver/persona_soul.md`

No team template.

## Non-goals

Anything that isn't an engineering-method skill or the framework's own tooling doesn't
belong in this index — no exceptions carved out here for any other kind of content.

> Last updated: 2026-07-08 | 19 skills, all tracked in this repo

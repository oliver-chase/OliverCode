# Live session tracker — template

> Canonical template (OliverCode `core/templates/project/docs/`). Copy this
> section into the target repo's BACKLOG (or equivalent open-work ledger) as
> its head or tail section. The `deep-review` skill maintains it.
> `scripts/audit-staleness.py` reads the "Reviewed through" marker fleet-wide.

---

## Live session tracker — current state for the next agent

**Convention: this section is the always-current picture. Any agent —
including review/audit subagents — finishing a unit of work APPENDS a
one-line status entry under "Activity log" in the same commit as the
work, so an agent picking up mid-stream (or working in parallel) sees
reality, not a stale snapshot. One line per entry. Detail lives in the
commit message or the spec it points to.**

### Where things stand (<date>)

<3-8 bullets: what is built/verified, what changed most recently.
Rewrite this block to stay current — it is a summary, not a log.>

### Coverage

Reviewed through: `<commit sha>` (<date>, deep-review)
Audited (functionality) through: `<commit sha>` (<date>) — or "never"

### Open items (ranked — pick from the top)

- [ ] <highest-leverage next action, with enough context to start cold>
- [ ] <...>

### Deliberately kept / not built (validated decisions — do not redo)

- <file or feature> — <why it stays / why it wasn't built>

### Activity log (append here, newest last)

- <date time> [<agent/role>] <one line: what completed, commit sha>

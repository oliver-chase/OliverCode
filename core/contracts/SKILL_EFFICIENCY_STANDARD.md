# Skill Efficiency Standard

Status: Active
Effective Date: 2026-09-15
Scope: Every `SKILL.md` and its `references/` directory, in any fleet repo, including
OliverCode's own `skills/` and the personal skills folder

A skill is loaded into context before it runs and its instructions get re-executed on
every call. A word that does not need to be in the file is a repeated cost, not a
one-time one, and the same is true of a tool call the skill's own instructions cause an
agent to repeat. This standard holds both surfaces — what the file says and what running
it makes an agent do — to one bar.

## 1. No monolith SKILL.md

A `SKILL.md` past the word cap with no `references/` split forces every invocation to
load content most calls never touch. Split a self-contained section out once the file
crosses the cap the fleet's structure checker enforces (`MONOLITH_WORD_CAP` in
`check_skill_structure.py`, not restated here — see rule 5 below on why). `meeting-notes`
and `vtwo-sow-proposal` are the reference pattern: a short `SKILL.md` that routes, and
`references/*.md` loaded only for the branch actually taken.

## 2. No duplicate paragraphs

The same paragraph restated across two skills, or twice inside one skill, is loaded
twice for no added information. Extract it to one file and have every consumer cite it —
the pattern `personal/_shared/asd-ste100-requirement.md` and
`vtwo-hr/_shared/tracker-conventions.md` already use. A restated paragraph that a fleet
audit did not yet catch is still a defect; catching it earlier does not change the fix.

**A vendored copy needs a hash check, not just an extraction.** Splitting content out
solves the token cost. It does not solve drift once more than one copy legitimately
needs to exist on disk (a plugin-less skill has no shared `references/` import, so some
families vendor a master into every consumer). When that is the real shape, pair it with
a `check-consistency.py`-style script that fails when a copy diverges from its master —
`vtwo-growth-shared`'s `CONTEXT-*.md` files are the reference pattern. A duplicate with
no hash check watching it is a duplicate the fleet will not notice drifting.

## 3. Writing itself is held to the density gate

`docs/SKILLS-PLACEMENT.md` already makes ASD-STE100 a warned, gated check for every
`SKILL.md`. That gate is this standard's authoring-density axis — restated here only as
a pointer, not a second copy: dense, unhedged, un-duplicated prose is not a style
preference for a skill file, it is the same token-cost concern as rules 1 and 2 applied
to the sentence level instead of the file level.

## 4. Automate the gap instead of asking for it

A skill that asks the user for something an MCP call, an env value, or a file on disk
could establish on its own spends a conversation turn — and the tokens in it — on
information the machine already has. `candidate-tracker-setup`'s convention is the
reference pattern: try automatic discovery first (a `sharepoint_search`, a synced local
path, a `.env.local` already partially filled), and ask only for what discovery could
not resolve. `automation-first-agent-design` states the general form: a deterministic
script call that always gives the same answer for the same input costs a fixed, small
number of tokens once; the same lookup reasoned through by an agent costs tokens on
every single call and can answer differently each time. Prefer the deterministic path
wherever correctness does not require judgment.

## 5. MCP-call efficiency, by name

A skill that documents an MCP-backed workflow is judged on the same named anti-patterns
`skill-governance/skill-fleet-audit`'s `check_mcp_patterns.py` checks for — full detection logic and
real precedent for each lives in that skill's `references/mcp-checks.md`, not restated
here:

- `no-concise-mode` — a documented search tool with no mention of concise/response-format
- `no-pagination` — a documented search tool with no mention of cursor/pagination
- `per-field-search-loop` — one search per blank field instead of one search per record
- `fuzzy-search-only` — a fuzzy search tool with no direct-path alternative documented
- `no-dry-run-first` — a write to a live/shared target with no dry-run-first step
- `no-pick-one-rule` — two alternative methods for one operation with no rule to finish
  one before starting the other

Each is grounded in a real, previously-shipped defect (SPEC-9, SPEC-16 in the vault's
`01 - Skills/_BACKLOG.md`), not a hypothetical.

## Enforcement reality

Mechanical today, for the personal skills folder only: `skill-governance/skill-fleet-audit` runs all
three checkers named above (structure/duplication, MCP-efficiency, ASD-STE100 clarity)
and its `SKILL.md` states the pattern each finding must clear before being treated as a
real defect. ASD-STE100 alone is also checked fleet-wide at commit time per
`docs/SKILLS-PLACEMENT.md` and `docs/GOVERNANCE.md`'s coverage table.

OliverCode's own `skills/` directory has no equivalent structure or MCP-efficiency gate
yet — rules 1, 2, 4, and 5 apply to it by this standard but are checked only by hand
until that gate exists (tracked in the `OliverCode` GitHub Project, issue #5). Until then, treat this file as the bar a
skill is written and reviewed against, not as something a hook currently blocks a commit
on outside the vault.

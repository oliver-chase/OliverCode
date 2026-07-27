---
name: docs-reality-audit
description: "Use when the user asks 'are these docs accurate', 'audit the docs', 'check the README against the code', 'do these docs contradict each other', or reports doc drift/stale instructions. Cross-checks every factual claim against live code, flags doc-vs-doc contradictions, consolidates to one file per concept."
---

# Docs Reality Audit

## Truth Hierarchy

```
Live code/config > package.json/tooling output > git log recency > docs
```

Docs are never truth — they're a claim about truth. A doc that reads as authoritative (dated, "Status: Active", specific line numbers, structured tables) is not more likely to be correct than a stale one. Verify every load-bearing claim against the thing it describes before trusting it.

## When to Use

The user wants documentation simplified, "brought up to date," or reviewed for accuracy — not just tidied. Also use proactively when a doc's own internal evidence (a "last updated" date far behind recent commits, a status note contradicted by the file tree) suggests drift.

## Process

### Phase 1 — Inventory + Recency Signal

```bash
find <repo-root> -iname "*.md" -not -path "*/node_modules/*" -not -path "*/archive/*" | sort
git log -1 --format=%ad --date=short -- <doc>          # doc's last touch
git log --oneline -15                                   # what's actually been happening lately
```

Compare doc last-touch dates against recent commit activity in the areas they describe. A doc untouched while its subject area has 10+ recent commits is the highest-probability drift candidate — read it first.

Also check local-vs-tracked drift before reading content: `git status` + `git diff origin/main --name-only`. A doc file present locally but not in git (or vice versa) needs reconciling before you audit its content — you could otherwise be auditing a file nobody else's clone even has.

### Phase 2 — Read Every Doc Fully

Skimming misses contradictions. Read each doc completely and extract its verifiable claims: routes/pages, file paths, env vars, table row counts (migrations, stories, API routes), commands, design tokens/colors/fonts, "required files" lists, status labels ("Active", "Functional", "Archived").

### Phase 3 — Verify Every Claim Against Code

Never trust a doc's inventory of itself. Check the filesystem directly:

| Claim type | Verify against |
|---|---|
| Routes/pages exist | `find app -name "page.tsx"` (or framework equivalent) — not the doc's route table |
| Commands work | `package.json` `scripts` block |
| Env vars | `.env.example` + the config loader (e.g. `lib/config/env.ts`) that reads `process.env` |
| Migration/file counts | `ls <migrations-dir>` — count directly, don't trust a doc's "N migrations" claim |
| Design tokens/colors/fonts | The actual CSS/theme file's current contents, not a PRD or historical mockup |
| Cron/schedule claims | The actual scheduler config (`wrangler.toml`, CI YAML, crontab) — read its comments, they often record what was *tried and reverted* |
| CI/deploy steps described in docs | `.github/workflows/*.yml` — confirm the doc's described steps match what the workflow actually runs |
| Story/ticket IDs in status tables | The actual story/ticket files — an ID scheme with zero matching files is fiction, however structured the table looks |
| "Required files" / "deliberately removed" lists | Check existence directly — these lists across different docs frequently contradict each other |

### Phase 4 — Cross-Doc Contradiction Check

```bash
grep -rln "<claim-or-number>" --include="*.md" .
```

The same fact stated in two files is itself a finding, independent of which one (if either) is correct — per the no-duplication rule, one of them is wrong the moment the other changes, even if both are accurate today.

### Phase 5 — Dependency Scan Before Touching Anything

Before deleting, renaming, or merging any doc file, check what actually depends on its path:

```bash
grep -rl "<filename>" --include="*.ts" --include="*.mjs" --include="*.py" --include="*.sh" --include="*.json" --include="*.yml" . | grep -v node_modules | grep -v archive
```

Catches `require_file`-style shell gates, code comments citing the doc, CI workflows, and PR templates. Update these alongside the doc change — a doc merge that breaks a structure-check script is not a simplification.

### Phase 6 — Design the Target Structure

Apply concept ownership: every fact, table, or contract gets exactly one home file; every other file references it by name instead of restating it. Typical shape for a small-to-mid repo:

- One root `README.md` — front door, quick start, links out.
- One current-state doc (route inventory, data model, contracts, known gaps) — not split into N parts unless a real enforced size cap requires it (check for one before assuming — a "split for size compliance" note is often a one-time decision with no enforcement behind it anymore).
- One architecture/tech-stack doc.
- One doc per genuinely distinct operational concern (e.g. a bot, a setup/install flow) — merge sibling files that repeat the same env-var/command lists under different headings.
- Delete point-in-time audit/snapshot files that no longer describe current reality and aren't append-only evidence records (see Pitfalls — don't confuse the two).
- Don't combine docs that serve different audiences even if they'd otherwise fit the same concept (e.g. CLAUDE.md/AGENTS.md vs CONTRIBUTING.md vs ARCHITECTURE.md serve different readers) — "no duplication" targets restating the same fact twice, not collapsing every doc into one file.

### Phase 7 — Handle Ambiguous Backlog/Roadmap Content

If an audit turns up a backlog, roadmap, or status table that can't be verified against code (no matching story files, IDs from a scheme nobody recognizes), that's a business judgment call, not a code fact — don't silently delete it and don't silently keep asserting it. Ask the user: cut it, keep it explicitly labeled as unverified, or pause for them to review. Whatever they choose, if it's kept, flag it in the new doc as needing owner review rather than reproducing it as settled fact.

### Phase 8 — Execute + Reference Fixes

Rewrite/merge/delete per the target structure. Fix every downstream reference found in Phase 5 (scripts, code comments, cross-links between docs).

### Phase 9 — Verify

```bash
npm run check:structure   # or equivalent structure/lint gate
grep -rn "<deleted-or-renamed-filename>" --include="*.md" --include="*.ts" --include="*.sh" . | grep -v node_modules | grep -v archive
```

Confirm the gate still passes and no dangling references remain.

## Key Pitfalls (Check Every Audit)

| Pitfall | Why it bites |
|---|---|
| Trusting a doc's own "current design system" / "current stack" claim | Multiple docs can each claim to be current and contradict each other — only the file that matches the live CSS/config wins |
| A structured status table with plausible-looking IDs | Structure and specificity are not evidence. Cross-check IDs against real files before treating rows as fact |
| Editing dated QA/evidence log entries to match the new doc structure | Evidence logs (dated "on YYYY-MM-DD we did X") are historical record, not living docs — rewriting them falsifies the audit trail. Only fix live navigation references, never the timestamped entries themselves |
| Deleting/merging a doc without grepping for hardcoded path references | Breaks shell `require_file` gates, stale code comments, CI configs silently |
| Assuming a doc split (e.g. "part-01..part-06") is enforced | Check for an actual size-cap validator before assuming the split can't be undone — it's often just a one-time unenforced decision that's now causing the docs to drift out of sync with each other |
| "Fixing" a stale doc mechanically without checking relevance | Ask whether the described feature is still used/prominent before polishing a more-accurate detail onto it; sometimes the right fix is to trim, not correct |
| Applying a vault-specific formatting rule (e.g. "no tables") to an unrelated repo | Formatting standards from one system (e.g. a Word-paste vault) don't automatically transfer to a git-hosted code repo's README — GitHub renders tables fine; port the *discipline* (SSOT, no duplication), not every literal rule |

## Complementary Skills — Use Alongside, Don't Duplicate

This skill covers doc-vs-code truth and doc consolidation only. It deliberately does not hunt for code bugs, quality issues, or UI problems — pull in the dedicated tool for those instead of improvising a lighter version inline:

- **`/code-review`** — when the audit's code-verification steps (Phase 3) turn up an actual correctness bug in the code itself (not just a doc claiming something false about it), don't fix it ad hoc as a side effect of the doc audit. Run `/code-review` on it as its own pass.
- **`/simplify`** — if Phase 3/4 surfaces real duplication or dead code in the codebase (not just in the docs), that's a `/simplify` job, not a docs-reality-audit job — they share the no-duplication principle but operate on different material.
- **`diagnosing-bugs`** — if verifying a doc's claim requires figuring out *why* something is actually broken (not just confirming that it is), switch to that skill for the root-cause work, then come back to the doc fix once the real behavior is known.
- **`/ux-ui`** — docs-reality-audit doesn't evaluate interface/interaction quality. If the project has a UI and the audit is part of a broader "review this project" ask, pair with `/ux-ui` for the visual/UX pass — run them as separate, parallel-purpose passes, not one folded into the other.

## Report Format

- File-count before/after (e.g. "25 doc files → 12, N contradictions found").
- A findings table: file, claim, verified fact, fix applied.
- An explicit "needs owner review" section for anything ambiguous/business-judgment (see Phase 7) — never silently resolved.
- If a complementary skill (above) was invoked as part of this audit, name it and summarize what it found separately from the doc findings.

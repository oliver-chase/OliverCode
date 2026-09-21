---
name: docs-reality-audit
description: "Use when the user asks 'are these docs accurate', 'audit the docs', or 'do these docs contradict each other'. Also use for 'check the README against the code' or a doc-drift/stale-instructions report. Cross-checks every factual claim against live code, flags doc-vs-doc contradictions, consolidates to one file per concept."
---

# Docs Reality Audit

## Truth Hierarchy

```
Live code/config > package.json/tooling output > git log recency > a configured GitHub Project's live state > docs
```

Docs are never truth — they're a claim about truth. A doc that reads as authoritative (dated, "Status: Active", specific line numbers, structured tables) is not more likely to be accurate than a stale one. Check every load-bearing claim against the thing it describes before trusting it.

## When to Use

The user wants documentation simplified, "brought up to date," or reviewed for accuracy — not just tidied. Also use proactively when a doc's own internal evidence suggests drift. Example signals: a "last updated" date far behind recent commits, or a status note the file tree contradicts.

## Process

### Phase 1 — Inventory + Recency Signal

```bash
find <repo-root> -iname "*.md" -not -path "*/node_modules/*" -not -path "*/archive/*" | sort
git log -1 --format=%ad --date=short -- <doc>          # doc's last touch
git log --oneline -15                                   # what's actually been happening lately
```

Compare doc last-touch dates against recent commit activity in the areas they describe. A doc untouched while its subject area has 10+ recent commits is the highest-probability drift candidate — read it first.

Also check local-vs-tracked drift before reading content: `git status` + `git diff origin/main --name-only`. A doc file present locally but not in git (or vice versa) needs reconciling before you audit its content. Otherwise you could be auditing a file nobody else's clone even has.

### Phase 2 — Read Every Doc Fully

Read each doc completely — skimming misses contradictions. Extract its verifiable claims: routes/pages, file paths, env vars, and commands. Also capture table row counts (migrations, stories, API routes), design tokens/colors/fonts, "required files" lists, and status labels ("Active", "Functional", "Archived").

### Phase 3 — Check Every Claim Against Code

Never trust a doc's inventory of itself. Check the filesystem directly, per claim type. See `references/claim-checks-table.md` for the full table — routes, commands, env vars, migration counts, design tokens, cron/schedule, CI steps, ticket IDs, and required-files lists.

### Phase 4 — Cross-Doc Contradiction Check

```bash
grep -rln "<claim-or-number>" --include="*.md" .
```

The same fact stated in two files is itself a finding, independent of which one (if either) is accurate. Per the no-duplication rule, one of them turns wrong the moment the other changes, even if both are accurate today.

### Phase 5 — Check a Configured GitHub Project (When One Exists)

Skip this phase if the repo has no `backlog-config.json` (or its per-repo equivalent) — no
configured Project, nothing to check. When one exists:

```bash
gh project view <projectNumber> --owner <repoOwner> --format json   # shortDescription, item count
gh issue list --repo <repoOwner>/<repoName> --state open --limit 20 --json number,title
```

A configured Project is live state, not a doc — it drifts independently of any file in the
repo. Spot-check its `shortDescription` and a sample of open issues against whatever the repo's
own docs claim about current status, open work, or backlog size (a README's "N open items," a
status doc's "in progress" list). Flag drift the same way any other Phase 3 finding gets
flagged — report it, don't silently edit the Project or the doc to match the other.

### Phase 6 — Dependency Scan Before Touching Anything

Before deleting, renaming, or merging any doc file, check what actually depends on its path:

```bash
grep -rl "<filename>" --include="*.ts" --include="*.mjs" --include="*.py" --include="*.sh" --include="*.json" --include="*.yml" . | grep -v node_modules | grep -v archive
```

Catches `require_file`-style shell gates, code comments citing the doc, CI workflows, and PR templates. Update these alongside the doc change — a doc merge that breaks a structure-check script is not a simplification.

### Phase 7 — Design the Target Structure

Apply concept ownership: every fact, table, or contract gets exactly one home file. Every other file references it by name instead of restating it. Typical shape for a small-to-mid repo:

- One root `README.md` — front door, quick start, links out.
- One current-state doc (route inventory, data model, contracts, known gaps). Don't split it into N parts unless a real, enforced size cap requires it — check for one before assuming. A "split for size compliance" note is often a one-time decision with no enforcement left behind it.
- One architecture/tech-stack doc.
- One doc per genuinely distinct operational concern (e.g. a bot, a setup/install flow) — merge sibling files that repeat the same env-var/command lists under different headings.
- Delete point-in-time audit/snapshot files that no longer describe current reality and aren't append-only evidence records (see Pitfalls — don't confuse the two).
- Don't combine docs that serve different audiences even if they'd otherwise fit the same concept (e.g. CLAUDE.md/AGENTS.md vs CONTRIBUTING.md vs ARCHITECTURE.md serve different readers) — "no duplication" targets restating the same fact twice, not collapsing every doc into one file.

### Phase 8 — Handle Ambiguous Backlog/Roadmap Content

If an audit turns up a backlog, roadmap, or status table, check it against code first. One that fails — no matching story files, or IDs from an unrecognized scheme — is a business judgment call, not a code fact. Don't silently delete it, and don't silently keep asserting it. Ask the user: cut it, keep it explicitly labeled as unverified, or pause for them to review. Whatever they choose, if it's kept, flag it in the new doc as needing owner review rather than reproducing it as settled fact.

### Phase 9 — Execute + Reference Fixes

Rewrite/merge/delete per the target structure. Fix every downstream reference found in Phase 6 (scripts, code comments, cross-links between docs).

### Phase 10 — Check

```bash
npm run check:structure   # or equivalent structure/lint gate
grep -rn "<deleted-or-renamed-filename>" --include="*.md" --include="*.ts" --include="*.sh" . | grep -v node_modules | grep -v archive
```

Check that the gate still passes and no dangling references remain.

## Key Pitfalls (Check Every Audit)

See `references/pitfalls.md` for the full table. It covers design-system claims, plausible-looking status IDs, dated evidence-log entries, and ungrepped path references before a delete or merge. It also covers assumed-enforced doc splits, mechanical fixes on dead features, and vault-specific rules leaking into unrelated repos.

## Complementary Skills — Use Alongside, Don't Duplicate

See `references/complementary-skills.md` for the dedicated tool to reach for instead of improvising: `/code-review`, `/simplify`, `diagnosing-bugs`, or a frontend/UX skill.

## Report Format

- File-count before/after (e.g. "25 doc files → 12, N contradictions found").
- A findings table: file, claim, checked fact, fix applied.
- An explicit "needs owner review" section for anything ambiguous/business-judgment (see Phase 8) — never silently resolved.
- If this audit invoked a complementary skill (above), name it and summarize what it found separately from the doc findings.

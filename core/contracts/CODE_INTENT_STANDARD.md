# Code Intent Standard

Status: Active
Effective Date: 2026-07-27
Scope: All repositories, modules, and workstreams

Code records what it does. This standard is about recording **why**, in a form
that cannot quietly go stale.

The failure this prevents: a decision is made for a good reason, written into a
comment, and six months later a refactor undoes it because the reason is no
longer legible. The comment survives; the protection does not.

## 1. Comment the decision, not the mechanism

A comment restating the code is noise. A comment naming the defect the code
prevents is protection.

```ts
// BAD — restates the line below it
// strip the data URI
if (/^data:/i.test(src)) return alt;

// GOOD — names what breaks without it
// MARKDOWN-DATAURI-1: lazy-loaders park a 1x1 base64 PNG in `src`. Emitting
// it tripped the injection guard and quarantined ordinary pages.
if (/^data:/i.test(src)) return alt;
```

Write the comment so it answers the question a reader will actually have:
*"can I delete this?"*

## 2. Every non-obvious decision gets an ID

Format: `AREA-TOPIC-N` (`ROBOTS-4XX-1`, `CACHE-POLICY-1`). Assign one when the
code does something a competent reader would otherwise simplify away.

An ID is required when the decision is:
- a fix for a defect that reached production or a live run,
- a deliberate deviation from an obvious implementation,
- a security or correctness boundary,
- an asymmetry (fail-closed here, fail-open there).

Not required for ordinary code that reads as intended.

## 3. IDs live in one indexed ledger

A `DECISIONS.md` in the consuming repo's docs directory: one row per ID — what it protects, source file, test.
The **reasoning stays in the source comment**, beside the code it governs. The
ledger is an index, not a second copy.

## 4. The ledger is mechanically enforced

A gate in the repo's `check` target (or the repo equivalent) must fail when:
- an ID in the code has no ledger entry — a decision nobody can find is one the
  next reader will undo,
- a ledger entry names code that no longer exists — an entry describing deleted
  code is worse than none, because it is confidently wrong,
- a test references an ID that exists nowhere else — it reads as authoritative
  and is fiction.

Report, but do **not** fail, decisions with no test. Some are structural — a
build flag, a packaging choice — and have nothing a unit test can hold. Making
it fatal produces hollow tests, which is worse than the gap.

A reference implementation is a short script in the consuming repo's own `scripts/`:
grep the source tree for `[A-Z]+-[A-Z0-9]+-\d+` IDs, parse the ledger's rows, and
diff the two sets in both directions. Under a hundred lines; write it once per repo.

## 5. Volatile numbers never live in prose

Test counts, file counts, coverage percentages, benchmark timings and dated
measurements must not be hand-maintained in a README or a doc.

They rot immediately. Observed for real: a README's test count was corrected four
separate times in a single build session and was wrong again by the next commit.

- **State the command**, not the number: point at the check target rather than
  quoting its output.
- **Dated measurements** ("55/60 sources read") go in the backlog's tracker
  *with their date*, once. Never restated in a source comment or a second doc.
- Say so in the file, so a well-meaning reader does not add them back.

A fact stated in two places is wrong the moment one changes.

## 6. Tests assert the intent, not the implementation

Name the test after the decision, and make it fail for that reason:

```ts
// GOOD — fails if the protection is removed
test('a credentialed target never reaches the public proxy', ...)

// WEAK — passes for reasons unrelated to the decision
test('fetchViaJina returns null', ...)
```

**Ablate before trusting.** Remove the guard, confirm the test goes red,
restore. A test that stays green without the code it claims to protect is
worse than no test, because it reports confidence it has not earned. This
found four hollow tests in a single session, each written by the person who
believed they were testing the behaviour.

## 7. Prefer boundary tests over volume

A suite that grows without finding defects is measuring the wrong thing. Where
a system meets reality — real networks, real files, real inputs — a small
number of live checks earns more per line than a large unit suite.

Record that honestly when it happens. Observed for real: every defect found in a
full day of work on a crawler came from running it against real websites; its
~590 unit tests found none of them.

## Enforcement reality

Points 4 and 5 are mechanically enforceable and should be gated. Points 1, 2, 3,
6 and 7 are instruction text — see this repo's CONTRIBUTING "Enforcement Reality"
section before assuming a written rule is unbreakable.

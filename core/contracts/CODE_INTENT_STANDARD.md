# Code Intent Standard

Status: Active
Effective Date: 2026-07-27
Scope: All repositories, modules, and workstreams

Code records what it does. This standard is about recording **why**, in a form
that cannot quietly go stale.

The failure this prevents: a decision is made for a good reason, written into a
comment, and six months later a refactor undoes it because the reason is no
longer legible. The comment survives. The protection does not.

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

**Keep it short.** A comment states the decision and the failure it prevents,
in roughly three to six lines. Anything longer is a narrative, and narratives
belong in the DECISIONS ledger with an ID the comment points at.

**The sentence form is non-negotiable: state the thing, attach its cause.**
*This is what this is, because of this.* Nothing before the statement, nothing
after the cause.

```ts
// BAD — builds up to it, then restates it
// We need to be careful about how the cap is sized here. Cloudflare has a
// per-invocation subrequest ceiling, and each promote costs several. So the
// cap is deliberately conservative. In short, it is sized for subrequests.
const MAX_PROMOTES = 1;

// GOOD — statement, cause, stop
// Sized for Cloudflare's per-invocation subrequest ceiling, not wall-clock: one
// promote pays several subrequests, and exceeding the ceiling kills the run.
const MAX_PROMOTES = 1;
```

Three things that are always cuts, never edits: an opening that announces what
the comment is about, a closing that summarises what it just said, and a second
copy of something a doc or the code below already owns.

**Think before you write it (`docs/WRITING_PROCESS.md`).** The gate below is QA.
Writing to a cap produces a block that passes at 19 lines and still says in three
sentences what one carries. Voice and Readability in
`docs/DOCUMENTATION_STANDARD.md` govern comment prose as well as docs.

**Density is a guideline, not a gate: aim under 25% of non-blank source lines.**
The gate reports it and never fails on it, because density cannot distinguish a
file of two-line decision records — correct, and high — from one restating
itself. It catches what block length cannot see: many MEDIUM comments, each
closing with its own summary. Measured across this fleet, human-written working
code sits near 12%, and every repo where an agent had been over-explaining sat at
25% or above.

The test: a reader scrolling to find the code should not have to scroll past
the explanation of it. A 39-line file header is not documentation, it is an
essay in the wrong file — and it rots faster than short comments because
nobody re-reads it when the code changes underneath.

**This is checked, not gated.** `core/templates/project/scripts/check-comment-budget.mjs`
fails on any contiguous comment block over 20 lines — more than triple the
ceiling above, so it catches essays and leaves judgment calls alone. It runs
from each repo's validation target and from **no pre-commit hook in any repo**,
so a commit that skips validation skips this. Treat it as the check that finds
the problem, not the thing that stops it landing. Per-repo overrides and
exemptions (each needing a stated `why`) go in a root `.comment-budget.json`.

Density is reported by the same script and never fails. A repo can legitimately
run high density in short comments sitting beside the code they govern. Block
length is the property that has no defence.

## 2. A non-obvious decision may carry an ID

Format: `AREA-TOPIC-N` (`ROBOTS-4XX-1`, `CACHE-POLICY-1`). Use one when the
code does something a competent reader would otherwise simplify away. An ID is optional.
The decision-records gate checks only that an ID already in the code is indexed.

An ID is worth adding when the decision is:
- a fix for a defect that reached production or a live run,
- a deliberate deviation from an obvious implementation,
- a security or correctness boundary,
- an asymmetry (fail-closed here, fail-open there).

Skip it for ordinary code that reads as intended.

Exception: a file inside a skill folder that ships in a zip carries no ID and points to no
ledger. Its comment says what the code does and keeps the reason in plain words. The commit
or the issue holds the longer reasoning.

**Exception: code that ships in a zip.** A skill folder uploaded to another organization holds no decision ID, no ledger and no history. A comment in it says what the code does. The reason lives in the rule's own doc, the commit message or the closed issue. Sections 2 to 4 do not apply to those files.

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
diff the two sets in both directions. Under a hundred lines. Write it once per repo.
`check_decision_ledger` in OliverCode's `scripts/lib/consistency_check.py` is one to
copy from. Skip IDs that sit inside a quoted string — a fixture carrying one as
payload data reads as a reference and is not one.

## 4b. Comments are written for longevity

A comment that states current-state specifics — a count, a date, a list of which files
do something — is wrong the moment the state changes, and nothing reminds anyone to
update it. Two rules keep comments from drifting:

- **Past tense is stable. Present tense drifts.** "A loose filter exempted template
  hooks from the scan" records an event and stays true forever. "The three hooks are
  identical" is a claim about now, goes stale silently, and belongs in a check, not a
  comment.
- **The why stays. The perishable specifics go.** Keep the defect the code prevents.
  Drop the session date, the file count at the time, the tally of occurrences — if a
  number matters, it belongs in a test or a gate that fails when it changes, or in the
  backlog's dated tracker where the date is part of the record.

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
full day of work on a crawler came from running it against real websites. Its
~590 unit tests found none of them.

## Enforcement reality

Point 1's length rule and points 4 and 5 are mechanically enforceable and should
be gated. Point 1 ships a gate. Points 2, 3, 6 and 7 are instruction text — see
this repo's CONTRIBUTING "Enforcement Reality" section before assuming a written
rule is unbreakable.

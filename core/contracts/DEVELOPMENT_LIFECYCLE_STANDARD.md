# Development Lifecycle Standard

Status: Active
Effective Date: 2026-07-27
Scope: All repositories, modules, and workstreams

How work moves from an idea to shipped code, in every repo, without being asked.
The other contracts govern artifacts — this one governs the sequence.

Applies to any non-trivial change. A typo fix does not need a spec.

---

## 1. Gap analysis before specs

Do not spec from a description of the problem. Measure first.

Count what exists, run what runs, read the live code. A gap analysis that
cites no command is a guess. The output is a list of differences between what
is claimed and what is true — each with the evidence that proves it.

**Measure, do not assume.** "Fallow is huge" became actionable only once
counted: 141,801 lines, of which 13,000 were build artifacts and 11,140 were a
single backlog file.

---

## 2. Spec before build

Every gap becomes a written spec before any code is written. A spec states:

- the **failure** it prevents, concretely,
- what is **in scope** and explicitly what is not,
- the **watch-out** — the way a plausible implementation gets it wrong.

Specs live in the repo's `docs/BACKLOG.md`. Nothing is built that is not
specced. Nothing is specced that cannot name its failure.

---

## 3. Prioritise by cost of being wrong

Rank by what breaking it costs, not by effort:

1. **Silent data loss** — wrong output that looks right. Highest, always.
2. **Security boundary** — a guard that can be bypassed.
3. **Visible failure** — loud, attributable, recoverable.
4. **Cost and performance.**
5. **Ergonomics.**

A defect that surfaces as *worse results blamed on something else* outranks one
that throws. An exception gets fixed. Silently thinner data gets shipped.

---

## 4. Build, verify, commit — one loop per spec

Per spec, in order:

1. Write the failing test **first**, at a seam that reaches the real bug.
2. Implement.
3. **Ablate** — remove the guard, confirm the test goes red, restore.
4. Run the repo's own `check`/`validate` and read the exit code, not a grepped
   line. A filtered log hides failing suites.
5. Commit with the WHY. Push.

One spec per commit. A commit spanning two specs cannot be reverted cleanly.

---

## 5. QA is a separate pass, by a separate reader

The author cannot QA their own work. They will confirm what they intended.
Where an agent is available, QA runs as its own adversarial pass with an
explicit brief to find what is wrong.

QA verifies by **running**, never by reading. Its findings are fixed before the
work is called done, and a finding in the author's own recent edits is the most
valuable kind.

**For a rendered or executable artifact — an HTML page, an SVG, a UI, a chart, a
game, a script with observable output — running it means observing the actual
render, not parsing the file.** A static check (a linter, `node --check`, an XML
parser) confirms the file is well-formed. It does not confirm the artifact looks
or behaves correctly, and those are different claims. Before calling this kind of
work done: render it in its real environment (a headless browser and a
screenshot for web artifacts, an SVG-to-PNG render, executing a script and
capturing its output), then actually look at what came back — read the
screenshot, read the console, check the layout is intact and nothing is
obscured. A produced-but-unlooked-at screenshot is not observation. Stop once
you've looked and it's clean. Re-render only after a change, not to accumulate
confidence on an artifact that already looked right the first time.

---

## 6. Prefer boundary verification over volume

A suite that grows without finding defects measures the wrong thing. Verify where the
system meets reality (real networks, real files, real inputs), and say so honestly when
volume was not what found the bug.

---

## 7. Simplify as part of finishing, not later

A change is not done until you have asked what it made redundant. Merge
duplicated helpers, delete dead code, collapse a constructor that four call
sites hand-rolled. Removal is a deliverable.

Never remove functionality to reduce size. Reduce the number of places a
behaviour is expressed instead.

---

## 8. Consistency across repos is the point

The same question gets the same answer in every repo: same backlog policy, same
comment discipline, same doc shape, same commit format, same verification
command name. A reader moving between repos should never have to relearn.

Where a repo deviates, the deviation is documented with its reason or removed.

---

## Token efficiency

This standard is itself subject to it. Prefer:

- **Deterministic scripts over model calls.** A gate that greps is cheaper,
  faster and more accurate than asking a model to check the same thing.
- **Pointers over restatement.** A contract that repeats another contract is
  two things to keep in sync. Name the owner instead.
- **Measure once, cite everywhere.** A number belongs in one place with its
  date. Every other mention links to it.
- **Read what you need.** Targeted greps and line ranges over whole-file reads.

## Related contracts

| Contract | Owns |
|---|---|
| `PROJECT_HYGIENE_STANDARD.md` | Story and epic hygiene, commit format |
| `PROJECT_STRUCTURE_STANDARD.md` | Folder layout |
| `EXECUTION_CONTRACT.md` | Gate mechanics, evidence schema, the pre-commit hook contract this loop ends in |
| `../../docs/DOCUMENTATION_STANDARD.md` | README and doc shape, backlog policy |

## Enforcement reality

Steps 4 and 5 are partly gated by each repo's `check`/`validate` and its
pre-commit hooks. The sequencing itself is instruction text — see
CONTRIBUTING's "Enforcement Reality" before assuming a written rule is
unbreakable.

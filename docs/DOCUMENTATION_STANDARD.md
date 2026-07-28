# Documentation Standard

The locked structure, voice, and naming for every README and document in this framework and
in every repo it governs. When anyone — the original operator or a stranger on a fork — asks
for a README or documentation on any part of a codebase, the result follows this file. It is
a contract, not a suggestion: the same request produces the same shape of document in every
repo, every time.

`bash scripts/validate.sh` enforces the mechanical parts (reference integrity, doc/code
consistency, the feature-map index). The writing rules below are what an agent applies; the
`writing-documentation` skill loads this file and is the way to invoke them.

---

## The shape of a README

A README is problem-driven storytelling in a fixed order. It opens with what the thing is in
one plain sentence, then tells the reader why it exists through the concrete problems that
drove its design — not a feature list, the problems. Everything after that earns its place by
answering a question a reader actually has, in the order they would ask.

The locked outline:

1. **`# repo-name`**, then one plain sentence stating what this is. A sentence, not a
   blockquote, not a tagline.
2. **The driving problems.** One to three short paragraphs, each a real problem with a
   concrete consequence, each answered by a design choice. "Point one at `169.254.169.254`
   and it will retrieve your cloud credentials" is the register — a specific danger, then
   what the design does about it.
3. **Install / first use.** Runnable immediately, with real-looking values. State what the
   zero-config path costs and does. No prose between the reader and a working example.
4. **How it works**, named in the reader's terms ("How it reads a page", not "Processing
   pipeline"). Where behaviour escalates or branches, a numbered list where each step names
   the failure the previous step cannot solve. Attach the reason to the mechanism in the
   same breath: "The order is deliberate. A 403 is usually a bot wall…"
5. **What comes back / what you get.** The actual fields, objects, or artifacts, annotated.
   Show failure shapes here too — what the reader holds when it does not work, and which
   field to act on.
6. **Design decisions.** A handful of subsections, each headed by the decision stated as a
   claim ("URLs are screened before they are requested"), each defending it with the attack,
   cost, or failure it prevents. This is where the narrative lives; it is the section a
   maintainer rereads a year later.
7. **Task-oriented sections** as the surface area demands — one per major capability, each
   self-contained.
8. **Documentation.** A two-column table linking EVERY document in the repo with a one-line
   purpose each. Complete, not curated: a doc missing from this table is unreachable, and
   nothing may be unreachable.
9. **Status.** Hard facts, no adjectives: runtime requirements, what is verified and
   how — stated as the command that proves it (`npm run validate`, `bash
   scripts/validate.sh`), not as a hand-maintained number. Volatile counts (tests,
   files, coverage) rot immediately and are governed by
   `core/contracts/CODE_INTENT_STANDARD.md` §5: name the command, and quote a number
   only as a dated measurement where the date is part of the sentence.
10. **License.** One line, and only where the repo actually ships a license and
    licensing matters to a reader (a public or forkable repo). A private product
    repo with no licensing story omits the section — an empty ritual section is
    exactly the padding this outline exists to prevent.

Sections are separated by `---` rules. Length follows surface area — a small tool gets a
short README in the same order, never a padded one.

## Voice

- **Problem first, mechanism second.** Every capability is introduced by the failure or cost
  that makes it necessary. A reader who skips the mechanism still learns why it exists.
- **Attach the reason.** No rule or behaviour is stated without its why, in the same
  paragraph. "Off unless a request explicitly asks for it" is incomplete until the sentence
  that explains what silent spending would look like.
- **Concrete over abstract.** Real addresses, real prices, real field names, worked
  micro-examples. If a claim can be demonstrated in four lines ("Which number is the seat
  count?"), demonstrate it rather than asserting it.
- **Failure modes are content, not caveats.** What comes back when it fails, which field to
  branch on, what retrying will and will not change — in the main flow, not a footnote.
- **Present tense, active, declarative.** "Every hostname is resolved and checked." Short
  sentences carry the claims; longer ones carry the reasoning. Vary the rhythm.
- **Numbers are evidence.** "48 tests cover this behaviour alone" is a sentence; "well
  tested" is not. Never a superlative, never hype, never an exclamation.
- **Second person for the reader's actions, third for the system's.** "Feed a model
  `markdown`, not `text`" — then why.
- **No history in current-state docs.** Never "previously", "no longer", "has been removed".
  What was removed does not appear; `git log` is the changelog. The one exception is a
  design-decision defence where the old failure IS the reason — one clause, never a dated
  note.

## Formatting

- `---` between major sections.
- **Bold lead-ins** open list items and short paragraphs that enumerate ("**Request the
  page.** Works for most of the web.").
- Tables only where the content is genuinely a matrix — options, coverage grids, the
  documentation index. Narrative everywhere else; a table of prose is a smell.
- Code blocks use real-looking values and carry inline annotations naming what each line
  demonstrates. A reader should be able to paste the first example and watch it work.
- Mermaid diagrams where flow or ownership matters, with the reader's own code drawn as a
  participant — the diagram shows where their responsibility ends and the tool's begins.
- Headers state a subject in the reader's vocabulary. No gerund headers ("Getting
  Started" becomes "How to Get Started" or "Install"), no trailing punctuation.

## File naming and the document set

Documents live in `docs/` and are named `CAPS-KEBAB.md`: `ARCHITECTURE.md`, `REFERENCE.md`,
`ADOPTING.md`, `BACKLOG.md`, `TROUBLESHOOTING.md`. Root level carries only `README.md`,
`CLAUDE.md`, `CONTRIBUTING.md`, `LICENSE`, and — where the repo declares one — the quality
baseline. Multi-word names hyphenate: `SKILLS-PLACEMENT.md`, `EXTERNAL-TOOLING.md`.

Every document opens the same way: `# Title`, then one orientation sentence saying what the
file covers and — where relevant — who should read something else instead ("Full
option-by-option detail. Start with the README if you just want to use the thing.").

The standing set, present in any repo with enough surface to need it:

| File | Carries |
|---|---|
| `README.md` | The narrative above — the one document written for a stranger |
| `docs/ARCHITECTURE.md` | How a request or change actually flows, module map, design boundaries |
| A reference doc (`REFERENCE.md`, or split by surface) | Every option and field, exhaustively — the README links here instead of bloating. This repo splits its own across `FEATURE_MAP.md` and `OLIVERCODE_LAUNCHER.md` |
| `docs/ADOPTING.md` | Onboarding path for a new user or a fork, stepwise, each step verifiable |
| `docs/BACKLOG.md` | Open work only — see below |
| `docs/TROUBLESHOOTING.md` | Failures a user will actually hit, symptom-first |

One concept, one home. A rule stated in two documents is a future contradiction; secondary
mentions point to the owning doc by name. `docs/FEATURE_MAP.md` (where present) is the
machine-checked index mapping every capability to its one owning doc.

## The backlog policy

`docs/BACKLOG.md` holds open work only, and opens by saying so. History lives in git: an
entry leaves the file when its work ships. No archive sections accumulating. A reader of the
backlog learns what does not work yet — which is why the README's documentation table
describes it as "read before assuming a capability exists".

## Always current — the sync rule

Documentation that lags the code is worse than no documentation, because it is believed.

- A change to behaviour, options, structure, or file layout updates every document that
  states the old truth **in the same commit**. Not a follow-up, not a sweep later.
- The README's documentation table, the feature map, and the backlog are part of "every
  document".
- `bash scripts/validate.sh` fails closed on the drift it can detect: dangling references,
  doc/code contradictions, index omissions. What it cannot detect is still the rule; the
  gate is the floor, not the standard.
- A capability change is incomplete until `docs/FEATURE_MAP.md` (where present) is updated
  in the same change set.

## The GitHub About section

Every repo carries a filled-in About: a description and topics. The description is one dense
sentence-group in the README's own register — what it is, the differentiator, and the cost
or trust posture if one exists. Topics are the real technologies and problem domains. An
empty About is treated as missing documentation; `olivercode health` checks for it where the
`gh` CLI is available and warns where it cannot check.

```bash
gh repo edit --description "..." --add-topic <topic>
```

## Scope

This standard governs OliverCode itself, every repo the framework stamps or governs, and any
fork. It ships inside the framework precisely so a fork inherits it whole: ask an agent for
a README anywhere downstream and this is the shape it produces. The `writing-documentation`
skill is the invocation path; `core/templates/project/` carries the same expectations into
newly bootstrapped repos.

Agent-facing files (`CLAUDE.md`, skill files) follow their own contracts — they are loaded
context, not documentation, and compress accordingly. Client-facing brand content follows
the operator's own voice standards, which live outside this framework.

# Documentation Standard

The locked structure, voice, and naming for every README and document in this framework and
in every repo it governs. When anyone — the original operator or a stranger on a fork — asks
for a README or documentation on any part of a codebase, the result follows this file. It is
a contract, not a suggestion: the same request produces the same shape of document in every
repo, every time.

`bash scripts/validate.sh` enforces the mechanical parts (reference integrity, doc/code
consistency, the feature-map index). The writing rules below are what an agent applies. The
`writing-documentation` skill loads this file and is the way to invoke them.

---

## The shape of a README

A README is problem-driven storytelling in a fixed order, written for a reader on their
first day: someone who knows the business context but none of the internals. Every sentence
must pass the read-aloud test — a smart stranger reading it once, out loud, understands it
with no follow-up question.

**Write for the adopter, not for the builder.** The reader is deciding whether this belongs
in their stack, and they are reading it cold. A maintainer already knows why each rule
exists, so a maintainer can compress a decision into the rule it produced. A reader holding
only the rule has to reconstruct the reasoning that justified it, and most will not.

So each claim arrives in three moves, in this order: the situation the reader will recognise,
the decision taken about it, then the mechanism that implements the decision. "A 403 is
usually a bot wall rather than a refusal, so a real browser is tried before a paid API" is
the shape. The compressed form of that same fact — "escalate cheapest-first" — is an
internal principle, correct and unreadable, and it belongs in `ARCHITECTURE.md` if anywhere.

Compression is still the goal at the sentence level. What this rule forbids is dropping the
reasoning, not spending words on it: a sentence that adds no fact is still cut, and a
paragraph that restates the one above it is still deleted.

That audience sets how terms are introduced, never which terms are used. The precise
term stays — `symlink`, `gitignored`, `pre-commit hook`, `fork` are the correct words and
replacing them with a vague paraphrase ("protected project", "saves") loses the precision
an expert reader relies on. Instead, the plain explanation attaches at first use: "a
symlink — a pointer file, so every project reads one shared original", "gitignored, so git
never uploads it". After the first use, the bare term is free to carry the rest of the
document.

Two failure modes, both banned: insider shorthand with no gloss ("a bug in the fork, not
your machine" is a riddle to a reader who does not know what a fork is), and generic
paraphrase that deletes the term ("checks that run when work is saved" in place of
pre-commit hooks). The first loses the new reader. The second loses everyone else.

**Which terms need a gloss is decided by one test: could the reader look it up and get the
right answer?** `ETag`, `robots.txt`, `JSON-LD` and `304` are the shared vocabulary of the
domain and stand bare — glossing them insults the reader and costs a line each. A term
carrying meaning specific to this codebase (`rung`, `lane`, `hasContentData`) or a literal
whose significance is not in its name (`169.254.169.254` is an IP address until you are told
it dispenses cloud credentials) is glossed at first use and bare thereafter.

It opens with what the thing is in one plain sentence, then tells the reader why it exists
through the concrete problems that drove its design — not a feature list, the problems.
Everything after that earns its place by answering a question a reader actually has, in the
order they would ask.

The locked outline:

1. **`# repo-name`**, then one plain sentence stating what this is and what a reader can do
   with it. A sentence, not a blockquote, not a tagline, and not a list of verbs standing in
   for one.
2. **The driving problems.** One to three short paragraphs, each a real problem with a
   concrete consequence, each answered by a design choice. "Point one at `169.254.169.254`
   and it will retrieve your cloud credentials" is the register — a specific danger, then
   what the design does about it. Name each problem in its own first words ("The first is
   security"). A reader counting two problems and finding one unlabelled has to work out
   which they just read. Order them by what the reader came for, not by what the author
   finds most interesting — a threat model opening a document written for someone who has
   not yet decided to use the thing answers a question they have not asked.
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
   claim, each defending it with the attack, cost, or failure it prevents. This is where the
   narrative lives. It is the section a maintainer rereads a year later. A heading is a
   claim a stranger can evaluate ("Every hostname is resolved before it is requested"), not
   a principle only the author can decode — "Repeat crawls converge on free" names a real
   property and tells a first-time reader nothing about what the library does.
7. **Task-oriented sections** as the surface area demands — one per major capability, each
   self-contained.
8. **Documentation.** A two-column table linking EVERY document in the repo with a one-line
   purpose each. Complete, not curated: a doc missing from this table is unreachable, and
   nothing may be unreachable.
9. **Status.** Hard facts, no adjectives: runtime requirements, what is verified and
   how — stated as the command that proves it (`npm run validate`, `bash
   scripts/validate.sh`), not as a hand-maintained number. Volatile counts (tests,
   files, coverage) go stale immediately: name the command, and quote a number
   only as a dated measurement where the date is part of the sentence.
10. **License.** One line, and only where the repo actually ships a license and
    licensing matters to a reader (a public or forkable repo). A private product
    repo with no licensing story omits the section entirely.

Sections are separated by `---` rules. Length follows surface area — a small tool gets a
short README in the same order, never a padded one.

## Index READMEs

Some READMEs catalog a set of things instead of introducing one thing: a skill suite, a
monorepo of packages, a folder of tools. The product outline above does not fit them. An
index README answers six questions in this order, each under its own heading:

1. **What is this, and who is it for.** Two sentences, then one short paragraph on how it is
   built.
2. **How do I get it.** Clone, install and the first command, in a code block.
3. **How is it organized.** A directory tree in a code block, then one short subsection per
   top-level folder: what belongs there, what does not, and where the detail lives.
4. **How do the parts relate.** Shipping and dependency rules, as tables where the content is
   a matrix (audience by destination, folder by dependency).
5. **What is in each part.** One subsection per group: two or three sentences on what the
   group is for and what it depends on, then a two-column table with one row per item, the
   item's name and what it does.
6. **How to keep it current.** One short section.

Rules that apply to index READMEs on top of Voice and Readability:

- **One idea per paragraph, three sentences at most.** A paragraph that names folders, rules
  and commands together is three paragraphs. Split it by subject under headings. A single
  block over about 600 characters is a word wall however accurate it is.
- **Gloss every internal term at first use.** `org-context`, `runtime dependency`, `swap set`
  and `bundle` mean nothing to a reader on day one. Say what each one is in a clause the
  first time it appears. Leave established terms bare, per the gloss test above.
- **Structure carries the reading order.** Headings name subjects, trees show layout, tables
  hold matrices, code blocks hold commands. A matrix written as a sentence ("`org` uploads,
  `shared` goes to the colleague repo, `personal` stays") is a table.
- **A table row describes the item in its own terms.** It is the opening of the item's own
  description, not its trigger list, and a reader of the row alone knows what the item does.
- **Every named path, command, count and row is checked against the repo before delivery.**
  List what was checked in the reply. A row that drifts from its item's own file is the
  failure this section exists to prevent. State a count only as the command that reports it.
- **Describe the current structure only.** Never say how files used to be arranged.

## Voice

Voice for all writing belongs to the `shared-company` skill's voice files (`voice-core.md`
first). `WRITING_PROCESS.md` adds the repository-documentation thinking. Problem-first,
attach-the-reason, concrete-over-abstract, failure-modes-as-content, and numbers-as-evidence
are all stated once already, with the reasoning, under "The shape of a README" above — this
section holds only what's specific to a README or repo doc and said nowhere else:

- **Second person for the reader's actions, third for the system's.**
- **No history in current-state docs.** Never "previously", "no longer", "has been removed".
  `git log` is the changelog. A design-decision defence may carry one clause of history where
  the old failure is the reason. Same rule the Index-README rules state for "current
  structure only" — one rule, two contexts, not two rules.

## Readability

- **One idea per paragraph.** A paragraph that needs a fourth sentence is usually two.
- **Break up prose.** Put a code block, list or table within every few paragraphs.
- **The squint test.** A reader scanning only headers, bold lead-ins and code blocks must still
  get the whole story. Pull a load-bearing fact out of mid-paragraph.
- **Lists carry parallel items. Paragraphs carry reasoning.** A chain of because-therefore steps
  loses the connecting words when bulleted.

## Sentence clarity

`SKILL.md`, `CLAUDE.md`, skill and tool descriptions, error strings and CLI help text are read by
an agent that has no human to resolve ambiguity, so they get the `asd-ste100` skill in strict
mode. A commit-time gate warns on every staged `SKILL.md`, `CLAUDE.md` and `references/*.md`
(`docs/GOVERNANCE.md`'s coverage table).

READMEs, other docs and code comments are not run through strict mode and are never held to its
sentence-length cap. Never let an automated rewrite flatten a hedge ("may have failed") or split a
sentence that compresses several observations into one claim.

## Formatting

- `---` between major sections.
- **Bold lead-ins** open list items and short paragraphs that enumerate ("**Request the
  page.** Works for most of the web.").
- Tables only where the content is genuinely a matrix — options, coverage grids, the
  documentation index. Narrative everywhere else. A table of prose is a smell.
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
| `docs/BACKLOG.md` | Only for a repo with no `backlog-config.json` — see below |
| `docs/TROUBLESHOOTING.md` | Failures a user will actually hit, symptom-first |

One concept, one home. A rule stated in two documents is a future contradiction. Secondary
mentions point to the owning doc by name. `docs/FEATURE_MAP.md` (where present) is the
machine-checked index mapping every capability to its one owning doc.

## The backlog policy

A repo whose `CLAUDE.md` names a `backlog-config.json` has no `docs/BACKLOG.md` to maintain
— its backlog lives in the GitHub Project that `backlog-management` and `board-hygiene`
read and write. This section governs the other case: a repo (OliverCode included) whose
backlog is a tracked file.

`docs/BACKLOG.md` opens by saying what it holds. Finished busywork is deleted, not ticked —
an entry whose work shipped leaves the file, because git already holds that history. A
bounded "Design decisions" section and a "Resolved" section are allowed to stay: each
entry there earns its place by recording a failure class a gate now exists to stop, not by
being a log of what happened. A reader of the backlog should still come away knowing what
does not work yet — which is why the README's documentation table describes it as "read
before assuming a capability exists".

## Always current — the sync rule

Stale documentation misleads readers precisely because they trust it, so currency is a
hard requirement, not a preference.

- A change to behaviour, options, structure, or file layout updates every document that
  states the old truth **in the same commit**. Not a follow-up, not a sweep later.
- The README's documentation table, the feature map, and the backlog are part of "every
  document".
- `bash scripts/validate.sh` fails closed on the drift it can detect: dangling references,
  doc/code contradictions, index omissions. What it cannot detect is still the rule. The
  gate is the floor, not the standard.
- A capability change is incomplete until `docs/FEATURE_MAP.md` (where present) is updated
  in the same change set.

## The GitHub About section

Every repo carries a filled-in About: a description and topics. The description is one dense
sentence-group in the README's own register — what it is, the differentiator, and the cost
or trust posture if one exists. Topics are the real technologies and problem domains. An
empty About is treated as missing documentation. `olivercode health` checks for it where the
`gh` CLI is available and warns where it cannot check.

```bash
gh repo edit --description "..." --add-topic <topic>
```

## Scope

This standard governs OliverCode itself, every repo the framework stamps or governs, and any
fork. It ships inside the framework precisely so a fork inherits it whole: ask an agent for
a README anywhere downstream and this is the shape it produces. The `writing-documentation`
skill is the invocation path. `core/templates/project/` carries the same expectations into
newly bootstrapped repos.

**Voice and Readability also govern code comment prose.** A comment is short documentation, and the problem-first and
attach-the-reason rules apply to it unchanged.

Agent-facing files (`CLAUDE.md`, skill files) follow their own contracts. They are loaded
context, not documentation, and compress accordingly. Company and client writing follows the
`shared-company` voice files, not this document.

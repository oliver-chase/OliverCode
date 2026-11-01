# Documentation standard

Every README and document in OliverCode, in each repo it governs and in any fork follows this layout. Its words follow `docs/VOICE.md`. `bash scripts/validate.sh` checks internal references, doc-to-code consistency and the feature map, and fails the run on any drift it finds.

## The README

A README serves a reader on their first day, who knows the business and none of the internals. Its sections come in this order:

1. The title is the repo name, followed by one sentence on what the repo does and what a reader can do with it
2. The driving problems take one to three short paragraphs, each naming a real problem, what it costs and the design choice that answers it
3. Install and first use give commands a reader can run at once, with realistic values
4. How it works explains the system in the reader's terms
5. What comes back shows the real fields, files or results, including what the reader receives when something fails
6. Design decisions state each decision as a claim and defend it with the failure it prevents
7. Task sections follow wherever the repo's surface needs them
8. Documentation is a two-column table that links every document in the repo with a one-line purpose, because a document missing from it is unreachable
9. Status gives the runtime requirements and the command that proves what works
10. License appears when the repo ships one and a reader needs to know it

A small tool gets a short README in the same order.

## Index READMEs

Some READMEs catalog a set of things, such as a skill suite, a monorepo or a folder of tools. They answer six questions in order, each under its own heading:

1. What is this, and who is it for?
2. How do I get it?
3. How is it organized? A directory tree answers this
4. How do the parts relate? A table answers this wherever the content forms a matrix
5. What is in each part? One table row per item describes it in its own terms
6. How do I keep it current?

Check every path, command and row against the repo before the README ships.

## Files and where they live

Documents live in `docs/` and use CAPS-KEBAB names, such as `FEATURE-MAP.md`. The root holds only these documents: `README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`, `LICENSE` and a declared quality baseline.

A repo with enough surface keeps this set:

| File | What it holds |
|---|---|
| `README.md` | The document a new reader starts from |
| `ARCHITECTURE.md` | How a change flows through the system, the module map and its boundaries |
| A reference doc, one file or split by surface | Every option and field. OliverCode splits its reference across `docs/FEATURE-MAP.md` and `docs/OLIVERCODE-LAUNCHER.md` |
| `docs/ADOPTING.md` | The steps a new user or a fork follows, each one verifiable |
| `docs/DECISIONS.md` | Each design decision whose reasoning is longer than a code comment, cited by ID |
| `docs/BACKLOG.md` | The live tracker, or the open items for a repo without a GitHub Project |
| `docs/TROUBLESHOOTING.md` | The failures a user will hit, listed by symptom |

Each concept has one home, and every other mention points to it by name. `docs/FEATURE-MAP.md` maps each capability to the document that owns it, and `scripts/validate.sh` checks that it is complete.

## Numbers in prose

A count that changes, such as tests, gates or coverage, never appears in a document. Give the command that produces it. A dated measurement goes in the backlog's live tracker once, with its date.

## The backlog

A repo whose `CLAUDE.md` names a `backlog-config.json` keeps its open work in that GitHub Project, which `backlog-management` and `board-hygiene` maintain. OliverCode works this way. Its `docs/BACKLOG.md` holds only the live tracker that the `audit` skill maintains, with the review marker `scripts/audit-staleness.py` reads. Every design decision, including each failure class a gate exists to stop, lives in `docs/DECISIONS.md`.

A repo without a `backlog-config.json` keeps its open items in `docs/BACKLOG.md`. Finished work leaves the file, because git keeps that history.

## Keeping documents current

A change to behavior, options, structure or file layout updates every document that states the old fact, in the same commit. The README's documentation table, the feature map and the backlog all count as documents. `scripts/validate.sh` catches the drift it can detect, and the rule still applies to the drift it cannot.

## CLAUDE.md

`CLAUDE.md` loads into every session, so every word in it is paid on every turn of every session. It holds only the rules a session must follow from any folder, each as a short paragraph or bullet that says what to do and when. The detail behind a rule lives in the document it names, which loads only when that rule fires. A new rule earns its place when a session would act wrongly without it, and it goes under the heading that already covers its kind of work. A repo's own `CLAUDE.md` holds only what is true of that repo.

## Text an agent reads

`SKILL.md`, `CLAUDE.md`, tool descriptions, error messages and CLI help reach an agent with no person to resolve an ambiguity. The `asd-ste100` gate checks every staged `SKILL.md`, `CLAUDE.md` and `references/*.md` file, and `docs/GOVERNANCE.md` says where it warns and where it blocks. Text in a skill that a person reads follows `docs/VOICE.md`, with every sentence at 25 words or fewer.

## The GitHub About

Every repo has a filled-in About, with a one-sentence description and topics that name its real technologies and problem areas. An empty About counts as missing documentation, and `olivercode health` reports it wherever the `gh` CLI is available.

```bash
gh repo edit --description "..." --add-topic <topic>
```

## Where this applies

This standard governs OliverCode, every repo it governs and any fork. A repo bootstrapped from `core/templates/project/` gets a quality baseline that points here. A self-contained suite that ships its own `docs/VOICE.md` follows its own documentation rules.

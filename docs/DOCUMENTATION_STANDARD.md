# Documentation Standard

The structure, naming and upkeep rules for every README and document in this framework and in every repo it governs. How to write the words lives in one place, `docs/VOICE.md`, and this file does not restate it.

`bash scripts/validate.sh` enforces the mechanical parts (reference integrity, doc/code consistency, the feature-map index). Read it, with `docs/VOICE.md`, before writing any README or doc.

---

## The README outline

A README is written for a reader on their first day, who knows the business context and none of the internals. It follows this order:

1. **`# repo-name`**, then one sentence stating what this is and what a reader can do with it.
2. **The driving problems.** One to three short paragraphs, each a real problem with a concrete consequence and the design choice that answers it.
3. **Install and first use.** Runnable immediately, with real-looking values.
4. **How it works**, named in the reader's terms.
5. **What comes back.** The actual fields, objects or artifacts, including what the reader holds when it fails.
6. **Design decisions.** Each headed by the decision stated as a claim, and defended by the failure it prevents.
7. **Task-oriented sections** as the surface area demands.
8. **Documentation.** A two-column table linking every document in the repo with a one-line purpose each. A doc missing from this table is unreachable.
9. **Status.** Runtime requirements and what is verified, stated as the command that proves it. A volatile count appears only as a dated measurement.
10. **License.** Only where the repo ships one and licensing matters to a reader.

Length follows surface area. A small tool gets a short README in the same order.

## Index READMEs

A README that catalogs a set of things (a skill suite, a monorepo, a folder of tools) answers six questions in this order, each under its own heading:

1. What is this, and who is it for.
2. How do I get it.
3. How is it organized, with a directory tree.
4. How do the parts relate, with tables where the content is a matrix.
5. What is in each part, with one table row per item that describes the item in its own terms.
6. How to keep it current.

Every named path, command, count and row is checked against the repo before delivery.

## Sentence clarity

`SKILL.md`, `CLAUDE.md`, skill and tool descriptions, error strings and CLI help text are read by an agent with no human to resolve ambiguity, so they get the `asd-ste100` skill in strict mode. A commit-time gate warns on every staged `SKILL.md`, `CLAUDE.md` and `references/*.md` (`docs/GOVERNANCE.md`'s coverage table). Text inside a skill that a person reads follows `docs/VOICE.md`, within the gate's 25-word cap.

## File naming and the document set

Documents live in `docs/` and are named `CAPS-KEBAB.md`. Root level carries only `README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `LICENSE` and, where the repo declares one, the quality baseline. Every document opens with `# Title` and one sentence saying what it covers.

The standing set, present in any repo with enough surface to need it:

| File | Carries |
|---|---|
| `README.md` | The document written for a stranger |
| `docs/ARCHITECTURE.md` | How a request or change flows, the module map and design boundaries |
| A reference doc (`REFERENCE.md`, or split by surface) | Every option and field. This repo splits its own across `FEATURE_MAP.md` and `OLIVERCODE_LAUNCHER.md` |
| `docs/ADOPTING.md` | The onboarding path for a new user or a fork, each step verifiable |
| `docs/BACKLOG.md` | Open items for a repo with no `backlog-config.json`, and decision rationale otherwise |
| `docs/TROUBLESHOOTING.md` | Failures a user will hit, symptom first |

One concept has one home. Secondary mentions point to the owning doc by name. `docs/FEATURE_MAP.md`, where present, is the machine-checked index from every capability to its owning doc.

## The backlog policy

A repo whose `CLAUDE.md` names a `backlog-config.json` keeps its open work in the GitHub Project that `backlog-management` and `board-hygiene` read and write (OliverCode included, per `core/contracts/PROJECT_STRUCTURE_STANDARD.md`). Its `docs/BACKLOG.md` keeps only a bounded "Design decisions" section and a "Resolved" section, where each entry records a failure class a gate now stops.

A repo with no `backlog-config.json` keeps its open items in `docs/BACKLOG.md`. Finished work leaves the file, because git holds that history.

## Always current — the sync rule

- A change to behaviour, options, structure or file layout updates every document that states the old truth **in the same commit**.
- The README's documentation table, the feature map and the backlog count as documents.
- `bash scripts/validate.sh` fails closed on the drift it can detect. What it cannot detect is still the rule.
- A capability change is incomplete until `docs/FEATURE_MAP.md`, where present, is updated in the same change set.

## The GitHub About section

Every repo carries a filled-in About: a one-sentence description and topics naming the real technologies and problem domains. An empty About counts as missing documentation. `olivercode health` checks for it where the `gh` CLI is available.

```bash
gh repo edit --description "..." --add-topic <topic>
```

## Scope

This standard governs OliverCode, every repo the framework stamps or governs, and any fork. `core/templates/project/` carries it into newly bootstrapped repos.

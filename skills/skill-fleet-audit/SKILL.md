---
name: skill-fleet-audit
description: "Audits the skill fleet: structure, MCP call patterns, writing clarity, history language, doc-sync, portability, file weight and over-engineering. Trigger on 'audit my skills', 'check doc sync', 'check portability', 'simplify the skills', 'is this over-engineered', 'how did that session go'."
---

# Skill Fleet Audit

The mechanical check that keeps every skill lean and portable. The dimensions below state the bar, and the scripts enforce it.

## Opening message

Send this first, in one turn, exactly as written, with no other opening line and no closing recap. A request that names its own dimension or target skips the message.

> A lean, portable skill fleet stays easy to trust, copy and maintain.
>
> I run the fleet checks and merge what they find into one report. I fix cheap, checked findings directly. A larger decision, such as splitting or merging a skill, becomes a backlog item for you to decide.
>
> It helps to name any skill or check you already suspect. Rough notes are fine.
>
> You can answer in any of these ways:
> 1. Say "audit my skills" and I will run the structure, MCP pattern and writing clarity checks on every skill.
> 2. Name one dimension, such as doc sync, portability, file weight or dead code, and I will run that check alone.
> 3. Name a skill or folder, or ask me to review the task that just ran, and I will scan that one target.

## The fleet root

The fleet root is a folder that holds skill folders directly, or one level inside a family folder. Each script scans it by default. Set `SKILL_FLEET_ROOT` to point every script at another folder, or pass a path argument to scan one skill, one family or one fleet. When this skill sits directly under the fleet root with no family folder, set `SKILL_FLEET_ROOT`.

## Dimensions

"Gate" means a finding makes the script exit 1, and a commit hook may block on it. "Reports" means a finding is a candidate for a human to judge. A reporting script can exit 1 too, so a runner must not treat its exit code as a gate.

| # | Dimension | Script | What it flags | Effect |
|---|---|---|---|---|
| 1 | Dangling references | `check_skill_structure.py` | A skill named as a skill that resolves to no skill in the fleet or in `~/.claude/skills`. A backticked file name or run script that a skill's text cites and its own folder does not hold | Gate |
| 2 | MCP call patterns | `check_mcp_patterns.py` | A search loop per blank field. Two or more subagents at once. A tell to the person to configure a connector | Gate |
| 3 | Writing clarity and description length | `check_clarity.py` | An ASD-STE100 violation in a `SKILL.md` or a `references/*.md` file. A description over the word cap | A hard violation exits 1. A long description only reports |
| 4 | History language | `check_plan_doc_leak.py` (check 3) | An ISO date, an issue id, a history word or a narration phrase about who approved a rule in a `SKILL.md` or a `references/*.md` file. The reason for a rule belongs in the family `DECISIONS.md`. A line that needs one for real ends with `<!-- allow-history -->` | Gate |
| 5 | Plan docs | `check_plan_doc_leak.py` (checks 1 and 2) | A file under `<repo>/docs/plans/` or `<repo>/docs/specs/`, a file named like a backlog, or a `SPEC-N` citation | Gate |
| 6 | Issue citations | `check_issue_refs.py` | A `#N` that is not a real issue in the repo named by `SKILL_FLEET_ISSUE_REPO`. Needs `gh` on the path. With no repo named, it prints a note and passes. `--staged` scans staged files | Gate |
| 7 | Name leak | `check_name_leak.py` | A real name or email from a `.env.local` in another file. The machine account name or a home path in a skill file. A name-shaped string next to a resume filename reports only | Gate |
| 8 | Hard-wrapped paragraphs | `check_line_wrap.py` | A paragraph written as several source lines. `--fix` joins it to one line | Gate |
| 9 | Doc-sync | `check_doc_sync.py` | A skill missing from the fleet `README.md` rows, a row with no skill, or a missing `~/.claude/skills/` symlink | Gate |
| 10 | Portability | `check_portability.py` | A skill that follows, loads or reads a `skill-governance/` path. That folder holds the audit tooling and does not travel with a skill | Gate |
| 11 | Weight metrics | `check_skill_structure.py --weight`, and `--routes` | One ranked table of every skill. The columns are file count, size, untested scripts, `SKILL.md` lines, description words, unreferenced files, uncalled scripts, unloaded references, and in-family and cross-family reference counts. `--routes` lists route rows that load more than 2000 words. It ranks candidates for a read and makes no judgment | Reports |
| 12 | Usage | No script. Follow `references/usage-audit-process.md` | The real tool calls of one just-run task | Reports |
| 13 | Retired terms | `check_retired_terms.py` | A term that a decision retired, still taught in a `SKILL.md`, a `README.md` or a doc under `skill-governance/`. A `DECISIONS.md` row that says "Reversed by" an id the list does not own. The list lives in the retired-terms.json file in the fleet's .fleet-audit folder and starts empty | Gate |
| 14 | Outside references | `check_outside_refs.py` | A skill names a vault, a numbered vault folder, the framework repo or a name history. Staged files that name the framework repo fail too. The `skill-governance` family is checked for the numbered folder and the framework repo only | Gate |
| 15 | Skill folder contents | `check_skill_folder.py` | A skill folder holds a decision ledger, a cache, a compiled file or a local file such as `.env.local`. Move a ledger to the family folder | Gate |
| 16 | Wording | `check_wording.py` | A file or folder name inside a skill that ends in a number (`playbook-1`). A ticket reference in prose | Gate |
| 17 | README facts | `check_readme_facts.py` | The fleet README tree lists a top-level folder that is not on disk, or omits one. A dependency row disagrees with the folder's `_REQUIRES`. A file or folder the README names is not on disk | Gate. Fix the README text to match the files |
| 18 | Simplification review | No script. Follow `references/simplification-review.md` | Over-engineering and duplication in one skill or family. Examples: words that restate a rule, a route that loads an unneeded file, and code with no caller. Also a list written twice and a gate that guards nothing. Every finding gets a file and a line. Each decision is Remove, Inline, Merge, Rewrite or Keep | Reports |
| 19 | Dead code | `check_dead_code.py` | An unused import in a script. A top-level function or class that no other non-test text names. A file in a skill that no other file in the skill cites | Gate. Row 11 reports the same on request |
| 20 | Word budget | `check_skill_budget.py` | A skill that carries more words than its row in the skill-budgets.json file in the fleet's .fleet-audit folder, or a row for a skill that is not in the fleet. A skill with no row is not checked. `--measure` prints a budget 10% above each skill's count | Gate. Raise the row in the same change that adds the words |
| 21 | Prose reads | No script | A quoted trigger phrase in a description with no matching operation in the body. Several ask-the-user steps in a row that one batched question would replace | Reports |
| 22 | Opening message | `check_opening_message.py` | A skill with no `Opening message` section, or one that holds neither a list of three or more items nor a pointer to an existing file | Gate |
| 23 | Script documentation | `check_script_docs.py` | A script subcommand no doc names, or a documented `script.py command` that does not exist | Gate |

## Commit tools

`commit_paths.py <message-file> <path-list-file>` commits only the named paths in a tree that several sessions share. `precheck.py <path-list-file>` runs the repo's `.githooks/pre-commit` against those paths and commits nothing.

## Process

1. Run dimensions 1 to 3 with no argument. Merge the output into one report.
2. Run any other dimension the request names.
3. When the request names one just-run task, such as "how did that session go", run dimension 12 and follow its steps. For an ended session, ask the user to paste excerpts.
4. For each finding, open the quoted location and judge it in context. A phrase shared on purpose is not drift.
5. Fix checked, cheap findings directly. Write a larger decision, such as a skill split or merge, into a backlog item. Hand ordering to the `plan` skill. Never auto-fix a structural decision.

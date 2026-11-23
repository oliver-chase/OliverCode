# The ten lenses

Every route applies all ten. State each lens's result, including "checked, nothing found" with what was checked.

## 1. Autonomy and user flow

A person who has never seen the target gets from download to a first result by talking, without knowing a command, a subcommand or a config key.

- Walk the real first run on a clean checkout: copy it into a temp folder with a fresh `HOME`, then follow only what the README and the entry skill say
- The entry point asks where the person is and skips what does not apply
- Walk each missing prerequisite step by step: what it is, why, what it costs, and the clicks or command the agent runs
- A step that tells the person to run a command, edit a file or set a key is a finding, and so is a dead end where one step's output has no next step
- Every question that offers a default shows the bring-your-own choice, and every result names where it landed

## 2. Self-containment

The target runs on a clean machine with no owner paths, no other repo and no owner data.

- Grep shipped files for absolute paths, `$HOME`, `../` out of the target and names of other repos
- Build the owner's identifiers from the target's own evidence: the git remote owner and authors (`git log --format='%an %ae' | sort -u`), names and IDs in config, data and example files, brand colors and fonts, and the product or niche the examples assume. Grep every shipped file for each. A hit outside an example file is a finding, and so is a default that is one owner's choice, such as a niche, color or store name
- Every example value is an obvious placeholder, such as `my-shop`, `123` or `#000000`. A real-looking name, ID or color named once as "such as" is the leak a name list never catches
- Copy the target alone into an empty folder and run its main entry. A missing file or unset key is a finding

## 3. Accuracy

Every claim is checked against the code, and the code wins.

- Run, list or read every path, command, flag, count and behavior a doc or skill names, and name any two files that state one fact differently
- Each bug carries its failure scenario and a repro that the audit session ran
- Each closed issue the scope cites has a commit, and the fix is in the code today. An issue closed as not planned (`gh issue list --state closed --json number,stateReason`) is a decision: read its closing comment and report the reason, and report a defect only where the board or docs still claim the feature
- A check that can never fail, and a test that stays green with the code it guards removed, are findings. The audit session proves it in step 4 by removing the guard in a scratch copy and watching that one test, then restoring it

## 4. One home per concept

- The same rule, list, schema, command chain or explanation in two or more files. Name the one home and where each copy points
- Run `olivercode cutlist --dupes` for the count of helpers with the same body in two or more files, and merge each pair into one module that both callers import
- Near-duplicates a byte check misses: a reworded rule, two functions doing one job, two tests covering one behavior
- Competing standards: a second writing, style, layout or process rule beside the one that owns it
- A copy that a self-contained part needs is kept when a recorded reason and a check that keeps the copies identical both exist

## 5. Over-engineering and unused parts

- Code, config keys, flags, gates, templates, docs and whole skills that nothing uses. Grep the whole target for each name, including shell calls and same-folder imports. A reference only from its own test does not count
- A mechanism bigger than its job: a mode no one selects, a baseline that never drops, a gate that cannot name the defect it prevents, a menu no real user takes, a workaround for a problem that no longer exists (rerun the problem to check), or a skill that fires on nothing a person says
- Data bloat: a file per day, week or run, or a readings file that never rolls up (skill-creation rule 14)
- Size: a file over 400 lines, tests or docs that outweigh the code they cover, a module with one consumer, two files that merge, a custom script a standard tool replaces, a config file that restates defaults. Each is a finding with its lines

**Usage evidence.** For each command, scheduler, gate or flag ask "has it ever run?" and record evidence a person could check: an installed job (`ls ~/Library/LaunchAgents`, `crontab -l`), a state or log file, a registered repo, a commit or release that used it, or a nonzero count in a log. A part referenced only by docs, its own tests or an unfilled registry entry counts as unused.

**Test necessity.** For each test module report tests of counts, totals and exact message wording, one behavior covered at two levels, tests of process tooling that cover no product behavior, and tests a mutation would not fail (the audit session mutates a scratch copy, never the repo). Give a verdict on tests per 100 lines of code and a cut list in lines.

**Existing tools.** For each mechanism that distributes or enforces rules, name the standard tool that does the same job (pre-commit framework, lefthook, a global `core.hooksPath`, GitHub rulesets, a package manager) and why it is or is not used.

## 6. Cost in use, in tokens and runtime

- Always-loaded text: every `CLAUDE.md` in the chain, its imports and every skill description. Count characters, and estimate tokens at four characters each
- Per-trigger text: each skill body and the references a route loads. A route that loads a file it does not use is a finding, and so are two skills or files that load overlapping content for one task
- Runtime of hooks and scripts that run on every session, tool call or stop: time them
- Inefficiency: work repeated across calls, a read or API call that could be cached or batched, a loop a standard tool replaces, and a task a cheaper model does as well
- Prose that re-explains what a script prints, and steps a script could do. Rewrite loaded text to the fewest words that keep the rule

## 7. Voice

`VOICE.md` is the only writing standard. Read it first, then check every text a person reads.

- Run `python3 skills/audit/scripts/fleet_check.py <target>` for the mechanical kinds with their file and line, and read the text for the rest
- Count violations by kind: contrast framing, fragments, filler openings, process history in reader text, curly quotes, Title Case headings, trailing periods on bullets
- Name every file that sets writing rules of its own. A self-contained suite's byte-identical copy of `VOICE.md` is the same standard

## 7b. Design

OliverCode's `docs/DESIGN.md` is the only design standard. Read it and the target's own `docs/DESIGN.md`, then check every page, slide, image and interface the target makes.

- Count hits on the tells list by kind, and name the file and line for each
- Check color tokens, type weights, the 4-pixel grid, contrast, phone width and dark theme against the rules
- A suite that ships visuals carries a byte-identical copy of OliverCode's `docs/DESIGN.md` at its own `docs/DESIGN.md`. A target with visual output and no brand design note is a finding

## 8. Documentation coverage

The target has a documentation repository: one entry for the whole tool and one for every part, each true today.

- Whole tool: the README states what it is, who it is for, how to install it, the first result and where everything lives. A layout doc names every top-level folder, and each decision is recorded where it was made
- Every part (each skill, agent, command, gate, hook, script and config file) has one entry stating its job, how it starts (trigger phrase, command or hook event), what it reads and writes, the files it owns, how it fails and how to recover. A skill carries its entry in its own `SKILL.md` and references
- A hand-written entry that is wrong is an accuracy finding, and a part with no entry is a finding at the part's own priority

## 9. Functionality gaps

- For each job the README promises, an entry point, a test and a doc exist, and a failure says what to do next
- A manual step a script could do, a dead end, an error with no recovery, and a capability the target's own goal implies but lacks
- Extend what exists before adding anything. Each gap story names what it extends or replaces, whether it is core or an add-on, and its net lines and always-loaded tokens. A gap that costs more than it saves is an owner decision

## 10. Portability and sharing

Decide first whether the target should be shareable, from what it is, and record the verdict with its reason in the README or `<target>/docs/SHARING.md`. Never assume.

- **Portable** is the default for a tool, framework, skill or template meant to run for someone else. It is done when a stranger can clone it, run its first step by talking, and find no owner data, secrets or personal addresses in the tree or the history
- **Personal** fits a target built on the owner's own accounts, data or life, such as Apple Notes or Photos skills, family records or a private deployment. State why it should not be shared, and still keep secrets and owner data out of git and out of anything that leaves the machine
- **Portable after fixes** is a portable target with blockers, each one a story. Say which verdict you reached and why, and let the owner overturn it
- Run `python3 skills/audit/scripts/portability.py <target>`. It lists tracked secret files, home paths, owner identities in the tree, personal emails and secret-shaped values in the history, and a missing license, README or `.gitignore` entry
- Commits: every author and committer address is a noreply or project address. History that holds a secret or owner data gets an owner-decision story, since removing it rewrites shared history (`git filter-repo`), and the credential is revoked first. Add a `.mailmap` for old identities
- Settings: a private repo meant to be shared names the steps to publish it, and a public repo has a license and a security contact

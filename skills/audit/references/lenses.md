# The seven lenses

Every route applies all seven. State each lens's result in the report, including "checked, nothing found" with what was checked.

## 1. Autonomy and user flow

A person who has never seen the target gets from download to a first result by talking. They never need to know a command, a subcommand or a config key.

- Walk the real first run on a clean checkout: clone or copy into a temp folder with a fresh `HOME`, then follow only what the README and the entry skill say
- The entry point asks where the person is and skips what does not apply
- Each missing prerequisite is walked step by step: what it is, why it is needed, what it costs, and the exact clicks or the command the agent runs for them
- A step that tells the person to run a command, edit a file or set a key is a finding. So is a dead end, where one step's output has no next step
- Every question that offers a default also shows the bring-your-own choice, and every delivered result names where it landed

## 2. Self-containment

The target runs on a clean machine with no owner paths, no other repo and no owner data.

- Grep shipped files for absolute paths, `$HOME`, `../` out of the target, and names of other repos
- Build the owner's identifiers from the target's own evidence, with no list required: the git remote owner and authors (`git log --format='%an %ae' | sort -u`), names and IDs in config, data and example files, brand colors and fonts, and the product or niche the examples assume. Grep every shipped file for each. A hit outside an example file is a finding
- A default that is one owner's choice, such as a niche, a color, a city or a store name, is owner data even with no name attached
- Copy the target alone into an empty folder and run its main entry. A missing file or unset key is a finding

## 3. Accuracy

Every claim is checked against the code, and the code wins.

- Every path, command, flag, count and behavior a doc or skill names: run it, list it or read it
- Two files that state one fact differently: name both
- Each bug carries its failure scenario and a repro that was run
- Each closed issue the scope cites: its commit exists and the fix is in the code today
- A check that can never fail, and a test that stays green with the code it guards removed, are findings. Prove it by removing the guard and watching the test, then restore it

## 4. One home per concept

- The same rule, list, schema, command chain or explanation in two or more files. Name the one home and where each copy points instead
- Near-duplicates that a byte check misses: the same rule reworded, two functions doing one job, two tests covering one behavior
- Competing standards: a second writing, style, layout or process rule beside the one that owns it
- A copy that a self-contained part needs is kept when a recorded reason and a check that keeps the copies identical both exist

## 5. Over-engineering and unused parts

- Code, config keys, flags, gates, templates, docs and whole skills that nothing uses. Grep the whole target for each name, including shell calls and same-folder imports. A reference only from its own test does not count
- A mechanism bigger than its job: a mode no one selects, a baseline that never drops, a gate that cannot name the defect it prevents, a menu no real user takes
- Workarounds for a problem that no longer exists. Rerun the problem to check
- A skill that does not earn its trigger: its job is done by another, or it fires on nothing a person says

## 6. Token cost in use

- Always-loaded text: every `CLAUDE.md` in the chain, its imports, and every skill description. Count characters, and estimate tokens at four characters each
- Per-trigger text: each skill body and the reference files a route loads. A route that loads files it does not use is a finding
- Chains: two skills or files that load overlapping content for one task
- Runtime cost of hooks and scripts that run on every session, tool call or stop: time them
- Prose that re-explains what a script prints, and steps a script could do

## 7. Voice

`VOICE.md` is the only writing standard. Read it first, then check every text a person reads.

- Count violations by kind: contrast framing, fragments, filler openings, process history in reader text, curly quotes, Title Case headings, trailing periods on bullets
- Name every file that sets writing rules of its own, such as a style section, a sentence cap or a lint standard
- A self-contained suite's byte-identical copy of `VOICE.md` is the same standard

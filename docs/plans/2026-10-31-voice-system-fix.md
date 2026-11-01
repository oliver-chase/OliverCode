# Plan: One voice, three writing sources
Date: 2026-10-31
Related: `~/.claude/skills/clean-writing/` (SKILL.md, voice/baseline.md, voice/voice.md, voice/voice-internal.md), OliverCode `CLAUDE.md`, `.claude-optimization/memory/USER.md`, `docs/WRITING_PROCESS.md`, `docs/DOCUMENTATION_STANDARD.md`, `docs/EXTERNAL-TOOLING.md`, `skills/writing-documentation/SKILL.md`, `automated-content-flow/scripts/dashboard.py`

## Goal

The system carries too many writing instructions, and they pull against each other. This plan cuts them to three sources and rebuilds the voice around the model reply the owner supplied, so every output reads like it: chat, documents, interface copy and the messages skills send.

The model reply has five traits:

1. **Value first.** It opens with what the reader can accomplish ("Explore your accounts, track audience growth, and identify opportunities to expand your reach").
2. **Instructions that name the action and the control.** "Click any account card below to view its performance and activity." "Select the How It Works tab at the top."
3. **Numbers with meaning.** Counts become a snapshot, and the reply points to what is changing, what is working and where the next opportunity is.
4. **Full, warm sentences.** It acknowledges the person's intent ("I understand what you're getting at") and uses natural connecting words.
5. **A clear shape.** The answer comes first, then a labeled "Why this works," then one larger recommendation.

The output it replaces read: "2 accounts, 101 followers, 1,049 posts booked, each card opens that account. How the system works is in its own tab."

## Target in five lines

1. Three writing sources remain. `baseline.md` holds the always-on rules and a short before and after. `voice.md` holds the full model reply and the detail by audience. ASD-STE100 governs agent-only text and stays as it is.
2. `voice-internal.md` and `docs/WRITING_PROCESS.md` are deleted. Anything in them still worth keeping moves into `voice.md` in one line.
3. Every other place that talks about voice keeps one pointer to clean-writing and restates nothing: the global `CLAUDE.md`, USER.md, `DOCUMENTATION_STANDARD.md`, the `writing-documentation` skill, the 12 ecommerce shop skills, and the family-stories and AI Workshops `CLAUDE.md` files.
4. Text a person reads inside a skill (opening messages, questions, options) follows `voice.md`. STE's strict mode keeps governing procedures an agent runs, and its 25-word cap still applies to everything it scans.
5. Verified by reading: the links to the two deleted files (clean-writing `SKILL.md`, OliverCode `README.md`, `FEATURE_MAP.md`, `DOCUMENTATION_STANDARD.md`, `writing-documentation/SKILL.md`, `scripts/lib/duplication_check.py`), the 13 opening-message skills, the 12 identical ecommerce lines and the dashboard strings. Guessed: how much of the clipped chat style comes from Claude Code's own system prompt, which this plan can only override.

## Steps

1. **Rewrite `baseline.md` around the model.** Replace "Compress the wording and never the content" with "Keep every fact and cut only filler words." Add the five traits as rules, plus one line saying these rules override any default instruction to keep replies short, in chat as well as in files. Add a two-line before and after from the dashboard header. Keep the existing rules on facts, owners, dates and contrast framing. Hold the file to roughly its current length by merging bullets that overlap. — *why:* it is the only voice rule that loads in every session, including chat, and today it lists only what to remove. *Risk:* medium, because every session reads it.

2. **Rebuild `voice.md` as the single guide.** Put the full model reply and the rejected output at the top, with the five traits labeled. Keep one short entry per audience: chat replies, emails and messages, notes, documents and READMEs, interface copy, and posts. Move in from `voice-internal.md` only the rules with no other home: the email subject states the ask and its date, and decision documents open with the decisions. Remove every license for fragments, shorthand, lowercase or brevity. Cut the sections that repeat the baseline. — *why:* one guide replaces three overlapping files, and the model reply becomes the reference every rule points back to. *Risk:* low.

3. **Delete `voice-internal.md` and `docs/WRITING_PROCESS.md`.** Update the files that link to them: the clean-writing `SKILL.md`, OliverCode `README.md` (doc table row), `docs/FEATURE_MAP.md`, `docs/DOCUMENTATION_STANDARD.md`, `skills/writing-documentation/SKILL.md` and the quoted path in `scripts/lib/duplication_check.py`. Also reword the code comment at line 211 of `scripts/check-comment-budget.mjs` in oliver-studios, tesknota, fallow and oliver-crawl, which names WRITING_PROCESS. — *why:* both files repeat or contradict the baseline, and WRITING_PROCESS.md sends voice to a `shared-company` skill that does not exist. *Risk:* medium, because OliverCode's validation checks references and duplication.

4. **Reduce every other voice mention to one pointer.**
   - Global `CLAUDE.md`: keep the baseline import and one line sending documents, emails, posts and slide copy to clean-writing. Remove the `sow-proposal` pointer, because that skill is not installed.
   - `USER.md`: delete "Compact bullets, never restate," "Expects direct answers without narration" and "Reports: Compact bullet + root-cause-chain." Keep the rules about acting promptly, which are not about voice.
   - `DOCUMENTATION_STANDARD.md`: replace the Voice and Readability sections with one pointer to `voice.md`. Keep the README structure, naming and formatting sections. In Sentence clarity, state that text a person reads inside a skill follows `voice.md`.
   - `writing-documentation/SKILL.md`: point step 1 at `voice.md`.
   - `docs/EXTERNAL-TOOLING.md`: remove the caveman row, which recommends compressing chat output by about 65%.
   - `skill-creation/references/opening-message-convention.md`: replace its writing rules with a pointer to `voice.md`, and keep the structure rules and the 25-word cap.
   - The 12 ecommerce shop skills, family-stories `CLAUDE.md` rule 6 and the AI Workshops `CLAUDE.md` Writing section: replace each voice line with one pointer to clean-writing, in the form each repo's portability rule allows.
   - Leave oliver-studios `BRAND-VOICE-BASELINE.md`, `cf-community` and `voice.json` alone. They set the voice of generated posts per account.
   — *why:* one concept gets one home, so a future fix lands once. *Risk:* low per file. The portability rules in the vault and the ecommerce repo decide the exact pointer wording.

5. **Record the lesson in memory.** Add one entry to `.claude-optimization/memory/MEMORY.md` saying the model reply in `voice.md` is the standard for every output. — *why:* the owner asked the system to learn from this example. *Risk:* low.

6. **Rewrite the person-facing text that was written in the old style.** Rewrite the 13 opening messages (apple-library-router, apple-notes-cleanup, apple-photos-organizer, board-hygiene, clean-writing, dinner-grocery-planner, disk-cleanup, family-readme-audit, plan-pressure-test, skill-creation, skill-family-packager, skill-fleet-audit, vault-folder-organization). Rewrite the section ledes and empty states in `automated-content-flow/scripts/dashboard.py` (about 25 strings) so each one says what the reader can do there. Show the owner each before and after, because these go out word for word. Ask separately whether the overview headline should lead with growth and opportunity, with followers and posts booked as supporting numbers. — *why:* this is the fixed text people see, and it is where the old style shows most. *Risk:* medium, because `test_dashboard.py` asserts some strings and another session may be editing the suite.

7. **Verify.** In a fresh session, ask for a description of the dashboard header, a short status email and the clean-writing opening message. Grade each against the five traits and record the result under Findings. Run OliverCode's `bash scripts/validate.sh`, the vault's pre-commit gates, the clean-writing linter tests and the content-flow tests (`.venv/bin/python -m unittest discover -s scripts`). Commit each repo to main after its own validation passes. — *why:* a rule change counts only if the output changes. *Risk:* low.

## Risks

- The model reply's commentary uses contrast framing ("not just a collection of activity metrics," "Moves beyond describing interface mechanics"), which the baseline bans. → The owner decides before step 1 whether explanations may use it. The ban stays until then.
- Removing every brevity license changes meeting notes and Apple Notes output too. → The owner asked for the model style in every output. Notes keep every decision, number and owner.
- Claude Code's own system prompt keeps asking for short replies. → Step 1 overrides it in the always-on file, and step 7 tests whether the override holds.
- Deleting two files can leave a broken reference or trip the duplication check. → Step 3 updates every file found linking to them, and step 7 runs validation before any commit.
- Another session may be editing the vault or the content-flow suite. → Read each file again before editing it, commit only this plan's changes, and never stash in a shared tree.

## Definition of Done

- [ ] Three writing sources remain: `baseline.md`, `voice.md` and ASD-STE100
- [ ] `voice-internal.md` and `WRITING_PROCESS.md` are gone, and nothing links to them
- [ ] Every other voice mention is one pointer to clean-writing
- [ ] No file permits fragments, shorthand or compressed chat
- [ ] `voice.md` holds the model reply, and MEMORY.md points to it
- [ ] The 13 opening messages and the dashboard copy are rewritten and approved by the owner
- [ ] Three fresh-session samples match the model reply, recorded under Findings
- [ ] Every touched repo's validation passes, and each repo is committed to main

## Findings

- The ASD-STE100 linter checks length, semicolons, phrasal verbs, nominalization, marketing adjectives, synonym rotation, passive voice and compound tenses. The model reply's sentences pass its 25-word cap, so the gate can stay as it is. The clipped style came from authors applying STE habits to text people read.
- The ecommerce shop skills already say their voice line "overrides any instruction to compress, shorten or drop words," which shows the compression problem was noticed there before.
- The 12 ecommerce voice lines stay as they are. Shipped skill text may not name a sibling skill, and each line already asks for full, plain sentences. For the same reason, `opening-message-convention.md` states the model's traits directly and does not name clean-writing.
- `docs/NEW_MACHINE.md` told a new machine to install the caveman compression plugin. Step 4 removed that step, and the adoption skill no longer lists caveman.
- OliverCode's validation was already failing at HEAD because `scripts/lib/local_config.py` had no feature-map entry. It is an internal data loader, so it joined the exemption list.

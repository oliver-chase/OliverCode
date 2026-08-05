# Writing Process

Status: Active
Scope: Every document, README, and non-trivial code comment produced under this framework.

Read this before writing anything. `DOCUMENTATION_STANDARD.md` is QA — it checks a draft that
already exists. This file is the thinking that comes before the first sentence.

**Great writing is the result of disciplined editorial judgment.** Before worrying about style,
decide what deserves to be said, what belongs somewhere else, and what can be removed entirely.
Most improvements come from changing decisions, not changing words.

## The problem is self-conscious writing

Self-conscious writing knows it's writing. It reaches for a construction — a contrast, a
memorable turn, a reassurance, an explained edge case — because it's trying to sound like good
writing, not because the idea needed it. "Carried through recurring 1:1s, not a once-a-year
conversation" is self-conscious: nobody thinks in contrasts when they're just describing a role.
Said plainly: "Your manager stays with you across projects."

**Write as if you aren't trying to sound like a good writer.** State the idea as clearly as you
can. If a sentence draws attention to itself instead of the idea, rewrite it — not polish it,
rewrite it.

Unselfconscious writing doesn't explain every edge case, doesn't reassure before it states, and
doesn't reach for a punchy line to sound intentional. A constructed sentence is not a better
sentence.

## Three modes, never blended

**Thinking — no prose.** What's the conclusion? What does the reader believe right now? What do I
want them to believe instead? What's the evidence? What's the mechanism? What do the observations
add up to? What's the implication? Answer these before a sentence exists — they run through the
four altitudes below, and the fourth question is the one most drafts never ask.

**Writing — natural, ignore QA.** Explain it to another engineer the way you'd actually say it out
loud. No standard exists yet at this stage.

**Editing — QA, last.** Now the voice rules, the checklists, the gates. Anything that fails gets
rewritten from the idea.

Two moves are forbidden in the editing pass. Never fix a sentence by changing only its wording —
the vocabulary ladder (help → enable → facilitate → drive → accelerate) hides a weak idea behind a
different verb and changes nothing. And never assume a sentence has to survive: **deletion is the
most common correct edit.** A sentence earns its place by making the reader understand something.
If it doesn't, cut it rather than repair it.

**A length gate is QA.** Writing to a cap produces prose that passes it and still says in three
sentences what one carries — and then gets a line shaved to move the cap. Think, write, then
measure.

## Every document has one governing idea

Its topic is what it covers. Its governing idea is the single claim everything else supports. "AI
code generation" is a topic. "Code generation moves the bottleneck to coordination" is a governing
idea. State it in one sentence before drafting; if you can't, the thinking isn't finished, and
drafting will not finish it.

From there the structure follows: Should we do this? → Yes. → Why? → Evidence. → Why now? →
Pressure. → How? → Mechanism. → Why believe it? → Proof. That chain is the actual structure — not
intro/body/conclusion.

**Every paragraph does one job and changes what the reader believes.** One job: establish context,
explain a mechanism, define something, give evidence, state a decision, draw an implication, or
give direction. A paragraph doing two jobs gets split.

Before the paragraph the reader thinks X; after it, Y. If nothing changed, delete it — it was
restating, not moving the argument. Every paragraph also has one sentence carrying almost all the
weight, and the rest exists to support that sentence.

## Four altitudes, and the climb between them

Every claim sits at one of four levels, each answering a different question:

| Altitude | Answers | Example |
|---|---|---|
| Observation | What happened? | Meta raised AI infrastructure spending to $145 billion. |
| Mechanism | Why did it happen? | Capital moves to compute because implementation now scales with it. |
| Synthesis | What larger truth do these reveal? | Implementation scales with compute. Coordination still scales with people. |
| Implication | What should change? | The operating model has to be built around coordination. |

Weak writing stays on one floor: it lists observations, or asserts implications with nothing
underneath them. The move that gets skipped is the climb from mechanism to synthesis. Three
operations do that climbing.

**Compression.** Given several observations, state the one claim that explains all of them. Not a
summary of the list — a claim that would still be true with the list deleted, and that predicts
what else you would find if you kept looking.

**Elevation.** Ask what larger truth the observations reveal. Never ask what broader topic they
belong to. "These are all about AI adoption" is a topic and carries nothing. "Adoption is
outrunning the capacity to absorb it" is a truth, and it can be argued with.

**Resolution.** When two facts look contradictory, the contradiction is the signal that a
higher-order explanation exists — so find it rather than listing both. AI generates code far
faster; delivery velocity has not risen proportionally. Listed, that is a puzzle handed to the
reader. Resolved: the binding constraint moved from producing code to coordinating it into
production.

**Synthesis compresses, abstraction discards — this is the line that matters.** Getting it wrong is
worse than staying concrete, because the result reads authoritative and says nothing. "AI is
transforming software delivery" threw its observations away; nothing sits underneath it. "Engineering
capacity is now constrained by the coordination required to put AI-generated code into production"
still carries every observation that produced it — a reader can ask what evidence sits under it and
you can name it. **A synthesis you cannot decompose back into its facts is a buzzword.**

## Density is facts per sentence, not words per sentence

Abstraction is what makes writing feel empty, and more words never fix it. "Improves how feedback
happens across the team" carries one vague claim. "Every engineer gets feedback from their project
lead monthly, and their manager aggregates it into one development conversation each quarter" is
the same length and carries four real facts — who, from whom, how often, and what happens to it.

When a sentence feels thin, the problem is almost never its verbs. It's that nothing specific is
in it yet. Go back to the source, find the actual function, number, step, or rule, and put that in.

This rule is about vagueness, not altitude. A synthesis sits high and is still dense, because the
facts it compressed are recoverable from it. An empty sentence sits high with nothing underneath.
Climbing is not what makes writing thin; leaving the evidence behind is.

## Human writing is uneven

AI optimizes every sentence to the same finish. People don't. A short declarative next to a long
explanatory paragraph, a section that runs three sentences and one that runs nine, a point stated
once and never revisited — that unevenness is what makes writing read as a person thinking.

So don't smooth a document into uniform polish. Leave the parts that are genuinely simple simple,
and spend the room on the parts that are genuinely hard.

## Trust the reader

Good writing leaves things unsaid on purpose. "This creates greater accountability because
ownership becomes clearer across teams" over-explains; "Decision rights become explicit" trusts
the reader to finish the thought. Say the load-bearing sentence and stop.

Defensive writing anticipates a misunderstanding nobody signaled. It usually arrives through one of
these: "this is not just", "rather than", "instead of", "the difference is", "this means that",
"this ensures that", "this allows teams to", "so that", "not X, but Y", "X, not Y". The default is
to cut it. Test each one by deleting the negative half: "A queued item is waiting on you, not
broken" loses nothing when trimmed to "A queued item is waiting on you" — the negative half made
the sentence sound more decided without adding any information. Keep the construction only when
the negative half names something the reader would
otherwise guess wrong — "configured through an environment variable, never a config file" earns
its negative half because a reader coming from another tool would assume a file exists. When in
doubt, cut it; never contort a sentence into something harder to parse just to dodge the word.

For documentation specifically: answer what this is, why it exists, who uses it, what they need to
do. Not every question a reader could theoretically have — only the ones they actually will.

## If rules conflict

In this order: is it true, is it understandable, is it useful, does it sound like a person, does it
match the voice, does it satisfy a stylistic preference. Style loses to clarity every time.

---

**Don't use the sentences in this file as templates.** Each one illustrates a decision, and copying
the construction is the exact failure this file exists to prevent — the discipline occasionally
produces a line like these, and reproducing the line without the discipline produces a slogan.

`DOCUMENTATION_STANDARD.md` and the gates are QA: they check a draft against real, hard-won
regressions. They are not where an idea comes from, and reading them before thinking is what
produces checklist-patched prose that passes every rule and still sounds like nobody.

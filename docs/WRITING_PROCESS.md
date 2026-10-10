# Writing Process

Status: Active
Scope: Documents, READMEs and non-trivial code comments produced under this framework.

How to write anything, including the voice, belongs to the `shared-company` skill's voice files
(`voice-core.md` first). This file adds the thinking that applies to repository documentation and
comments. `DOCUMENTATION_STANDARD.md` and the gates check a draft that already exists.

## Decide before drafting

- **Give the document one governing idea.** Its topic is what it covers. Its governing idea is the
  claim everything else supports. "Code generation moves the bottleneck to coordination" is a
  governing idea. "AI code generation" is a topic. If you cannot state the idea in one sentence,
  the thinking is not finished.
- **Give each paragraph one job:** context, mechanism, definition, evidence, decision, implication
  or direction. A paragraph doing two jobs gets split. A paragraph that changes nothing the reader
  believes gets deleted.
- **Climb from observation to mechanism to synthesis.** A list of observations leaves the reader
  to find the pattern. Compression states the one claim that explains them. Resolution explains an
  apparent contradiction instead of listing both facts.
- **Keep the facts under a synthesis.** "Engineering capacity is constrained by the coordination
  needed to ship AI-generated code" can be traced to its evidence. "AI is transforming software
  delivery" cannot, so it is a buzzword.

## Edit by deciding, not by rewording

- **Deletion is the most common correct edit.** A sentence stays only if it makes the reader
  understand something.
- **Raise density with facts, not with length.** "Improves how feedback happens" carries one vague
  claim. "Each engineer gets monthly feedback from their project lead, and their manager combines
  it into one quarterly conversation" carries four facts. When a sentence feels thin, go back to the
  source and find the function, number, step or rule.
- **Cut packaging, keep content:** wind-ups, restatements, reassurance and the history of how a
  rule was learned. Keep the facts, boundary conditions and examples that show how a rule applies.
- **Cut a defensive "not X" half** when the reader would not have guessed X. Keep it when a reader
  from another tool would assume the wrong thing.
- **Measure last.** A length gate is a check on a finished draft. Writing to a cap produces text
  that passes and still says in three sentences what one carries. Work out the mechanism in full,
  then compress.

## If rules conflict

Check in this order: is it true, is it understandable, is it useful, does it match the voice, does
it satisfy a style preference. Style loses to clarity every time.

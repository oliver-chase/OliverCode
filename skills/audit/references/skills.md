# Skills

A skill, a family of skills or a whole skills folder. Read every `SKILL.md`, every reference, script, test and config in scope, and the README rows that describe them.

## The mechanical checks

Run these from this skill's folder before reading. Each scans every skill under `SKILL_FLEET_ROOT`, or the path given as an argument. A finding is a candidate to judge in context, and a phrase shared on purpose is not drift.

```bash
python3 scripts/check_skill_structure.py <path>            # a cited skill or file that does not exist
python3 scripts/check_skill_structure.py --weight <path>   # files, size, description words, unreferenced and uncalled files per skill
python3 scripts/check_skill_structure.py --routes <path>   # route rows that load more than 2,000 words for one task
```

A fleet with checks of its own runs them too. Its `<repo>/.githooks/pre-commit.local` names them.

## What to judge in each skill

- **Trigger and job.** Each phrase in the description has an operation in the body. Two skills that answer the same phrase overlap, so name which one keeps it
- **Words.** A sentence the model would follow anyway, a rule restated from its home, a hedge, or an example that only repeats the rule above it
- **Structure.** A route that loads a file it does not use, a reference that is one paragraph, two modes that overlap, a question no real user answers differently
- **Code.** A function with one caller, a wrapper that only forwards, a flag never set, an error path that cannot happen, a script nothing calls, a test that asserts a constant
- **Dedup.** Every path that writes the same record checks for an existing match the same way
- **Numbers.** Each threshold, cadence or cap cites where it came from
- **A missing connector.** Each skill that calls an optional connector has a real fallback: it prints the content to paste, skips the step and says so, or gives the manual step
- **Manual steps.** Each step a person does either could be automated or says why it stays manual
- **Output.** Each result names where it landed, in which format
- **Documentation.** Lens 8 for the skill: a person can learn from its own files what it does, how to start it, what it reads and writes and how it fails

## A session that just ran

When the request is about a task this session just ran, list its real tool calls in order. Flag duplicate calls, the wrong tool for a known path, an unbounded read, a retry loop with no stop, an unused result, and a switch to a costlier approach while the first still worked. Then name what the skill should have said and did not. An ended session's calls cannot be recovered, so ask the person to paste them.

## Before and after

Record these before the first fix and again after the last, in the story's comments:

```bash
python3 scripts/check_skill_structure.py --weight <path>
find <path> -name '*.md' | xargs wc -w | tail -1
find <path> -type f \( -name '*.py' -o -name '*.js' -o -name '*.sh' \) -not -name 'test_*' | xargs wc -l | tail -1
```

# Story template

Every story and epic body uses this format, and `skills/backlog/scripts/check_story_format.py` verifies it. Run `python3 scripts/check_story_format.py BODY_FILE` from this skill's folder, or pipe the body on stdin. The exit status is 1 when a part is missing, and each missing part prints with its fix.

## The format

A story body has five parts, in this order:

1. The user story sentence: `**As the <role>**, I want <the ask>, so that <the outcome>.`
2. Gherkin acceptance criteria in a `gherkin` fence: one `Feature:`, and one or more `Scenario:` blocks that each hold Given, When and Then lines (And and But continue a step)
3. The epic link on its own line: `Epic: #<number>`, or `Epic: <owner>/<repo>#<number>` for an epic in another repo
4. The fields on one line: `Priority: P0|P1|P2. Size: XS|S|M|L|XL. Work type: Story.`
5. Optional detail after the fields, such as the fit check from `SKILL.md` and a re-runnable audit command for an L or XL item

Name the role for the person who gets the outcome. The owner is `the owner`. Write each scenario so a second agent can QA the story from the criteria alone.

An epic body uses the same parts with `Work type: Epic`, no `Epic:` line, and a `**Stories, in order**` list of its stories.

## Worked example: a story

````markdown
**As the owner**, I want a failed nightly backup to message me the same day, so that I never find a gap in my backups by accident.

```gherkin
Feature: Backup failure alert
  Scenario: The nightly backup fails
    Given the nightly backup job ran and exited with an error
    When the job finishes
    Then the owner receives a message naming the failed step
    And the message arrives before 9am the same day

  Scenario: The nightly backup succeeds
    Given the nightly backup job ran and exited cleanly
    When the job finishes
    Then no message is sent
```

Epic: #50
Priority: P1. Size: S. Work type: Story.
````

## Worked example: an epic

````markdown
**As the owner**, I want every backup to run unattended and report its own failures, so that losing data requires two things to break at once.

```gherkin
Feature: Backups that watch themselves
  Scenario: A backup run completes
    Given the nightly backup is scheduled
    When it runs
    Then the result is recorded and any failure reaches the owner the same day
```

**Stories, in order**
1. Schedule the nightly backup
2. Alert the owner when a backup fails
3. Test a restore every month

Priority: P1. Size: M. Work type: Epic.
````

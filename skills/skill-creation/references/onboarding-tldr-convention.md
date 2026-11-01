# Onboarding TLDR Convention

Every setup, connect, or onboarding skill and mode follows this. It sets the shape and placement of the block a user sees before any question gets asked. Discovery rules (discover before asking, never repeat a probe, blank is legitimate) belong to the family that owns the setup.

## The opening block

Place it right after the `# <Skill Title>` heading, before the first Step or Phase:

1. One sentence: what this skill sets up.
2. A table with one row per input the skill asks about:

   | Input | If you have it | If you don't |
   |---|---|---|
   | <thing> | <what we do with it> | <what we build or ask instead> |

3. One closing line: every "if you don't" path is a real, working setup. Nothing here blocks starting.

## Questions that offer a default

State both real options as parallel choices. Never write "I'll create a blank one from the default template", because it hides the bring-your-own option.

- **"Do you have one to provide that I can build from?"** The user's own file becomes the starting point. A working config derived from a real non-template example is a third option. State it on its own.
- **The pre-configured default.** Never call it "blank". Say what it contains, such as the column list or the section headings.

## Static or live

- The skill already runs a probe before it asks anything, such as a connector check or a file search. The block reports what the probe found. It replaces or leads the probe's own status lines. Never print both.
- The skill has no probe. The block stays static text describing both paths. Do not add a connector call only to fill the block.
- A skill that asks a question before its status step moves the status step first.

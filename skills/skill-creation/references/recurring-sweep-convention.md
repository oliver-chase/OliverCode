# Recurring sweep convention

A skill that searches the same sources on every run (a tracker, an inbox pass, a status check) follows this. It keeps each run small and complete.

## Run state
- The skill saves the date of each source's last finished run inside the data it maintains, such as a sheet in the workbook it updates. State that lives in the person's own file follows the file.
- A run starts one day before the saved date. A message that landed late that day is covered, and the write commands skip what the data already holds.
- A source with no saved date starts a set number of days back. The number is a setting with a default.
- A source counts as finished only when every search ran and every result page was read. A source that did not finish keeps its old date, so the next run covers the span it missed.

## Search shape
- A search names a purpose, never a tool. The skill maps each purpose to whatever connector the person has.
- One query covers a group of known addresses when the connector accepts OR. A search by name follows each address search.
- A long list of people splits into batches. Each batch has an id built from the window start and a hash of its names. A script marks a batch when its report shows every page was read, so an interrupted run resumes on the batches not marked.
- Only one subagent runs at a time, per the fleet rule.

## Reading what the search returns
- A fact that names nobody, such as "send him the letter", gets its person from the thread, the same day's neighbouring messages and the calendar.
- A person who is promised a later step stays at the stage they hold, with a note of who referred them and what is expected.
- When the search still cannot answer, the skill asks one question with the evidence found beside it. A cell stays blank only after that question or the owner's word to keep it blank.

## Check before you ship
- A `check` or `plan` command prints the windows and batches, so the model never works them out.
- A test covers the window start, the batch ids and the resume. Remove each guard once and watch its test fail.

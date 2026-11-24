# Versioning

OliverCode has one version, MAJOR.MINOR.PATCH, held in `VERSION` and described in `CHANGELOG.md`. The version moves at most once per day of activity, and the daily cut decides every bump from this file with no owner step.

## How the version moves

`olivercode version-cut` (a launchd job runs it nightly, and `--schedule` installs the job) reads every commit that reached main since the previous cut and does one of two things:

- No commit since the previous cut makes no new version
- Any other run sets `VERSION` to the next number and writes that version's `CHANGELOG.md` section, headed with its date and grouped under each story its commits file under. A commit files under the `(#N)` at the end of its subject, or under the `Story: #N` line in its body when the subject has none. A commit with neither lands under "No story"

Each number counts up on its own and never rolls over, so 1.9.0 is followed by 1.10.0. A MAJOR bump zeroes MINOR and PATCH, and a MINOR bump zeroes PATCH. The first cut set 1.0.0, because OliverCode is in daily use.

No ordinary commit edits `VERSION` or `CHANGELOG.md`. The `version-files` commit gate refuses one, and only the cut, which sets `OLIVERCODE_VERSION_CUT=1` for its own commit, may write them.

## What each number means

The cut picks the highest level any commit since the previous cut reaches.

| Level | A story did this | Example |
|---|---|---|
| MAJOR | Removed or renamed a command, skill, gate, config key or file layout that a user or fleet repo relies on | A story removes `olivercode land`, or renames `docs/AUDITED.txt` |
| MINOR | Added a command, skill, gate or file the reader uses | A story adds `olivercode drain` or a new skill under `skills/` |
| PATCH | Only fixed or trimmed something that already existed | A story makes `olivercode land` retry a push, or shortens a message |

A cut does not hold a breaking change for a later cut. Every commit since the previous cut is read in the same run, so one MAJOR covers all of them. The CHANGELOG section states the reason for the MAJOR and holds an upgrade note for each breaking commit, taken from the `Upgrade:` line in the commit body when it has one.

## The rules the cut reads

The block below is the only rule list. The cut reads it as JSON, so an edit here changes the next cut. A commit counts as MAJOR only when it deletes or renames a file that matches a `major.paths` pattern, whatever its subject says. It counts as MINOR when its subject holds a `minor.words` entry or when it adds a file that matches a `minor.paths` pattern. Any other commit is PATCH. Patterns use shell wildcards, and a `*` crosses folders.

```cut-rules
{
  "major": {
    "paths": ["skills/*/SKILL.md", "core/hooks/gates/*", "scripts/lib/cmd_*.py", "docs/CONTRACT.md", "shared/*.json"]
  },
  "minor": {
    "words": ["add", "adds", "added", "brings back", "new"],
    "paths": ["skills/*/SKILL.md", "core/hooks/gates/*", "scripts/lib/cmd_*.py", "core/templates/project/*", "shared/*.json"]
  }
}
```

## Where the version shows

`olivercode health` keeps printing how many commits a checkout is behind upstream, and the `stable` tag still marks the last commit the owner confirmed. `VERSION` tells a reader which release a checkout holds, and `CHANGELOG.md` tells them what changed and what to do about a MAJOR.

The cut runs from the OliverCode engine, which reads `version_cut.py` from `core/templates/project/scripts/`. Fleet repos do not get the cut or the docs check, because both are engine-only tools. The version a checkout holds is the one in the engine's `VERSION`.

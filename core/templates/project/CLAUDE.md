> Framework rules (voice, practice, gates and skill placement) load on their own from
> `~/.claude/CLAUDE.md`, which links into OliverCode. To read a file in OliverCode, resolve its
> path with `dirname "$(readlink ~/.claude/CLAUDE.md)"`. This file holds only what is specific
> to this repo.

# <Repo> — Agent rules

Read before working here:
- <each document that is authoritative for this repo. List only files that exist. The convention is `docs/repo-structure-contract.md`, and `docs/backlog-config.json` when the repo has a GitHub Project.>

Run `bash scripts/validate.sh` before every commit. It is this repo's canonical validation.

Rules:
- An owner request that changes files is filed as a story with Gherkin criteria under an epic before work starts, per the `backlog` skill. A small change, as RULES.md "The backlog" defines it, needs no story and cites the open epic's number in its commit. There is no QA phase and no pull request: the builder makes a quick pass, runs validation, then commits, pushes and merges at the end of the work without being asked, and a different agent QAs only when the owner requests it

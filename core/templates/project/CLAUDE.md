> Framework rules (voice, practice, gates and skill placement) load on their own from
> `~/.claude/CLAUDE.md`, which links into OliverCode. To read a file in OliverCode, resolve its
> path with `dirname "$(readlink ~/.claude/CLAUDE.md)"`. This file holds only what is specific
> to this repo.

# <Repo> — Agent rules

Read before working here:
- <each document that is authoritative for this repo. List only files that exist. The convention is `docs/repo-structure-contract.md`, and `docs/backlog-config.json` when the repo has a GitHub Project.>

Run `bash scripts/validate.sh` before every commit. It is this repo's canonical validation.

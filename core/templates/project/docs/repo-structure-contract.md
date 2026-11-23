# Repo structure contract

Status: Active

## Canonical contract sources

1. `OliverCode/docs/RULES.md` ("Project structure")
2. `OliverCode/docs/CONTRACT.md`

## Profile

This repo uses the GitHub Project backlog profile. Its backlog is the GitHub Project named
in `docs/backlog-config.json`, read and written by the `backlog` skill.

## Required structure

1. Root docs:
- `README.md`
- `CLAUDE.md`
- `docs/repo-structure-contract.md`
2. Backlog:
- `docs/backlog-config.json` — the `backlog` skill's config for this repo's Project

## Branches

This repo works on `main`. If it needs a development or staging branch, name it here with
what moves through it.

## Enforcement

1. `bash scripts/validate.sh`, which also runs `npm run validate` when the repo has one

## Learning loop

Name the file or script behind each step, as `docs/CONTRACT.md` ("Learning loop") defines them.

- Record: <where each action is logged with its date, reason and metric>
- Read: <how the result is read after the review window>
- Compare: <the market or peer signal the result is checked against>
- Decide: <how a change is kept or reverted, and where the reason is logged>
- Thin data: <what the repo reports when there are too few readings>

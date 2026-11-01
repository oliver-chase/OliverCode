# No icons standard

Status: Active
Effective Date: 2026-05-22
Scope: ALL projects, ALL channels, ALL contributors. No exceptions.

## Rule

Zero emojis, icons, or decorative Unicode — anywhere: code, comments, commits, docs, PRs,
issues, chat, CLI output, config files. Plain text only. If text needs emphasis, use
structure (headings, lists, bold, italics), never icons. No override mechanism.

## Enforcement

Gate 2 (Icon/Emoji scan) of `.githooks/pre-commit` is the enforcement source of truth,
including the exact blocked Unicode ranges — not restated here, since a second copy of
that range list would just drift from the scanner's own. `governance-secrets-gate.yml`
(the CI template for downstream repos) does secret-filename gating only; it does not scan
for emoji.

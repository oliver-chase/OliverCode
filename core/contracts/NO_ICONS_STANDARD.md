# No Icons Standard

Status: Active
Effective Date: 2026-05-22
Scope: ALL projects, ALL channels, ALL contributors. No exceptions.

## Rule

**Zero emojis. Zero icons. Zero decorative Unicode.**

Plain text only. This is permanent and universal.

## Applies To

| Channel | Enforcement |
|---|---|
| Email (sent or received) | Zero emojis in subject lines, body text, signatures |
| Telegram messages | Zero emojis in any message, reply, or channel description |
| Documentation (all repos) | Zero emojis in markdown, code comments, READMEs, ADRs |
| Commit messages | Zero emojis in subject lines or bodies |
| Code comments | Zero emojis in inline comments, docstrings, JSDoc |
| PR descriptions and reviews | Zero emojis in titles, descriptions, or review comments |
| Issue titles and descriptions | Zero emojis |
| Slack / Discord / any chat | Zero emojis |
| CLI output and logs | Zero emojis |
| Configuration files | Zero emojis in YAML, JSON, TOML, .env files |

## Blocked Unicode Ranges

All emoji and decorative Unicode is blocked — emoticons, pictographs, transport/map
symbols, flags, dingbats, variation selectors, regional indicators, decorative geometric
shapes, and the like. The authoritative, exact range list is the emoji scanner in
`.githooks/pre-commit` (Gate 2: Icon/Emoji scan), which is the enforcement source of truth.

## Rationale

1. **Professionalism** — Emojis undermine the tone of serious business communication.
2. **Consistency** — Mixed emoji/text creates unpredictable rendering across devices and platforms.
3. **Searchability** — Emojis break grep, search, and automated analysis tools.
4. **Accessibility** — Screen readers handle emojis inconsistently; plain text is universally accessible.
5. **Version control hygiene** — Emojis in commit messages and code comments degrade diffs and blame views.

## Enforcement

1. **Pre-commit hooks** — Both public and private repo hooks block commits containing any emoji characters.
2. **CI gates** — GitHub Actions governance-secrets-gate includes emoji scanning.
3. **Review policy** — PR reviews flag and reject emoji-containing contributions.
4. **No exceptions** — This standard has no override mechanism. If text needs emphasis, use structure: headings, lists, bold, or italics — never icons.

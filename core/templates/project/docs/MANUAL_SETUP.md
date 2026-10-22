# Manual Setup

Fastest path for a new local checkout, after `README.md`'s load order has you reading
`docs/SETUP_MODES.md`:

1. Create local runtime env from `.env.example`
2. Keep real values in `.env.local` only
3. Keep private runtime artifacts in `.secrets/*`
4. Run `bash scripts/run-profile-checks.sh --profile local-runtime --mode repo-local`

## Private overlay workflow

Use `private-overlay` only when you need:
- mirrored runtime env values
- delegated tokens
- host scheduler wiring
- machine-specific private assets

In that mode:
- tracked docs stay generic
- `.env.example` stays placeholder-only
- local/private values stay out of git

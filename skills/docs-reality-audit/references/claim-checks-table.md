# Phase 3 — Claim-Type Check Table

Never trust a doc's inventory of itself. Check the filesystem directly:

| Claim type | Check against |
|---|---|
| Routes/pages exist | `find app -name "page.tsx"` (or framework equivalent) — not the doc's route table |
| Commands work | `package.json` `scripts` block |
| Env vars | `.env.example` + the config loader (e.g. `lib/config/env.ts`) that reads `process.env` |
| Migration/file counts | `ls <migrations-dir>` — count directly, don't trust a doc's "N migrations" claim |
| Design tokens/colors/fonts | The actual CSS/theme file's current contents, not a PRD or historical mockup |
| Cron/schedule claims | The actual scheduler config (`wrangler.toml`, CI YAML, crontab) — read its comments, they often record what was *tried and reverted* |
| CI/deploy steps described in docs | `.github/workflows/*.yml` — check that the doc's described steps match what the workflow actually runs |
| Story/ticket IDs in status tables | The actual story/ticket files — an ID scheme with zero matching files is fiction, however structured the table looks |
| "Required files" / "deliberately removed" lists | Check existence directly — these lists across different docs frequently contradict each other |

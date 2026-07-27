# Supabase & Cloudflare Keepalive Standard

Indexed in `docs/FEATURE_MAP.md`. The four template files this standard installs ship from
`core/templates/project/` via the `conditionalFiles` block of
`shared/project-bootstrap-manifest.json` — synced only into repos whose `keepalive` profile
block enables them, since a repo with no database has no use for a Supabase keepalive script:

| Template | Installed as | When |
|---|---|---|
| `core/templates/project/supabase/keepalive.sql` | `supabase/keepalive.sql` | `keepalive.supabase.enabled` |
| `core/templates/project/scripts/supabase-keepalive.js` | `functions/api/admin/keepalive.js` | Supabase keepalive on Cloudflare Pages |
| `core/templates/project/scripts/oc-supabase-keepalive.sh` | `scripts/oc-supabase-keepalive.sh` | Supabase keepalive with no Cloudflare deployment |
| `core/templates/project/scripts/cf-worker-keepalive.js` | reference only — paste the route into the worker's own `fetch` handler | `keepalive.cloudflare.enabled` |

## Problem

Serverless Postgres providers (Neon, Supabase) and free-tier Cloudflare resources
may pause or hibernate after periods of inactivity (typically 7+ days). This
standard codifies a lightweight keepalive mechanism for every Oliver repo that
uses Supabase or deploys to Cloudflare.

## Two Keepalive Patterns

### 1. Supabase DB Keepalive

**What it does:** Writes a row to `_keepalive_log` table every 15 minutes.
This generates a real database write, resetting any compute-hibernation timer.

**Prerequisites** (one-time per Supabase project):
- Run `core/templates/project/supabase/keepalive.sql` in the Supabase SQL editor
  (creates `_keepalive_log` table and index)

**How to wire per repo:**

| Deployment type | Mechanism | Where the endpoint lives | How it's triggered |
|---|---|---|---|
| Cloudflare Pages | CF Pages Function | `functions/api/admin/keepalive.js` | Cloudflare Dashboard → Cron Triggers → `*/15 * * * *` |
| Next.js (self-hosted) | Next.js API route | `app/api/admin/keepalive/route.ts` | External cron service |
| Scripted cron | Standalone bash script | `core/templates/project/scripts/oc-supabase-keepalive.sh` | crontab / external scheduler `0 */6 * * *` |

**Cloudflare Pages setup:**
1. Add the keepalive endpoint file (`functions/api/admin/keepalive.js`)
2. Go to Cloudflare Dashboard → Pages → `<project>` → Settings → Cron Triggers
3. Add trigger: Pattern `*/15 * * * *`, Endpoint `/api/admin/keepalive`

**Scripted cron setup** (for repos not deployed to Cloudflare):
```bash
# Make the wrapper script executable
chmod 755 core/templates/project/scripts/oc-supabase-keepalive.sh

# Register a crontab entry (every 6 hours). Provide the env vars inline or via the
# crontab environment; the script writes one _keepalive_log row per run.
0 */6 * * * SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
  /abs/path/to/core/templates/project/scripts/oc-supabase-keepalive.sh >> /abs/path/to/keepalive.log 2>&1
```

**Env vars required:**
```
SUPABASE_URL=<project-url>
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
KEEPALIVE_SOURCE=<repo-name>  # optional label for _keepalive_log.source column
```

### 2. Cloudflare Workers Keepalive

**What it does:** Adds a `GET /keepalive` endpoint to each worker and a
CF Cron Trigger that hits every 5 minutes. Also serves as a health check.

**To add to a new worker:**
1. Add the keepalive route at the top of the worker's `fetch` handler:
   ```js
   if (url.pathname === '/keepalive') {
     return new Response(JSON.stringify({ ok: true, ts: new Date().toISOString(), worker: 'worker-name' }), {
       headers: { 'Content-Type': 'application/json' },
     });
   }
   ```
2. Add `[triggers]` to the worker's `wrangler.toml`:
   ```toml
   [triggers]
   crons = ["*/5 * * * *"]
   ```
3. Deploy with `npx wrangler deploy`

### 3. Parked / Inactive Projects

For repos that are intentionally inactive:
- Keep the endpoint file present but returning a parked response
- Keep `wrangler.toml` `[[crons]]` commented out with clear instructions
- Set `keepalive.active: false` in `repo-profiles.json`

## Per-Repo Status

Each repo's actual keepalive configuration lives in its `keepalive` block in
`local/repo-profiles.json` (gitignored — see `docs/BACKLOG.md` G1) or, for a fresh
clone with no local fleet configured, `shared/repo-profiles.example.json`. That JSON
is the sole source of truth — no markdown table duplicates it here, since two copies
of the same fact drift independently and the JSON is already machine-readable.

## Adding a New Repo

When onboarding a new repo that uses Supabase:

1. Add `keepalive` block to the repo's entry in `local/repo-profiles.json` (gitignored, real fleet) or `shared/repo-profiles.example.json` (tracked placeholder)
2. If deployed to Cloudflare Pages: add `functions/api/admin/keepalive.js` from template
3. If deployed to Cloudflare Worker: add `/keepalive` route + `[triggers]` cron
4. If non-deployed: install `oc-supabase-keepalive.sh` as a crontab / external cron job
5. Ensure `_keepalive_log` table exists in the Supabase project
6. Configure the cron trigger (Cloudflare Dashboard or crontab)
7. Run the repo's canonical validation to confirm nothing broke

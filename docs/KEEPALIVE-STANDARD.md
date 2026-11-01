# Supabase & Cloudflare Keepalive Standard

Indexed in `docs/FEATURE-MAP.md`. The three template files this standard uses ship from
`core/templates/project/` and are listed in the `conditionalFiles` block of
`shared/project-bootstrap-manifest.json`. `olivercode bootstrap` prints each one with its
condition, and you copy it by hand into a repo whose `keepalive` profile block enables it,
since a repo with no database has no use for a Supabase keepalive script. No command reads
the `keepalive` block or copies these files for you:

| Template | Installed as | When |
|---|---|---|
| `core/templates/project/supabase/keepalive.sql` | `supabase/keepalive.sql` | `keepalive.supabase.enabled` |
| `core/templates/project/scripts/supabase-keepalive.js` | `functions/api/admin/keepalive.js` | Supabase keepalive on Cloudflare Pages |
| `core/templates/project/scripts/oc-supabase-keepalive.sh` | `scripts/oc-supabase-keepalive.sh` | Supabase keepalive with no Cloudflare deployment |
| (no file — the route below is the whole change) | paste into the worker's own `fetch` handler | `keepalive.cloudflare.enabled` |

## Problem

Serverless Postgres providers (Neon, Supabase) and free-tier Cloudflare resources
may pause or hibernate after periods of inactivity (typically 7+ days). This
standard codifies a lightweight keepalive mechanism for every governed repo that
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
     return new Response(JSON.stringify({ ok: true, ts: new Date().toISOString(), worker: env.KEEPALIVE_SOURCE || 'unnamed' }), {
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
- Set `keepalive.supabase.enabled` and `keepalive.cloudflare.enabled` to `false` in `repo-profiles.json`

## Per-Repo Status

Each repo's keepalive configuration lives in the `keepalive` block of its profile, and
`REGISTRY-PRIVATE-1` in `docs/DECISIONS.md` says which registry file holds the profiles. That JSON
is the sole source of truth — no markdown table duplicates it here, since two copies
of the same fact drift independently and the JSON is already machine-readable.

## Adding a New Repo

Follow the per-deployment-type steps above (Cloudflare Pages, Worker, or scripted cron),
add the repo's `keepalive` block per "Per-Repo Status" above, then run the repo's canonical
validation to confirm nothing broke.

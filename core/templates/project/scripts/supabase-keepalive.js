// Supabase Keepalive — Cloudflare Pages Function Template
//
// Writes a row to _keepalive_log to prevent serverless Postgres compute
// hibernation (Neon, Supabase) after 7+ days of inactivity.
//
// No auth — system-level operation. Triggered by Cloudflare Cron Trigger.
//
// Configure: Cloudflare Dashboard > Pages > project > Settings > Cron Triggers
//   Pattern: */15 * * * *
//   Endpoint: /api/admin/keepalive  (or /api/keepalive)
//
// Customize per repo: change 'source' default below to match the repo name.

export async function onRequestGet({ env }) {
  var url = env.SUPABASE_URL || env.NEXT_PUBLIC_SUPABASE_URL;
  var key = env.SUPABASE_SERVICE_ROLE_KEY;

  if (!url || !key) {
    return new Response(JSON.stringify({ ok: false, reason: 'not_configured' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  try {
    var source = env.KEEPALIVE_SOURCE || env.CF_PAGES_BRANCH || 'unnamed';
    var res = await fetch(url + '/rest/v1/_keepalive_log', {
      method: 'POST',
      headers: {
        'apikey': key,
        'Authorization': 'Bearer ' + key,
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal',
      },
      body: JSON.stringify({ source: source }),
    });

    return new Response(JSON.stringify({ ok: res.ok, ts: new Date().toISOString(), source: source }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: (e && e.message) || 'Unknown error', ts: new Date().toISOString() }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

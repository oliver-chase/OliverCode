"""City page (#1001): the organization, the live work and every open story as one self-contained HTML page.

`render(data, tokens)` turns the page data into HTML and calls nothing. `refresh_issues(slug, cache)` reads a repo's open issues over REST for the
30-minute rewrite and fetches only the issues whose updated time changed since the last read. It spends no GraphQL.

The data is a dict: `run` (None when idle, else repo, title, models, builders, finish, plan, building), `last_landed`, `repos` (name, slug,
description, pushed, activity, issues) and `landed` (number, title, repo, landed_at, commit, model). An issue carries number, title, priority,
status, body_html, updated_at and building.
"""

from __future__ import annotations

import html
import json
import re
import subprocess

DEFAULT_TOKENS = {
    "field": "#FFFFFF",
    "text": "#000000",
    "sub": "#475569",  # slate subheadings
    "line": "#CBD5E1",  # thin dividers and card outlines
    "highlight": "#C4A8FF",  # bright pastel lavender that leans blue, for fills, outlines and markers and never body text
    "serif": "'Fraunces', Georgia, 'Times New Roman', serif",
    "sans": "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
    "mono": "'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace",
}
FONTS_URL = "https://fonts.googleapis.com/css2?family=Fraunces:wght@600&family=Inter:wght@400;600&family=JetBrains+Mono:wght@400&display=swap"
TERMS = {  # one line each, shown as a tooltip wherever the term appears in the page's own words
    "round": "One pass of a builder over a story, ending in a commit or a stop.",
    "claim": "A builder marks a story as its own so no second builder takes it.",
    "gate": "A check that must pass before a commit or a landing goes through.",
}
SECTIONS = (("building", "Building now"), ("org", "Organization"), ("stories", "Open stories"), ("landed", "Landed"))
STYLE = """
:root{--field:%(field)s;--text:%(text)s;--sub:%(sub)s;--line:%(line)s;--hi:%(highlight)s;--serif:%(serif)s;--sans:%(sans)s;--mono:%(mono)s;
--s1:8px;--s2:16px;--s3:24px;--s4:40px;--tap:44px}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:72px}
body{margin:0;background:var(--field);color:var(--text);font:400 16px/1.6 var(--sans);overflow-x:hidden}
h1,h2,h3{font-family:var(--serif);font-weight:600;margin:0 0 var(--s2);overflow-wrap:anywhere}
h1{font-size:2rem}h2{font-size:1.5rem}h3{font-size:1.125rem}
.sub{color:var(--sub)}
code,.mono{font-family:var(--mono)}
main{max-width:1080px;margin:0 auto;padding:0 var(--s2) var(--s4)}
section{padding:var(--s3) 0}
nav{position:sticky;top:0;z-index:5;background:var(--field);border-bottom:1px solid var(--line);display:flex;gap:var(--s1);flex-wrap:wrap;padding:0 var(--s2)}
nav a,.top,.jump,summary{min-height:var(--tap);display:inline-flex;align-items:center}
nav a{padding:0 var(--s1);color:var(--text);text-decoration:none}
nav a:hover,nav a:focus{box-shadow:inset 0 -3px var(--hi)}
.card,.panel{border:1px solid var(--line);border-radius:8px;padding:var(--s2);background:var(--field)}
.live{border-color:var(--hi);border-width:2px}
.grid{display:grid;gap:var(--s2);grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr))}
ul{margin:0;padding-left:var(--s3)}
hr{border:0;border-top:1px solid var(--line);margin:var(--s2) 0}
.marker{display:inline-block;width:12px;height:12px;border-radius:50%;background:var(--hi);margin-right:var(--s1)}
.marker.pulse{animation:pulse 1.6s ease-in-out infinite}
@keyframes pulse{50%{transform:scale(1.6);opacity:.5}}
@media (prefers-reduced-motion:reduce){.marker.pulse{animation:none}html{scroll-behavior:auto}}
.root{display:inline-block;border:2px solid var(--text);border-radius:8px;padding:var(--s1) var(--s2);font:600 1.125rem var(--serif)}
.tree{display:flex;flex-direction:column;align-items:center}
.tree .stem{width:2px;height:var(--s3);background:var(--line)}
.tree .stem.hi{background:var(--hi)}
.branches{display:grid;gap:var(--s2);grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));width:100%;border-top:2px solid var(--line);padding-top:var(--s3);position:relative}
.branches.hi-line{border-top-color:var(--hi)}
.branches>details{position:relative}
.branches>details::before{content:"";position:absolute;left:50%;top:calc(-1 * var(--s3));width:2px;height:var(--s3);background:var(--line)}
.branches>details.live::before{background:var(--hi)}
@media (max-width:640px){.branches{border-top:0;padding-top:0}.branches>details::before{display:none}.tree .stem{display:none}.tree{align-items:stretch}}
details.card>summary{cursor:pointer;justify-content:space-between;gap:var(--s1);font-weight:600}
.row{border-bottom:1px solid var(--line)}
.row>summary{cursor:pointer;gap:var(--s2);flex-wrap:wrap}
.row.building>summary{box-shadow:inset 0 -3px var(--hi)}
.body{padding:var(--s2);overflow-x:auto;overflow-wrap:anywhere}
.body img,.body pre{max-width:100%}
.box{display:inline-block;width:16px;height:16px;border:2px solid var(--text);margin-right:var(--s1);vertical-align:middle;text-align:center;line-height:12px;font-size:12px}
.box.done{background:var(--hi)}
.jump{color:var(--text);border:1px solid var(--text);border-radius:8px;padding:0 var(--s2);text-decoration:none;background:var(--field);margin-top:var(--s1)}
.top{position:fixed;right:var(--s2);bottom:var(--s2);z-index:6;justify-content:center;min-width:var(--tap);border:2px solid var(--hi);border-radius:50%;background:var(--field);color:var(--text);text-decoration:none}
abbr[title]{text-decoration:underline dotted var(--sub);cursor:help}
"""


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def tip(text: str) -> str:
    """Wrap each glossary term in a tooltip. `text` is already escaped, so the terms are matched in escaped text."""
    pattern = re.compile(r"\b(" + "|".join(TERMS) + r")\b", re.IGNORECASE)
    return pattern.sub(lambda m: f'<abbr tabindex="0" title="{esc(TERMS[m.group(1).lower()])}">{m.group(1)}</abbr>', text)


def anchor(slug: str, number=None) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")
    return f"{base}-{number}" if number is not None else base


def banner(run, last_landed) -> str:
    if not run:
        tail = f" Last landed: #{esc(last_landed['number'])} {esc(last_landed['title'])}." if last_landed else ""
        return f'<section id="building"><h2>Building now</h2><div class="card"><span class="marker"></span>The runner is idle.{tail}</div></section>'
    building = run.get("building", [])
    plan = "".join(
        f'<li class="mono">{"<span class=marker></span><b>" if n in building else ""}#{esc(n)}{"</b>" if n in building else ""}</li>' for n in run.get("plan", [])
    )
    facts = (
        f"<li>Repo: {esc(run.get('repo'))}</li><li>Started by: {esc(run.get('title'))}</li>"
        f"<li>Models: {esc(', '.join(run.get('models', [])))}</li><li>Builders: {esc(run.get('builders'))}</li>"
        f"<li>Estimated finish: {esc(run.get('finish') or 'not yet estimated')}</li>"
    )
    return (
        f'<section id="building"><h2>Building now</h2><div class="card live"><p><span class="marker pulse"></span><b>Live</b></p>'
        f"<ul>{facts}</ul><hr><h3 class=\"sub\">Planned in order</h3><ol>{plan}</ol></div></section>"
    )


def org_chart(repos, run) -> str:
    active = run.get("repo") if run else None
    cards, hi = [], False
    for repo in repos:
        live = repo["slug"] == active or repo["name"] == active
        hi = hi or live
        cards.append(
            f'<details class="card{" live" if live else ""}"><summary><span>{esc(repo["name"])}</span>'
            f'<span class="mono">{len(repo.get("issues", []))} open</span></summary><hr><ul>'
            f"<li>{esc(repo.get('description') or 'No description')}</li><li>Last update: {esc(repo.get('pushed'))}</li>"
            f"<li>Last activity: {esc(repo.get('activity'))}</li></ul>"
            f'<a class="jump" href="#{anchor(repo["slug"])}">Open stories</a></details>'
        )
    return (
        f'<section id="org"><h2>Organization</h2><div class="tree"><div class="root">OliverCode</div><div class="stem{" hi" if hi else ""}"></div>'
        f'<div class="branches{" hi-line" if hi else ""}">{"".join(cards)}</div></div></section>'
    )


def stories(repos) -> str:
    out = ['<section id="stories"><h2>Open stories</h2>']
    for repo in repos:
        rows = []
        for i in repo.get("issues", []):
            body = i.get("body_html") or "<p>No description.</p>"
            rows.append(
                f'<details class="row{" building" if i.get("building") else ""}" id="{anchor(repo["slug"], i["number"])}"><summary>'
                f'<span class="mono">#{esc(i["number"])}</span><span>{esc(i["title"])}</span>'
                f'<span>{esc(i.get("priority"))}</span><span>{tip(esc(i.get("status")))}{" (building)" if i.get("building") else ""}</span></summary>'
                f'<div class="body">{body}</div></details>'
            )
        out.append(f'<div class="panel" id="{anchor(repo["slug"])}"><h3 class="sub">{esc(repo["name"])}</h3>{"".join(rows) or "<p>No open stories.</p>"}</div>')
    out.append("</section>")
    return "".join(out)


def landed(items) -> str:
    rows = "".join(
        f'<li><span class="box done" aria-hidden="true">&#10003;</span><a href="#{anchor(i["repo"], i["number"])}">#{esc(i["number"])} {esc(i["title"])}</a>'
        f'<ul><li>Landed {esc(i["landed_at"])}</li><li class="mono">{esc(i["commit"])}</li><li>Model: {esc(i["model"])}</li></ul></li>'
        for i in items
    )
    return f'<section id="landed"><h2>Landed</h2><div class="panel"><ul style="list-style:none;padding:0">{rows or "<li>Nothing landed yet.</li>"}</ul></div></section>'


def render(data: dict, tokens: dict | None = None) -> str:
    """The whole page. `tokens` (the owner's own, #995) override the defaults one key at a time."""
    style = STYLE
    for key, value in {**DEFAULT_TOKENS, **(tokens or {})}.items():
        style = style.replace(f"%({key})s", value)
    nav = "".join(f'<a href="#{key}">{esc(label)}</a>' for key, label in SECTIONS)
    repos = data.get("repos", [])
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>OliverCode City</title><link rel="stylesheet" href="{FONTS_URL}"><style>{style}</style></head><body id="page-top">'
        f'<nav aria-label="Sections">{nav}</nav><main><h1>OliverCode City</h1>'
        f"{banner(data.get('run'), data.get('last_landed'))}{org_chart(repos, data.get('run'))}{stories(repos)}{landed(data.get('landed', []))}</main>"
        '<a class="top" href="#page-top" aria-label="Back to top">&#8593;</a></body></html>'
    )


def gh(args, runner=None):
    return (runner or (lambda a: subprocess.run(["gh", "api"] + a, capture_output=True, text=True, timeout=60)))(args)


def refresh_issues(slug: str, cache: dict, runner=None) -> dict | None:
    """The repo's open issues keyed by number, fetching only those updated since the cache's newest `updated_at`. REST only, no GraphQL.
    `cache` maps number to the stored issue row and is returned updated, or None when the read fails. A first read has no `since` and takes all."""
    since = max((row.get("updated_at", "") for row in cache.values()), default="")
    args = ["-X", "GET", f"repos/{slug}/issues", "-f", "state=all", "-f", "per_page=100", "--paginate", "--slurp"]
    if since:
        args += ["-f", f"since={since}"]  # state=all so an issue closed since the last read leaves the cache
    done = gh(args, runner)
    if done.returncode != 0:
        return None
    try:
        rows = [r for page in json.loads(done.stdout or "[]") for r in (page if isinstance(page, list) else [page])]
    except ValueError:
        return None
    merged = dict(cache)
    for row in rows:
        if not isinstance(row, dict) or "pull_request" in row:
            continue
        if row.get("state") == "closed":
            merged.pop(row["number"], None)
        else:
            merged[row["number"]] = row
    return merged


def body_html(slug: str, text: str, runner=None) -> str:
    """An issue body rendered by GitHub's own markdown endpoint (REST), or the escaped text when the read fails."""
    done = gh(["-X", "POST", "markdown", "-f", f"text={text}", "-f", "mode=gfm", "-f", f"context={slug}"], runner)
    return done.stdout if done.returncode == 0 and done.stdout else f"<pre>{esc(text)}</pre>"

---
name: repo-discovery
description: "Use when the user says 'explore this repo', 'what does this codebase do', 'give me an overview of this repo', 'onboard me to this project', or opens work in an unfamiliar repo before making changes. Read-only: surface scan, entry points (README/CLAUDE.md/ARCHITECTURE.md), source tree, key files."
---

# Repo Discovery — Read-Only Repository Exploration

## Process

Sequential commands, path-scoping, raw output-first. Never edit during discovery.

### Step 1 — Surface Scan

```bash
ls <repo-root>
```

Identify top-level structure: config files (package.json, Cargo.toml, setup.py), directory layout, README presence.

### Step 2 — Entry Points

Look for:
- `README.md` — project description
- `AGENTS.md` or `CLAUDE.md` — agent instructions
- `ARCHITECTURE.md` — architecture doc
- `CONTRIBUTING.md` — contribution rules
- `package.json`, `Cargo.toml`, `go.mod`, `Gemfile` — language + dependencies
- `.env.example` or `.env.local.example` — env vars needed
- `Makefile`, `Justfile`, `Taskfile.yml` — build/run commands

### Step 3 — Source Tree

```bash
find <repo-root>/src -maxdepth 3 -type d | sort   # or app/, lib/, core/
```

Identify module boundaries. Read the key entry point file.

### Step 4 — Key File Scan

Read these if they exist:
- `scripts/` directory listing
- `docs/` directory listing
- Main entry point (index.js, main.py, main.rs, app.tsx, etc.)
- Test directory listing

### Step 5 — Summary

Produce a compact table:

| Aspect | Finding |
|--------|---------|
| Language | Node.js v20 / Python 3.11 |
| Entry | `scripts/bot.js` |
| Tests | `tests/` — jest |
| DB | Supabase (via REST) |
| Config | `.env.local.example` |
| Docs | `docs/bot-status.md`, `docs/bot-tests.md` |
| Orchestration | `AGENTS.md` exists |

## Pitfalls

- **Don't read every file.** Discover the structure first, then read what's relevant.
- **Don't modify anything** during discovery. Read-only pass.
- **If `find` returns nothing**, adjust paths. Not all repos use `src/`.
- **If no README**, check for any `.md` file at root.

---

> Authored 2026-06-12.

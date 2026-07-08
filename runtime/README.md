# runtime/

The heavy, gitignored, per-machine local-state system (`control-plane/`) — not
tracked, not part of what a fresh clone gets. See `docs/FRAMEWORK_BOUNDARY.md`.

Agent activation does not live here: `~/.claude/CLAUDE.md` symlinks to this
repo's root `CLAUDE.md`, and `~/.claude/skills/` symlinks to `skills/` — see
`ARCHITECTURE.md` ("How Activation Works").

# runtime/

The heavy, gitignored, per-machine local-state system (`control-plane/`) — not
tracked, not part of what a fresh clone gets. See `docs/FRAMEWORK-BOUNDARY.md`.

Agent activation does not live here: `~/.claude/CLAUDE.md` symlinks to this
repo's root `CLAUDE.md`, and each skill in `skills/` gets its own symlink inside the real
`~/.claude/skills/` folder — see
`ARCHITECTURE.md` ("How activation works").

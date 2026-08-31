# OliverCode Launcher Contract

Current lightweight launcher surface:
- `olivercode bootstrap <repo-path> [--dry-run]` — stamps the project template into a repo per `shared/project-bootstrap-manifest.json`, creating its required directories. Honours the manifest's modes: `strict` files are overwritten (byte-identity is their contract), `presence` files only created when missing, so repo-specific content is never clobbered. `conditionalFiles` are reported rather than copied. `--dry-run` shows the plan and writes nothing.
- `olivercode discover --root DIR [--root DIR ...]` — read-only scan for git repos under the given roots, reporting each one's agent-rules filename and hook state, and inventorying `~/.claude` (skills linked here vs elsewhere vs real dirs vs broken), and emitting a `local/repo-profiles.json` skeleton with explicit `path` values. Excludes the OliverCode checkout itself — the framework governs the fleet, it is not part of it. The mechanical form of `docs/ADOPTING.md` Step 1, for adopting into a setup whose layout you do not already know by heart.
- `olivercode install` — symlinks this checkout's `CLAUDE.md` and every skill into `~/.claude`, creating the directory if absent. Never destructive: a real file at a target path is moved to `<name>.pre-olivercode` and the path printed, since that file is usually the operator's whole existing ruleset. Idempotent.
- `olivercode init` — seeds the gitignored `local/` overlay from the tracked example registries. Never overwrites an existing `local/` file, so it is safe to re-run; this is the first command a fork runs (`docs/ADOPTING.md`).
- `olivercode link-plugins [--dry-run]` — symlinks every plugin in the vault's `_Plugins/` into `~/.claude/plugins/`, the only directory Claude Code discovers plugins in. `install` covers `~/.claude/skills` and never touched this, so the links were made by hand and nothing would recreate them on another machine. Replaces a stale or broken link; never overwrites a real directory.
- `olivercode health [--root DIR]` — dependency/entrypoint/placement-drift checks (SYS-2), plus the topology checks: plugin links, remote reachability, tracked-file size against GitHub's 100MB limit, and each folder-level `_validate_structure.js`
- `olivercode update` — `git pull`, then runs `sync-hooks`
- `olivercode sync-hooks [--root DIR]` — converges pre-commit hooks + `core.hooksPath` across the fleet and vault (SYS-3); also runs automatically at the end of `update`
- `olivercode skills [--grep TERM]` — lists OliverCode's own orchestration skills under `skills/` (name + description, read from each `SKILL.md`'s frontmatter directly, never from a hand-maintained copy); `--grep` filters by name or description.

`--root DIR` overrides where fleet repos are looked for. The default is the parent of the
OliverCode checkout (the sibling layout). A fork whose repos live elsewhere needs it, and
without it every repo silently reports as "not present on this machine".

Unknown arguments are rejected with a nonzero exit rather than ignored. Silently ignoring
one is a wrong success: `sync-hooks --root /elsewhere` used to ignore the flag, sync the
default fleet, and report that it had worked.

The launcher invokes nothing outside this repo, and there are no hardcoded
vault/home/container paths — every path derives from the launcher's own
location (`__file__`).

Verification:
```bash
python3 scripts/olivercode --help
python3 scripts/olivercode health
python3 scripts/olivercode bogus || true
```

The launcher is intentionally small -- these 8 commands are the entire surface. The copy at
`runtime/control-plane/olivercode` (present only when the local control plane is installed)
is a thin shim that delegates to this same CLI; it carries no additional commands.

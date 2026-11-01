# OliverCode Launcher Contract

Current lightweight launcher surface:
- `olivercode bootstrap <repo-path> [--dry-run]` — stamps the project template into a repo per `shared/project-bootstrap-manifest.json`, creating its required directories. Honours the manifest's modes: `strict` files are overwritten (byte-identity is their contract), `presence` files only created when missing, so repo-specific content is never clobbered. `conditionalFiles` are reported rather than copied. `--dry-run` shows the plan and writes nothing.
- `olivercode discover --root DIR [--root DIR ...]` — read-only scan for git repos under the given roots, reporting each one's agent-rules filename and hook state, and inventorying `~/.claude` (skills linked here vs elsewhere vs real dirs vs broken), and emitting a `shared/repo-profiles.json` skeleton with explicit `path` values. Excludes the OliverCode checkout itself — the framework governs the fleet, it is not part of it. The mechanical form of `docs/ADOPTING.md` Step 1, for adopting into a setup whose layout you do not already know by heart.
- `olivercode install` — symlinks this checkout's `CLAUDE.md`, its `docs/VOICE.md` (as `~/.claude/VOICE.md`, which `CLAUDE.md` imports) and every skill into `~/.claude`, creating the directory if absent. It also merges OliverCode's three Claude Code hooks into `~/.claude/settings.json` and leaves every other key alone (`core/contracts/EXECUTION_CONTRACT.md` "Session Hooks"). Never destructive: a real file at a target path is moved to `<name>.pre-olivercode` and the path printed, since that file is usually the operator's whole existing ruleset. Idempotent.
- `olivercode health [--root DIR]` — dependency/entrypoint/placement-drift checks (SYS-2), plus the Claude Code hook entries in `~/.claude/settings.json` and the topology checks: skill links, voice copies (each installed suite's `docs/VOICE.md` must match this repo's), remote reachability, and tracked-file size against GitHub's 100MB limit. A repo, private repo or control plane that is not on this machine is noted once and not counted
- `olivercode update` — `git pull`, then runs `sync-hooks`
- `olivercode sync-hooks [--root DIR]` — converges pre-commit hooks + `core.hooksPath` across the fleet and the private repos (SYS-3). Also runs automatically at the end of `update`
- `olivercode audit-fleet` — runs `skill-fleet-audit`'s 3 static checks (structure, MCP patterns, clarity) against 2 roots: this machine's skills folder (`skillsRoot`) and OliverCode's own `skills/`. Non-interactive, writes findings to a log, never fixes anything. `scripts/local-scheduler/` can run it on a `launchd` schedule, but that's opt-in -- run `bash scripts/local-scheduler/install.sh` to turn it on; nothing installs it automatically.
- `olivercode push-fleet [--dry-run]` — pushes already-committed work, unattended, for OliverCode, each repo in `privateRepos` and each repo named in `pushRepos`. Never commits anything; skips and reports a repo with uncommitted changes or no upstream tracking branch. Each repo's own pre-push hook is the real safety gate.
- `olivercode skills [--grep TERM]` — lists OliverCode's own orchestration skills under `skills/` (name + description, read from each `SKILL.md`'s frontmatter directly, never from a hand-maintained copy). `--grep` filters by name or description.

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

The launcher is intentionally small -- the commands above are the entire surface. The copy at
`runtime/control-plane/olivercode` (present only when the local control plane is installed)
is a thin shim that delegates to this same CLI. It carries no additional commands.

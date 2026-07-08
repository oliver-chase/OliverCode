# OliverCode Launcher Contract

Current lightweight launcher surface:
- `olivercode health` — dependency/entrypoint/placement-drift checks (SYS-2)
- `olivercode update` — `git pull`, then runs `sync-hooks`
- `olivercode sync-hooks` — converges pre-commit hooks + `core.hooksPath` across the fleet and vault (SYS-3); also runs automatically at the end of `update`
- `olivercode skills [--grep TERM]` — lists OliverCode's own orchestration skills under `skills/` (name + description, read from each `SKILL.md`'s frontmatter directly, never from a hand-maintained copy); `--grep` filters by name or description.

OliverCode has no external runtime dependency. The launcher invokes no
external agent-runtime/docker infrastructure, and there are no hardcoded
vault/home/container paths — every path derives from the launcher's own
location (`__file__`).

Verification:
```bash
python3 scripts/olivercode --help
python3 scripts/olivercode health
python3 scripts/olivercode bogus || true
```

The launcher is intentionally small -- these 4 commands are the entire surface. The copy at
`runtime/control-plane/olivercode` (present only when the local control plane is installed)
is a thin shim that delegates to this same CLI; it carries no additional commands.

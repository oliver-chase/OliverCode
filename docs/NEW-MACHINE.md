# Rebuilding on a New Machine

Status: Active
Purpose: the order to restore this setup from nothing, and which steps no script can do.

`docs/ADOPTING.md` covers adopting OliverCode into a machine that already has work on it.
The other case, a blank machine restoring an existing setup from its remotes, is covered here.

Restoring starts at OliverCode. The fleet repos clone beside it, and this machine's own paths
go in one local file, so nothing tracked has to match this machine's folders.

---

## Order

- OliverCode comes first, because its `CLAUDE.md` holds the rules every session loads
- the fleet registry lives in a private repo under `olivercode/`, so it comes back with that
  repo's clone once `olivercode.local.json` names the repo under `privateRepos`
- the private repos, the skills folder and any repo outside the fleet folder are per machine, so they
  are named in `olivercode.local.json` before `sync-hooks` and `health` run

Clone OliverCode and each fleet repo side by side in one folder, then copy
`olivercode.local.example.json` to `olivercode.local.json` and fill in this machine's paths.
The rest follows `docs/ADOPTING.md`: Step 0 proves the clone, Step 2 runs `install`, Step 6
installs enforcement and Step 7 proves a gate blocks. Steps 1, 3, 4 and 5 are already done,
because the rules and the registry come back with the clones.

`health` is the checkpoint, and it must end HEALTHY. A registered repo that is not cloned here
is listed once and is not a failure.

---

## What no script restores

Each of these needs a person. They are listed so the list is finite rather than remembered.

**The other repos.** Each fleet repo is its own clone under `<fleet-root>/`.
`scripts/olivercode discover --root <dir>` finds whatever is present. It cannot clone what is
absent. The private repo's `olivercode/repo-profiles.json` lists what should be there.

**Marketplace plugins.** Third-party plugins are installed through Claude Code, not through this
repo. `docs/EXTERNAL-TOOLING.md` lists each one and what it is for.

**Obsidian plugins.** The vault tracks each plugin's `data.json` and `manifest.json`, so
settings come back with the clone. The compiled code does not. `.obsidian/community-plugins.json`
lists what to reinstall from the community store.

**MCP server authorization.** Interactive OAuth per server, in a Claude Code session.

---

## Verifying the restore

```bash
scripts/olivercode health        # HEALTHY, and the five topology checks pass
bash scripts/validate.sh         # gates, doc consistency, references, tests
bash scripts/qa/check-scenarios.sh   # the setup walkthroughs, in disposable sandboxes
```

A restore is finished when `health` is HEALTHY, a planted secret is refused by a real commit,
and a skill from each plugin is invocable as `/<plugin>:<skill>`.

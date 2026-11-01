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

```bash
# 1. OliverCode and the fleet repos, side by side in one folder (the fleet root)
git clone https://github.com/<owner>/OliverCode.git && cd OliverCode
OC="$(pwd)"                       # kept for step 5, run after cd-ing away
bash scripts/validate.sh          # the clone is sound before anything is changed

# 2. This machine's paths. Leave out what this machine does not have.
cp olivercode.local.example.json olivercode.local.json   # then edit it

# 3. Activate OliverCode: rules and skills into ~/.claude
scripts/olivercode install        # links CLAUDE.md, VOICE.md + skills, adds the hooks, backs up what it replaces

# 4. Confirm the fleet, then install enforcement
scripts/olivercode discover --root ../          # confirms what's present vs. the registry
scripts/olivercode sync-hooks
scripts/olivercode health                       # must end HEALTHY

# 5. Prove a gate blocks, rather than assuming it
cd <any governed repo>
bash "$OC/scripts/qa/probe-secret-gate.sh"    # writes a fake secret, commits, expects a block
```

`health` at step 4 is the checkpoint. It verifies the skill links, that every remote actually
resolves and that no tracked file exceeds GitHub's 100MB limit. A registered repo that is not
cloned here is listed once and is not a failure.

The keys `olivercode.local.json` takes are listed in `docs/ADOPTING.md`.

---

## What no script restores

Each of these needs a person. They are listed so the list is finite rather than remembered.

**The other repos.** Each fleet repo is its own clone under `<fleet-root>/`.
`scripts/olivercode discover --root <dir>` finds whatever is present. It cannot clone what is
absent. `shared/repo-map.json` is the tracked list of what should be there.

**Marketplace plugins.** Third-party plugins are installed through Claude Code, not through this
repo. `docs/EXTERNAL-TOOLING.md` lists each one and what it is for.

**OliverCode's own session hooks.** `olivercode install` writes them into
`~/.claude/settings.json`. `core/contracts/EXECUTION_CONTRACT.md` ("Session Hooks") says what each does.

**Obsidian plugins.** The vault tracks each plugin's `data.json` and `manifest.json`, so
settings come back with the clone. The compiled code does not. `.obsidian/community-plugins.json`
lists what to reinstall from the community store.

**MCP server authorization.** Interactive OAuth per server, in a Claude Code session.

---

## Verifying the restore

```bash
scripts/olivercode health        # HEALTHY, and the four topology checks pass
bash scripts/validate.sh         # gates, doc consistency, references, tests
bash scripts/qa/check-scenarios.sh   # the setup walkthroughs, in disposable sandboxes
```

A restore is finished when `health` is HEALTHY, a planted secret is refused by a real commit,
and a skill from each plugin is invocable as `/<plugin>:<skill>`.

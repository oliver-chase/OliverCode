# Rebuilding on a New Machine

Status: Active
Purpose: the order to restore this setup from nothing, and which steps no script can do.

`docs/ADOPTING.md` covers adopting OliverCode into a machine that already has work on it.
This file covers the other case: a blank machine, restoring an existing setup from its remotes.

The two differ in one way that matters. Adopting starts at OliverCode. Restoring starts at the
**vault**, because the vault holds the plugins and OliverCode is a submodule inside it.

---

## Order, and why it is this order

The pieces reference each other in both directions, so the sequence is not obvious and getting
it wrong leaves things half-wired:

- the vault holds `_Plugins/`, so the vault must exist before plugins can be linked
- OliverCode is a submodule *of* the vault, so it arrives with the vault or not at all
- the vault's `CLAUDE.md` points *at* OliverCode, so OliverCode must be installed for a
  session in the vault to load its rules
- `local/` is gitignored, so no clone brings the fleet config -- it is rebuilt, not restored

```bash
# 1. The vault, with the OliverCode submodule
git clone --recurse-submodules https://github.com/<owner>/vault.git "Obsidian Vault"
cd "Obsidian Vault"

# 2. Activate OliverCode: rules and skills into ~/.claude
cd "Oliver/Project Repos/OliverCode"
OC="$(pwd)"                       # kept for step 5, run after cd-ing away
bash scripts/validate.sh          # the clone is sound before anything is changed
scripts/olivercode install        # symlinks CLAUDE.md + skills, backs up what it replaces
scripts/olivercode init           # seeds local/ from the tracked examples

# 3. The plugins. Nothing else does this step.
scripts/olivercode link-plugins

# 4. Register the fleet, then install enforcement
scripts/olivercode discover --root ../          # writes a profile skeleton to paste into local/
#   ... paste into local/repo-profiles.json, add each repo's canonicalValidationCommand
scripts/olivercode sync-hooks
scripts/olivercode health                       # must end HEALTHY

# 5. Prove a gate blocks, rather than assuming it
cd <any governed repo>
bash "$OC/scripts/qa/probe-secret-gate.sh"    # writes a fake secret, commits, expects a block
```

`health` at step 4 is the checkpoint. It verifies the plugin links, that every remote actually
resolves, that no tracked file exceeds GitHub's 100MB limit, and that each folder-level
`_validate_structure.js` exits clean -- the four things that previously rotted silently.

---

## What no script restores

Each of these needs a person. They are listed so the list is finite rather than remembered.

**The other repos.** The vault deliberately holds only what is not already its own repo, so
the rest are separate clones under `Oliver/Project Repos/` plus `Oliver/Automation Assets/`.
`scripts/olivercode discover --root <dir>` finds whatever is present; it cannot clone what is
absent. `local/repo-map.json` in the old machine's config is the list of what should be there.

**The fleet config in `local/`.** Gitignored on purpose -- real repo names never enter tracked
files, which is what makes the fork shareable. `init` creates the files from tracked examples;
the real contents are re-entered. Copy `local/` off the old machine if it still exists.

**Marketplace plugins.** Third-party, installed through Claude Code, not through this repo:

```
/plugin marketplace add fivetaku/fablize        then  /plugin install fablize
/plugin marketplace add JuliusBrussee/caveman   then  /plugin install caveman
```

`docs/EXTERNAL-TOOLING.md` explains what each is for and why some rules in `CLAUDE.md` read as
arbitrary without them.

**Obsidian plugins.** The vault tracks each plugin's `data.json` and `manifest.json`, so
settings come back with the clone; the compiled code does not. `.obsidian/community-plugins.json`
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

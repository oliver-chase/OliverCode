# Public / Private Repository Standard

Status: Active
Effective Date: 2026-05-23
Scope: Every downstream repository under `Oliver/Project Repos/` that consumes OliverCode's
templates. Does not apply to OliverCode itself -- OliverCode is the standard-setter, not a
consumer of its own downstream template (`docs/SETUP_MODES.md`'s own text, "this repo uses
the OliverCode public/private boundary standard," would be circular applied to OliverCode's
own root). OliverCode's equivalent surfaces are `INSTALL.md`, `README.md`'s Quick Start, and
`local/` + `runtime/control-plane/` for its own local/private state.

## Goal
Every repo must separate:
- public tracked contract surface
- local runtime surface
- private operator overlay surface

Any repo with the full split profile serves as the reference implementation for this separation. Other repos may use simpler profiles, but they must keep the same boundary model.

## Required concepts
1. Installation profile and runtime mode are separate concepts.
2. Public repos own code, docs, templates, validators, and bootstrap entrypoints.
3. Private overlays own `.env.local`, `.secrets/*`, delegated tokens, `.runtime/`, per-agent OS state (e.g. `.claude-optimization/memory/`, `.claude-optimization/state/`), host scheduler wiring, and machine-specific state.
4. `.env.example` is placeholder-only and tracked.
5. `.env.local` is local-only and ignored.
6. `.secrets/README.md` is tracked. Other `.secrets/*` files are ignored.
7. README must link to canonical setup docs.
8. Each repo must provide:
   - `docs/SETUP_MODES.md`
   - `docs/MANUAL_SETUP.md`
   - `scripts/bootstrap-profile.sh`
   - `scripts/run-profile-checks.sh`

## Minimum standard profiles
Repos may extend these profiles, but they must support this baseline vocabulary:
- `repo-contract-only`: tracked code/docs/contracts only
- `local-runtime`: local runnable checkout using `.env.local`
- `private-overlay`: machine-specific/private runtime overlay

## Minimum runtime modes
- `repo-local`: repo-only validation without assuming vault/private runtime state
- `vault-integrated`: private integrated runtime with mirrored env and host wiring

## Validation contract
`scripts/run-profile-checks.sh` must, at minimum:
1. verify tracked setup files exist
2. verify `.env.example` exists
3. verify `.env.local` exists for `local-runtime` and `private-overlay`
4. verify `.secrets/README.md` exists for `private-overlay`
5. run repo-native hygiene validation when available

## Git hygiene contract
Repos must ignore at least:
- `.env.local`
- `.secrets/*`
and must re-include:
- `!.secrets/README.md`

## Standardization source
Canonical template files live in `OliverCode/core/templates/project/`. Apply them manually;
hooks specifically are converged by `scripts/olivercode sync-hooks`.

## Public-repo redaction
A public/shared repo describes the PATTERN, not your implementation. Never commit:
- Project names — use `[project-name]` placeholders
- Host paths — use `~/Documents/Obsidian Vault/`
- Personal identifiers, shell aliases, machine-specific configs
- Enumeration matching your actual project count

`repo-map.json` shows project PROFILES (governance templates), not actual projects — max two examples.

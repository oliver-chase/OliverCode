# OliverCode

A git-tracked governance framework for Claude Code: commit gates, contracts, and skills that load automatically in every repo you work in.

Two problems drive its design.

**An agent only follows rules it can see.** Rules files not named exactly `CLAUDE.md` never load. Rules living in one repo are absent in the next. A convention explained in chat is gone next session.

So everything here loads without being asked for — one symlink puts the same rules and skills into every session on the machine, and what must always hold is a git hook, not a hope.

**Hook enforcement fails open.** If `core.hooksPath` is unset, points at a missing directory, or the hook is not executable:

- git runs no hooks
- git prints nothing
- a commit carrying an API key simply succeeds

Most of this framework's checking exists to make that silence loud.

---

## Install

```bash
git clone <your-fork> OliverCode && cd OliverCode
bash scripts/validate.sh              # must pass on a bare clone — no config, no local/
scripts/olivercode install            # symlinks CLAUDE.md + skills into ~/.claude
scripts/olivercode init               # seeds local/ fleet config from tracked examples
```

A failure on a clean clone is a bug in the fork, not your machine.

Requirements: `python3`, `git`, `bash`, `perl` — nothing to install, no language dependencies. macOS verified (BSD userland, Bash 3.2); Linux should work, untested; Windows needs WSL.

**The faster path:** open the clone in Claude Code and say *"set up OliverCode for my machine"*. The `olivercode-adoption` skill ships project-level — available before anything is installed — and drives the whole onboarding, asking only the decisions that need you.

Nothing here destroys what you had:

- `install` backs up an existing `~/.claude/CLAUDE.md` to `CLAUDE.md.pre-olivercode` and prints the path
- `init` never overwrites an existing file
- both are safe to re-run

---

## How a repo becomes governed

Each step exists because the one before it is not enough on its own:

1. **Register the repo** in `local/repo-profiles.json` — `init` seeds it, `discover` emits a paste-ready profile per repo it finds. Repos need not share a parent; a profile's `path` reaches anywhere.
2. **`scripts/olivercode sync-hooks`** writes the gates into every registered repo. Read its per-repo lines: a repo reported as skipped is a repo it did not govern.
3. **Prove it blocks.** Stage a fake secret, watch the commit refuse. Installed and enforcing are different claims; `docs/ADOPTING.md` ends on this probe.
4. **`scripts/olivercode health`, on a schedule.** Nothing else detects a hook that quietly stopped applying.

An adopted repo gets six gates: secrets, emoji/icons, PII, deleted-repo references, workflow push-auth, planning-doc governance.

OliverCode runs two more on itself — contract integrity and token policy — that validate framework-only files. `docs/GOVERNANCE.md` holds the coverage table and the `hookVariant` escape hatch for a repo that must diverge.

---

## What you get

**On every commit, in every governed repo** — the gates. They fire whether or not anyone read the documentation, and cannot be skipped without `--no-verify`.

**In every Claude Code session, from any directory** — your `CLAUDE.md` rules and the full skill set, via `~/.claude` symlinks.

**When you run `bash scripts/validate.sh`** — doc/code consistency, reference integrity, the test suite, the fleet hook report. Fails closed on the first three.

**When you stamp a new repo** — `scripts/olivercode bootstrap` writes the project template per `shared/project-bootstrap-manifest.json`. Run `--dry-run` first; it shows every file it would touch.

---

## Three design decisions

### Only the hook is trusted to enforce

Contracts, templates, and skills are instruction text. An agent follows them because they load — a weaker guarantee than a gate that blocks.

The framework never blurs the two. `CONTRIBUTING.md`'s "Enforcement Reality" section lists which is which, and anything that must always hold is a hook, not a rule. When a finding class recurs, it becomes a check.

### Checks must be able to fail

The recurring defect in governance tooling is the check that reports success it never earned: a counter compared but never incremented, a scan that silently skips when its tool is missing, a "PASS" printed over an empty set.

`scripts/lib/falsifiability_check.py` hunts that shape mechanically. The test suite proves each checker by mutation — break the thing, assert the checker notices. A green result here means something was actually examined.

### Personal data never enters the tracked layer

Real fleet names, paths, and machine state live in gitignored `local/` and `runtime/`. Tracked files carry placeholders.

That split is enforced, not asked for: a consistency check reads your real repo names from the gitignored config — and from the sibling repos on disk — and fails the build if one appears in a tracked file. `scripts/qa/check-fork-usable.sh` proves a stranger's clone works with nothing of yours present.

---

## Verifying the whole story

```bash
bash scripts/qa/check-fork-usable.sh   # fast gate: clone works, adoption governs, gates block
bash scripts/qa/check-scenarios.sh     # exhaustive: 12 sandboxed setup scenarios
bash scripts/qa/full-qa-pass.sh        # code quality, docs cohesion, bloat, fork usability
```

The scenario matrix walks every documented setup shape in an isolated sandbox with a throwaway HOME — fresh machine, existing `~/.claude`, scattered fleets, wrong `--root`s, the full backout.

Every assertion maps to a sentence in the docs. When one fails, either the code or that sentence is lying.

---

## Documentation

| | |
|---|---|
| **[ADOPTING.md](docs/ADOPTING.md)** | Fork to governed fleet, step by step, ending in proof the gates block |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | The three layers, activation, dependency direction |
| **[GOVERNANCE.md](docs/GOVERNANCE.md)** | Every gate, what it blocks, per-repo coverage table |
| **[FEATURE_MAP.md](docs/FEATURE_MAP.md)** | Every capability mapped to its one owning doc — machine-checked |
| **[OLIVERCODE_LAUNCHER.md](docs/OLIVERCODE_LAUNCHER.md)** | The `olivercode` command surface |
| **[DOCUMENTATION_STANDARD.md](docs/DOCUMENTATION_STANDARD.md)** | The locked structure, voice, and naming for all docs, here and downstream |
| **[TOKEN_POLICY.md](docs/TOKEN_POLICY.md)** | What Gate 8 validates |
| **[SKILLS-PLACEMENT.md](docs/SKILLS-PLACEMENT.md)** | Where any new skill or agent file goes |
| **[FRAMEWORK_BOUNDARY.md](docs/FRAMEWORK_BOUNDARY.md)** | What this deliberately excludes |
| **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** | Symptom-first fixes, starting with gates that should have blocked |
| **[EXTERNAL-TOOLING.md](docs/EXTERNAL-TOOLING.md)** | Optional third-party plugins the posture assumes |
| **[KEEPALIVE_STANDARD.md](docs/KEEPALIVE_STANDARD.md)** | Supabase/Cloudflare keepalive contract |
| **[BACKLOG.md](docs/BACKLOG.md)** | Open work — read before assuming a capability exists |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | Enforcement Reality: what blocks vs what merely loads |
| **[QUALITY_BASELINE.md](QUALITY_BASELINE.md)** | The standard a governed repo is held to |
| **[CLAUDE.md](CLAUDE.md)** | The agent rules that load in every session |
| **[skills/INDEX.md](skills/INDEX.md)** | Catalog of every skill that ships |
| **[Contracts](core/contracts/)** | Structure, execution, hygiene, intent, file-location standards |
| **[Workflows](core/workflows/)** | Repeatable cross-repo procedures |
| **[Claude OS](.claude-optimization/README.md)** | Standalone memory/state layer |

## Status

`python3 -m unittest discover tests` is the test count and its result — the suites include mutation tests that prove the checkers can fail.

8 pre-commit gates on this repo;
an adopted repo receives six of those. Both counts are machine-verified against the hook files by `validate.sh`, so they cannot silently rot here.

`bash scripts/qa/check-scenarios.sh` is the setup matrix and prints its own tally. Pure `python3` + `bash` + `perl`, no package dependencies. macOS verified; CI ships ready and is enabled per fork.

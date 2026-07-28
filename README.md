# OliverCode

A git-tracked governance framework for Claude Code: commit gates, contracts, and skills that load automatically in every repo you work in.

Two problems drive its design.

An agent only follows rules it can see. Rules files that are not named exactly `CLAUDE.md` never load; rules living in one repo are absent in the next; a convention explained in chat is gone next session. So everything here loads without being asked for — one symlink puts the same rules and skills into every Claude Code session on the machine, from any working directory, and what must always hold is enforced by git hooks rather than by hoping the text was read.

The second problem is that hook enforcement fails open. If `core.hooksPath` is unset, points at a missing directory, or the hook file is not executable, git runs no hooks and prints nothing — a commit carrying an API key simply succeeds. Most of this framework's checking exists to make that silence loud: one command reports which repos are actually governed, and a probe in the onboarding path proves the gates block before you trust them.

---

## Install

```bash
git clone <your-fork> OliverCode && cd OliverCode
bash scripts/validate.sh              # gates, consistency, references, 122 tests
scripts/olivercode install            # symlinks CLAUDE.md + skills into ~/.claude
scripts/olivercode init               # seeds local/ fleet config from tracked examples
```

A fresh clone passes `validate.sh` with no configuration — no `local/`, no control plane, no surrounding directory layout. A failure on a clean clone is a bug in the fork, not in your machine. No package install, no language dependencies: `python3`, `git`, `bash`, and `perl` (the emoji gate refuses to run without it rather than passing silently). Developed and tested on macOS BSD userland, Bash 3.2; Linux should work and is untested; Windows needs WSL.

The faster path: open the clone in Claude Code and say *"set up OliverCode for my machine"*. The `olivercode-adoption` skill ships project-level — available before anything is installed — and drives the whole onboarding, asking only the decisions that need you.

`install` never destroys what you had: an existing `~/.claude/CLAUDE.md` is backed up to `CLAUDE.md.pre-olivercode` and the path printed, because that file is usually your whole accumulated ruleset. `init` never overwrites an existing file. Both are safe to re-run.

---

## How a repo becomes governed

Each step exists because the one before it is not enough on its own:

1. **Register the repo** in `local/repo-profiles.json` (`init` seeds it; `discover` emits a paste-ready profile per repo it finds). Registration first, because enforcement has to know what it governs before it can reach it. Repos need not share a parent — a profile's `path` field reaches anywhere.
2. **`scripts/olivercode sync-hooks`** writes the gate hooks into every registered repo and points `core.hooksPath` at them. Read its per-repo lines: a repo reported as skipped is a repo it did not govern.
3. **Prove it blocks.** Stage a fake secret, watch the commit refuse. The onboarding path (`docs/ADOPTING.md`) does this explicitly, because installed and enforcing are different claims.
4. **`scripts/olivercode health`, on a schedule.** The fail-open problem again: nothing else detects a hook that has quietly stopped applying. A single run at setup goes stale the moment a repo's config changes.

An adopted repo gets six gates — secrets, emoji/icons, PII, deleted-repo references, workflow push-auth, planning-doc governance. OliverCode runs two more on itself (contract integrity, token policy) that validate framework-only files. `docs/GOVERNANCE.md` holds the coverage table, plus the `hookVariant` escape hatch for a repo that must diverge.

---

## What you get

**On every commit, in every governed repo** — the gates, firing whether or not anyone read the documentation. They cannot be skipped without `--no-verify`.

**In every Claude Code session, from any directory** — your `CLAUDE.md` rules and the full skill set, via `~/.claude` symlinks.

**When you run `bash scripts/validate.sh`** — doc/code consistency, internal reference integrity, the test suite, and the fleet hook report. Fails closed on the first three.

**When you stamp a new repo** — `scripts/olivercode bootstrap` writes the project template (hooks, quality baseline, structure contract) per `shared/project-bootstrap-manifest.json`. `--dry-run` first shows every file it would touch.

---

## Three design decisions

### Only the hook is trusted to enforce

Contracts, templates, and skills are instruction text — an agent follows them because they load, and that is a weaker guarantee than a gate that blocks. The framework never blurs the two: `CONTRIBUTING.md`'s "Enforcement Reality" section lists which is which, and anything that must always hold is implemented as a hook, not written as a rule. A rule without a gate regresses; when a finding class recurs, it becomes a check.

### Checks must be able to fail

The recurring defect class in governance tooling is the check that reports success it never earned — a counter compared but never incremented, a scan that silently skips when its tool is missing, a "PASS" printed over an empty set. `scripts/lib/falsifiability_check.py` hunts that shape mechanically, and the test suite proves each checker fails by mutation: break the thing, assert the checker notices. A green result here means something was actually examined.

### Personal data never enters the tracked layer

Real fleet names, paths, and machine state live in gitignored `local/` and `runtime/`; tracked files carry placeholders. That split is what makes the repo forkable — and it is enforced, not asked for: a consistency check reads your real fleet names from the gitignored config and fails the build if one appears in a tracked file. `scripts/qa/check-fork-usable.sh` proves a stranger's clone works with nothing of yours present.

---

## Verifying the whole story

```bash
bash scripts/qa/check-fork-usable.sh   # a stranger's clone works; adoption path governs; gates block
bash scripts/qa/check-scenarios.sh     # 46 assertions across 12 sandboxed setup scenarios
bash scripts/qa/full-qa-pass.sh        # code quality, docs cohesion, bloat, fork usability
```

The scenario matrix walks every documented setup shape in an isolated sandbox with a throwaway HOME: fresh machine, existing `~/.claude`, scattered fleets, wrong `--root`s, the full backout. Every assertion maps to a sentence in the docs — when one fails, either the code or that sentence is lying.

---

## Documentation

| | |
|---|---|
| **[ADOPTING.md](docs/ADOPTING.md)** | Fork to governed fleet, step by step, ending in proof the gates block |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | The three layers, activation, dependency direction |
| **[GOVERNANCE.md](docs/GOVERNANCE.md)** | Every gate, what it blocks, per-repo coverage table |
| **[FEATURE_MAP.md](docs/FEATURE_MAP.md)** | Every capability mapped to its one owning doc — machine-checked |
| **[OLIVERCODE_LAUNCHER.md](docs/OLIVERCODE_LAUNCHER.md)** | The `olivercode` command surface |
| **[DOCUMENTATION_STANDARD.md](docs/DOCUMENTATION_STANDARD.md)** | The locked structure, voice, and naming for all docs — here and in every governed repo |
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
| **[Contracts](core/contracts/)** | Structure, execution, hygiene, file-location standards |
| **[Workflows](core/workflows/)** | Repeatable cross-repo procedures |
| **[Claude OS](.claude-optimization/README.md)** | Standalone memory/state layer |

## Status

122 tests across 9 files, including mutation suites that prove the checkers can fail. 8 pre-commit gates on this repo;
an adopted repo receives six of those. 46-assertion scenario matrix over 12 sandboxed setups. Pure `python3` + `bash` + `perl`, no package dependencies. macOS verified; CI ships ready and is enabled per fork.

## License

MIT

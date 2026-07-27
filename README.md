# OliverCode

**Think of OliverCode as the shared engine room for all your projects.** Instead of each repo reinventing how it validates code, guards secrets, or structures its skills, OliverCode provides one set of reusable contracts, templates, and governance gates that every project inherits.

If you're working in one of your product repos, you probably never interact with OliverCode directly — its value is that those projects share a common baseline for quality, security, and structure without duplicating effort.

**Who this is for:** developers who work across multiple repos with AI agents (Claude Code), and anyone who wants a governance/skills baseline that loads automatically in every session instead of being re-explained per project.

**Scope:** security, token optimization, development best practices/organization, and folder structure. Nothing else ships here — product logic stays in product repos, by contract (`docs/FRAMEWORK_BOUNDARY.md`).

## What You Get, and What Actually Enforces It

The single most useful thing to understand before adopting this: **exactly one layer blocks
you, and the rest is instruction text.**

| You get | Enforced by | Blocks you? |
|---|---|---|
| 8 pre-commit gates — secrets, emoji/icons, PII, deleted-repo refs, workflow push-auth, contract integrity, planning-doc governance, token policy | `.githooks/pre-commit`, installed per repo via `core.hooksPath` | **Yes.** Fires on every `git commit` |
| Doc/code consistency, internal reference integrity, tests | `bash scripts/validate.sh` | **Yes, when run.** Nothing auto-runs it |
| Fork usability + bloat/legacy limits | `scripts/qa/full-qa-pass.sh`, and CI where enabled | **Yes, when run** |
| Contracts, templates, workflows, structure standards | `core/` — inherited via the bootstrap manifest | No. An agent follows them because they load |
| Skills (engineering method + framework tooling) | `~/.claude/skills/` symlinks | No. The agent chooses to load one |

Two properties worth knowing up front, because both are counterintuitive:

- **Hook enforcement fails open.** If `core.hooksPath` is unset, points at a missing
  directory, or the hook is not executable, git runs no hooks *and prints nothing* — a commit
  carrying secrets simply succeeds. `scripts/olivercode health` is the only thing that
  detects it. Run it on a schedule, not just at setup.
- **A written rule is not an enforced rule.** `CONTRIBUTING.md`'s "Enforcement Reality"
  section lists which is which. Don't assume "it's in CLAUDE.md" means "it's blocked".

Why it is built this way: an agent that has to *discover* the rules will sometimes not. So
anything that must always apply is a hook or a gate, and everything else is loaded
automatically rather than referenced. `docs/governance.md` holds the gate list;
`docs/FEATURE_MAP.md` indexes every capability and the one doc that owns it.

## Quick Start

**Requirements.** `python3`, `git`, `bash`, POSIX shell tools, and `perl` (Gate 2's emoji
scan is a perl one-liner — the hook now refuses to run without it rather than passing
silently). `gh` is needed only if you commit files under `.github/workflows/`; Gate 5 blocks
those without a workflow-scoped credential. No package install, no language dependencies.

Developed and tested on macOS. The shell code is written for BSD userland (no `grep -P`,
Bash 3.2 compatible), so Linux should work and is untested; Windows needs WSL.

```bash
git clone <your-fork> OliverCode && cd OliverCode
python3 scripts/olivercode --help         # see what the framework can do
bash scripts/validate.sh                  # gates, consistency, references, tests
scripts/olivercode health                 # dependency, entrypoint, and drift checks
```

A fresh clone passes all of that with no setup — no `local/` config, no control plane, no
surrounding vault. If any of it fails on a clean clone, that is a bug in the fork, not your
machine. `bash scripts/qa/check-fork-usable.sh` checks exactly that, in a sandbox.

Then activate it, so the rules and skills load in every Claude Code session on your machine,
from any directory:

```bash
scripts/olivercode install     # symlinks CLAUDE.md + every skill into ~/.claude
scripts/olivercode init        # seeds local/ (your fleet config) from the tracked examples
scripts/olivercode health      # confirms every symlink and hook resolves
```

`install` never destroys what you already had: an existing real `~/.claude/CLAUDE.md` is moved
to `CLAUDE.md.pre-olivercode` and the path is printed, because that file is usually your whole
accumulated ruleset. `init` never overwrites an existing `local/` file. Both are safe to re-run.

**Don't want to read the docs?** Open this repo in Claude Code and say *"set up OliverCode
for my machine"*. The `olivercode-adoption` skill ships as a project-level skill, so it is
available the moment you clone — before anything is installed — and it drives the whole
process: it discovers what you already have, asks you the handful of decisions only you can
make, and does the rest.

**Or do it yourself:** `docs/ADOPTING.md` is the full onboarding path —
inventory, classify, merge your existing rules in, install enforcement, then prove the gates
actually block. The `olivercode-adoption` skill runs it as a guided, non-destructive audit.

## Where Things Live (and why)

One home per thing — the structure IS the documentation. If you're unsure where something
goes, this table is the answer; if it's not answered here, `docs/skills-placement.md` and
`core/contracts/PROJECT_STRUCTURE_STANDARD.md` are the tie-breakers.

| Directory | What lives here | What never goes here | Benefit |
|---|---|---|---|
| `skills/` | Engineering-method + framework-tooling skills, flat, one dir per skill | Product/GTM/vendor content | Symlink the whole set once — every skill invocable from any repo |
| `core/contracts/` | Structural standards every repo follows | Repo-specific rules | Change a standard once, whole fleet inherits it |
| `core/templates/project/` | The project template stamped into new repos (hooks, CI, docs) by `olivercode bootstrap` | Anything machine-specific | New repo starts compliant on day one |
| `shared/` | Bootstrap manifest, task policies, placeholder registries | Real fleet data | Tracked files stay generic; clone works for anyone |
| `local/` (gitignored) | YOUR real fleet registries | Anything you'd push | Personal data physically can't leak into git |
| `scripts/` | Launcher (`olivercode`: `health`, `update`, `sync-hooks`, `skills`) + validation gates | Product logic | One command surface, self-verifying |
| `.githooks/` | The 8 fail-closed pre-commit gates | Optional/soft checks | Enforcement that runs even when nobody reads the docs |
| `docs/` | Current-state authority docs only | History, roadmaps, session logs | Every doc describes what IS — no stale authority |
| `runtime/control-plane/` (gitignored) | Minimal private machine state | Anything a fork needs | Clone works standalone without it |

## How Projects Use This

Each product repo in your fleet inherits:
1. **Pre-commit hooks** (`.githooks/pre-commit`) — 8 gates: secrets, emoji, PII, deleted-repo refs, workflow push-auth, contract integrity, planning-doc governance (when its checker is present), and token policy
2. **Quality baseline** — shared template
3. **Governance standards** — what code belongs where, how to validate

OliverCode is NOT a runtime dependency — product repos run on their own stack (Next.js, Python, etc.). The framework stays in its own repo and defines standards, not implementations.

Enforcement honesty: the 8 hook gates are the only mechanically-enforced layer; every other rule is instruction text an agent follows but nothing blocks. See CONTRIBUTING.md's "Enforcement Reality" section.

## Recommended External Tooling

Not shipped here (third-party, install separately), but this framework's token-optimization posture assumes them:

| Tool | What it does | Install |
|---|---|---|
| [fablize](https://github.com/fivetaku/fablize) | Claude Code plugin: enforces completion-with-evidence, verification grounding, and systematic investigation as procedure — the enforcement-side complement to this repo's instruction-side practice rules. | `/plugin marketplace add fivetaku/fablize` then `/plugin install fablize` |
| [caveman](https://github.com/JuliusBrussee/caveman) | Claude Code plugin: compresses agent chat output ~65% with full technical accuracy. Pair with a `## Voice` section in your `CLAUDE.md` (see this repo's own for the pattern). | Claude Code plugin marketplace |
| [codeburn](https://github.com/getagentseal/codeburn) | Local token-usage/cost/health dashboard across AI coding tools. No proxy, no API keys — reads session data from disk. | per repo README |
| [taste-skill](https://github.com/Leonxlnx/taste-skill) | Anti-slop frontend design skills (13, install selectively). `design-taste-frontend` + `full-output-enforcement` are the load-bearing two. | `npx skills add https://github.com/Leonxlnx/taste-skill` |
| ui-ux-pro-max-cli | Broader design-asset suite (7 skills); `ui-styling` (shadcn/Tailwind implementation) is the load-bearing one. | npm |
| [claude-code-ui-agents](https://github.com/mustafakendiguzel/claude-code-ui-agents) | Frontend prompt library (plain markdown, fetch per task). | reference only |
| [Ant Design](https://github.com/ant-design/ant-design) | Component-API and design-token sanity reference — not a dependency. | reference only |

The `frontend-ui-references` skill documents when to reach for each of the design entries above -- it lives in the vault's `.olivercode/user-skills/`, not in this repo, since design/UI routing is outside OliverCode's own scope.

## Local State (gitignored)

Two directories live inside the repo tree but never push to GitHub:

- `local/` — your real fleet registries (`repo-map.json`, `repo-profiles.json`). Tracked `shared/*.example.json` files ship placeholders; everything works without `local/` present.
- `runtime/control-plane/` — minimal private machine state (see its README). OliverCode works standalone without it.

## Key Docs

| Doc | What it covers |
|---|---|
| [Architecture](ARCHITECTURE.md) | Why the framework exists, the three layers, and how activation works |
| [Governance](docs/governance.md) | What gates run before commit and what they block |
| [Feature Map](docs/FEATURE_MAP.md) | Canonical index of every framework capability |
| [CLI](docs/OLIVERCODE_LAUNCHER.md) | The `olivercode` command surface |
| [Framework Boundary](docs/FRAMEWORK_BOUNDARY.md) | What OliverCode is vs what it deliberately excludes |
| [Skills Placement](docs/skills-placement.md) | Where every skill/agent file lives, one home per layer |
| [Troubleshooting](docs/troubleshooting.md) | Common setup and command issues |
| [Adopting](docs/ADOPTING.md) | Forking this and onboarding your own repos, step by step |
| [License](LICENSE) | MIT — fork it, use it, no obligation back |
| [Contributing](CONTRIBUTING.md) | How to make changes to the framework |

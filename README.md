# OliverCode

**Think of OliverCode as the shared engine room for all your projects.** Instead of each repo reinventing how it validates code, guards secrets, or structures its skills, OliverCode provides one set of reusable contracts, templates, and governance gates that every project inherits.

If you're working in one of your product repos, you probably never interact with OliverCode directly — its value is that those projects share a common baseline for quality, security, and structure without duplicating effort. (Your fleet is declared in `local/repo-map.json`, gitignored; `shared/repo-map.json` ships a placeholder example.)

**Who this is for:** developers who work across multiple repos with AI agents (Claude Code), and anyone who wants a governance/skills baseline that loads automatically in every session instead of being re-explained per project.

**Scope:** security, token optimization, development best practices/organization, and folder structure. Nothing else ships here — product logic stays in product repos, by contract (`docs/FRAMEWORK_BOUNDARY.md`).

## What It Keeps

Everything in this repo falls into one of four categories — if it doesn't fit, it doesn't belong here:

- **run** — launcher and orchestration entrypoints (`scripts/olivercode`)
- **verify** — gates that prove the framework works (`scripts/validate.sh`)
- **ship** — contracts and templates that downstream repos inherit
- **support** — current-state docs that explain the active surface

## Quick Start

```bash
python3 scripts/olivercode --help         # see what the framework can do
scripts/olivercode health                 # dependency, entrypoint, and drift checks
bash scripts/validate.sh                  # gates, consistency, references, tests
scripts/olivercode skills                 # list the reusable skills
```

A fresh clone passes all of the above with no setup — no `local/` config, no control
plane, no surrounding vault. If any of them fails on a clean clone, that is a bug.

To make the skills and rules load automatically in every Claude Code session on your
machine (any repo, any directory):

```bash
mkdir -p ~/.claude/skills                                   # may not exist yet
ln -sfn "$(pwd)/CLAUDE.md" ~/.claude/CLAUDE.md              # back up any existing one first
for s in skills/*/; do ln -sfn "$(pwd)/$s" ~/.claude/skills/"$(basename "$s")"; done
scripts/olivercode health                                   # confirms every symlink resolves
```

If you already have a `~/.claude/CLAUDE.md`, do not overwrite it blindly — `docs/ADOPTING.md`
walks through merging your existing rules in rather than losing them.

**Adopting this across your own repos:** `docs/ADOPTING.md` is the onboarding guide, and the
`olivercode-adoption` skill runs it as a guided, non-destructive audit. See
`docs/skills-placement.md` for the full placement contract.

## Where Things Live (and why)

One home per thing — the structure IS the documentation. If you're unsure where something
goes, this table is the answer; if it's not answered here, `docs/skills-placement.md` and
`core/contracts/PROJECT_STRUCTURE_STANDARD.md` are the tie-breakers.

| Directory | What lives here | What never goes here | Benefit |
|---|---|---|---|
| `skills/` | Engineering-method + framework-tooling skills, flat, one dir per skill | Product/GTM/vendor content | Symlink the whole set once — every skill invocable from any repo |
| `core/contracts/` | Structural standards every repo follows | Repo-specific rules | Change a standard once, whole fleet inherits it |
| `core/templates/project/` | The project template stamped into new repos (hooks, CI, docs) | Anything machine-specific | New repo starts compliant on day one |
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
| [Install](INSTALL.md) | Minimal local requirements and first commands |
| [Contributing](CONTRIBUTING.md) | How to make changes to the framework |

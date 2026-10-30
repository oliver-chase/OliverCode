# Adopting OliverCode

How to take a fork of this framework and make it govern your own repos the way it governs
the fleet it came from. Written for the agent doing the work, with a human approving.

The governing rule for this whole process: **optimize, do not amputate.** You are pointing
existing rules at a shared home, not deleting them. Anything you cannot map to an OliverCode
concept stays exactly where it is. A rule you do not understand is a rule you keep.

**You do not have to read this.** Open this repo in Claude Code and say *"set up OliverCode
for my machine"* — the `olivercode-adoption` skill ships project-level, so it is available
immediately on a fresh clone, and it drives every step below, surfacing only the decisions
that genuinely need you. This document is the reference it works from.

---

## What you are actually installing

Two layers, and it matters which is which:

| Layer | Where | Tracked? | Who owns it |
|---|---|---|---|
| The framework + your fleet's real config | your OliverCode fork (`shared/repo-profiles.json` and friends) | yes, tracked | you |
| Activation | `~/.claude/CLAUDE.md` + `~/.claude/skills/*` symlinks | no, per machine | your machine |

Your fleet's real names and config live directly in the tracked registry — there is no
placeholder layer to keep in sync with it. `ARCHITECTURE.md`'s "The Two Layers" explains why.

## Step 0 — Prove the clone is sound before changing anything

```bash
git clone <your-fork> OliverCode && cd OliverCode
python3 scripts/olivercode --help
bash scripts/validate.sh
scripts/olivercode health
```

All three must pass on a clean clone with no configuration. `health` notes that there is no
control plane and WARNs about an unregistered fleet. That is correct and still reports HEALTHY.
If `validate.sh` fails here, stop — the fork is broken, not your setup.

One command checks all of this at once, in a sandbox with a throwaway HOME:

```bash
bash scripts/qa/check-fork-usable.sh
```

That check also walks this guide's own load-bearing steps against two throwaway repos --
fleet registration, `sync-hooks`, the secret probe, and `health` -- so the
instructions below are verified, not just written. If it passes, the fork is sound and every
failure below is a setup problem, not a repo problem. Run it after any change to the
framework's own plumbing. It is also Phase 4 of `scripts/qa/full-qa-pass.sh`.

**Enable CI in your fork.** `.github/workflows/framework-ci.yml` ships ready to run, but is
paused on the origin repo — `docs/GOVERNANCE.md`'s "Unified Validation Entrypoint" section
is the one home for why. Where CI is off, the local commands are the entire enforcement
layer — run `full-qa-pass.sh` before you push rather than assuming a build will catch it.

## Step 1 — Inventory before you touch anything

Write the inventory to a scratch file. You will need it to prove nothing was lost.

```bash
ls ~/.claude/                                   # what already exists
cat ~/.claude/CLAUDE.md 2>/dev/null             # existing global rules, if any
ls -la ~/.claude/skills/ 2>/dev/null            # existing skills, real dirs vs symlinks

# Find your repos and what governance each already has. Read-only. Pass every
# directory your code lives under -- they do not have to share a parent.
scripts/olivercode discover --root ~/dev --root ~/work
```

`discover` reports, per repo: which agent-rules file it has (if any), whether hooks are
installed, and which repos are ungoverned. It then inventories `~/.claude` — separating
skills symlinked into this checkout from ones symlinked elsewhere, real untracked
directories, and broken links — and ends with a profile skeleton containing explicit `path`
values, ready to paste into `shared/repo-profiles.json`.

Two things it will likely surface in an existing setup:

- **Rules files that are not named `CLAUDE.md`** — `AGENTS.md`, `.cursorrules`, and friends do
  not auto-load in Claude Code. They are invisible in practice, however good their content.
  Step 4 merges them in.
- **Repos with `hooksPath=unset`** — no gates at all, silently.
- **Real directories in `~/.claude/skills/`** — untracked content with no backup anywhere.
  Usually vendor skills, which is fine. Anything else is a skill that exists in exactly one
  place on one machine. Decide where it belongs before it is lost. `install` never touches
  these, and reports how many it left alone.

Record, for each existing rules file: what it says, and which of these it is —

- **machine-global** (applies everywhere) → belongs in the OliverCode `CLAUDE.md`
- **repo-specific** (only true for one product) → stays in that repo's `CLAUDE.md`
- **personal/business** (voice, GTM, hiring) → belongs in your own user-skills area, not in
  the framework — see `docs/SKILLS-PLACEMENT.md`

Most existing setups have all three tangled in one file. Separating them IS the adoption.

## Step 2 — Back up, then install activation

`install` backs up an existing `~/.claude/CLAUDE.md` to `CLAUDE.md.pre-olivercode` itself,
so do not copy it by hand first — you would be writing the same backup path twice. It does
**not** copy `~/.claude/skills/`, because it never deletes anything there. Back that up
yourself if you want a restore point:

```bash
cp -R ~/.claude/skills ~/.claude/skills.pre-olivercode 2>/dev/null || true

scripts/olivercode install     # symlinks CLAUDE.md + skills, backing up what it replaces
scripts/olivercode health
```

`install` reports how many skills it linked and how many real directories it left untouched.
`health` then checks every symlink resolves into this checkout. Keep the backups until the
whole process is done and verified.

## Step 3 — Merge your global rules in, do not replace them

Your old `~/.claude/CLAUDE.md` content does not disappear — it gets sorted:

1. Rules that are genuinely machine-global → add to your fork's `CLAUDE.md`, in the existing
   sections (`## Voice`, `## Development Practice`, `## Pre-Commit`, `## Enforcement`).
2. Rules that are really about one repo → move to that repo's own `CLAUDE.md`.
3. Rules that are personal/business content → a skill, placed per `docs/SKILLS-PLACEMENT.md`.
4. Anything you cannot classify → leave it in the global file and flag it for the human.

**The one hard constraint on the global file:** it loads from `~/.claude/CLAUDE.md` in
sessions whose working directory is almost never OliverCode. So every path in it must
resolve from anywhere. Use `$OC/...` for OliverCode's own files, resolved and checked:

```bash
OC="$(dirname "$(readlink ~/.claude/CLAUDE.md 2>/dev/null)" 2>/dev/null)"
[ -f "$OC/core/contracts/FRAMEWORK_BASELINE.md" ] || echo "OliverCode not installed"
```

A bare path like `scripts/validate.sh` means *the repo the agent is currently in*. That is
usually what you want — every repo has its own — but say so explicitly, or the next reader
assumes it means OliverCode's.

## Step 4 — Rewrite each repo's CLAUDE.md

For every repo, the file should carry **only what is specific to that repo**, headed by a
short block saying where the shared rules come from:

```markdown
> Framework rules (voice, practice, gates, skill placement) load automatically from
> `~/.claude/CLAUDE.md`, which symlinks into OliverCode. Resolve OliverCode's own path with
> `dirname "$(readlink ~/.claude/CLAUDE.md)"` when you need a file from it. This file carries
> only what is specific to this repo.

# <Repo> — Agent Rules

Read before working here:
- <the docs that are actually authoritative for this repo — list the files that exist,
  not the ones the template suggests. `docs/repo-structure-contract.md` and
  `docs/backlog-config.json` (naming the repo's GitHub Project) are the convention in
  `core/contracts/PROJECT_STRUCTURE_STANDARD.md`, but pointing at a file the repo does
  not have is worse than pointing at nothing>

Run `bash scripts/validate.sh` before commit (this repo's canonical validation).
```

Rules for this rewrite:

- **Never write a pointer relative to somewhere other than the reader's cwd.** Paths like
  `Some/Vault/Path/OliverCode/CLAUDE.md` do not resolve from inside the repo and are dead
  text. Verify each pointer with `ls` before you leave it in.
- **Do not delete repo-specific content** to make the file shorter. Duplicated *framework*
  rules come out. Repo truth stays.
- If a repo has an `AGENTS.md`, `.cursorrules`, or similarly-named rules file, merge it INTO
  `CLAUDE.md`. Claude Code only auto-loads `CLAUDE.md`. Anything else is invisible in
  practice. **Then decide the original's fate explicitly, and say which you chose:**
  - another tool still reads it (Cursor, Copilot, Codex) → keep it, and replace its body
    with a one-line pointer to `CLAUDE.md` so the two cannot drift into disagreeing
  - nothing reads it → delete it in the same commit as the merge. Git is the archive. A
    stale second rules file is the thing that made the content invisible in the first place

  Never leave both files carrying live rules. That is the duplication this step exists to end.

## Step 5 — Register your fleet

Enforcement has to know which repos it governs before it can reach them, so registration
comes first.

Edit `shared/repo-profiles.json` directly with your real repo names, validation commands,
and token policy. `_<field>_note` keys beside a worked example document the schema in place.
`scripts/olivercode discover` emits a paste-ready profile per repo, including the
`token_policy` block. Each profile needs that block, with `ignore_globs` and
`generated_artifact_dirs`, or Gate 8 fails the commit — `docs/TOKEN_POLICY.md` has the shape.

Confirm the fleet really registered before continuing:

```bash
scripts/olivercode health     # must list your repos by name, not "no fleet registered"
```

## Step 6 — Install enforcement

```bash
scripts/olivercode sync-hooks     # writes .githooks/ + sets core.hooksPath in every fleet repo
scripts/olivercode health         # confirms each repo's hooks are installed and current
```

`sync-hooks` resolves your fleet from `shared/repo-profiles.json` and expects those repos as
siblings of the OliverCode checkout. If your layout differs, see "Folder structure" below.
Every repo reported as `[SKIP] not present on this machine` is one it did **not** govern.
Read that list rather than the exit code.

An adopted repo gets nine gates, not the eleven OliverCode runs on itself: contract
integrity and token policy check framework-only things, so the template does not ship them.
`docs/GOVERNANCE.md` has the coverage table.

Know what you just installed: **hook enforcement fails open.** See
`docs/TROUBLESHOOTING.md`'s "Commits are passing gates that should have blocked them" for
why and how to fix it. `scripts/olivercode health` is the only detector — run it on a
schedule, not just at setup.

## Step 6b — Stamp the project template into a repo (optional)

Not part of the required path. `sync-hooks` already installs the gates, which is what
governs a repo. `bootstrap` goes further and stamps the full project template — the
quality baseline, structure contract, and supporting scripts declared in
`shared/project-bootstrap-manifest.json` — so a repo matches the standard on day one.

Use it for a **new** repo. For an existing one, look before you write:

```bash
scripts/olivercode bootstrap <repo> --dry-run    # prints NEW/OVERWRITE per file, writes nothing
scripts/olivercode bootstrap <repo>
```

The manifest gives every file a mode, and the mode determines whether your existing content is safe:

- `presence` — created only if absent. Existing content is never touched, and the run
  reports it as kept.
- `strict` — **overwritten**, because its contract is byte-identity with the template.
  The hooks and the shared baseline are strict. If you have hand-edited one of those in
  the target repo, your version is replaced.

`conditionalFiles` are listed, never copied: they depend on profile flags the repo may
not set, so the decision stays yours. Always run `--dry-run` against an existing repo
first and read the OVERWRITE lines — that list is exactly what you are agreeing to lose.

## Step 7 — Verify, with evidence

```bash
bash scripts/validate.sh          # gates, consistency, references, tests
scripts/olivercode health         # symlinks + per-repo hook install state
scripts/olivercode skills         # every skill discoverable
```

Then prove enforcement actually fires, rather than assuming it:

```bash
cd <one of your repos>
bash "$OC/scripts/qa/probe-secret-gate.sh"    # writes a fake secret, commits, expects a block
```

`scripts/qa/probe-secret-gate.sh` is the one home for this probe — see its own header for why
it writes straight into the repo instead of staging through `/tmp`.

If that commit succeeds, your hooks are not installed. Go back to Step 6.

## Step 8 — Reconcile, do not amputate

Last pass over what the inventory in Step 1 found:

- Anything you moved: confirm it exists at its new home before considering the old one gone.
- Anything you could not classify: it stays, and you tell the human what and why.
- Only after the human confirms: remove the `.pre-olivercode` backups.

Write the result as a short report: what moved where, what stayed, what is still ambiguous.

---

## Staying current with upstream

`olivercode update` pulls **this checkout's** tracking branch and re-syncs hooks. On a fork
that is your own `origin` — it does not fetch the upstream framework. That is deliberate: a
fork carries local edits to `CLAUDE.md`, contracts, and templates, and auto-merging upstream
over them would be destructive.

To take upstream changes, do it explicitly:

```bash
git remote add upstream <the repo you forked from>   # once
git fetch upstream
git log --oneline HEAD..upstream/main                # read what you are about to take
git merge upstream/main                              # resolve conflicts deliberately
bash scripts/qa/check-fork-usable.sh                 # prove the merge did not break the fork
scripts/olivercode sync-hooks                        # templates may have changed
```

Expect conflicts in `CLAUDE.md` and anything under `core/` you customized. Those are the
files you were supposed to change. Keep your version and take upstream's structural fixes.

## Backing out

Adopting this should not be a one-way door. To remove it:

```bash
# 1. Restore whatever install replaced (it never deletes)
mv ~/.claude/CLAUDE.md.pre-olivercode ~/.claude/CLAUDE.md    # if you had one

# 2. Drop the symlinks this checkout owns. Real directories are NOT ours -- leave them.
find ~/.claude/skills -maxdepth 1 -type l -lname '*/OliverCode/skills/*' -delete

# 3. Stop the hooks in each governed repo
git -C <repo> config --unset core.hooksPath          # per repo; .githooks/ can stay or go

# 4. The checkout itself is just a directory -- delete it.
```

Nothing outside those four places is touched: OliverCode writes no system config, no shell
profile, no launchd/cron entry, and nothing under any product repo except `.githooks/` and
that one git config key.

## Folder structure

The framework assumes one layout, in exactly two places: `sync-hooks` and `health` look for
fleet repos as **siblings of the OliverCode checkout**, and the vault-hook check looks three
levels up from it. Nothing else depends on where anything sits.

Recommended:

```
<workspace-root>/
├── OliverCode/              the fork -- framework, skills, contracts, gates, your real fleet config
│   └── runtime/control-plane/  (gitignored, optional) per-machine state
├── product-repo-a/          siblings of OliverCode
├── product-repo-b/
└── product-repo-c/
```

**If your repos do not share a parent at all** — the normal case when adopting into an
existing setup — give each profile an explicit `path` in `shared/repo-profiles.json`:

```json
"acme-api": { "name": "acme-api", "path": "~/work/clients/acme/api", ... }
```

`path` accepts absolute, `~`-relative, or fleet-root-relative values, and `discover` emits it
for you. Without it a repo is only findable at `<fleet-root>/<name>`, which is what makes a
tidy sibling layout the easy path rather than the required one.

If your repos DO share a parent that simply is not OliverCode's, pass `--root` instead:

```bash
scripts/olivercode sync-hooks --root /path/to/where/your/repos/live
scripts/olivercode health     --root /path/to/where/your/repos/live
```

Machine paths go in `olivercode.local.json` at the OliverCode root (gitignored; copy `olivercode.local.example.json`): `vaultRoot` for the vault's hooks and pushes, `skillsRoot` for the skill checks, `repoPaths` for a repo outside the fleet folder and `pushRepos` for extra `push-fleet` targets. `OLIVERCODE_VAULT_ROOT` and `OLIVERCODE_SKILLS_ROOT` override the file. An unset value means this machine has none, and nothing guesses it from the folder layout.

A layout the scripts cannot resolve degrades to WARN and skips. It never fails wrongly, but
it also never checks anything — **do not mistake the WARN for coverage.** If `sync-hooks`
reports every repo as skipped, your `--root` is wrong, not your fleet.

Inside each product repo, the structure contract is
`core/contracts/PROJECT_STRUCTURE_STANDARD.md`. The short version:

```
<product-repo>/
├── README.md
├── CLAUDE.md                       agent rules -- the only filename Claude Code auto-loads
├── .githooks/                      installed by sync-hooks, activated by core.hooksPath
├── docs/
│   ├── repo-structure-contract.md  this repo's declared paths
│   ├── backlog-config.json         names this repo's GitHub Project
│   ├── BACKLOG.md                  the live board, only if the repo has no backlog-config.json
│   └── ARCHITECTURE.md
└── scripts/validate.sh             this repo's canonical validation
```

Do not add top-level directories without a contract reason. That rule is the one that keeps
a fleet legible to an agent that has never seen it.

## What a fork gets, and what it does not

Tracked and shared: contracts, templates, skills, gates, launcher, docs, tests, and the
real fleet registries.

Never tracked, created per user: `runtime/control-plane/` (machine state),
`.claude-optimization/memory/` and `state/` (your agent's memory), and the `~/.claude/`
symlinks. The framework works without every one of them, and `scripts/validate.sh` passing
on a clean clone is the test of it.

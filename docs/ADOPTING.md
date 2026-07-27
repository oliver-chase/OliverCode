# Adopting OliverCode

How to take a fork of this framework and make it govern your own repos the way it governs
the fleet it came from. Written for the agent doing the work, with a human approving.

The governing rule for this whole process: **optimize, do not amputate.** You are pointing
existing rules at a shared home, not deleting them. Anything you cannot map to an OliverCode
concept stays exactly where it is. A rule you do not understand is a rule you keep.

Run this with the `olivercode-adoption` skill, which walks the same steps and stops for
approval at each gate.

---

## What you are actually installing

Three layers, and it matters which is which:

| Layer | Where | Tracked? | Who owns it |
|---|---|---|---|
| The framework | your OliverCode fork | yes, public | shared, forkable |
| Your fleet's real config | `local/` inside that fork | no, gitignored | you |
| Activation | `~/.claude/CLAUDE.md` + `~/.claude/skills/*` symlinks | no, per machine | your machine |

Nothing personal ever enters the tracked layer. That is what makes the fork shareable.

## Step 0 — Prove the clone is sound before changing anything

```bash
git clone <your-fork> OliverCode && cd OliverCode
python3 scripts/olivercode --help
bash scripts/validate.sh
scripts/olivercode health
```

All three must pass on a clean clone with no configuration. `health` will WARN about a
missing control plane and an unregistered fleet; that is correct and still reports HEALTHY.
If `validate.sh` fails here, stop — the fork is broken, not your setup.

## Step 1 — Inventory before you touch anything

Write the inventory to a scratch file. You will need it to prove nothing was lost.

```bash
ls ~/.claude/                                   # what already exists
cat ~/.claude/CLAUDE.md 2>/dev/null             # existing global rules, if any
ls -la ~/.claude/skills/ 2>/dev/null            # existing skills, real dirs vs symlinks
find . -maxdepth 2 -name "CLAUDE.md" -o -maxdepth 2 -name "AGENTS.md" | sort
for r in <your repos>; do
  echo "$r: hooksPath=$(git -C $r config --get core.hooksPath)"
done
```

Record, for each existing rules file: what it says, and which of these it is —

- **machine-global** (applies everywhere) → belongs in the OliverCode `CLAUDE.md`
- **repo-specific** (only true for one product) → stays in that repo's `CLAUDE.md`
- **personal/business** (voice, GTM, hiring) → belongs in your own user-skills area, not in
  the framework — see `docs/skills-placement.md`

Most existing setups have all three tangled in one file. Separating them IS the adoption.

## Step 2 — Back up, then install activation

```bash
cp ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.pre-olivercode 2>/dev/null || true
cp -R ~/.claude/skills ~/.claude/skills.pre-olivercode 2>/dev/null || true

mkdir -p ~/.claude/skills
ln -sfn "$(pwd)/CLAUDE.md" ~/.claude/CLAUDE.md
for s in skills/*/; do ln -sfn "$(pwd)/$s" ~/.claude/skills/"$(basename "$s")"; done
scripts/olivercode health
```

`health` now checks every symlink resolves into this checkout. Keep the backups until the
whole process is done and verified.

## Step 3 — Merge your global rules in, do not replace them

Your old `~/.claude/CLAUDE.md` content does not disappear — it gets sorted:

1. Rules that are genuinely machine-global → add to your fork's `CLAUDE.md`, in the existing
   sections (`## Voice`, `## Development Practice`, `## Pre-Commit`, `## Enforcement`).
2. Rules that are really about one repo → move to that repo's own `CLAUDE.md`.
3. Rules that are personal/business content → a skill, placed per `docs/skills-placement.md`.
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
- `docs/BACKLOG.md` — live board, canonical open work
- `docs/ARCHITECTURE.md` — technical map
- <the docs that are actually authoritative for this repo>

Run `bash scripts/validate.sh` before commit (this repo's canonical validation).
```

Rules for this rewrite:

- **Never write a pointer relative to somewhere other than the reader's cwd.** Paths like
  `Some/Vault/Path/OliverCode/CLAUDE.md` do not resolve from inside the repo and are dead
  text. Verify each pointer with `ls` before you leave it in.
- **Do not delete repo-specific content** to make the file shorter. Duplicated *framework*
  rules come out; repo truth stays.
- If a repo has an `AGENTS.md` or similarly-named rules file, merge it INTO `CLAUDE.md`.
  Claude Code only auto-loads `CLAUDE.md`; anything else is invisible in practice.

## Step 5 — Install enforcement

```bash
scripts/olivercode sync-hooks     # writes .githooks/ + sets core.hooksPath in every fleet repo
scripts/olivercode health         # confirms each repo's hooks are installed and current
```

`sync-hooks` resolves your fleet from `local/repo-profiles.json` and expects those repos as
siblings of the OliverCode checkout. If your layout differs, see "Folder structure" below.

Know what you just installed: **hook enforcement fails open.** If `core.hooksPath` is unset,
points at a missing directory, or the hook is not executable, git runs no hooks and prints
nothing — a commit carrying secrets simply succeeds. `scripts/olivercode health` is the only
thing that detects this. Run it on a schedule, not just at setup.

## Step 6 — Register your fleet (the local layer)

```bash
mkdir -p local
cp shared/repo-profiles.example.json local/repo-profiles.json
cp shared/repo-map.json             local/repo-map.json
```

Edit the copies with your real repo names, validation commands, and token policy. `local/` is
gitignored, so real names and paths never reach the tracked fork. Every loader tries `local/`
first and falls back to the tracked example with a WARN — which is why a stranger's clone
still works.

Each profile needs a `token_policy` block with `ignore_globs` and `generated_artifact_dirs`,
or Gate 8 fails the commit. `docs/TOKEN_POLICY.md` has the shape.

## Step 7 — Verify, with evidence

```bash
bash scripts/validate.sh          # gates, consistency, references, tests
scripts/olivercode health         # symlinks + per-repo hook install state
scripts/olivercode skills         # every skill discoverable
```

Then prove enforcement actually fires, rather than assuming it:

```bash
cd <one of your repos>
printf 'KEY="sk-%s"\n' "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" > /tmp/leak-probe.txt
cp /tmp/leak-probe.txt ./leak-probe.txt && git add leak-probe.txt
git commit -m "probe"      # MUST be blocked by Gate 1
git reset -q HEAD leak-probe.txt && rm -f leak-probe.txt
```

If that commit succeeds, your hooks are not installed. Go back to Step 5.

## Step 8 — Reconcile, do not amputate

Last pass over what the inventory in Step 1 found:

- Anything you moved: confirm it exists at its new home before considering the old one gone.
- Anything you could not classify: it stays, and you tell the human what and why.
- Only after the human confirms: remove the `.pre-olivercode` backups.

Write the result as a short report: what moved where, what stayed, what is still ambiguous.

---

## Folder structure

The framework assumes one layout, in exactly two places: `sync-hooks` and `health` look for
fleet repos as **siblings of the OliverCode checkout**, and the vault-hook check looks three
levels up from it. Nothing else depends on where anything sits.

Recommended:

```
<workspace-root>/
├── OliverCode/              the fork -- framework, skills, contracts, gates
│   ├── local/               (gitignored) YOUR real fleet config
│   └── runtime/control-plane/  (gitignored, optional) per-machine state
├── product-repo-a/          siblings of OliverCode
├── product-repo-b/
└── product-repo-c/
```

If your repos are not siblings, either pass `--root` where the scripts accept it, or set
`OLIVERCODE_VAULT_ROOT` so the placement-drift check knows where to look. A layout the
scripts cannot resolve degrades to WARN and skips — it never fails wrongly, but it also
never checks anything, so do not mistake the WARN for coverage.

Inside each product repo, the structure contract is
`core/contracts/PROJECT_STRUCTURE_STANDARD.md`. The short version:

```
<product-repo>/
├── README.md
├── CLAUDE.md                       agent rules -- the only filename Claude Code auto-loads
├── .githooks/                      installed by sync-hooks, activated by core.hooksPath
├── docs/
│   ├── repo-structure-contract.md  this repo's declared paths
│   ├── BACKLOG.md                  the live board
│   └── ARCHITECTURE.md
├── scripts/validate.sh             this repo's canonical validation
└── .github/user-stories/           story registry, if the repo uses stories
```

Do not add top-level directories without a contract reason. That rule is the one that keeps
a fleet legible to an agent that has never seen it.

## What a fork gets, and what it does not

Tracked and shared: contracts, templates, skills, gates, launcher, docs, tests, and
placeholder registries.

Never tracked, created per user: `local/` (your fleet), `runtime/control-plane/` (machine
state), `.claude-optimization/memory/` and `state/` (your agent's memory), and the
`~/.claude/` symlinks. The framework works without every one of them — that is the property
that makes it forkable, and `scripts/validate.sh` passing on a clean clone is the test of it.

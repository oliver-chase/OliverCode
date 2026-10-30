# OliverCode Sync Workflow

Use this workflow when the user asks to sync, reconcile, or refresh `OliverCode` metadata and docs.

## Scope

`OliverCode` is the shared orchestration repo at `OliverCode`, not an app repo.

This workflow keeps these files aligned with the live machine state:

- `shared/repo-map.json`
- `core/contracts/*`
- `ARCHITECTURE.md`
- `README.md`
- `CLAUDE.md`
- `shared/workflow-standards.md`

## Procedure

1. Confirm repo health.

```bash
git -C OliverCode status --short --branch
test -d OliverCode
```

2. Run structure drift checks.

```bash
.githooks/pre-commit
```

3. Reconcile local repo inventory against disk.

```bash
ls -1 <fleet-root>
jq -r '.repos[].name + " -> " + .path' OliverCode/shared/repo-map.json
```

4. If inventory drift exists:
- update `shared/repo-map.json`
- update `core/contracts/*` if machine-level aliases or shared roots changed
- align `ARCHITECTURE.md`
- align `README.md` and `CLAUDE.md` references

5. Run impact + structure checks.

```bash
.githooks/pre-commit
bash OliverCode/scripts/validate.sh
bash OliverCode/scripts/link-check.sh
```

6. Commit only sync-scope files.
- Do not stage unrelated runtime churn.
- Use a docs/process commit message.

Example:

```bash
git -C OliverCode add shared/repo-map.json docs README.md CLAUDE.md shared/workflow-standards.md
git -C OliverCode commit -m "docs: sync OliverCode repo map and workflow metadata"
```

7. Push `main` immediately.

```bash
git -C OliverCode push origin main
```

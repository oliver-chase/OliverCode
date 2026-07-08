---
name: structured-code-removal
description: "Remove a feature or module from a codebase by deleting the function, all call sites, dependent functions, signature updates, docstrings, validators, and tests."
---

# Structured Code Removal

## Process

### Phase 1 — Map the Removal Surface

1. Find the primary function/module being removed
2. Find all call sites (grep for function name, module require/import)
3. Find dependent functions (functions that call the target AND are only called by the target)
4. Find test files that test the target
5. Find documentation that references the target
6. Find validators/linters that check the target
7. Find config that references the target

### Phase 2 — Prune Dependents First

Remove dependent functions that have no other callers. Work bottom-up.

### Phase 3 — Remove Call Sites

Remove/replace each call to the target. Replace with:
- No-op (if the call had no side effects)
- Inline the logic (if simple)
- Redirect to a different function

### Phase 4 — Remove Primary

Delete the main function/module file.

### Phase 5 — Clean Up

- Remove tests
- Remove docs
- Remove validators
- Remove dead config entries
- Remove dead imports/exports

### Phase 6 — Verify

```bash
# No remaining references
grep -rn "functionName\|moduleName" --include="*.js" --include="*.ts" --include="*.py"

# Tests pass
<test-runner>

# App still starts
<startup-command>
```

## Pitfalls

- **Don't remove a function that's exported and used by another repo.** Check if it's a shared module.
- **Don't remove a function used in a cron script or shell wrapper.** Those aren't caught by code search.
- **Don't remove config entries that would break startup.** Some config is read unconditionally.
- **Don't remove imports that are re-exported.** A file might `import X` and `export { X }` — removing the import breaks downstream.

---

> Authored 2026-06-12.

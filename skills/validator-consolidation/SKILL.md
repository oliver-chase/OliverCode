---
name: validator-consolidation
description: "Consolidate overlapping validate-* scripts into grouped validators without breaking runners, docs, or nested-repo git boundaries."
---

# Validator Consolidation

## When to Consolidate

Multiple `validate-*.js` / `validate-*.sh` scripts with:
- Overlapping concerns (e.g., validate-email.js + validate-format.js both check email format)
- Shared dependencies (both read config.sheets.js)
- Different entry points (CLI flag vs direct run vs CI)

## Consolidation Pattern

### Step 1 — Map All Validators

```
scripts/
  validate-email.js       — checks email format + domain validity
  validate-format.js      — checks email format + subject format
  validate-coverage.js    — checks field coverage
  validate-structure.js   — checks directory structure
```

Identify overlap: email format is checked in 2 scripts.

### Step 2 — Create Grouped Validator

```javascript
// scripts/validators.js
module.exports = {
  emailFormat: function(email) { ... },
  subjectFormat: function(subject) { ... },
  fieldCoverage: function(fields) { ... },
  directoryStructure: function(dir) { ... },
};
```

### Step 3 — Update Individual Scripts

Each script calls the grouped validator:

```javascript
// validate-email.js — now a thin wrapper
const { emailFormat } = require('./validators');
var result = emailFormat(process.argv[2]);
console.log(result);
process.exit(result.valid ? 0 : 1);
```

### Step 4 — Update Runners

- Update CI config if it references individual script paths
- Update cron scripts if they call individual validators
- Update `package.json` scripts if they point to individual files

### Step 5 — Remove Old Scripts

Only after all runners are updated. Verify no `grep -rn "validate-email.js"` finds references.

## Pitfalls

- **Don't consolidate if scripts run at different lifecycle stages** (pre-commit vs CI vs ad-hoc). They may have different exit expectations.
- **Don't change exit codes.** If validate-email exits 1 on invalid, the consolidated version must too.
- **Don't consolidate test validators with production validators.** They serve different purposes.
- **Update docs last.** After all code changes, update any docs that list individual validators.

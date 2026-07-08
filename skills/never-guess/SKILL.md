---
name: never-guess
description: "When you don't know something, never guess — ask or look at the actual data."
---

# Never Guess — Data-First Protocol

**Core rule:** If you don't know, look it up. Don't estimate, don't assume, don't fabricate.

## When to Apply

| Situation | Instead of Guessing | Do This |
|-----------|-------------------|---------|
| File path unknown | Assume a probable path | `Glob(pattern)` or `Grep(pattern, path)` to locate it |
| Repo structure unknown | "probably under src/" | `Bash("ls -R")` or `Glob("**/*")` |
| Config value unknown | "likely 5" | `Read(config_file)` |
| Code behavior unknown | "should work" | `Bash("<test command>")` or read the code |
| File exists? | "I think so" | `Bash("test -f path && echo YES")` or just `Read(path)` and check the result |
| Metric unknown | "about X%" | Query the data source directly |

## Pitfalls

- **Don't fabricate directory listings.** If `ls` shows nothing, say it's empty.
- **Don't "recall" file contents** from memory. Read the file.
- **When searching:** if the first `Grep`/`Glob` finds nothing, try a different pattern — don't say "not found" after one attempt.
- **When reading:** if `Read` says not found, try the relative path and the vault-relative path.
- **No "around line X"** — use exact line numbers from the live file on disk. `Read` outputs line numbers.

---

> Authored 2026-06-12.

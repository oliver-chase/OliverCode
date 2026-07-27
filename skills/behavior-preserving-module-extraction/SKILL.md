---
name: behavior-preserving-module-extraction
description: "Use when the user says a script is 'too big', 'needs to be split up', 'extract a module from this', 'pull this logic into its own file', or wants a large script refactored into smaller pieces without changing behavior. Uses wrapper delegation and dependency injection so existing call sites keep working."
---

# Behavior-Preserving Module Extraction

## When to Use

A single file has grown past 500+ lines. It contains distinct clusters of functionality that don't share much state.

## 4-Step Process

### Step 1 — Identify Extractions

Scan the large file for:
- Functions that share a common prefix or import set
- Functions that all use the same data source (DB, API, file)
- Functions that can be tested independently

Group them into a proposed module.

### Step 2 — Create the Module

```python
# lib/new_module.py — extracted from big_script.py
def function_a(input):
    ...

def function_b(input):
    ...

def function_c(input):
    ...

```

Import it in the original file:

```python
from lib.new_module import function_a, function_b, function_c
```

### Step 3 — Wrapper Delegation

Replace the original function bodies with calls to the new module. Same signature, same behavior:

```python
# OLD
def function_a(input):
    # 50 lines of logic

# NEW
from lib.new_module import function_a as _function_a

def function_a(input):
    return _function_a(input)
```

This preserves all call sites — no caller needs to change.

### Step 4 — Remove Wrappers (Optional)

Once the new module is stable, update all call sites to import directly from the module. Then remove the wrapper functions from the original file.

## Fast Feedback

- Run tests after every extraction, not after all 6
- If the test suite is slow, run only the tests that touch the extracted functions
- Run the app and exercise the extracted functions manually if no automated tests exist

## Pitfalls

- **Don't extract if the functions share mutable global state.** Module extraction works for stateless or dependency-injected functions.
- **Don't extract if the functions use module-level imports that would cause circular dependencies.**
- **Don't change signatures during extraction.** Preserve the exact signature, including defaults.
- **Don't extract during a bug fix.** Extraction changes file layout — bug fixes change behavior. Do one at a time.

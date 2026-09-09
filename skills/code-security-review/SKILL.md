---
name: code-security-review
description: "Review code for real security vulnerabilities — injection, auth/authz bypass, insecure deserialization, secret handling, SSRF, path traversal, XSS, insecure direct object references. Use when the user asks for a security review, mentions a vulnerability class by name, or when touching auth, input parsing, file paths, external requests, or serialization."
---

# Security Review

A procedural checklist for finding real, exploitable vulnerabilities — not a restatement of "don't hardcode secrets." Pre-commit hooks already catch secrets/PII mechanically (`.githooks/pre-commit` Gate 1). This skill covers what a mechanical gate can't: judgment calls about how untrusted input flows through the system.

## Process

### Phase 1 — Map Trust Boundaries

Before looking for specific bugs, identify where untrusted data enters the system:
- User input (form fields, query params, request bodies, headers, cookies)
- File uploads and their declared vs. actual content type
- Data from third-party APIs or webhooks (even "trusted" partners can be compromised or send malformed data)
- Data read back from a database that another, less-trusted code path wrote

Everything downstream of these boundaries is suspect until validated. Everything upstream (internal config, code constants) is not the target of this review.

### Phase 2 — Walk Each Vulnerability Class Against the Boundaries Found

For each trust boundary from Phase 1, check the vulnerability classes that apply to how that data is used:

| Class | Look for | Concrete check |
|---|---|---|
| Injection (SQL/NoSQL/command/template) | User input concatenated into a query, shell command, or template string | `grep` for string concatenation or f-strings feeding into `execute(`, `exec(`, `spawn(`, template render calls — the fix is parameterized queries / escaped templating, never a blocklist |
| Auth bypass | An endpoint or action that should require a specific role/owner but only checks "is logged in" | For every mutating endpoint, confirm the check is "is this the right user," not just "is this a user" |
| Insecure Direct Object Reference (IDOR) | An ID taken from the request used to fetch/mutate a record without checking the requester owns it | `/api/orders/:id` that queries `orders WHERE id = :id` with no `AND user_id = current_user` clause |
| Insecure deserialization | `pickle.loads`, `yaml.load` (not `safe_load`), `eval`/`Function()` on data that crossed a trust boundary | Any deserializer that can execute code, fed by anything from Phase 1 |
| SSRF | Server making an outbound request to a URL supplied (even partially) by the user | Webhook URLs, "fetch this image from a URL" features, PDF/screenshot generators that follow user-supplied URLs |
| Path traversal | User-supplied filename/path used in a filesystem operation without normalization | `../../etc/passwd`-style checks — confirm the path is resolved and checked against an allowed root, not just string-matched for `..` |
| XSS | User content rendered without escaping, especially `dangerouslySetInnerHTML`/`v-html`/raw template output | Any place user content reaches the DOM outside the framework's default auto-escaping |
| CSRF | State-changing endpoint reachable via a simple `GET` or missing origin/token check | Relevant mainly for cookie-session auth. Less relevant for bearer-token APIs |
| Dependency vulnerabilities | Known-CVE packages in use | `npm audit` / `pip-audit` / equivalent — don't hand-review what a scanner already covers |

Skip rows that don't apply to the boundaries actually found in Phase 1 — a read-only static site has no SQL injection surface to check.

### Phase 3 — Verify, Don't Assume

A framework's default behavior is not a substitute for confirming it. React escapes by default. A specific component might still use `dangerouslySetInnerHTML`. An ORM parameterizes by default. A specific query might still use raw SQL for a "quick fix." Grep for the actual escape hatches (`dangerouslySetInnerHTML`, `raw(`, `execute(f"`, `.raw(`) rather than trusting the stack's general reputation.

### Phase 4 — Report

For each finding: the trust boundary, the vulnerability class, the exact file:line, a concrete exploit scenario (what input, what happens), and the fix. A finding without an exploit scenario is a style nitpick, not a security finding — if you can't describe how it's actually exploited, don't report it as a vulnerability.

## Pitfalls

- **Don't confuse "looks risky" with "is exploitable."** A raw SQL query built from a hardcoded string with no user input in it is not a SQL injection risk, however it looks. Trace the actual data flow before flagging.
- **Don't stop at the first layer.** An API that validates input at the route handler but calls an internal function elsewhere that skips validation is still vulnerable if that internal function is reachable another way.
- **Secrets in code are a different, already-mechanically-caught problem.** Don't spend review time re-finding what `.githooks/pre-commit` Gate 1 already blocks — this skill is for the vulnerability classes that require judgment, not pattern-matching.
- **A security review is not a rewrite.** Fix the specific vulnerable line. Don't use the finding as license to refactor the surrounding code.

## Related Skills

- `repo-audit-with-execution-batches` — Batch 6 (Security Surface) is a lightweight presence check (secrets, `.gitignore` coverage, public exposure) as part of a broader 7-part audit. Hand off to this skill for the actual vulnerability-class walkthrough rather than improvising it inline there.
- `diagnosing-bugs` — if a security finding needs root-cause work to understand why a check is missing (not just confirming that it's missing), switch to that skill for the investigation, then return here for the fix.

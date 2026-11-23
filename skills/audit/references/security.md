# Security

A security audit reports proven boundary crossings and nothing else. A finding names a lower-trust principal, the boundary it crosses and the effect observed on the other side. This route loads on "security audit" and runs the procedure of `SKILL.md` with the steps below in place of the lens tables.

## 1. Map

Write the map before judging any code. Read the repo and record:

- **Principals.** Each kind of actor (anonymous visitor, signed-in user, another tenant, admin, a service, a build or CI job, a dependency) and what each one holds: credentials, tokens, files, network reach, permissions
- **Entry points.** Every place input enters: HTTP routes, CLI arguments, files and uploads, queues and webhooks, environment variables, model or tool output, issue and PR text
- **Sinks.** Every place input lands: queries, shell and process calls, file paths, templates and HTML, deserializers, outbound requests, logs, permission and identity decisions
- **Trust edges.** Each place data or authority moves from a lower-trust principal to a higher one

The map is the first thing in the report's "What it is" section, as a table of principal, holds, entry points and sinks.

## 2. Load attack classes

Load only the class whose boundary the map found. A class with no matching entry point and sink is reported as "Checked, nothing found: no such boundary".

| Boundary found | Class | What to prove |
|---|---|---|
| Input reaches a shell, process or eval | Code and command execution | The input reaches the call unescaped, and the call runs it |
| Input reaches a query or template | Injection | The input changes the structure of the query or template |
| Input reaches a file path or archive entry | Path traversal | A path outside the intended root is read or written |
| Input reaches an outbound request | Server-side request forgery | The server fetches an address the caller chose, including internal ones |
| Input reaches HTML or a rendered page | Cross-site scripting | The input runs as script in another user's session |
| A route, command or tool acts for a principal | Authorization | A lower-trust principal performs an action or reads data reserved for another |
| A token, key or session is issued or checked | Authentication and secrets | A credential is forged, guessed, replayed, leaked to a lower-trust reader or kept in the repo |
| Bytes are deserialized or parsed from outside | Unsafe parsing | The parser builds objects or consumes resources the sender controls |
| CI, hooks, installers or dependencies run code | Supply chain | Untrusted code or text gets the job's secrets or write access |
| A model or agent reads untrusted text and holds tools | Prompt injection | Text from a lower-trust author changes what a tool with higher trust does |

## 3. Candidate gate

Each candidate passes this gate before it is a finding:

1. **Principal.** The lower-trust actor is named, and the map shows how they reach the entry point
2. **Boundary.** The boundary crossed is named, with the `file:line` of the entry point and the sink
3. **Effect.** The effect was observed: a reproduced request, a run of the code, or a traced path where each hop is read in the code. Reading a pattern that looks dangerous is not an observation

A candidate that fails the gate is a hardening note. A missing header, an absent rate limit, an outdated dependency with no reachable path and any best practice with no named principal, boundary or effect are hardening notes. They are listed once under "Read and unknown" with no priority and no issue, and no story is filed for them.

## 4. Severity

- **P0.** A proven crossing that gives a lower-trust principal code execution, another principal's data, or an admin action
- **P1.** A proven crossing with a bounded effect, such as a read of one class of non-secret data or an action on one resource
- **P2.** A proven crossing that needs a precondition the attacker cannot supply alone
- A crash, hang or exception is a denial-of-service candidate at most. It is raised to code execution only with a traced path from the input to the call that executes it, each hop read in the code

## 5. Report

Use the standard report headings. The findings table carries the principal, boundary, `file:line`, the observed effect and the smallest fix. Run each reproduction in a scratch copy and never against production or a real credential. File each finding by the standard procedure.

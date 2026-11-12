# Accepted audit rows

Audit findings the owner reviewed and kept, each with its reason. `skills/audit/scripts/done_check.py` reads the `Accepted:` lines and skips those rows.

Accepted: history-secret ed41d65 - secret-gate test fixture header only, no key material
Accepted: history-secret 4d0689e - secret-gate test fixture header only, no key material
Accepted: personal-email <owner-email> - the repository stays private, and docs/SHARING.md says how a public release leaves this history behind
Accepted: personal-email <owner-email> - the repository stays private, and docs/SHARING.md says how a public release leaves this history behind
Accepted: oversized scripts/lib/backlog_setup.py:1 - one cohesive command; a split adds an import seam with no reader
Accepted: owner-identity docs/AUDIT-ACCEPTED.md - this file names the accepted history addresses so done_check can match them

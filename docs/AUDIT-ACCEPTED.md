# Accepted audit rows

Audit findings the owner reviewed and kept, each with its reason. `skills/audit/scripts/done_check.py` reads the `Accepted:` lines and skips those rows.

Accepted: personal-email 2-addresses - pushed history cannot be rewritten
Accepted: history-secret 1-commits - the one commit is a made-up test fixture for redaction (skills/diagnosing-bugs/scripts/test_hitl_loop.py), never a credential; nothing to revoke, history not rewritten (#1399)

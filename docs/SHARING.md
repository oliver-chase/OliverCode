# Sharing

Sharing: portable - the shipped files name no machine and no owner beyond this repository's own board address in docs/backlog-config.json, which a fork replaces with `olivercode backlog-setup --apply`, and a fork sets its own paths in olivercode.local.json.

The repository is public. A second person gets the code by cloning the public repo, or by forking it on GitHub and cloning the fork. The history rows the audit reports are listed in `docs/AUDIT-ACCEPTED.md`. `python3 scripts/qa/leak_scan.py` names every tracked file that carries the owner's name, handle, email domain or home path (it derives them from git history and the origin remote, and exempts `docs/backlog-config.json`, which a fork replaces with `olivercode backlog-setup --apply`). `--release DIR` writes the one-commit neutral copy to DIR and scans it.

History keeps the owner's personal author address on earlier commits, and rewriting history is out of scope. Because the repository is public, a clone or fork carries that address. A fork's own commits use a GitHub noreply address, and `--release DIR` gives a copy without that history.

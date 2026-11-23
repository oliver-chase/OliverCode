"""`olivercode audit-mode [full|gated]`: show or change how the audit proceeds after its report."""

import sys

from lib.local_config import OC_ROOT


def command_audit_mode(argv: list[str]) -> int:
    scripts = str(OC_ROOT / "skills" / "audit" / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import audit_mode
    if len(argv) > 1 or (argv and argv[0] not in audit_mode.MODES):
        print("Usage: olivercode audit-mode [full|gated]")
        return 1
    return audit_mode.main(["set", argv[0]] if argv else [])

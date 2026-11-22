#!/usr/bin/env python3
"""Refuse the superseded manual Grafana admission writer before all effects.

Current app admission belongs to the catalog-driven reconciler and its Ansible
hook, not this historical preparation helper. Never forward execution: the
replacement has its own reviewed plan/apply gates and credential requirements.
"""

import sys


def main() -> int:
    """Report the authoritative owner without reading arguments or credentials."""
    sys.stderr.write(
        "Retired: grafana-app-admission.py does not read credentials or change identity.\n"
        "Current contract: docs/auth/app-access-groups.md\n"
        "Owner: ansible/roles/authentik/files/reconcile_app_access.py and "
        "ansible/roles/identity_app_access/\n"
        "Review that owner's separate plan/apply prerequisites; nothing was forwarded.\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

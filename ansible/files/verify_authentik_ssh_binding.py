"""Read-only root preflight. Refuse automatic adoption of existing Linux accounts.

A root-owned enrollment marker reserves a reviewed UUID/name pair before the
users role runs. No marker is inferred from usernames, email, groups or keys.
"""
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import uuid

DIRECTORY = Path('/var/lib/homelab-authentik-ssh-bindings')


def verify(name, ident, directory=DIRECTORY):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', name) or name in {'root', 'alchemmist', 'ghactions'}:
        raise ValueError('Restricted username required')
    if str(uuid.UUID(ident)) != ident or uuid.UUID(ident).int == 0:
        raise ValueError('Canonical UUID required')
    try:
        pwd.getpwnam(name)
        exists = True
    except KeyError:
        exists = False
    marker = directory / (name + '.json')
    if os.path.lexists(directory):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('Enrollment directory must be root-owned and private')
    if os.path.lexists(marker):
        info = marker.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 1024:
            raise ValueError('Enrollment marker must be a private root-owned regular file')
        if json.loads(marker.read_text()) != {'name': name, 'uuid': ident}:
            raise ValueError('Immutable host binding mismatch')
    elif exists:
        raise ValueError('Existing unbound Linux account: stop for separately reviewed migration')
    return {'bindingVerified': True, 'accountExists': exists}


if __name__ == '__main__':
    try:
        print(json.dumps(verify(*sys.argv[1:])))
    except (ValueError, OSError, TypeError):
        # Never print raw files/exception text from a host.
        raise SystemExit('SSH binding preflight refused; inspect account ownership and root enrollment marker')

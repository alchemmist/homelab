#!/usr/bin/env python3
"""Forced-command SSH receiver: append-only dated n8n archives, no remote shell."""
import datetime
import hashlib
import os
from pathlib import Path
import sys
import uuid


def main():
    os.umask(0o077)
    if os.environ.get('SSH_ORIGINAL_COMMAND', '') not in ('', 'receive-n8n-backup'):
        raise SystemExit('unsupported command')
    directory = Path.home() / 'backups/n8n'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = 'n8n-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12] + '.tar.gz'
    partial = directory / (name + '.partial')
    digest = hashlib.sha256()
    size = 0
    try:
        with partial.open('xb') as out:
            while chunk := sys.stdin.buffer.read(1024 * 1024):
                size += len(chunk)
                if size > 2 * 1024**3:
                    raise ValueError('archive exceeds 2 GiB limit')
                out.write(chunk)
                digest.update(chunk)
            out.flush()
            os.fsync(out.fileno())
        if size < 32:
            raise ValueError('empty/truncated archive')
        # No unpacking of untrusted paths. Atomic publication only after EOF.
        partial.rename(directory / name)
        with (directory / (name + '.sha256')).open('x') as out:
            out.write(digest.hexdigest() + '  ' + name + '\n')
        print(name, size, digest.hexdigest())
    finally:
        partial.unlink(missing_ok=True)


if __name__ == '__main__':
    main()

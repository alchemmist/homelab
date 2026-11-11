#!/usr/bin/env python3
"""Forced-command SSH receiver: append-only dated n8n archives, no remote shell."""
import datetime
import hashlib
import os
from pathlib import Path
import sys
import gzip
import tarfile
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
        # Fully validate gzip CRC before publishing. Never extract remote paths.
        with gzip.open(partial, 'rb') as compressed:
            expanded = 0
            while chunk := compressed.read(1024 * 1024):
                expanded += len(chunk)
                if expanded > 4 * 1024**3:
                    raise ValueError('expanded archive exceeds limit')
        with tarfile.open(partial, 'r:gz') as archive:
            names = {m.name.removeprefix('./') for m in archive.getmembers()}
            if not {'data/database.sqlite', 'manifest.json', 'encryption-key'} <= names:
                raise ValueError('missing recovery state')
        # Atomic publication only after successful transfer and archive validation.
        partial.rename(directory / name)
        with (directory / (name + '.sha256')).open('x') as out:
            out.write(digest.hexdigest() + '  ' + name + '\n')
        print(name, size, digest.hexdigest())
    finally:
        partial.unlink(missing_ok=True)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Run INSIDE the worker via explicit operator exec, never service startup.
Before EVERY Git push (auto-Argo) and before future two-job retry:
backup online SQLite to private PVC file, stream stdout to host0600, remove PVC
file in finally. Caller must use umask077 and redirect stdout directly to a
private file, never terminal/log. No serialize(), restores or lease changes.
"""
import argparse
import os
import sqlite3
import sys
import tempfile
import time


def backup(source, directory, max_bytes=512*1024*1024, deadline_seconds=60):
    os.umask(0o077)
    fd,path=tempfile.mkstemp(prefix='.spi-prechange-',suffix='.sqlite',dir=directory)
    os.close(fd)
    start=time.monotonic()
    try:
        src=sqlite3.connect('file:'+source+'?mode=ro',uri=True)
        dst=sqlite3.connect(path)
        try:
            def progress(status,remaining,total):
                if total*src.execute('PRAGMA page_size').fetchone()[0]>max_bytes or time.monotonic()-start>deadline_seconds:
                    raise RuntimeError('backup bound exceeded')
            src.backup(dst,pages=128,progress=progress,sleep=0.05)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise RuntimeError('backup integrity failure')
        finally:
            dst.close();src.close()
        if os.path.getsize(path)>max_bytes:
            raise RuntimeError('backup size exceeded')
        with open(path,'rb') as f:
            while True:
                chunk=f.read(64*1024)
                if not chunk:break
                sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
    finally:
        for suffix in ('','-wal','-shm','-journal'):
            try:os.unlink(path+suffix)
            except FileNotFoundError:pass

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',default='/data/spi.sqlite')
    p.add_argument('--private-pvc-directory',required=True)
    a=p.parse_args();backup(a.source,a.private_pvc_directory)

#!/usr/bin/env python3
"""Private CLI-only online backup. Failed/truncated stdout MUST be deleted.
POSIX main-thread deadline assumes normally interruptible OS I/O; no guarantee
is possible for uninterruptible kernel I/O. Never invoke in HTTP worker threads.
"""
import argparse
import os
import signal
import sqlite3
import sys
import tempfile
import time


def backup(source, directory, max_bytes=512*1024*1024, deadline_seconds=60):
    if deadline_seconds <= 0 or max_bytes <= 0:
        raise ValueError('invalid bounds')
    start=time.monotonic()
    old_handler=signal.getsignal(signal.SIGALRM)
    old_timer=signal.getitimer(signal.ITIMER_REAL)
    path=None; src=None; dst=None
    def expired(*args):
        raise TimeoutError('backup deadline exceeded')
    def check():
        if time.monotonic()-start >= deadline_seconds:
            expired()
    signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,deadline_seconds)
    try:
        fd,path=tempfile.mkstemp(prefix='.spi-prechange-',suffix='.sqlite',dir=directory)
        os.close(fd)
        src=sqlite3.connect('file:'+source+'?mode=ro',uri=True,timeout=min(0.05,deadline_seconds))
        dst=sqlite3.connect(path,timeout=min(0.05,deadline_seconds))
        page_size=src.execute('PRAGMA page_size').fetchone()[0]
        def progress(status,remaining,total):
            check()
            if total*page_size>max_bytes:
                raise RuntimeError('backup size exceeded')
        src.backup(dst,pages=128,progress=progress,sleep=0.01)
        dst.set_progress_handler(lambda: int(time.monotonic()-start >= deadline_seconds),100)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise RuntimeError('backup integrity failure')
        check()
        dst.close();dst=None
        src.close();src=None
        if os.path.getsize(path)>max_bytes:
            raise RuntimeError('backup size exceeded')
        with open(path,'rb') as f:
            while True:
                check()
                chunk=f.read(64*1024)
                if not chunk:break
                sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        check()
    finally:
        try:
            if dst is not None:dst.close()
            if src is not None:src.close()
            if path:
                for suffix in ('','-wal','-shm','-journal'):
                    try:os.unlink(path+suffix)
                    except FileNotFoundError:pass
        finally:
            signal.setitimer(signal.ITIMER_REAL,0)
            signal.signal(signal.SIGALRM,old_handler)
            if old_timer[0]:
                signal.setitimer(signal.ITIMER_REAL,max(0.000001,old_timer[0]-(time.monotonic()-start)),old_timer[1])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',default='/data/spi.sqlite')
    p.add_argument('--private-pvc-directory',required=True)
    p.add_argument('--deadline-seconds',type=float,default=60)
    a=p.parse_args()
    try:
        backup(a.source,a.private_pvc_directory,deadline_seconds=a.deadline_seconds)
    except Exception:
        # Do not expose SQLite messages, paths, source data or credentials.
        print('BACKUP_FAILED: output invalid; delete private host file',file=sys.stderr)
        # Avoid interpreter shutdown re-flushing a broken/blocked stdout pipe.
        os._exit(1)

if __name__=='__main__':main()

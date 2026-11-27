#!/usr/bin/env python3
"""Witness transaction: an ambiguous disconnect leaves a durable global hold."""

import fcntl
import os
import sys
from pathlib import Path


def serve(directory: Path, owner: str, incoming, outgoing) -> int:
    if owner not in ("socrat-2", "socrat-4"):
        return 2
    with (directory / "transition.lock").open("a") as mutex:
        try:
            fcntl.flock(mutex, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 1
        claim = directory / "transition.claim"
        try:
            stream = claim.open("x")
        except FileExistsError:
            return 1
        fd = os.open(directory, os.O_DIRECTORY)
        try:
            with stream:
                stream.write(owner + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(fd)
            outgoing.write(b"LOCKED\n")
            outgoing.flush()
            # Never clear ownership on EOF, timeout, crash or an unknown verb.
            # Only the session that created the hold can commit or abort it.
            if incoming.readline(16) not in (b"COMMIT\n", b"ABORT\n"):
                return 2
            claim.unlink()
            os.fsync(fd)
            outgoing.write(b"RELEASED\n")
            outgoing.flush()
            return 0
        finally:
            os.close(fd)


if __name__ == "__main__":
    os.umask(0o077)
    sys.exit(
        serve(
            Path("/var/lib/homelab-vpn-witness"),
            sys.argv[1],
            sys.stdin.buffer,
            sys.stdout.buffer,
        )
    )

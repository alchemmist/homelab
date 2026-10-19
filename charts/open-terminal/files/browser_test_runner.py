#!/usr/bin/env python3
import argparse
import ctypes
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def processes():
    result = {}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            stat = (directory / 'stat').read_text()
            fields = stat[stat.rindex(')') + 2:].split()
            result[int(directory.name)] = (int(fields[1]), int(fields[19]))
        except (OSError, ValueError, IndexError):
            pass
    return result


def descendants():
    current = processes()
    parents = {os.getpid()}
    owned = set()
    while True:
        children = {(pid, start) for pid, (ppid, start) in current.items() if ppid in parents}
        additions = children - owned
        if not additions:
            return owned
        owned.update(additions)
        parents.update(pid for pid, start in additions)


def send(identity, sig):
    pid, start = identity
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        stat = Path(f'/proc/{pid}/stat').read_text()
        current_start = int(stat[stat.rindex(')') + 2:].split()[19])
        if current_start == start:
            signal.pidfd_send_signal(descriptor, sig)
    except (ProcessLookupError, FileNotFoundError):
        pass
    finally:
        os.close(descriptor)


def reap():
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def cleanup(owned, grace):
    deadline = time.monotonic() + grace
    while True:
        owned.update(descendants())
        current = processes()
        owned = {identity for identity in owned if current.get(identity[0], (None, None))[1] == identity[1]}
        if not owned:
            return
        expired = time.monotonic() >= deadline
        for identity in owned:
            send(identity, signal.SIGKILL if expired else signal.SIGTERM)
        reap()
        if expired and time.monotonic() >= deadline + 2:
            raise RuntimeError('Browser test processes did not exit after SIGKILL')
        time.sleep(0.05)


def run(command, timeout=180, grace=2):
    if sys.platform != 'linux':
        raise RuntimeError('homelab-browser-test requires Linux')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    interrupted = []
    previous = {}
    owned = set()
    process = None
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous[sig] = signal.signal(sig, lambda number, frame: interrupted.append(number))
    try:
        process = subprocess.Popen(command, start_new_session=True)
        deadline = time.monotonic() + timeout
        while True:
            owned.update(descendants())
            result = process.poll()
            if interrupted:
                return 128 + interrupted[0]
            if result is not None:
                return result if result >= 0 else 128 - result
            if time.monotonic() >= deadline:
                print(f'Browser test exceeded {timeout:g} seconds; terminating its processes', file=sys.stderr)
                return 124
            time.sleep(0.05)
    finally:
        try:
            cleanup(owned, grace)
            if process is not None:
                process.wait()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('timeout must be finite and positive')
    return number


def main():
    parser = argparse.ArgumentParser(description='Run a bounded browser test and clean up all its child processes')
    parser.add_argument('--timeout', type=positive, default=180)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('a command is required after --')
    try:
        return run(command, args.timeout)
    except (OSError, RuntimeError) as error:
        print(f'Browser test failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

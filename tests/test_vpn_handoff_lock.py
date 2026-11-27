"""Exercise a candidate host-local writer interlock with independent processes."""

import fcntl
import subprocess
import sys


def test_writer_gate_survives_contender_restart_and_releases_on_owner_exit(tmp_path):
    gate = tmp_path / "vpn-owner.lock"
    gate.touch()
    contender = """import fcntl, sys
with open(sys.argv[1], 'rb') as gate:
    try:
        fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(42)
"""
    owner = """import fcntl, sys
with open(sys.argv[1], 'rb') as gate:
    fcntl.flock(gate, fcntl.LOCK_EX)
    print('ready', flush=True)
    sys.stdin.read()
"""
    with subprocess.Popen(
        [sys.executable, "-c", owner, str(gate)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    ) as process:
        try:
            assert process.stdout.readline() == b"ready\n"
            for _ in range(3):
                assert (
                    subprocess.run(
                        [sys.executable, "-c", contender, str(gate)], timeout=5
                    ).returncode
                    == 42
                )
        finally:
            process.kill()
    with gate.open("rb") as recovered:
        fcntl.flock(recovered, fcntl.LOCK_EX | fcntl.LOCK_NB)

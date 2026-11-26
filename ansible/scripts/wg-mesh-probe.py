#!/usr/bin/env python3
"""Measure directed reachability on wg-socrat; atomically publish textfile metrics."""

import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OUT = Path('/var/lib/node_exporter/textfile_collector')


def probe(peer):
    label, ip = peer.split('=', 1)
    result = subprocess.run(
        ['ping', '-n', '-I', 'wg-socrat', '-q', '-c', '3', '-W', '2', ip],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12, check=False,
    )
    return f'socrat_wg_mesh_reachable{{source="{sys.argv[1]}",target="{label}"}} {int(result.returncode == 0)}\n'


def main():
    with ThreadPoolExecutor(max_workers=12) as pool:
        metrics = ''.join(pool.map(probe, sys.argv[2:]))
    metrics += f'socrat_wg_mesh_checked_seconds{{source="{sys.argv[1]}"}} {int(time.time())}\n'
    with tempfile.NamedTemporaryFile(mode='w', dir=OUT, delete=False) as tmp:
        tmp.write(metrics)
    os.chmod(tmp.name, 0o644)
    os.replace(tmp.name, OUT / 'wg-socrat-mesh.prom')


if __name__ == '__main__':
    main()

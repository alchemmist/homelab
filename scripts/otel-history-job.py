import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def launch(binary, backup, workspace, receipt, max_bytes, timeout):
    workspace = workspace.resolve(strict=True)
    for forbidden in ('/var/lib', '/private/var/lib', '/host', '/etc', '/private/etc', '/srv'):
        if workspace == Path(forbidden) or Path(forbidden) in workspace.parents:
            raise ValueError('Production workspaces are forbidden')
    if workspace.stat().st_mode & 0o077:
        raise ValueError('Migration workspace must be private')
    if not (workspace / 'state.json').is_file():
        raise ValueError('A prepared migration workspace is required')
    jobs = workspace / 'jobs'
    if jobs.is_symlink():
        raise ValueError('Symlinked job directories are forbidden')
    jobs.mkdir(mode=0o700, exist_ok=True)
    run = jobs / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8])
    run.mkdir(mode=0o700)
    pinned = run / 'otel-history'
    shutil.copyfile(binary, pinned)
    pinned.chmod(0o700)
    command = [sys.executable, str(ROOT / 'scripts/otel-history-migrate.py'),
               '--binary', str(pinned), '--backup', str(backup.resolve(strict=True)),
               '--receipt', str(receipt.resolve(strict=True)), '--workspace', str(workspace),
               '--resume', '--revalidate-classifier', '--resume-partial-exports', '--max-bytes-per-block', str(max_bytes),
               '--command-timeout-seconds', str(timeout)]
    request = {'schemaVersion': 1, 'createdAt': datetime.now(timezone.utc).isoformat(),
               'binarySHA256': hashlib.sha256(pinned.read_bytes()).hexdigest(),
               'command': command, 'productionModified': False,
               'environment': {'GOMEMLIMIT': '2GiB', 'GOMAXPROCS': '2'},
               'memoryLimitIsSoft': True}
    save(run / 'request.json', request)
    descriptor = os.open(run / 'worker.log', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as log:
        worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_run', '--run-directory', str(run)],
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                  start_new_session=True)
    save(run / 'worker.json', {'pid': worker.pid, 'runDirectory': str(run)})
    return {'pid': worker.pid, 'runDirectory': str(run)}


def execute(run):
    request = json.loads((run / 'request.json').read_text())
    environment = {**os.environ, **request['environment']}
    try:
        if hashlib.sha256((run / 'otel-history').read_bytes()).hexdigest() != request['binarySHA256']:
            raise OSError('Pinned binary checksum mismatch')
        result = subprocess.run(request['command'], env=environment, check=False)
        receipt = {'finishedAt': datetime.now(timezone.utc).isoformat(), 'returnCode': result.returncode,
                   'success': result.returncode == 0, 'productionModified': False}
    except OSError as error:
        receipt = {'finishedAt': datetime.now(timezone.utc).isoformat(), 'returnCode': None,
                   'success': False, 'error': str(error), 'productionModified': False}
    save(run / 'result.json', receipt)
    return 0 if receipt['success'] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['launch', '_run'])
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--receipt', type=Path, default=ROOT / 'deploy/monitoring/migration-evidence/backup-20261028.json')
    parser.add_argument('--run-directory', type=Path)
    parser.add_argument('--max-bytes-per-block', type=int, default=64 * 1024 ** 3)
    parser.add_argument('--command-timeout-seconds', type=int, default=43200)
    args = parser.parse_args()
    try:
        if args.action == '_run':
            if args.run_directory is None:
                raise ValueError('run-directory is required')
            return execute(args.run_directory.resolve(strict=True))
        if args.binary is None or args.backup is None or args.workspace is None:
            raise ValueError('binary, backup and workspace are required')
        if args.max_bytes_per_block <= 0 or args.command_timeout_seconds <= 0:
            raise ValueError('Byte and time budgets must be positive')
        print(json.dumps(launch(args.binary.resolve(strict=True), args.backup, args.workspace, args.receipt,
                                args.max_bytes_per_block, args.command_timeout_seconds), indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

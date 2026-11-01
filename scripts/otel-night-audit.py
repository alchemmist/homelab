"""Finite, read-only overnight audit alongside an already running historical job.

Does not enable production ingestion, clear prerequisites, or count as a soak.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def save(path, document):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(document, indent=2) + '\n')
    temporary.replace(path)


def audit(args):
    os.umask(0o077)
    args.output.mkdir(mode=0o700, exist_ok=False)
    environment = {**os.environ, 'PATH': '/tmp/otel-migration-ssh/bin:' + os.environ['PATH']}
    report = {'startedAt': datetime.now(timezone.utc).isoformat(), 'productionModified': False,
              'prerequisitesAutomaticallyCleared': False, 'productionCutoverPerformed': False,
              'soakStarted': False, 'cycles': [], 'success': False}
    try:
        for index in range(args.hours):
            cycle = args.output / ('cycle-%02d' % index)
            cycle.mkdir(mode=0o700)
            inventory, check = cycle / 'inventory.json', cycle / 'preflight.json'
            for command in ('collect', 'check'):
                argv = [sys.executable, str(ROOT / 'scripts/otel-migration-preflight.py'), command,
                        '--output', str(inventory if command == 'collect' else check)]
                if command == 'check':
                    argv += ['--inventory', str(inventory)]
                with (cycle / (command + '.log')).open('x') as log:
                    result = subprocess.run(argv, env=environment, stdin=subprocess.DEVNULL, stdout=log,
                                            stderr=subprocess.STDOUT, timeout=300)
                if result.returncode not in ((0,) if command == 'collect' else (0, 1)):
                    raise RuntimeError('Read-only nightly inventory/preflight command failed')
            state = json.loads(args.state.read_text())
            record = {'observedAt': datetime.now(timezone.utc).isoformat(),
                      'verifiedOlderBackupBlocks': sum(item.get('status') == 'roundtrip-verified' for item in state['blocks'].values()),
                      'olderBackupComplete': state.get('complete') is True,
                      'sourceOperation': state.get('currentOperation'),
                      'preflight': json.loads(check.read_text())}
            if args.job_result.exists():
                record['historyJob'] = json.loads(args.job_result.read_text())
                if record['historyJob'].get('success') is not True:
                    raise RuntimeError('Historical job failed; do not start replacement work')
            report['cycles'].append(record)
            save(args.output / 'progress.json', report)
            if args.normalization_result.exists():
                normalized = json.loads(args.normalization_result.read_text())
                report['normalizationCompletedSuccessfully'] = normalized.get('success') is True
                if normalized.get('success') is not True:
                    raise RuntimeError('Native metadata normalization failed')
                if state.get('complete') is True:
                    report['success'] = True
                    report['stopReason'] = 'older-backup-roundtrip-and-metadata-completed; production prerequisites remain independent'
                    break
            if index + 1 < args.hours:
                time.sleep(3600)
        else:
            report['success'] = True
            report['stopReason'] = 'finite-audit-window-ended; this-is-not-migration-completion'
    except Exception as error:
        report['errorType'] = type(error).__name__
        raise
    finally:
        report['finishedAt'] = datetime.now(timezone.utc).isoformat()
        report['migrationCompleted'] = False
        save(args.output / 'result.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('state', 'job-result', 'normalization-result', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--hours', type=int, default=16)
    args = parser.parse_args()
    if not 1 <= args.hours <= 24:
        parser.error('Audit must be finite: 1–24 hours')
    audit(args)

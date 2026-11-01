import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time


def workers(snapshot, group, binary):
    result = []
    for line in snapshot.splitlines():
        fields = line.strip().split(None, 3)
        if len(fields) != 4 or not all(value.isdigit() for value in fields[:3]):
            continue
        pid, process_group, rss = map(int, fields[:3])
        if process_group == group and (fields[3] == str(binary) or fields[3].startswith(str(binary) + ' ')):
            result.append({'pid': pid, 'rssBytes': rss * 1024})
    return result


def observe(run, interval):
    run = run.resolve(strict=True)
    if run.stat().st_mode & 0o077 or run.stat().st_uid != os.getuid():
        raise ValueError('Job directory must be private and controller-owned')
    request = json.loads((run / 'request.json').read_text())
    worker = json.loads((run / 'worker.json').read_text())
    group = worker['pid']
    command = request['command']
    workspace = Path(command[command.index('--workspace') + 1])
    output = run / 'resource-observation.json'
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    result = {'schemaVersion': 1, 'startedAt': datetime.now(timezone.utc).isoformat(),
              'sampleIntervalSeconds': interval, 'samplingMayMissShortPeaks': True,
              'rssScope': 'Go child processes only; excludes coordinator and supervisor',
              'hardMemoryLimitEnforced': False, 'productionModified': False,
              'workerGroup': group, 'binarySHA256': request['binarySHA256'], 'phases': {}}
    while True:
        snapshot = subprocess.check_output(['ps', '-ax', '-o', 'pid=,pgid=,rss=,command='], text=True, timeout=15)
        identity = subprocess.run(['ps', '-p', str(group), '-o', 'command='], capture_output=True, text=True, timeout=15)
        if identity.returncode or 'otel-history-job.py _run' not in identity.stdout or str(run) not in identity.stdout:
            result['stoppedReason'] = 'supervisor-no-longer-present'
        state = json.loads((workspace / 'state.json').read_text())
        operation = state.get('currentOperation', {})
        observed = workers(snapshot, group, run / 'otel-history')
        if observed:
            key = operation.get('block', 'unknown') + ':' + operation.get('phase', 'unknown')
            entry = result['phases'].setdefault(key, {'sampleCount': 0, 'sampledPeakRSSBytes': 0})
            entry['sampleCount'] += 1
            entry['lastObservedAt'] = datetime.now(timezone.utc).isoformat()
            entry['sampledPeakRSSBytes'] = max(entry['sampledPeakRSSBytes'], sum(item['rssBytes'] for item in observed))
        receipt = run / 'result.json'
        if receipt.exists():
            result['jobResult'] = json.loads(receipt.read_text())
            result['stoppedReason'] = 'job-result-published'
        result['lastObservedAt'] = datetime.now(timezone.utc).isoformat()
        temporary = run / 'resource-observation.tmp'
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
        temporary.chmod(0o600)
        temporary.replace(output)
        if 'stoppedReason' in result:
            return result
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-directory', type=Path, required=True)
    parser.add_argument('--interval-seconds', type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.interval_seconds <= 60:
        raise ValueError('Observation interval must be between 1 and 60 seconds')
    os.umask(0o077)
    observe(args.run_directory, args.interval_seconds)


if __name__ == '__main__':
    main()

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('signal_preflight', ROOT / 'scripts/otel-migration-preflight.py')
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)

POD_PROBE = '''import concurrent.futures, json, subprocess, urllib.parse
WINDOW = 600
LIMIT = 1048576
process = subprocess.run(['kubectl','get','pods','-A','-o','json'],capture_output=True,check=True)
pods = json.loads(process.stdout)['items']
sources=[]
for pod in pods:
    meta,spec,status=pod['metadata'],pod['spec'],pod.get('status',{})
    statuses={entry['name']:entry for key in ('containerStatuses','initContainerStatuses','ephemeralContainerStatuses') for entry in status.get(key,[])}
    for container in spec.get('containers',[])+spec.get('initContainers',[])+spec.get('ephemeralContainers',[]):
        observed=statuses.get(container['name'],{})
        state=next((key for key in ('running','terminated','waiting') if key in observed.get('state',{})), 'unknown')
        env=[entry['name'] for entry in container.get('env',[]) if entry['name'].startswith(('OTEL_','JAEGER_','ZIPKIN_','TRACING_'))]
        args=container.get('command',[])+container.get('args',[])
        flags=sorted({argument.split('=')[0] for argument in args if argument.startswith('--') and any(word in argument.split('=')[0] for word in ('otel','tracing','trace-endpoint','traces-endpoint'))})
        annotations=sorted(key for key in meta.get('annotations',{}) if key.startswith('instrumentation.opentelemetry.io/'))
        sources.append({'namespace':meta['namespace'],'pod':meta['name'],'container':container['name'],
            'node':spec.get('nodeName'),'phase':status.get('phase'),'image':container['image'],
            'containerState':state,'restartCount':observed.get('restartCount',0),
            'ephemeral':container in spec.get('ephemeralContainers',[]),
            'ownerKinds':sorted({owner['kind'] for owner in meta.get('ownerReferences',[])}),
            'tracingEnvironmentNames':env,'tracingArgumentNames':flags,'instrumentationAnnotationNames':annotations})
def measure(source):
    if source['phase'] not in ('Running','Succeeded','Failed'):
        return {**source,'measurementAvailable':False,'reason':'container-not-started'}
    ns,pod,container=[urllib.parse.quote(source[key],safe='') for key in ('namespace','pod','container')]
    params=urllib.parse.urlencode({'container':container,'sinceSeconds':WINDOW,'limitBytes':LIMIT,'timestamps':'true'})
    path='/api/v1/namespaces/'+ns+'/pods/'+pod+'/log?'+params
    try:
        result=subprocess.run(['kubectl','get','--raw',path],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=20)
    except subprocess.TimeoutExpired:
        return {**source,'measurementAvailable':False,'reason':'api-timeout'}
    if result.returncode:
        return {**source,'measurementAvailable':False,'reason':'api-unavailable'}
    size=len(result.stdout)
    lines=result.stdout.count(b'\\n')
    return {**source,'measurementAvailable':True,'bytes':size,'lines':lines,'truncated':size>=LIMIT}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    measured=list(executor.map(measure,sources))
print(json.dumps({'windowSeconds':WINDOW,'limitBytesPerContainer':LIMIT,'sources':measured}))
'''

JOURNAL_PROBE = (ROOT / 'scripts/otel-journal-probe.py').read_text().split("\nif __name__", 1)[0] + """
paths=[]
for root in ('/var/log/journal','/run/log/journal'):
    try:
        paths.extend(Path(root).glob('*/system*.journal'))
    except OSError:
        pass
readable=bool(paths) and all(os.access(path,os.R_OK) for path in paths)
report={'systemJournalAccessVerified':False,'journalFileCount':len(paths),'windowSeconds':600}
if readable:
    counts=collect()
    report.update(systemJournalAccessVerified=counts['systemJournalReadSucceeded'] and counts['invalidRecords']==0,
                  bytes=counts['serializedBytes'],lines=counts['records'],truncated=counts['truncated'])
else:
    report['reason']='system-journal-read-access-unverified'
print(json.dumps(report))
"""



def privileged_journals(directory, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    if (directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o077
            or directory.stat().st_uid != os.getuid()):
        raise ValueError('Journal evidence directory must be private and not symlinked')
    reports = {}
    for node in ['socrat-0', 'socrat-1', 'socrat-2', 'socrat-3']:
        path = directory / (node + '.json')
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError('Journal evidence files must be private regular files')
        if path.stat().st_uid != os.getuid():
            raise ValueError('Journal evidence must belong to the controller user')
        report = json.loads(path.read_text())
        observed = datetime.fromisoformat(report['collectedAt'])
        if observed.tzinfo is None or not -30 <= (now - observed).total_seconds() <= 900:
            raise ValueError('Journal evidence is stale or has an invalid timestamp')
        for field in ['records', 'serializedBytes', 'messageBytes', 'invalidRecords', 'windowSeconds']:
            if type(report[field]) is not int or report[field] < 0:
                raise ValueError('Journal counts must be nonnegative integers')
        if report['schemaVersion'] != 1 or report['windowSeconds'] != 600 or report['invalidRecords']:
            raise ValueError('Unsupported or incomplete journal measurement')
        if (report.get('rootAccessVerified') is not True or report.get('systemJournalReadSucceeded') is not True
                or report.get('truncated') is not False or report.get('rawLogBodiesPersisted') is not False
                or report.get('productionModified') is not False):
            raise ValueError('Journal evidence does not establish a complete privileged read-only measurement')
        reports[node] = {
            'systemJournalAccessVerified': True, 'rootAccessVerified': True,
            'collectedAt': report['collectedAt'], 'windowSeconds': report['windowSeconds'],
            'bytes': report['serializedBytes'], 'messageBytes': report['messageBytes'],
            'lines': report['records'], 'truncated': False,
        }
    return reports


def summarize(pods, journals):
    sources = pods['sources']
    measured = [source for source in sources if source.get('measurementAvailable')]
    truncated = [source for source in measured if source['truncated']]
    missing = [source for source in sources if not source.get('measurementAvailable')]
    window = pods['windowSeconds']
    if window <= 0:
        raise ValueError('Measurement window must be positive')
    total_bytes = sum(source['bytes'] for source in measured)
    active = [source for source in sources if source.get('containerState') == 'running']
    active_missing = [source for source in active if not source.get('measurementAvailable')]
    active_truncated = [source for source in active if source.get('truncated')]
    state_unknown = [source for source in sources if source.get('containerState', 'unknown') == 'unknown']
    return {
        'schemaVersion': 1, 'collectedAt': datetime.now(timezone.utc).isoformat(),
        'productionModified': False, 'rawLogBodiesPersisted': False,
        'windowSeconds': window, 'containerSourceCount': len(sources),
        'measuredContainerCount': len(measured), 'truncatedContainerCount': len(truncated),
        'unavailableContainerCount': len(missing), 'observedContainerLogBytes': total_bytes,
        'activeContainerCount': len(active), 'activeUnavailableContainerCount': len(active_missing),
        'activeTruncatedContainerCount': len(active_truncated),
        'containerStateUnknownCount': len(state_unknown),
        'activeLogAPIsReadable': bool(active) and not active_missing and not active_truncated and not state_unknown,
        'observedContainerBytesPerSecond': total_bytes / window,
        'logRatesComplete': False, 'countsAreLowerBounds': True,
        'observedSourcesReadable': not truncated and not missing and bool(sources)
                            and set(journals) == {'socrat-0', 'socrat-1', 'socrat-2', 'socrat-3'}
                            and all(item['systemJournalAccessVerified'] for item in journals.values()),
        'diskProjectionVerified': False, 'traceRateMeasured': False,
        'tracingConfigurationIsOnlyAHint': True,
        'sources': sources, 'journals': journals,
        'limitations': [
            'Ten-minute byte counts are observations, not peak rates or a retention-capacity approval.',
            'API timestamps are included; CRI framing, multiline handling, indexes, WALs and queues need separate budgeting.',
            'Environment and flag names do not prove SDK instrumentation or trace delivery.',
            'Unprovisioned host logs, rotated files and previous container incarnations are not fully accounted for.',
            'Sensitive historical logs must not be imported into Loki; no raw log bodies are saved by this tool.',
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssh-host', default='socrat-0')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--journal-inspection-directory', type=Path)
    parser.add_argument('--limit-bytes-per-container', type=int, default=1048576)
    args = parser.parse_args()
    try:
        if not 1048576 <= args.limit_bytes_per_container <= 16 * 1048576:
            raise ValueError('Log inspection cap must be between 1 and 16 MiB per container')
        probe = POD_PROBE.replace('LIMIT = 1048576', 'LIMIT = ' + str(args.limit_bytes_per_container))
        pods = PREFLIGHT.remote(args.ssh_host, ['python3', '-c', probe])
        journals = privileged_journals(args.journal_inspection_directory) if args.journal_inspection_directory else {
            node: PREFLIGHT.remote(node, ['python3', '-c', JOURNAL_PROBE])
            for node in ['socrat-0', 'socrat-1', 'socrat-2', 'socrat-3']}
        report = summarize(pods, journals)
        PREFLIGHT.save(args.output, report)
        print(json.dumps({key: report[key] for key in ('containerSourceCount', 'measuredContainerCount',
                          'truncatedContainerCount', 'unavailableContainerCount',
                          'observedContainerBytesPerSecond', 'logRatesComplete', 'traceRateMeasured')}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

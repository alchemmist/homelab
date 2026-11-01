"""Metadata-only application signal registry; no credentials or log bodies.

Configuration hints never certify application SDK spans. No deployments change.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('production_bootstrap', ROOT / 'scripts/otel-production-bootstrap.py')
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)
PREFIXES = ('OTEL_', 'ENABLE_OTEL', 'LITELLM_OTEL', 'JAEGER_', 'ZIPKIN_', 'TRACING_')


def container_record(namespace, workload, kind, template, container, init=False):
    names = sorted({entry['name'] for entry in container.get('env', []) if entry.get('name', '').startswith(PREFIXES)})
    flags = sorted({argument.split('=', 1)[0] for argument in container.get('command', []) + container.get('args', [])
                    if argument.startswith('--') and any(word in argument.split('=', 1)[0].lower() for word in ['otel', 'tracing', 'trace-endpoint', 'traces-endpoint'])})
    annotations = sorted(key for key in template.get('metadata', {}).get('annotations', {}) if key.startswith('instrumentation.opentelemetry.io/'))
    return {'namespace': namespace, 'workload': workload, 'kind': kind, 'container': container['name'],
            'image': container.get('image'), 'initContainer': init,
            'tracingEnvironmentNames': names, 'tracingArgumentNames': flags,
            'instrumentationAnnotationNames': annotations,
            'opaqueEnvironmentSourcesPresent': bool(container.get('envFrom')),
            'configurationHintPresent': bool(names or flags or annotations),
            'internalSdkTraceDeliveryVerified': False, 'applicationLogDeliveryVerified': False,
            'supportedSdkDecision': 'requires-version-specific-review',
            'ingressSpansDoNotCertifyInternalSdk': True}


def summarize(objects):
    records = []
    incarnations = []
    for obj in objects:
        kind, meta, spec = obj['kind'], obj['metadata'], obj.get('spec', {})
        if kind in ('Job', 'ReplicaSet') and any(owner.get('kind') in ('CronJob', 'Deployment') for owner in meta.get('ownerReferences', [])):
            continue
        if kind == 'CronJob':
            template = spec.get('jobTemplate', {}).get('spec', {}).get('template', {})
        elif kind == 'Pod':
            template = {'metadata': meta, 'spec': spec}
        else:
            template = spec.get('template', {})
        if kind == 'Pod':
            status = obj.get('status', {})
            for item in status.get('containerStatuses', []) + status.get('initContainerStatuses', []):
                incarnations.append({'namespace': meta['namespace'], 'pod': meta['name'],
                                     'container': item['name'], 'imageID': item.get('imageID'),
                                     'ready': item.get('ready', False), 'restartCount': item.get('restartCount', 0),
                                     'phase': status.get('phase'), 'deliveryVerified': False})
        # Controllers cover managed pod templates; incarnations remain separate.
        if kind == 'Pod' and meta.get('ownerReferences'):
            continue
        for key in ['containers', 'initContainers']:
            for container in template.get('spec', {}).get(key, []):
                records.append(container_record(meta['namespace'], meta['name'], kind, template, container, key == 'initContainers'))
    records.sort(key=lambda record: (record['namespace'], record['kind'], record['workload'], record['container']))
    return {'collectedAt': datetime.now(timezone.utc).isoformat(), 'productionModified': False,
            'metadataOnly': True, 'environmentValuesSaved': False, 'logBodiesRead': False,
            'sourceCount': len(records), 'configurationHintCount': sum(record['configurationHintPresent'] for record in records),
            'internalSdkCoverageComplete': False, 'hostServiceRegistryStillRequired': True,
            'managedPodIncarnationDeliveryStillRequiresSeparateEvidence': True,
            'configurationIsNotDeliveryEvidence': True, 'sources': records,
            'podIncarnations': sorted(incarnations, key=lambda row: (row['namespace'], row['pod'], row['container']))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    objects = BOOTSTRAP.kube('get', 'deployments,statefulsets,daemonsets,cronjobs,jobs,replicasets,pods', '-A', '-o', 'json')['items']
    report = summarize(objects)
    if args.output.exists():
        raise ValueError('Preserve prior registry observations')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({key: report[key] for key in ['sourceCount', 'configurationHintCount', 'internalSdkCoverageComplete', 'productionModified']}))


if __name__ == '__main__':
    main()

"""Fenced source-only switcher update preserving proof-gated vLLM trace flags.

No image/profile/model/DB/GPU/auth changes. Only reviewed server.py and its
checksum rollout change. Single identical profile permits safe CPU overlap;
never kills draining old pods or touches the GPU Deployment.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('bootstrap', ROOT / 'scripts/otel-production-bootstrap.py')
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)
BASELINE_SHA = '710f1c7aa0ddcc2f3813a8a99f06f745f11ffdfcf1fbd7e0633a53528254edad'


def run(output, apply):
    os.umask(0o077)
    controller = Path.home() / 'Library/Application Support/homelab/otel-controller'
    if not output.resolve().is_relative_to(controller.resolve()):
        raise ValueError('Private preimages must remain in durable controller root')
    output.mkdir(mode=0o700)
    kube = BOOTSTRAP.kube
    cm = kube('-n', 'llm', 'get', 'configmap', 'llm-switcher', '-o', 'json')
    deployment = kube('-n', 'llm', 'get', 'deployment', 'llm-switcher', '-o', 'json')
    desired = (ROOT / 'charts/llm-switcher/files/server.py').read_text()
    source_sha = hashlib.sha256(desired.encode()).hexdigest()
    if hashlib.sha256(cm['data']['server.py'].encode()).hexdigest() not in (BASELINE_SHA, source_sha):
        raise ValueError('Live switcher source differs from reviewed baseline; no blind overwrite')
    if len(json.loads(cm['data']['profiles.json'])) != 1:
        raise ValueError('Multiple model profiles prohibit uncoordinated CPU overlap')
    if deployment['spec'].get('replicas', 1) != 1 or deployment.get('status', {}).get('availableReplicas') != 1:
        raise ValueError('Require one healthy original switcher replica')
    (output / 'configmap-before-private.json').write_text(json.dumps(cm))
    (output / 'deployment-before-private.json').write_text(json.dumps(deployment))
    receipt = {'applied': False, 'sourceSHA256': source_sha, 'modelProfilesImageAuthAndGpuUnchanged': True,
               'oldPodsForceKilled': False, 'oldReplicaDrainComplete': False}
    def record():
        (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    record()
    if not apply:
        print(json.dumps(receipt)); return
    if cm['data']['server.py'] == desired and deployment['spec']['template'].get('metadata', {}).get('annotations', {}).get('checksum/server') == source_sha:
        pods = kube('-n', 'llm', 'get', 'pods', '-l', 'app=llm-switcher', '-o', 'json')['items']
        old = [p for p in pods if p['metadata'].get('annotations', {}).get('checksum/server') != source_sha]
        if old:
            raise ValueError('Already updated source still has old draining pods; never force kill')
        receipt.update(alreadyReconciled=True, newSourceReady=True, oldReplicaDrainComplete=True, oldPodDrainPending=[])
        record(); print(json.dumps(receipt)); return
    updated = kube('-n', 'llm', 'patch', 'configmap', 'llm-switcher', '--type=json', '-p', json.dumps([
        {'op': 'test', 'path': '/metadata/resourceVersion', 'value': cm['metadata']['resourceVersion']},
        {'op': 'replace', 'path': '/data/server.py', 'value': desired}]), '-o', 'json')
    try:
        kube('-n', 'llm', 'patch', 'deployment', 'llm-switcher', '--type=strategic', '-p', json.dumps({
            'metadata': {'resourceVersion': deployment['metadata']['resourceVersion']},
            'spec': {'strategy': {'type': 'RollingUpdate', 'rollingUpdate': {'maxSurge': 1, 'maxUnavailable': 0}},
                     'template': {'metadata': {'annotations': {'checksum/server': source_sha}}}}}), '-o', 'json')
    except Exception:
        kube('-n', 'llm', 'patch', 'configmap', 'llm-switcher', '--type=json', '-p', json.dumps([
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': updated['metadata']['resourceVersion']},
            {'op': 'replace', 'path': '/data/server.py', 'value': cm['data']['server.py']}]), '-o', 'json')
        raise
    receipt['applied'] = True; record()
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        live = kube('-n', 'llm', 'get', 'deployment', 'llm-switcher', '-o', 'json')
        pods = kube('-n', 'llm', 'get', 'pods', '-l', 'app=llm-switcher', '-o', 'json')['items']
        desired_pods = [p for p in pods if p['metadata'].get('annotations', {}).get('checksum/server') == source_sha
                        and any(c['type'] == 'Ready' and c['status'] == 'True' for c in p.get('status', {}).get('conditions', []))]
        old = [p for p in pods if p['metadata'].get('annotations', {}).get('checksum/server') != source_sha]
        if live.get('status', {}).get('observedGeneration', 0) >= live['metadata']['generation'] and desired_pods:
            receipt.update(newSourceReady=True, oldReplicaDrainComplete=not old,
                           oldPodDrainPending=[p['metadata']['name'] for p in old])
            record()
            if not old:
                print(json.dumps(receipt)); return
        time.sleep(3)
    raise ValueError('New source or natural old-pod drain pending; preimages retained, do not force kill or enable GPU tracing yet')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(args.output, args.apply)

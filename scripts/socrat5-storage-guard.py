#!/usr/bin/env python3
"""Audit/create the owned local-only admission boundary; never overwrite drift."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import time

NAME = 'homelab-socrat5-local-storage'
KINDS = ('ValidatingAdmissionPolicy', 'ValidatingAdmissionPolicyBinding')


def kub(args, document=None):
    p = subprocess.run(['env', 'K3S_CONFIG_FILE=/dev/null', 'kubectl', '--kubeconfig',
                        '/etc/rancher/k3s/k3s.yaml'] + args,
                       input=None if document is None else json.dumps(document),
                       text=True, capture_output=True, timeout=30)
    if p.returncode:
        raise RuntimeError('Kubernetes operation failed; inspect privately, do not replay writes')
    return json.loads(p.stdout) if p.stdout.strip() else None


def canonical(spec):
    s = json.loads(json.dumps(spec))
    c = s.get('matchConstraints')
    if c:
        if c.get('matchPolicy') == 'Equivalent':
            c.pop('matchPolicy')
        for name in ('namespaceSelector', 'objectSelector'):
            if c.get(name) == {}:
                c.pop(name)
        for r in c.get('resourceRules', []):
            if r.get('scope') == '*':
                r.pop('scope')
    return s


def validate_existing(want, have):
    if have['metadata'].get('labels', {}).get('homelab.io/owner') != 'socrat5-worker':
        raise ValueError('Foreign ownership; refuse adoption')
    if canonical(want['spec']) != canonical(have['spec']):
        raise ValueError('Admission guard drift; explicit review/preimage/CAS required')


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    docs = json.loads(args.manifest.read_text())
    if [o['kind'] for o in docs] != list(KINDS) or any(
            o['metadata']['name'] != NAME for o in docs):
        raise ValueError('Unexpected scope')
    before = [kub(['get', o['kind'], NAME, '--ignore-not-found', '-o', 'json']) for o in docs]
    for want, have in zip(docs, before):
        if have:
            validate_existing(want, have)
    missing = [o for o, have in zip(docs, before) if not have]
    if before[1] and not before[0]:
        raise ValueError('Partial live binding: inspect first')
    if args.apply and missing:
        os.umask(0o077)
        receipt = Path('/var/lib/homelab-recovery') / (
            'socrat5-storage-guard-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
        receipt.mkdir(mode=0o700)
        with (receipt / 'before-and-desired.json').open('x') as f:
            json.dump({'before': before, 'desired': docs}, f)
            f.flush()
            os.fsync(f.fileno())
        for o in missing:
            # Native create is the absent-object CAS; never apply/replace a foreign live policy.
            actual = kub(['create', '-f', '-', '-o', 'json'], o)
            (receipt / (o['kind'] + '.accepted.json')).write_text(json.dumps(actual))
            if o['kind'] == KINDS[0]:
                for _ in range(15):
                    current = kub(['get', KINDS[0], NAME, '-o', 'json'])
                    if 'typeChecking' in current.get('status', {}):
                        break
                    time.sleep(1)
                if current.get('status', {}).get('typeChecking', {}).get('expressionWarnings'):
                    raise ValueError('CEL type warnings; binding not created')
    print(json.dumps({'operations': len(missing), 'apply': args.apply,
                      'policy': NAME, 'live_overwrites': 0}))


if __name__ == '__main__':
    main()

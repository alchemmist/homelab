"""Refresh only this host's cert-manager leaf and explicitly scoped source secrets.

Bootstrap JWTs are private; refresh uses the same narrowly scoped ServiceAccount's
named TokenRequest, not a host administrator kubeconfig. CA private keys are never read.
"""
import base64
import argparse
import urllib.error
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import urllib.request

ROOT = Path('/var/lib/homelab-otel')


def atomic(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(value)
    temporary.chmod(0o600)
    temporary.replace(path)


def run(verify_scope=False):
    os.umask(0o077)
    if os.geteuid() != 0 or ROOT.is_symlink():
        raise ValueError('Root-owned native host workspace required')
    cfg = json.loads((ROOT / 'credentials.json').read_text())
    token = json.loads((ROOT / 'token.json').read_text())
    context = ssl.create_default_context(cafile=str(ROOT / 'kubernetes-ca.crt'))

    def api(path, payload=None, method=None):
        headers = {'Authorization': 'Bearer ' + token['token']}
        if payload is not None:
            headers['Content-Type'] = 'application/merge-patch+json' if method == 'PATCH' else 'application/json'
        request = urllib.request.Request(cfg['apiServer'] + path, data=json.dumps(payload).encode() if payload is not None else None,
                                         headers=headers, method=method)
        with urllib.request.urlopen(request, context=context, timeout=15) as response:
            return json.load(response)

    namespace = '/api/v1/namespaces/' + cfg['namespace']
    if verify_scope:
        try:
            api(namespace + '/secrets/otel-root-ca')
        except urllib.error.HTTPError as error:
            if error.code != 403:
                raise
        else:
            raise ValueError('Host credentials may read CA private key; refusing overprivileged bootstrap')
    if verify_scope or (datetime.fromisoformat(token['expirationTimestamp'].replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds() < 43200:
        token = api(namespace + '/serviceaccounts/' + cfg['serviceAccount'] + '/token',
                    {'apiVersion': 'authentication.k8s.io/v1', 'kind': 'TokenRequest', 'spec': {'expirationSeconds': 86400}})['status']
        atomic(ROOT / 'token.json', json.dumps(token))
    secret = api(namespace + '/secrets/' + cfg['secret'])['data']
    certificate = base64.b64decode(secret['tls.crt'], validate=True)
    fingerprint = hashlib.sha256(certificate).hexdigest()
    destination = ROOT / 'certificates' / fingerprint
    changed = not (ROOT / 'tls').exists() or (ROOT / 'tls').resolve() != destination
    if changed:
        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        for name, key in [('ca.crt', 'ca.crt'), ('client.crt', 'tls.crt'), ('server.crt', 'tls.crt'), ('client.key', 'tls.key'), ('server.key', 'tls.key')]:
            (destination / name).write_bytes(base64.b64decode(secret[key], validate=True))
            (destination / name).chmod(0o600)
        subprocess.run(['openssl', 'verify', '-CAfile', str(destination / 'ca.crt'), str(destination / 'client.crt')],
                       capture_output=True, check=True, timeout=10)
        check = ssl.create_default_context(cafile=str(destination / 'ca.crt'))
        check.load_cert_chain(str(destination / 'client.crt'), str(destination / 'client.key'))
        temporary = ROOT / 'tls.next'
        temporary.symlink_to(destination)
        temporary.replace(ROOT / 'tls')
    if cfg['sourceReferences']:
        mirror = {}
        for reference in cfg['sourceReferences']:
            kind = reference.get('resource', 'secrets')
            original = api('/api/v1/namespaces/' + reference['namespace'] + '/' + kind + '/' + reference['secret'])['data']
            value = original[reference['key']]
            mirror[reference['targetKey']] = base64.b64encode(value.encode()).decode() if kind == 'configmaps' else value
        current = api(namespace + '/secrets/otel-source-auth')['data']
        if mirror != current:
            api(namespace + '/secrets/otel-source-auth', {'data': mirror}, method='PATCH')
    grafana = cfg.get('grafanaDatasourceSecret')
    if grafana:
        leaf = api(namespace + '/secrets/' + grafana['leafSecret'])['data']
        secure = {name: base64.b64decode(leaf[key]).decode() for name, key in [('tlsCACert', 'ca.crt'), ('tlsClientCert', 'tls.crt'), ('tlsClientKey', 'tls.key')]}
        sources = [{'name': name, 'uid': name.lower(), 'type': name.lower(), 'access': 'proxy', 'url': 'https://10.250.0.3:' + str(port),
                    'isDefault': False, 'editable': False, 'jsonData': {'tlsAuth': True, 'tlsAuthWithCACert': True, 'tlsSkipVerify': False}, 'secureJsonData': secure}
                   for name, port in [('Loki', 3100), ('Tempo', 3200)]]
        sources[0]['jsonData']['derivedFields'] = [{'name': 'TraceID', 'matcherRegex': 'trace_id=([0-9a-f]{32})', 'datasourceUid': 'tempo', 'url': '$${__value.raw}'}]
        sources[1]['jsonData']['tracesToLogsV2'] = {'datasourceUid': 'loki', 'spanStartTimeShift': '-1m', 'spanEndTimeShift': '1m', 'filterByTraceID': True}
        data = {'otel-datasources.yaml': base64.b64encode(json.dumps({'apiVersion': 1, 'datasources': sources}).encode()).decode()}
        target = namespace + '/secrets/' + grafana['targetSecret']
        if api(target)['data'] != data:
            api(target, {'data': data}, method='PATCH')
    for reference in cfg.get('mirroredTLSSecrets', []):
        data = api('/api/v1/namespaces/' + reference['namespace'] + '/secrets/' + reference['secret'])['data']
        target = '/api/v1/namespaces/' + reference['targetNamespace'] + '/secrets/' + reference['targetSecret']
        if api(target)['data'] != data:
            api(target, {'data': data}, method='PATCH')
            if reference.get('reloadDeployment'):
                fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
                api('/apis/apps/v1/namespaces/' + reference['targetNamespace'] + '/deployments/' + reference['reloadDeployment'],
                    {'spec': {'template': {'metadata': {'annotations': {'homelab.alchemmist.xyz/otel-leaf-sha256': fingerprint}}}}}, method='PATCH')
    if changed:
        for unit in ['homelab-otel-loki.service', 'homelab-otel-tempo.service', 'homelab-otel-traces.service', 'homelab-otel-agent.service', 'homelab-otel-application-ingress.service']:
            active = subprocess.run(['systemctl', 'is-active', '--quiet', unit], capture_output=True)
            if active.returncode == 0:
                subprocess.run(['systemctl', 'restart', unit], capture_output=True, check=True, timeout=90)
    print(json.dumps({'node': cfg['node'], 'certificateChanged': changed, 'credentialRefreshSucceeded': True, 'caPrivateKeyRead': False}))


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--verify-scope", action="store_true")
        run(parser.parse_args().verify_scope)
    except Exception as error:
        # Do not include HTTP response bodies, private key material, or bearer tokens.
        print(json.dumps({'credentialRefreshSucceeded': False, 'errorType': type(error).__name__}))
        raise SystemExit(1)

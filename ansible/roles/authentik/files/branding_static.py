#!/usr/bin/env python3
"""Render isolated same-origin branding assets; no credentials or application JS."""
import hashlib
import json
from pathlib import Path
import sys


def render(root):
    assets = json.loads((root / 'assets.json').read_text())
    binary = {}
    names = {}
    import base64
    for key, asset in assets.items():
        path = root / asset['path']
        if path.suffix not in {'.woff2', '.webp', '.avif', '.svg', '.css'}:
            raise ValueError('Only reviewed font/image/scene CSS assets may be served')
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != asset['sha256']:
            raise ValueError('Asset checksum mismatch')
        name = digest[:12] + '-' + path.name
        binary[name] = base64.b64encode(content).decode()
        names[key] = name
    if sum(len(base64.b64decode(value)) for value in binary.values()) > 16_000_000:
        raise ValueError('Static bundle exceeds reviewed total budget')
    # Each immutable shard stays below the API object's serialized size limit.
    chunks = []
    chunk = {}
    size = 0
    for key, value in sorted(binary.items()):
        length = len(base64.b64decode(value))
        if length > 650_000:
            raise ValueError('Individual asset exceeds ConfigMap shard budget')
        if size + length > 650_000:
            chunks.append(chunk)
            chunk, size = {}, 0
        chunk[key] = value
        size += length
    if chunk:
        chunks.append(chunk)
    random_config = ''
    random_locations = ''
    nature_file = root / 'nature.json'
    if nature_file.exists():
        photos = json.loads(nature_file.read_text())['photos']
        if not 2 <= len(photos) <= 100:
            raise ValueError('Nature collection must have 2..100 reviewed photos')
        if len({p['id'] for p in photos}) != len(photos):
            raise ValueError('Duplicate Nature ID')
        import re
        if any(not re.fullmatch('[0-9a-f]{12}', p['id']) for p in photos):
            raise ValueError('Invalid Nature ID')
        # Equal weights to two decimal places, final bucket receives rounding remainder.
        base, remainder = divmod(10000, len(photos))
        weights = [f" {(base + (i < remainder)) / 100:.2f}% {p['id']};" for i, p in enumerate(photos[:-1])]
        weights.append(f" * {photos[-1]['id']};")
        random_config = 'split_clients "$request_id" $nature_scene {\n' + '\n'.join(weights) + '\n}\n'
        css_rows=[f" {p['id']} {names[p['sceneCss']]};" for p in photos]
        random_config += 'map $nature_scene $nature_css {\n'+'\n'.join(css_rows)+'\n}\n'
        random_locations += '''
  location = /-/quiet-mono/v1/nature/scene.css {
   alias /assets/$nature_css;
   default_type text/css;
   add_header Cache-Control "no-store" always;
   add_header X-Content-Type-Options nosniff always;
   add_header X-Quiet-Mono-Scene $nature_scene always;
   limit_except GET HEAD { deny all; }
  }
'''
        random_config += 'map $http_accept $nature_format { default webp; ~*image/avif avif; }\n'
        for variant in ['desktop', 'mobile']:
            rows = [f" {p['id']}:webp {names[p[variant]]};" for p in photos]
            rows += [f" {p['id']}:avif {names[p[variant+'Avif']]};" for p in photos]
            random_config += f'map "$nature_scene:$nature_format" $nature_{variant} {{\n' + '\n'.join(rows) + '\n}\n'
            random_locations += f"""
  location = /-/quiet-mono/v1/nature/{variant} {{
   if ($request_method !~ ^(GET|HEAD)$) {{ return 403; }}
   absolute_redirect off;
   return 302 /-/quiet-mono/v1/$nature_{variant};
   add_header Cache-Control "no-store" always;
   add_header X-Content-Type-Options nosniff always;
   add_header Vary Accept always;
   add_header X-Quiet-Mono-Scene $nature_scene always;
   limit_except GET HEAD {{ deny all; }}
  }}
"""
    config = '''worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 128; }
http {
 __NATURE_CONFIG__
 include /etc/nginx/mime.types;
 types { image/avif avif; }
 default_type application/octet-stream;
 access_log off;
 server_tokens off;
 sendfile on;
 client_body_temp_path /tmp/client_temp;
 proxy_temp_path /tmp/proxy_temp;
 fastcgi_temp_path /tmp/fastcgi_temp;
 uwsgi_temp_path /tmp/uwsgi_temp;
 scgi_temp_path /tmp/scgi_temp;
 server {
  listen 8080;
  location = /healthz { return 200 "ok\\n"; }
  __NATURE_LOCATIONS__
  location /-/quiet-mono/v1/ {
   alias /assets/;
   add_header Cache-Control "public, max-age=31536000, immutable";
   add_header X-Content-Type-Options nosniff always;
   limit_except GET HEAD { deny all; }
  }
  location / { return 404; }
 }
}
'''
    config = config.replace('__NATURE_CONFIG__', random_config).replace('__NATURE_LOCATIONS__', random_locations)
    digest = hashlib.sha256(json.dumps({'binary': binary, 'config': config}, sort_keys=True).encode()).hexdigest()[:12]
    name = 'socrat-authentik-theme'
    config_name = name + '-' + digest
    labels = {'app.kubernetes.io/name': name}
    namespace = 'identity'
    meta = lambda resource: {'name': resource, 'namespace': namespace, 'labels': labels}
    image = json.loads((root / 'static-image.json').read_text())['image']
    if '@sha256:' not in image:
        raise ValueError('Static image must be pinned by registry digest')
    shards = []
    for chunk in chunks:
        shard_name = name + '-assets-' + hashlib.sha256(json.dumps(chunk, sort_keys=True).encode()).hexdigest()[:12]
        shards.append({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta(shard_name),
                       'immutable': True, 'binaryData': chunk})
    items = [
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta(config_name), 'immutable': True,
         'data': {'nginx.conf': config}},
        *shards,
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': meta(name), 'spec': {
            'replicas': 1, 'selector': {'matchLabels': labels},
            'strategy': {'type': 'RollingUpdate', 'rollingUpdate': {'maxSurge': 1, 'maxUnavailable': 0}},
            'template': {'metadata': {'labels': labels}, 'spec': {
                'automountServiceAccountToken': False,
                'nodeSelector': {'kubernetes.io/hostname': 'socrat-0'},
                'securityContext': {'runAsNonRoot': True, 'runAsUser': 101, 'runAsGroup': 101,
                                    'fsGroup': 101, 'seccompProfile': {'type': 'RuntimeDefault'}},
                'containers': [{'name': 'static', 'image': image, 'imagePullPolicy': 'IfNotPresent',
                    'command': ['nginx'], 'args': ['-g', 'daemon off;'],
                    'ports': [{'name': 'http', 'containerPort': 8080}],
                    'securityContext': {'readOnlyRootFilesystem': True, 'allowPrivilegeEscalation': False,
                                        'capabilities': {'drop': ['ALL']}},
                    'resources': {'requests': {'cpu': '5m', 'memory': '16Mi', 'ephemeral-storage': '32Mi'},
                                  'limits': {'cpu': '100m', 'memory': '64Mi', 'ephemeral-storage': '64Mi'}},
                    'readinessProbe': {'httpGet': {'path': '/healthz', 'port': 'http'}, 'periodSeconds': 5},
                    'livenessProbe': {'httpGet': {'path': '/healthz', 'port': 'http'}, 'periodSeconds': 15},
                    'volumeMounts': [{'name': 'config', 'mountPath': '/etc/nginx/nginx.conf', 'subPath': 'nginx.conf', 'readOnly': True},
                                     {'name': 'assets', 'mountPath': '/assets', 'readOnly': True},
                                     {'name': 'tmp', 'mountPath': '/tmp'}]}],
                'volumes': [{'name': 'config', 'configMap': {'name': config_name, 'items': [{'key': 'nginx.conf', 'path': 'nginx.conf'}]}},
                            {'name': 'assets', 'projected': {'sources': [
                                {'configMap': {'name': shard['metadata']['name'], 'items': [
                                    {'key': key, 'path': key} for key in sorted(shard['binaryData'])]}}
                                for shard in shards]}},
                            {'name': 'tmp', 'emptyDir': {'sizeLimit': '32Mi'}}]}}}},
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': meta(name), 'spec': {'selector': labels,
            'ports': [{'name': 'http', 'port': 80, 'targetPort': 'http'}]}},
        {'apiVersion': 'networking.k8s.io/v1', 'kind': 'Ingress', 'metadata': {**meta(name),
            'annotations': {'traefik.ingress.kubernetes.io/router.priority': '120'}}, 'spec': {
            'ingressClassName': 'traefik', 'tls': [{'hosts': ['auth.socrat.alchemmist.xyz'], 'secretName': 'authentik-tls'}],
            'rules': [{'host': 'auth.socrat.alchemmist.xyz', 'http': {'paths': [{
                'path': '/-/quiet-mono/v1/', 'pathType': 'Prefix',
                'backend': {'service': {'name': name, 'port': {'number': 80}}}}]}}]}}
    ]
    return {'apiVersion': 'v1', 'kind': 'List', 'items': items}


if __name__ == '__main__':
    # JSON documents are valid YAML. Separate resources avoid kubectl's List-kind
    # OpenAPI-v2 fallback; each built-in resource keeps Strict v3 validation.
    for item in render(Path(sys.argv[1]))['items']:
        print('---')
        print(json.dumps(item))

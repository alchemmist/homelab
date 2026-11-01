import argparse
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request


IMAGES = {'collector': ('otel/opentelemetry-collector-contrib', '0.164.0'),
          'loki': ('grafana/loki', '3.7.9'), 'tempo': ('grafana/tempo', '2.10.10'),
          'validationPrometheus': ('prom/prometheus', 'v3.15.0-distroless')}
ACCEPT = ', '.join(['application/vnd.oci.image.index.v1+json',
                    'application/vnd.docker.distribution.manifest.list.v2+json',
                    'application/vnd.oci.image.manifest.v1+json',
                    'application/vnd.docker.distribution.manifest.v2+json'])


def resolve(repository, version):
    query = urllib.parse.urlencode({'service': 'registry.docker.io', 'scope': 'repository:' + repository + ':pull'})
    with urllib.request.urlopen('https://auth.docker.io/token?' + query, timeout=30) as response:
        token = json.load(response)['token']
    request = urllib.request.Request('https://registry-1.docker.io/v2/' + repository + '/manifests/' + version,
                                     headers={'Authorization': 'Bearer ' + token, 'Accept': ACCEPT})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        digest = response.headers['Docker-Content-Digest']
    if digest != 'sha256:' + hashlib.sha256(body).hexdigest():
        raise ValueError('Registry manifest digest mismatch')
    manifest = json.loads(body)
    platform = [entry for entry in manifest.get('manifests', [])
                if entry.get('platform', {}).get('os') == 'linux'
                and entry.get('platform', {}).get('architecture') == 'amd64']
    if len(platform) != 1:
        raise ValueError('Expected one linux/amd64 manifest')
    return {'repository': 'docker.io/' + repository, 'version': version, 'indexDigest': digest,
            'linuxAMD64Digest': platform[0]['digest'], 'image': 'docker.io/' + repository + '@' + digest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'schemaVersion': 1, 'images': {name: resolve(*image) for name, image in IMAGES.items()},
              'tempoVersionRationale': 'Pinned patched 2.10 monolithic release; do not silently adopt Tempo 3 architecture.'}
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()

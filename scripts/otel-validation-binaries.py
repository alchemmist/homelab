import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request


BINARIES = {'collector': 'otelcol-contrib', 'loki': 'loki', 'tempo': 'tempo', 'validationPrometheus': 'prometheus'}
IMAGE_PATHS = {'collector': 'otelcol-contrib', 'loki': 'usr/bin/loki', 'tempo': 'tempo', 'validationPrometheus': 'usr/bin/prometheus'}
MAX_LAYER_BYTES = 512 * 1024 ** 2
MAX_BINARY_BYTES = 1024 ** 3


def token_for(repository):
    query = urllib.parse.urlencode({'service': 'registry.docker.io', 'scope': 'repository:' + repository + ':pull'})
    with urllib.request.urlopen('https://auth.docker.io/token?' + query, timeout=30) as response:
        return json.load(response)['token']


def request(repository, reference, token, kind):
    return urllib.request.Request('https://registry-1.docker.io/v2/' + repository + '/' + kind + '/' + reference,
                                  headers={'Authorization': 'Bearer ' + token,
                                           'Accept': 'application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'})


def extract(image, name, output):
    repository = image['repository'].removeprefix('docker.io/')
    token = token_for(repository)
    with urllib.request.urlopen(request(repository, image['linuxAMD64Digest'], token, 'manifests'), timeout=30) as response:
        manifest_body = response.read()
    if 'sha256:' + hashlib.sha256(manifest_body).hexdigest() != image['linuxAMD64Digest']:
        raise ValueError('Image manifest checksum mismatch')
    manifest = json.loads(manifest_body)
    target = output / BINARIES[name]
    if target.exists() or target.is_symlink():
        raise ValueError('Existing validation binaries are never overwritten')
    for layer in manifest['layers']:
        if layer['size'] > MAX_LAYER_BYTES:
            raise ValueError('Image layer exceeds the inspection budget')
        with tempfile.TemporaryFile(dir=output) as stream:
            digest = hashlib.sha256()
            size = 0
            with urllib.request.urlopen(request(repository, layer['digest'], token, 'blobs'), timeout=120) as response:
                while data := response.read(4 * 1024 ** 2):
                    size += len(data)
                    if size > MAX_LAYER_BYTES:
                        raise ValueError('Image layer exceeds the inspection budget')
                    digest.update(data)
                    stream.write(data)
            if size != layer['size'] or 'sha256:' + digest.hexdigest() != layer['digest']:
                raise ValueError('Image layer checksum mismatch')
            stream.seek(0)
            with tarfile.open(fileobj=stream, mode='r:*') as archive:
                for member in archive:
                    if member.name.removeprefix('./').lstrip('/') != IMAGE_PATHS[name]:
                        continue
                    if not member.isfile() or member.size > MAX_BINARY_BYTES:
                        raise ValueError('Unexpected image binary member')
                    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o700)
                    with os.fdopen(descriptor, 'wb') as destination, archive.extractfile(member) as source:
                        shutil.copyfileobj(source, destination, 4 * 1024 ** 2)
                    if target.stat().st_size != member.size:
                        raise ValueError('Truncated image binary')
    if not target.exists():
        raise ValueError('Expected validation binary was not found in the pinned image')
    with target.open('rb') as stream:
        binary_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(target), 'image': image['image'], 'sha256': binary_digest, 'bytes': target.stat().st_size}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--component', choices=list(BINARIES))
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, exist_ok=False)
    lock = json.loads(args.lock.read_text())
    receipt = {'schemaVersion': 1, 'architecture': 'linux/amd64', 'binaries': {}}
    for name, image in lock['images'].items():
        if args.component and args.component != name:
            continue
        receipt['binaries'][name] = extract(image, name, args.output)
        print(name + ': extracted and verified', flush=True)
    with (args.output / 'receipt.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()

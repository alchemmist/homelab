"""Build a hash-verified upstream OCI archive for offline containerd import."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tarfile
import urllib.request

spec = importlib.util.spec_from_file_location('native_images', Path(__file__).with_name('otel-validation-binaries.py'))
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)


def run(lock, component, output):
    os.umask(0o077)
    output.mkdir(mode=0o700, exist_ok=False)
    image = json.loads(lock.read_text())['images'][component]
    repository = image['repository'].removeprefix('docker.io/')
    token = images.token_for(repository)
    blobs = output / 'oci' / 'blobs' / 'sha256'
    blobs.mkdir(mode=0o700, parents=True)
    with urllib.request.urlopen(images.request(repository, image['linuxAMD64Digest'], token, 'manifests'), timeout=60) as response:
        manifest = response.read()
    if 'sha256:' + hashlib.sha256(manifest).hexdigest() != image['linuxAMD64Digest']:
        raise ValueError('Upstream OCI manifest differs from lock')
    (blobs / image['linuxAMD64Digest'].split(':')[1]).write_bytes(manifest)
    document = json.loads(manifest)
    for descriptor in [document['config'], *document['layers']]:
        path = blobs / descriptor['digest'].split(':')[1]
        digest = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(images.request(repository, descriptor['digest'], token, 'blobs'), timeout=180) as response, path.open('xb') as stream:
            while chunk := response.read(4 * 1024**2):
                size += len(chunk)
                if size > descriptor['size']:
                    raise ValueError('OCI blob size exceeds pinned manifest')
                digest.update(chunk)
                stream.write(chunk)
        if size != descriptor['size'] or 'sha256:' + digest.hexdigest() != descriptor['digest']:
            raise ValueError('OCI blob checksum differs')
    (output / 'oci' / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
    (output / 'oci' / 'index.json').write_text(json.dumps({'schemaVersion': 2, 'manifests': [{'mediaType': document['mediaType'],
        'digest': image['linuxAMD64Digest'], 'size': len(manifest), 'platform': {'os': 'linux', 'architecture': 'amd64'},
        'annotations': {'org.opencontainers.image.ref.name': image['repository'] + ':' + image['version']}}]}))
    with tarfile.open(output / 'image.tar', 'x') as tar:
        for path in (output / 'oci').iterdir():
            tar.add(path, arcname=path.name)
    print(json.dumps({'verifiedUpstreamOCIArchive': True, 'component': component, 'manifestDigest': image['linuxAMD64Digest']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--component', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.lock, args.component, args.output)

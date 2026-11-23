"""Extract and verify telemetry validation binaries from pinned images."""

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

BINARIES = {
    "collector": "otelcol-contrib",
    "loki": "loki",
    "tempo": "tempo",
    "validationPrometheus": "prometheus",
}
IMAGE_PATHS = {
    "collector": "otelcol-contrib",
    "loki": "usr/bin/loki",
    "tempo": "tempo",
    "validationPrometheus": "usr/bin/prometheus",
}
MAX_LAYER_BYTES = 512 * 1024**2
MAX_BINARY_BYTES = 1024**3


def token_for(repository):
    query = urllib.parse.urlencode(
        {"service": "registry.docker.io", "scope": "repository:" + repository + ":pull"}
    )
    with urllib.request.urlopen("https://auth.docker.io/token?" + query, timeout=30) as response:
        return json.load(response)["token"]


def request(repository, reference, token, kind):
    return urllib.request.Request(
        "https://registry-1.docker.io/v2/" + repository + "/" + kind + "/" + reference,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json",
        },
    )


def download_layer(repository, layer, token, stream) -> None:
    """Download one layer blob into stream, verifying its size and digest."""
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(
        request(repository, layer["digest"], token, "blobs"), timeout=120
    ) as response:
        while data := response.read(4 * 1024**2):
            size += len(data)
            if size > MAX_LAYER_BYTES:
                msg = "Image layer exceeds the inspection budget"
                raise ValueError(msg)
            digest.update(data)
            stream.write(data)
    if size != layer["size"] or "sha256:" + digest.hexdigest() != layer["digest"]:
        msg = "Image layer checksum mismatch"
        raise ValueError(msg)
    stream.seek(0)


def write_member(archive, member, target) -> None:
    """Copy one archive member to target with O_EXCL, after sanity checks."""
    if not member.isfile() or member.size > MAX_BINARY_BYTES:
        msg = "Unexpected image binary member"
        raise ValueError(msg)
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o700)
    with (
        os.fdopen(descriptor, "wb") as destination,
        archive.extractfile(member) as source,
    ):
        shutil.copyfileobj(source, destination, 4 * 1024**2)
    if target.stat().st_size != member.size:
        msg = "Truncated image binary"
        raise ValueError(msg)


def extract(image, name, output):
    repository = image["repository"].removeprefix("docker.io/")
    token = token_for(repository)
    with urllib.request.urlopen(
        request(repository, image["linuxAMD64Digest"], token, "manifests"), timeout=30
    ) as response:
        manifest_body = response.read()
    if "sha256:" + hashlib.sha256(manifest_body).hexdigest() != image["linuxAMD64Digest"]:
        msg = "Image manifest checksum mismatch"
        raise ValueError(msg)
    manifest = json.loads(manifest_body)
    target = output / BINARIES[name]
    if target.exists() or target.is_symlink():
        msg = "Existing validation binaries are never overwritten"
        raise ValueError(msg)
    for layer in manifest["layers"]:
        if layer["size"] > MAX_LAYER_BYTES:
            msg = "Image layer exceeds the inspection budget"
            raise ValueError(msg)
        with tempfile.TemporaryFile(dir=output) as stream:
            download_layer(repository, layer, token, stream)
            with tarfile.open(fileobj=stream, mode="r:*") as archive:
                for member in archive:
                    if member.name.removeprefix("./").lstrip("/") != IMAGE_PATHS[name]:
                        continue
                    write_member(archive, member, target)
    if not target.exists():
        msg = "Expected validation binary was not found in the pinned image"
        raise ValueError(msg)
    with target.open("rb") as stream:
        binary_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "path": str(target),
        "image": image["image"],
        "sha256": binary_digest,
        "bytes": target.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--component", choices=list(BINARIES))
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, exist_ok=False)
    lock = json.loads(args.lock.read_text())
    receipt = {"schemaVersion": 1, "architecture": "linux/amd64", "binaries": {}}
    for name, image in lock["images"].items():
        if args.component and args.component != name:
            continue
        receipt["binaries"][name] = extract(image, name, args.output)
        print(name + ": extracted and verified", flush=True)
    with (args.output / "receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()

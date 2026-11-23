# Harbor writable-filesystem contract (install_cert.sh)

Verified against the pinned images of `deploy/argocd/apps/harbor.yaml`
(harbor 2.15.4 / chart 1.19.4, digests pinned in `deploy/platform/harbor/values.yaml`).

## What was done

- Per-workload NetworkPolicies (`charts/harbor/templates/networkpolicy.yaml`).
- `portal` + `redis` containers run with `readOnlyRootFilesystem: true`
  (commit `5c6dfe9e7`).

## Evidence

### portal: Docker-verified read-only root

harbor-portal@sha256:01edf478505b21dba23a83c095f6ecac0c1e705690093edbab41e9a4d6754a75,
run as `--read-only --user 10000:10000 --tmpfs /tmp`, serving the chart's own
`portal/configmap.yaml` nginx.conf (pid + all `*_temp_path` under `/tmp`):

    $ curl http://127.0.0.1:8080/  ->  HTTP 200

So in-cluster the portal container only needs the `emptyDir` at `/tmp`.

### redis (valkey): config analysis

`valkey-photon` config in image: `daemonize no`, `supervised no`,
`logfile ""` (stdout), `pidfile /var/run/redis_6379.pid`, `dir /var/lib/redis`.
With `daemonize no` valkey never writes the pidfile; all persistence
(`save` RDB snapshots) writes into `dir`, which is the `data` PVC mounted at
`/var/lib/redis`. Docker verification is impossible on the Apple Silicon host:
the amd64 image segfaults inside qemu both with and without `--read-only`,
crashing at image startup, so the crash is an emulation artifact unrelated to
the filesystem mode.

## Why the remaining 5 containers cannot be read-only

`core`, `jobservice`, `registry`, `registryctl`, `trivy` all run the same
image entrypoint `/harbor/install_cert.sh` (`/home/harbor/`, `/home/scanner/`
for trivy variants) before exec'ing the main binary on every start:

    if [ ! -f $ORIGINAL_LOCATION/ca-bundle.crt.original ]; then
        cp /etc/pki/tls/certs/ca-bundle.crt $ORIGINAL_LOCATION/ca-bundle.crt.original
    fi
    cp $ORIGINAL_LOCATION/ca-bundle.crt.original /etc/pki/tls/certs/ca-bundle.crt

The script requires both the image root (`/harbor/ca-bundle.crt.original`) and
the OS CA store (`/etc/pki/tls/certs/ca-bundle.crt`) to be writable; it invokes
unconditionally on Photon. Observed in Docker with `--read-only` on harbor-core:

    cp: /harbor/ca-bundle.crt.original: Read-only file system

An emptyDir overlay on either path also removes the source of the subsequent
`cp`, so the copies fail; hiding `/harbor` hides the main binary itself.
Manifest-level overlays therefore cannot keep these containers read-only —
conclusion: the write is an upstream image design, not a deployment defect.

## Possible long-term fixes (not done here)

- fork/rebuild harbor images with a pre-baked `ca-bundle.crt.original` and
  patched entrypoint, or
- propose to goharbor an env switch to skip runtime CA re-assembly
  (upstream issue/PR), or
- an initContainer that stages the CA store into an emptyDir and an image
  variant whose entrypoint reads only staged state.

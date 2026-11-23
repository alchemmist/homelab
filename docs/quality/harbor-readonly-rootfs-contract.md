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

## Env/secret wiring of `harbor-core`, `harbor-jobservice`, `harbor-registry`, `harbor-trivy`

This deployment runs harbor with `externallyManagedRuntimeSecrets: true`
(`deploy/platform/harbor/values.yaml`): the `harbor-core`, `harbor-jobservice`,
`harbor-pg-common` and related Secrets are provisioned out-of-band (harbor
uploads its config through the bootstrap contract rather than rendered
Secrets), and the vendored upstream chart templates wire the runtime tokens
exclusively through `secretKeyRef` environment variables:

- `harbor-core` (`charts/harbor/templates/core/core-dpl.yaml`): `_REDIS_URL_CORE`,
  `CORE_SECRET`, `JOBSERVICE_SECRET`, `REGISTRY_CREDENTIAL_PASSWORD`,
  `CSRF_KEY` etc. via `secretKeyRef` on `secretName` values like
  `harbor-core`/`harbor-jobservice`;
- `harbor-jobservice`: `CORE_SECRET`, `JOBSERVICE_SECRET`;
- `harbor-registry` (registry + registryctl containers): `REGISTRY_HTTP_SECRET`,
  `REGISTRY_RELOAD_KEY`;
- `harbor-trivy`: `TRIVY_REDIS_URL`… and `SCANNER_TRIVY_REDIS_URL` from
  `secretKeyRef`.

The harbor Go binaries consume these values from the process environment
only (no flag/file alternative exists for CSRF keys, registry shared secret
or the jobservice token in the pinned 2.15.4 binaries; the same env-reading
pattern is shipped by the upstream chart for every deployment), so
`env-value-from` and `read-secret-from-env-var` are unimplementable for these
four Deployments in this repository. Together with the install_cert.sh
writable-filesystem requirement above (which covers `no-read-only-root-fs`
for `harbor-core`, `harbor-jobservice`, `harbor-registry` and `harbor-trivy`),
these findings are registered in
`ci/quality/providers/harbor-image-contracts.yaml` with this document as
evidence.

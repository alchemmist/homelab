# Reproducing the projected schemas

The native Kubernetes schemas are unmodified, locked files. For the CRD object
itself and the custom resources, `quality/schemas.lock.json` also records the
exact source, input bytes (SHA-256), GVK and output SHA-256. Do not substitute a
schema catalog's `main` for the installed controller version.

Extract the specified member from the repository's locked Prometheus chart, or
render the indicated cert-manager template with Helm 3.19.0. Rancher's release
is v2.15.2. CNPG chart 0.29.2 packages controller 1.30.2. Use the immutable
raw file URLs in the lock. The Traefik CRD comes from the K3s v1.36.5+k3s1
bundled chart, not from guessing based on a Traefik container tag:
`https://k3s.io/k3s-charts/assets/traefik-crd/traefik-crd-40.1.5+up40.1.0.tgz`
(SHA-256 `749676684b53240c9024578b8e211053d4e6881c3d54dccb66d5308a01bcb489`).
Acquisition is separate from CI. Verify the input digest, then run locally:

```sh
uv run python scripts/quality/project_schema.py INPUT API_VERSION KIND > output.json
```

For `CustomResourceDefinition` pass `--component` with the locked Kubernetes
OpenAPI component. Compare output bytes to the lock. Projection closes structured
objects, preserves dictionary values, recursive references and free-form
extensions, and validates standard ObjectMeta. JSON Schema alone does not run
Kubernetes CEL, defaulting, conversion, or admission webhooks. Native schema,
Helm and lint errors still block; no resource is approved or skipped here.

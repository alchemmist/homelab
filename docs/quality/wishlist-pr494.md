# Wishlist manifest findings — PR #494

**Disposition: no safe source change without owner decisions.** The blocking offline
manifest report attributes 14 findings to Wishlist. This is not an exception or
waiver; it records the concrete acceptance needed before a later implementation.
No production runtime or user data was inspected for this decision.

The current release is not a generic stateless web pod. It is pinned to the
Wishlist image and owns the app's `/data` volume; the active values enable the
image optimizer, PostgreSQL, telemetry and the accepted `wishlist-socrat5`
stateful placement. The application also uses S3, a PostgreSQL TLS CA, an
application client certificate, and `wishlist-secrets`. These are real service
contracts and must not be removed or replaced to clear a static finding.

| Finding(s) | Required decision/evidence before changing the release |
| --- | --- |
| Default service account | Verify the actual rendered app and initializer have no Kubernetes API use; then explicitly disable token automount for the app pod. Do not grant a new role or change the separate optimizer's already-disabled token. |
| `env-value-from` ×2 / `read-secret-from-env-var` ×2 | Identify each rendered secret reference and verify the exact application image supports mounted/file credentials, including PostgreSQL credentials, telemetry client-key use and rotation/reload behavior. Test successful renewal and denied unrelated secret access with disposable fixtures. Preserve existing secret keys and native TLS. |
| Missing liveness/readiness probes | Obtain the image's supported health contract and distinguish process health from PostgreSQL/S3/optimizer dependency health. Test startup, healthy response, dependency failure, recovery and restart behavior; do not invent a route or use dependency reachability as a liveness signal. |
| Read-only root filesystem ×2 / non-root ×2 | Verify the numeric UID/GID of the pinned app image and initializer and enumerate runtime writes (including optimizer scratch, temporary files and data/cache paths). Test the exact rendered security context with a disposable volume and the real pinned image; preserve PVC contents and ensure no writes escape declared writable mounts. No UID, writable path, or claim migration is guessed here. |
| Non-isolated pod | Compose offline with the actual optimizer, PostgreSQL, S3/RustFS, DNS, telemetry collector and ingress owners. Decide the exact frontend/optimizer and app dependency peer set, including required egress. Then test every permitted flow and representative denied flows in a disposable environment. Do not add a default-deny policy with guessed peers. |
| CPU/memory requests | Obtain measured startup/steady-state and image-optimization resource floors for the real app image and active workload. The optimizer already has its own memory and scratch limits; do not copy those values to the app or invent CPU/memory requests. |

Scoped checks performed against the current source: `tests/test_wishlist_images.py`,
`tests/test_wishlist_observability.py`, and `tests/test_wishlist_vm105.py` (10 passed),
and a local `helm template` render of the production Wishlist values. These verify
the existing optimizer boundary, observability credential scope, and retained
stateful handoff contracts; they do not establish the missing image/runtime
contracts above or clear the 14 findings.

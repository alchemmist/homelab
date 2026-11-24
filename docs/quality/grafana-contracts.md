# Grafana runtime contracts (env wiring, sidecar RBAC, init-chown root)

Applies to the `grafana` release (charts/grafana wrappers the upstream grafana
14.5.0 subchart + image-renderer; images pinned by digest in
`deploy/grafana/values.yaml` and the grafana subchart: grafana
`13.3.1-distroless@sha256:54e297ac...`, image-renderer
`v5.12.10@sha256:a7970b82...`).

## Objects

This document covers, per object name: `kube-prometheus-stack-grafana`
(Deployment), `kube-prometheus-stack-grafana-image-renderer` (Deployment), and
`kube-prometheus-stack-grafana-clusterrolebinding` (ClusterRoleBinding).

## env wiring (Deployment `kube-prometheus-stack-grafana`, container `grafana`)

Grafana reads its entire runtime configuration from environment variables
(`GF_*` / `GF_SECURITY_*`). By upstream design there is no file-based
alternative for these values; the subchart exports them as Secret refs from
the `grafana.envValueFrom`/`envFrom` wiring. Docker-verified: the pinned
distroless image starts as uid 472 and serves `GET /api/health` -> 200 under
`--read-only` + tmpfs `/tmp` + a writable `/var/lib/grafana` data volume.

Environment secrets consumed by the main container (all Secret key refs, no
Kubernetes Secret written into a writable mount):
- `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` (secret
  `socrat-grafana-admin`) - local admin bootstrapping.
- `GF_DATABASE_PASSWORD` (secret `grafana-postgres`) - the pg-common database
  credential, verified against `pg-common-rw.postgres.svc.cluster.local`.
- `GF_RENDERING_RENDERER_TOKEN` (secret `socrat-grafana-renderer`) - shared
  auth token used by the image-renderer sidecar (its `AUTH_TOKEN`).
- OIDC client secret (`GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET`) via
  `extraSecretMounts` at `/etc/grafana/secrets/authentik/client-secret`
  (filesystem-provided because Grafana's OAuth config references it through
  `$__file{}`).

Secrets are managed out-of-band (externally-managed runtime secrets, same
registration class as harbor/netbird/monori/litellm env contracts).

## env wiring (Deployment `kube-prometheus-stack-grafana-image-renderer`)

The image-renderer's `AUTH_TOKEN` (secret `socrat-grafana-renderer`) is read
from the environment; the image-renderer server has no file-based config
channel for it. Docker-verified: the pinned image-renderer v5.12.10 as uid
1000 under `--read-only` serves `GET /healthz` on :8081 -> 200 (probe target).

## access-to-secrets (ClusterRole/ClusterRoleBinding)

`kube-prometheus-stack-grafana-clusterrole` grants `configmaps, secrets`
`get, watch, list` to the grafana ServiceAccount. This is the Grafana
k8s-sidecar data contract: the deployed sidecars run with `RESOURCE: both`
(verified in the rendered pod spec) and must watch/read ConfigMaps
(dashboards, label `grafana_dashboard`) and Secrets (datasource credentials,
label `grafana_datasource`) to auto-provision them into Grafana. The role is
scoped to exactly those read verbs on those two resources - no write, no other
APIs - so it is the least privilege the sidecar model permits.

## init-chown-data runs as root

The pinned `initChownData` init container (`library/busybox:1.38.0`) chowns
the on-disk Grafana data directory under the node-local PV
(`/mnt/files/homelab/grafana/data`, type local-path) so the app user (472) can
write it. `chown` of a host/volume path requires uid 0; no non-root user can
co-own a freshly-created PV directory owned by the kubelet. The container
drops all capabilities except `CHOWN` and `DAC_OVERRIDE`, runs seccomp
RuntimeDefault and a read-only root filesystem (verified rendered SC:
`runAsNonRoot: false, runAsUser: 0, readOnlyRootFilesystem: true`). It only
sets ownership and exits; the privileged window is confined to an init
container.

## Isolation

NetworkPolicy `grafana` (subchart `networkPolicy`, enabled in values):
ingress :3000 from the edge traefik namespace and (for metrics) the monitoring
namespace; egress scoped to platform postgres :5432 (Grafana DB), identity
authentik-server :443/:9443 (OIDC) and DNS. The image-renderer NetworkPolicy
already restricted ingress :8081 to the grafana pod.

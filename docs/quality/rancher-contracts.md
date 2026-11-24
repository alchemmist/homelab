# Rancher cluster-manager contracts

The `rancher` release (`charts/rancher`, vendored Rancher 2.15.3, image
`rancher/rancher:v2.15.3@sha256:3f3a50c6...`, namespace cattle-system) manages
the local Kubernetes cluster. Its mandatory contracts follow from what Rancher
upstream does, not from a loose over-privilege.

## rancher Deployment (rancher/rancher)

- **run-as-non-root / no-read-only-root-fs**: `/usr/bin/entrypoint.sh`
  (verified via `docker run --entrypoint sh` against the pinned image) restores
  `/var/lib/rancher-data/local-catalogs` git repos at every startup
  (`git checkout HEAD` per repo), moves cgroup subtrees, and initializes
  `/var/lib/rancher/k3s` state (`rm node-passwd`, etcd symlink/reset). The
  catalog dirs and k3s state must be written and chowned on startup, which a
  read-only root filesystem and a non-root user cannot satisfy. Rancher server
  is the cluster manager and runs as root by design.
- **privileged-ports**: the rendered deployment passes
  `--http-listen-port=80 --https-listen-port=443`, the standard public
  web/HTTPS ports for the Rancher UI and API. Rancher binds them as root; the
  K8s `privileged-ports` advisory is informative here, not a violation.
- **cluster-admin-role-binding**: Rancher is a Kubernetes multi-cluster
  manager; the local cluster it runs in is the very cluster it manages, so the
  ServiceAccount is bound to `cluster-admin` by the chart's own
  `clusterRoleBinding.yaml`. This is the documented upstream requirement
  (Rancher installs with cluster-admin on the local cluster). It is the
  intended access model, not an accidental escalation. Requires the
  owner-reviewed exception (see the explicit registry pin).

## rancher-post-delete Job (rancher/shell, teardown RBAC)

`access-to-secrets` and `access-to-create-pods` come from the chart's
`post-delete-hook-cluster-role.yaml`: uninstalling Rancher must enumerate and
delete secrets, services, configmaps and serviceaccounts, and create/delete
cleanup jobs. This is the documented Rancher teardown RBAC scope - read/delete
for the cleanup of exactly Rancher's resources. Least privilege for an
uninstaller.

## What was fixed in this pass

- pre-upgrade + post-delete hook Jobs: `runAsNonRoot: true` uid/gid 1000
  (the scripts are pure kubectl orchestration; no host-level/root ops were
  found in `scripts/pre-upgrade-hook.sh` / `post-delete-hook.sh`, and the
  pinned `rancher/shell` image itself defaults to uid 1000), all capabilities
  dropped, RuntimeDefault seccomp, read-only rootfs, resource requests/limits
  set, and `ttlSecondsAfterFinished: 3600`.
- NetworkPolicies `rancher-isolation` and `rancher-pre-upgrade-isolation`
  (cattle-system): ingress :80/:443 from edge traefik; egress DNS, the public
  443 edge, and the in-cluster API; hook Jobs reach the API + DNS only.

# Harbor container registry

Public endpoint: **https://harbor.socrat.alchemmist.xyz**.
Official Harbor chart **1.19.4**, Harbor **2.15.4**, archive SHA-256 pinned in
`ansible/roles/harbor/defaults/main.yml`. Values: `deploy/harbor/values.yaml`.

## Architecture and access

All six Pods (seven containers) run on socrat-0. Traefik home and VPS share
ingress and the cert-manager-managed `harbor-tls` certificate. Edge namespace
allowlist includes `harbor`, including HTTP-01 solver resources.

Registration is disabled and only admins can create projects. Both `homelab`
and the default `library` project are private. `homelab` initially has an 80 GiB
Harbor project quota. There is no anonymous pull of private images.

Robot accounts expire after **90 days** and must be renewed/rotated before expiry:

- `ci-push`: repository pull/push in `homelab` only;
- `cluster-pull`: repository pull only in `homelab`.

The initializer never silently rotates existing robots. If the local credential
file is missing but a robot exists, it stops: rotate that robot deliberately.
Do not use admin credentials in CI or application namespaces.

Credentials are generated once on socrat-0 under
`/home/alchemmist/.cache/homelab-harbor/` (0700 directory, 0600 credential files).
`private-values.json` contains the initial admin password and database/encryption
secrets. Robot results are `ci-push.json` and `cluster-pull.json`. Do not print,
commit, or place these in logs. Helm release Secrets also contain sensitive values.
Admin login is `admin`; retrieve the password through a private local channel.

Initial robot credentials were also copied to the administrator Mac under
`~/.config/homelab/harbor/`, outside Git. The smoke-test Docker login uses the
isolated `~/.config/homelab/harbor/docker/` directory, not the normal Docker config.
Docker config contains a credential, not encryption; protect it like a password.

## Deployment

From `ansible/`, with verified SSH access:

```sh
ansible-playbook playbooks/harbor.yml
```

When dual-address public SSH selects the VPS, use a verified direct inventory
hostname override and the existing host key alias, not StrictHostKeyChecking=no.
The initial deployment used home IP `109.173.40.247` and
`HostKeyAlias=[socrat.alchemmist.xyz]:2222`.

The playbook prepares the namespace, reconciles edge ingress, checks at least
6 GiB available RAM and 150 GiB free disk, deploys Harbor, waits for TLS,
configures projects/robots, and sets PV reclaim policies to Retain.
It does not redeploy existing applications or migrate their GHCR references.

Use image names such as:

```text
harbor.socrat.alchemmist.xyz/homelab/blog:<git-sha>
```

CI should push immutable git-SHA tags and deploy by digest. Put the push robot
in the CI secret store. Create a `kubernetes.io/dockerconfigjson` Secret with the
pull robot in each consuming namespace and reference it in `imagePullSecrets`.
No cluster-wide unauthenticated registry or insecure TLS exception is needed.
Fleet image automation credentials are a separate integration, not yet configured.

### Blog CI/CD pilot (2026-11-01)

`alchemmist/blog` now validates the Hugo/Pagefind site in GitHub Actions, builds
`site/Dockerfile.blog`, and pushes the image to Harbor with its Git SHA as the
tag. CI then makes one Argo CD Application `PATCH` containing the pushed
`sha256` digest; it does not commit a version bump to Git or issue a separate
Sync request. Argo auto-sync is enabled only for the `blog` Application, with
`prune=false` and `selfHeal=false`.

The `blog` AppProject restricts source to this repository, destination to the
`blog` namespace, and its `ci` role to `applications,update` on `blog/blog`.
The project token is a GitHub Actions secret, not stored in Git. Rotate it before
its one-year expiry. The `blog-harbor-pull` Secret supplies namespace-scoped
registry authentication. The Argo Application renders only the `Service`,
`Deployment`, and `Ingress`; its Helm chart and base values remain in
`homelab/main`, while the live image digest is held in the Application object.
The AppProject and Application were created through the Argo API and are not yet
represented as manifests in Git.

The first CI-published image was applied successfully; both replicas became
ready on socrat-1 and socrat-3, Argo reported `Synced/Healthy`, and both public
blog hostnames returned HTTP 200. Pulling the ~235 MB content layer to socrat-3
took about 13 minutes, so monitor Argo health during future releases. The prior
live image was `ghcr.io/alchemmist/blog:7da9b66790ef5c669561ad4791977eb42ae14c08`.
For emergency rollback, set the Application's Helm parameters to that GHCR
repository/tag and clear `image.digest`; auto-sync will restore it. The next CI
release replaces the parameter list with Harbor's new digest.

The old Helm release record is retained for audit; Fleet/Helm no longer
reconcile this workload. Do not run `helm upgrade` or `helm uninstall` for
`blog` after this ownership transfer. Other applications still using GHCR have
not been migrated.

## Storage, retention and recovery

Explicit **local-path** PVCs: registry 100 GiB, PostgreSQL 5 GiB, Redis 1 GiB.
All reside on socrat-0; no NFS dependency is added. PVC keep annotations and PV
Retain protect against normal Helm uninstall/PVC deletion, not disk loss.
Local-path requested capacity is **not an enforced filesystem quota**. Monitor
actual filesystem usage; Harbor's project quota does not include every kind of
filesystem overhead, logs or deleted-but-not-garbage-collected layers.

This is **single-node storage, not HA**. An outage of socrat-0 prevents push and
uncached pull even if the VPS ingress is alive. Existing running containers are
not stopped by registry loss. Do not make Harbor's own bootstrap depend on itself:
upstream Harbor images remain on Docker Hub.

Trivy, automatic garbage collection and retention deletion are not enabled.
Choose release/rollback retention before scheduling deletion; deleting a tag
needed by a Deployment can break its next restart.

**Scheduled independent backups are not configured yet.** Before relying on this
registry as the sole image copy, establish and test off-node backups. Preserve:

1. An application-consistent PostgreSQL dump (`pg_dump` from harbor-database).
2. Registry PVC contents, coordinated with the database and without concurrent
   pushes/deletes/GC; use a maintenance window to quiesce writers.
3. Bootstrap secrets, chart version, values, TLS/token signing Secrets and robot
   credentials, in encrypted private backup storage, not Git.

Restore into isolated storage first: recover the same chart and secrets, database
and registry data, then verify authenticated pull by known digest. Do not delete
original PVs or overwrite a running database to test restoration. Redis is not a
substitute for the PostgreSQL/registry backup.

## Initial verification (2026-10-30)

- Trusted HTTPS and `/api/v2.0/health` 200 through both public IPs; all components healthy.
- Anonymous `/v2/` returns 401 through both entrances.
- Push robot uploaded `homelab/registry-smoke:1.37.0` (BusyBox linux/amd64).
- A Pod on socrat-1 pulled it with the pull-only robot, `imagePullPolicy: Always`,
  and logged `harbor-pull-ok`.
- Smoke Pod and its temporary image-pull Secret removed after verification;
  the small smoke image remains available for future checks.
- Jobservice restarted during initial dependency startup, then became Ready.

Not verified: physical node-loss or restore from backup. CI integration and
initial deployment migration are verified for the blog pilot only; other
application image references remain unchanged.

## Distributed HA work

The requested HA migration is tracked in [harbor-ha.md](harbor-ha.md). Initial
read-only preflight is implemented and currently blocks staging on resource
headroom, including OTel reservations. No distributed dependencies or storage
migration have been applied. The active installation above is unchanged.

## Authentik migration (2026-11-01)

Native OIDC is active; `homelab-owner` maps to Harbor system admin. Local `admin`
remains break-glass and robots are unchanged. The saved initial admin password may
be stale; do not reset it or rerun the old initializer just to change auth. A supported
Secret-backed CONFIG_OVERWRITE_JSON and conditional Helm identity overlay preserve
OIDC configuration. See [identity/access-management.md](identity/access-management.md)
for migration, backup/restore evidence and remaining browser acceptance.

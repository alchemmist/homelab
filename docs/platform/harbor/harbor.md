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
Fleet image automation was never configured. Homelab GitOps no longer uses Fleet GitRepos; image rollout is Argo CD. This pilot note is historical and is not an instruction to enable Fleet.

### Blog CI/CD pilot (2026-11-01)

`alchemmist/blog` now validates the Hugo/Pagefind site in GitHub Actions, builds
`site/Dockerfile.blog`, and pushes the image to Harbor with its Git SHA as the
tag. CI then makes one Argo CD Application `PATCH` containing the pushed
`sha256` digest; it does not commit a version bump to Git or issue a separate
Sync request. Argo auto-sync is enabled only for the `blog` Application, with
`prune=false` and `selfHeal=false`.

The `blog` AppProject restricts source to this repository, destination to the
`blog` namespace, and its `ci` role to `applications,update` on `blog/blog`.
Its namespace-resource allowlist contains `Service`, `Deployment`, `ReplicaSet`,
`Pod`, and `Ingress`; cluster-scoped resources are not allowed. The `ReplicaSet`
and `Pod` entries let Argo CD include the Deployment's generated children in the
resource tree. Argo RBAC is application-scoped rather than field-scoped: the
token can update other fields on this one
Application, so digest-only behavior is a workflow convention, backed by the
project's source, destination, and resource restrictions. The project token is a
GitHub Actions secret, not stored in Git. Rotate it before its one-year expiry.
The `blog-harbor-pull` Secret supplies namespace-scoped registry authentication.
The chart and base values remain in `homelab/main`, while the live image digest
is held in the Application object. The AppProject and Application were created
through the Argo API and are not yet represented as manifests in Git.

The first CI-published image was applied successfully; both replicas became
ready on socrat-1 and socrat-3, Argo reported `Synced/Healthy`, and both public
blog hostnames returned HTTP 200. During the slow pull, socrat-3 briefly stopped
posting node status, then recovered. Pulling the ~235 MB content layer to socrat-3
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

Trivy and scan-on-push are enabled for `homelab` and `library` (verified
2026-11-04). Weekly GC runs Sunday 03:00 UTC with one worker, explicitly
`delete_untagged=false` and `delete_tag=false`. Artifact/tag retention deletion
is **not** enabled: preserve every release, in-use and rollback artifact.
The API-applied policy is recorded in
`deploy/platform/harbor/maintenance-policy.json`; this file documents Harbor DB
settings and is not automatically applied by Helm. A successful non-deleting
dry-run preceded scheduling; its inventory of 60 artifacts / 62 tags was unchanged.

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
OIDC configuration. See [identity/access-management.md](../../auth/architecture/access-management.md)
for migration, backup/restore evidence and remaining browser acceptance.


## Verified scanning and GC (2026-11-04)

- Authenticated through the existing break-glass admin, without changing passwords,
  OIDC, signing keys, or robot rights. Credentials are never tracked in Git.
- Trivy v0.75.0 is the enabled default scanner. Cats manual scan completed Success.
- Re-published the *identical* existing Socrat Home index at its existing tag;
  automatic scan-on-push completed Success in 8 seconds. No tag target or image
  changed. Its report found 216 vulnerabilities (3 Critical / 60 High); Cats found
  53 (1 Critical / 5 High). Vulnerability remediation is separate work. Pull
  blocking by severity was not enabled, so scans do not unexpectedly block releases.
- GC execution 13: Success, dry-run true, deletion of untagged artifacts and tags
  both false, one worker, server-enforced 2h safety window. No unreferenced artifacts,
  0 purged blobs/manifests, 0 freed bytes. Full artifact/tag inventory unchanged.
- Weekly schedule 3: `0 0 3 * * 0` UTC; first run 2026-11-08 03:00 UTC.
  No artifact/tag retention policy was created. This conservative GC may reclaim
  nothing when no artifacts have been explicitly removed; that is intentional.
- Job logs currently use stdout only, so the Harbor GC log-download API returns
  500. Dry-run parameters/results were verified in jobservice stdout and GC history;
  this does not indicate a failed GC or jobservice restart.
- LMS, Cats, Format Quorum and all three Monori CI releases are verified end-to-end.
  Cats, Format Quorum, Monori and Socrat Home run from Harbor. GHCR originals are
  retained, and LMS remains GHCR intentionally. All 42 Argo Applications were
  Synced/Healthy; Harbor restart alerts resolved without disabling alert rules.

## Hosted-runner graph-release transport compatibility (2026-11-09)

The SPI/bot release failure was Go TLS key-share transport compatibility, not a
missing `/service/token` secret. Python HTTPS verified existing robot pull/push
grant; isolated BuildKit uses `GODEBUG=tlsmlkem=0` with a private ephemeral Docker
config from `scripts/harbor_ci_auth.py`. Normal TLS validation and public DNS
remain enabled; no global daemon/ingress TLS policy, robot rights or cluster
pull identity changed. The experimental Harbor TLSOption was reverted and
removed. Bot run42629684670 and SPI run42622862630 completed the ordinary
Harbor→homelab→Argo cycle. See monitoring/alert-graphs.md for pinned digests and
activation proof; do not rotate working secrets to diagnose this TLS symptom.

## Harbor: the Socrat cluster registry

> **PostgreSQL (2026-11-20):** The working registry DB is the external `pg-common/registry`; the original PVC is retained, blob storage was not moved. [Operations and CA](../../data/postgresql/postgres-platform.md).

Snapshot of **October 30, 2026**. Harbor is already deployed; the distributed HA
scheme is not deployed yet due to resources. This is context and an
instruction, not a replacement for a live check.

## Observer: current restriction as of November 8, 2026

**`homelab-observer` does not open Harbor.** Native Guest correctly forbade
push/delete, but the old CLI secret kept receiving pull after the IdP group was
removed. Therefore only the observer admission and its Guest bindings in
`homelab`, `library`, `spi-triage` were removed; the owner, robots and other
grants are untouched. Verified: the old synthetic session sees zero projects,
a new registry JWT contains no actions. An already issued signed JWT is not
revoked retroactively (a 30min TTL was observed).

Do not restore these rights from an old bootstrap/readiness receipt, do not
delete people or reset their passwords to bypass the cache. Reopening needs a
separate native revocation acceptance:
[#134](https://github.com/alchemmist/homelab/issues/134),
[observer evidence](../../records/handoffs/observer-acceptance-20261108.md).
The remaining registry/robot information below keeps its snapshot date.

## Entry and state

- Public UI and registry: **https://harbor.socrat.alchemmist.xyz**.
- Harbor **2.15.4**, official chart **1.19.4**, archive SHA-256 pinned.
- The ordinary human web login is **native Authentik OIDC/MFA** with separately
  reviewed project permissions. The local **admin** is kept for emergency
  recovery, not as the shared everyday login. The old description “admin only,
  no personal users” refers to the initial bootstrap, not the current mode.
- The initial admin password on socrat-0:
  `~/.cache/homelab-harbor/private-values.json`, field `harborAdminPassword`.
  After a password change in the UI, the file does not guarantee the password
  is current.
- Never print passwords, robot secrets or private-values contents into chat,
  logs or Git. On the Mac the password can be piped straight into `pbcopy` over
  SSH without printing it in the terminal. Do not use robot account logins for
  the web UI.

## Images and automation

Private project **homelab**, initial quota 80 GiB. The standard `library`
project was also switched to private. Only admins create projects.

Image reference format:

```text
harbor.socrat.alchemmist.xyz/homelab/<application>:<git-sha>
```

For production, pinning the digest is preferable. Do not rely on the mutable
`latest`.

**Project-scoped** (not global) robot accounts were created:

| Purpose | Name in the credential file | Rights |
|---|---|---|
| CI | `name` field from `ci-push.json` | repository pull/push in homelab only |
| Kubernetes | `name` field from `cluster-pull.json` | repository pull in homelab only |

Use the exact name from the file: Harbor adds a robot/project prefix. Both
expire **90 days from creation**; timely rotation is required. If the local
credential file disappears, the initializer does not silently recreate an
existing robot: the rotation must be explicitly agreed.

Credentials on socrat-0, directory 0700, files 0600:

```text
~/.cache/homelab-harbor/private-values.json
~/.cache/homelab-harbor/ci-push.json
~/.cache/homelab-harbor/cluster-pull.json
```

On the Mac, robot credentials are copied outside the repository:

```text
~/.config/homelab/harbor/ci-push.json
~/.config/homelab/harbor/cluster-pull.json
```

### Push from the Mac

The command below passes the password via stdin, not a command-line argument.
It uses a separate Docker config without changing the primary Docker login:

```sh
python3 - <<'PY'
import json
from pathlib import Path
import subprocess
root = Path.home() / '.config/homelab/harbor'
r = json.loads((root / 'ci-push.json').read_text())
config = root / 'docker'
config.mkdir(mode=0o700, exist_ok=True)
subprocess.run(['docker', '--config', str(config), 'login',
                'harbor.socrat.alchemmist.xyz', '--username', r['name'],
                '--password-stdin'], input=r['secret'], text=True, check=True)
(config / 'config.json').chmod(0o600)
PY

docker tag my-app:build harbor.socrat.alchemmist.xyz/homelab/my-app:<git-sha>
docker --config "$HOME/.config/homelab/harbor/docker" push \
  harbor.socrat.alchemmist.xyz/homelab/my-app:<git-sha>
```

Replace `<git-sha>` with a real SHA. The Docker config contains the secret in
reversibly encoded form: protect it like a password. In CI use a secret store
and an ephemeral Docker config; do not copy the admin password.

### Pull from Kubernetes

- Create a `kubernetes.io/dockerconfigjson` Secret with the **pull-only** robot.
- The Secret is needed **in every namespace** where the application pulls
  private images.
- Reference it via Pod `imagePullSecrets` or an explicitly chosen
  ServiceAccount. Do not change all ServiceAccounts globally without a reason.
- Do not put credentials into open Helm values or Git. Argo CD reads Git; there
  are no separate Fleet GitRepos in the repository.
- No insecure registry/TLS skip verify is needed: the HTTPS is trusted.

**The migration to Harbor is already done for the blog, Cats, Format Quorum,
Monori and Socrat Home; LMS intentionally remains on GHCR.** Do not enable
Fleet image automation: the Fleet GitOps manifests are removed, rollout
happens via Argo CD. Verified CI runs and digests are given in the later dated
sections.

## How it is deployed now

All components on **socrat-0**, 6 Pods / 7 containers. Local-path PVCs:
registry 100 GiB, PostgreSQL 5 GiB, Redis 1 GiB. PVC keep and PV reclaim
**Retain**. This protects against resource deletion, it is **not a backup**
and not HA. Local-path capacity is not a hard filesystem quota.

Two public ingresses (home and VPS) share one ingress/TLS Secret.
The `harbor` namespace is included in `charts/traefik-edge/values.yaml`.

If socrat-0 is lost, new push/pull are unavailable; running containers keep
working. Scheduled independent backups and restore are **not configured yet**.
Do not make Harbor the only copy of critical images until they are.
Trivy, automatic GC and retention deletion are still disabled.

Sources and application:

- `deploy/harbor/values.yaml`;
- `ansible/roles/harbor/`, `ansible/playbooks/harbor.yml`;
- `docs/platform/harbor/harbor.md` — operations and recovery;
- from `ansible/`: `ansible-playbook playbooks/harbor.yml`.

An SSH dual-address hostname can land on the wrong public entrance. For
socrat-0 the home override `Hostname=109.173.40.247` with the previous
`HostKeyAlias=[socrat.alchemmist.xyz]:2222` is verified. Do not disable host key
checking. Do not run the playbook automatically just to read state.

Verified: health 200 and trusted TLS through both public IPs; anonymous `/v2/`
401; a BusyBox push by the push robot, a pull by a Pod on socrat-1 with the
pull robot and `Always`, log `harbor-pull-ok`. The test Pod and temporary
Secret were removed; the smoke image kept. This is not a node-failure or
restore test.

## The agreed HA direction

The user chose a full distributed Harbor but accepted the current lack of
resources. The plan is in `docs/platform/harbor/harbor-ha.md`:

1. Two replicas each of core/portal/jobservice/registry on socrat-0/1.
2. A three-node S3 store on socrat-0/1/3, Garage with RF=3 as the candidate;
   compatibility and quorum/rejoin still need testing.
3. CloudNativePG, 3 PostgreSQL instances with synchronous replication.
4. Redis/Valkey + Sentinel on three nodes; **not Redis Cluster**.
5. Keep the URLs, encryption/token signing keys and users/robots.

The goal is to survive the loss of one node, including socrat-0. **Do not
promise survival of losing the apartment:** two of the three nodes of the
scheme are at home; the quorum disappears together with them.

HA dependencies and migration are **not applied**. A read-only preflight is
implemented:

```sh
python3 scripts/harbor-ha-preflight.py collect --output /tmp/harbor-ha-inventory-UNIQUE.json
python3 scripts/harbor-ha-preflight.py check \
  --inventory /tmp/harbor-ha-inventory-UNIQUE.json \
  --output /tmp/harbor-ha-capacity-UNIQUE.json
```

New unique names; files 0600, no overwriting. Data older than 15 minutes is
rejected. Exit 1 — resource blocker, 2 — inspection error. Even a successful
gate does not authorize a cutover: backups/restore, compatibility and failover
tests are still needed.

The policy `deploy/harbor/ha-policy.json` keeps the OTel reservation
independently of its unfinished files. If a local OTel policy is present, the
larger reservation is taken; a missing file does not zero out the already
agreed memory need.

First gate: socrat-1/3 lack RAM and scheduler headroom; socrat-0 fails the disk
margin given the preliminary staging budget. The historical report is in
`deploy/harbor/migration-evidence/capacity-initial.json`; do not treat it as
live. Do not shrink budgets for a green result, do not take resources from
OTel and do not delete data without agreement. The next step is a decision on
RAM/capacity, then an independent verified backup and an isolated HA
foundation deployment.


## Addition November 1, 2026: Authentik

**Harbor now uses native OIDC / Authentik**: provider grant_types fixed,
`systeminfo.auth_mode=oidc_auth`, owner group → system admin. The old local
admin remains the emergency entry. The initial admin password turned out to be
stale; it was not reset. A supported CONFIG_OVERWRITE_JSON from a Secret and a
separate Helm overlay were applied. Private projects and scoped robots are
preserved: after the migration the pull-only robot received a BusyBox manifest
200 with the previous digest. Browser owner login still needs verification.

Before the switch, an encrypted DB+registry+credentials backup was made on
the Mac; the PG18 dump was restored into an isolated PG18, three blobs were
SHA-256 checked. This is not a full Harbor DR. Do not apply the legacy
bootstrap API with the stale initial password after OIDC activation. Other
SSO details/boundaries: `docs/auth/architecture/identity.md`.

## Runtime repair — 2026-11-04

- Argo rendering upstream `lookup`/random Secret defaults rotated internal core/jobservice tokens. A running core retained its original environment, causing jobservice internalconfig HTTP 401. Restored runtime token/password values privately, retained the original signing keypair from the private Helm release, and disabled rendering existing runtime Secrets with `externallyManagedRuntimeSecrets: true`. Existing Secrets remain in the cluster; their Argo tracking annotations were removed explicitly, without pruning or credential publication.
- Core CONFIG_OVERWRITE_JSON now references `socrat-authentik-harbor/config-json`, preserving the deployed Authentik configuration rather than applying db_auth defaults.
- Verified Harbor health API healthy; core/jobservice/database/registry Ready. Trivy enabled with CPU/memory limits and verified Ready. Scan-on-push and GC are NOT yet verified: bootstrap admin credential cannot authenticate to administrative GC API; do not reset OIDC/admin credentials or schedule destructive retention to bypass this.
- Removed unused switcher monitoring objects and unused syncthing-private-nginx ConfigMap after confirming no pod references. No global prune enabled. Cert-manager selector drift and remark42 credential preservation corrected in Git.
- Release action now pins GitHub host keys, uses an explicit private key without ssh-agent, bounds network calls/retries, uses SSH-over-443, and rebases the same commit on concurrent main updates including remote ref lock races. Static/unit checks pass; main and v1 published through 56037a9. LMS end-to-end verification remains pending.
- GitHub status reports an active Git Operations incident (intermittent Git errors); observed SSH auth failures and HTTPS Internal Server Error. No proof of deploy-key expiration. Do not rotate all keys as an incident workaround.
- Remaining: LMS HA ownership drift, scan-on-push/GC administrative access, exact-digest registry/CI migration. Backups/NFS remain outside this task.

### Migration and upload-path verification — 2026-11-04

- All 42 Applications reached Synced/Healthy after LMS HA ownership restoration (`849e078`); CNPG 3/3, existing backup PVC and schedule preserved. No backup redesign or NFS work performed.
- Copied the exact missing Format Quorum and Monori sync OCI indexes. Verified digest plus both amd64/attestation child manifests through the public Harbor endpoint with the existing pull robot. Copied/pinned Cats, Format Quorum, Monori front/back/sync and Socrat Home to Harbor; namespace pull Secrets provisioned before activation. GHCR originals retained, LMS remains GHCR by agreement, deleted Yandex Voice application not recreated.
- Monori sync's large layers needed a bounded internal-registry upload with existing registry credentials, followed by public authenticated manifest publication and digest verification. Temporary copier pods and their credential Secret were deleted.
- Corrected earlier timeout diagnosis: traefik-edge had no request-body deadline, but the separate k3s home Traefik still used its default 60s read timeout. This caused public Harbor large-layer PUT/PATCH HTTP 499. Updated the existing HelmChartConfig and Ansible home_ingress_ha role to preserve tracing/HA arguments and disable web/websecure body-read deadlines. Kept the bundled Rancher/k3s chart and verified deployed flags and 2/2 rollout.
- Source CI commits: Cats `84cf901`, Format Quorum `74b7e85`, Monori `71cac39` publish to both Harbor and GHCR in the same build, then invoke the existing single-step deploy action. Removed the active legacy SSH deploy workflows in Format Quorum and Monori. Cats run `41831884179` succeeded; Format Quorum run `41831893923` succeeded after the home-ingress fix. Monori run `41831902224` is still being verified; front/back publish+record steps have succeeded.
- Scan-on-push and GC remain blocked on working administrative Harbor access. Both the provisioned bootstrap password and original private Helm-release admin password return 401. Robot credentials support image push/pull, not global administration. No password/OIDC reset, DB credential changes, retention deletion or GC scheduling performed to bypass this. Trivy is Ready, but that alone does not prove a successful vulnerability scan.

### Final verified checkpoint — 2026-11-04

Monori CI **41831902224** completed successfully after the home-ingress timeout fix, including all three build/publish/record steps. Current Harbor indexes and all child manifests verified with the pull robot and matched to live Deployment images:

- Cats: `sha256:ffef7edb39d622190b6ba88642bc35f7a8b159943532517889a3ff8d795ed179` (2 Ready).
- Format Quorum: `sha256:2c7127c13aa1ea1efd1ab6e59d4f0a043d19a46ec70462d2ddf876dc351eb153` (1 Ready).
- Monori front: `sha256:ef7def1d4eafdfa28cf4bd72f26fda1bceeb5c335510e26a56029a9f9b1b03c6`; back: `sha256:4543c95fe7f26b342878cee4cee0648918c6ed55f1f62584227661c3efe11ff6`; sync: `sha256:762c3b18504541e195b99ee2999fe723a466ff0bccb06211c87c75a038d33dbd` (each Ready; sync rollout completed).
- Socrat Home: `sha256:41e26b089357b32fc7caefc21dc2bc1dfcb12c7e8f90373fb11dfefb152c734f` (2 Ready; source was already this exact live GHCR index). No separate upstream repository or CI invented.

The only running own-service GHCR image is LMS, intentionally retained there. All temporary image-copy Pods and their credential Secret are removed. Remaining gate is administrative access for scan-on-push and GC: request a working existing admin credential/session through a private local channel; never paste credentials into issue/chat/Git. Until then neither GC dry-run/schedule nor scan-on-push is claimed enabled. No tag/artifact retention deletion performed.

### Administrative gate resolved — 2026-11-04

Working existing break-glass admin access was supplied privately; no password/OIDC/robot-rights reset performed. Scan-on-push enabled and read back for homelab and library. Trivy v0.75.0 default scanner verified with Cats manual scan Success (53 vulnerabilities, 1 Critical/5 High) and actual Socrat Home push-triggered automatic scan Success (216 vulnerabilities, 3 Critical/60 High). The latter re-published identical bytes at an existing tag; no image or tag target changed. Pull blocking was not enabled.

GC dry-run execution 13 succeeded with delete_untagged=false, delete_tag=false, workers=1, server safety window 2h: 0 purged blobs/manifests, 0 bytes freed; all 60 artifacts and 62 tags unchanged. Weekly schedule 3 configured for Sunday 03:00 UTC (cron `0 0 3 * * 0`, next 2026-11-08). No retention/deletion policy enabled. Conservative no-op GC when there are no unreferenced artifacts is expected. API-applied policy intent recorded in deploy/platform/harbor/maintenance-policy.json; Helm does not apply this JSON. Job log download API returns 500 because existing jobLoggers is stdout-only; job parameters/success were verified in stdout and GC history. No broader logging/storage change made.

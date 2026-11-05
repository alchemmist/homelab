# Reader-only namespace relocation (source prepared, NOT activated)

This supersedes the shared-edge watch-list/restart prerequisite in earlier live
handoffs. Identity is already watched by both entrances. Do not apply the old
edge namespace handoff diff. No edge Deployment, strategy, ports, RBAC or replicas
change is needed or authorized. Public acceptance remains incomplete; DNS sudo
and human browser/native OIDC acceptance remain independent pending gates.

## Source boundary

`gateway.namespace` defaults to `rustfs`; only `rustfs` and `identity` render.
It moves only reader Deployment, Service, isolation NetworkPolicy and reader
Ingress. Authentik console/certificate/outpost Ingress remains identity unchanged.
Storage, retained PVC/PV, root/OIDC Secrets and RustFS stay rustfs (Application
release namespace must remain rustfs). The reader image now defaults exclusively
to `http://rustfs.rustfs.svc.cluster.local:9000`; no arbitrary destination or
redirect is allowed. A new image is required before relocation. Current live
values, image and disabled browser routes remain unchanged in this source phase.

## Permissions and CNI are gates, not assumptions

The Application uses project `default` and in-cluster server. No AppProject
restrictions are defined in this repository: before activation inspect actual
project destinations (both rustfs and identity), namespace resource whitelist /
blacklist for Deployment/Service/NetworkPolicy/Ingress, and controller RBAC.
Explicit namespaces are supported by Argo; destination.namespace is only the
default. Stop on permission denial rather than broadening project privileges.

Policies use combined exact namespace AND pod selectors: reader -> rustfs:9000,
rustfs ingress <- selected reader namespace, existing DNS and exact Authentik
/32s only. There is intentionally NO namespace-wide identity allowance.

Actual source `charts/traefik-edge/templates/deployment.yaml` uses hostNetwork,
node socrat-2, replicas 1/Recreate, and instance label (not the kube-system
`app.kubernetes.io/name: traefik` selector in reader ingress). Therefore that
selector is NOT evidence that VPS traffic can enter the reader. Host-network
traffic may be classified as node traffic or bypass policy depending on CNI;
SNAT/DNAT/source identity must be measured, not inferred. Do not add node/public
CIDR allowances speculatively. Pending tests at BOTH actual entrances: authenticated
reader succeeds, anonymous/forged headers fail; unrelated identity and rustfs pods
cannot connect to reader; unrelated pods cannot reach S3; reader cannot connect
to arbitrary egress; reader S3 GET and Authentik discovery succeed. Record CNI
implementation/version, observed source IP and enforceability, including a
negative test from the relevant node boundary. If hostNetwork bypass prevents
negative enforcement, stop public activation and report evidence for separately
reviewed node firewall enforcement, not an unreviewed broad allow.

## Deliberate activation (separate authorization; no commands executed here)

1. Review exact commit and clean-tree diff; run offline suites/render/lint. Build
   linux/amd64 services/rustfs_gateway from that commit with pinned base. Push an
   immutable source tag only after approval. Query authenticated registry manifest
   Docker-Content-Digest and independently hash the exact manifest bytes. Use the
   ACTUAL registry digest in tracked live image values; local OCI digest can differ
   after push (the previous 41fd2a -> 0af2fdaa incident proved this). Retain source,
   platform, base, build and remote-manifest provenance privately without tokens.
2. Inspect only metadata for collisions and actual project permissions. Prepare
   identity `rustfs-reader` with ONLY access-key/secret-key and
   `rustfs-harbor-pull` with ONLY dedicated pull-robot dockerconfigjson. An approved
   operator may securely copy those two exact existing rustfs Secrets using a
   private mode0700 workspace/files0600 or nonlogging pipe, reconstructing fresh
   metadata/type/data (no resourceVersion/UID/owner refs/last-applied). Never dump
   to terminal/Git. No root, writer, OIDC or registry-admin credentials copied;
   no extra service-account permissions. Verify key names/type and matching
   private hashes without printing values; clean temporary files. This document
   does not authorize secret access in the source phase.
3. New image must be published/verified first. Render gateway.namespace=identity,
   new registry digest, browserRoutes=false. Preview exact Argo diff: only reader
   relocation plus the two exact namespace/pod S3 policy peers and image. Do NOT
   change Application destination or enable browser routes. Disable prune for
   this migration sync explicitly: ensure new reader/service/policy is created
   and health/reader loopback/auth/download tests pass BEFORE old reader deletion.
   RustFS ingress now admits identity reader; old rustfs reader can lose S3 access
   during this private migration. No promise of old-reader traffic continuity.
4. After new reader tests, delete/prune ONLY old rustfs Deployment/rustfs-gateway,
   Service/rustfs-gateway, NetworkPolicy/rustfs-gateway-isolation. Inventory those
   exact IDs in reviewed diff; never namespace-wide prune/delete. If a prior
   reader Ingress exists, separately review its exact removal after new acceptance
   (none is live today). NEVER remove RustFS, storage/PV/PVC or identity objects.
5. DNS additive update, valid TLS/SNI, then explicitly enable browser routes only
   after admission. Complete both-entrance CNI gates above plus real owner/platform
   login, unaffiliated rejection, native callback/STS, logout/revocation, bounded
   authenticated download/hash and slow-peer tests. No SPI publisher/backend switch
   until public foundation acceptance. No shared-edge rollout at any step.

## Rollback

Keep browser routes false (or explicitly disable first). Restore reviewed default
reader namespace/image values and sync with prune off; recreate/test rustfs reader
and restore its exact S3 ingress peer BEFORE removing only the new identity reader
Deployment/Service/NetworkPolicy. Preserve Secrets pending deliberate cleanup;
never delete shared identity resources or any retained storage. No edge rollback
or restart is involved. Keep provenance, private credentials and fixture journal.

## Actual private execution — 2026-11-05

Reader relocation is now executed, not merely prepared. Reviewed image source
`eba1d839ac2313d7694aa0d2e7be70269af9a01a`; activation commit
`586109ae1803be25f02d8ef23338c89125b647ed`. Manual Argo sync explicitly used
`prune:false`; after exact old-resource cleanup Argo independently reported
Synced/Healthy/Succeeded at that revision. Browser routes remain false; SPI unchanged.

Published linux/amd64 immutable full-source-SHA tag under
`harbor.socrat.alchemmist.xyz/homelab/rustfs-gateway`. Pinned base remains
`python:3.13-alpine@sha256:7984cf56ceaddebe4fefeb75d64000b9f45d8b77b11a09b24524da6cdc3af0c8`.
Actual authenticated registry manifest, independently hashed from downloaded bytes:
`sha256:9253d36e923e216cd34714a5baf9b57d1bb5577bf52c4671a4f8d302a27fef57`.
Local digest `4766a5e0...` differed and was NOT deployed.

Default AppProject allows both namespaces; controller create checks for exact
Deployment/Service/NetworkPolicy passed, no RBAC edits. No target resource/Secret
collisions. Only reader and dedicated pull-robot Secrets were reconstructed with
fresh metadata in identity; exact types/key sets/private equality verified. Reader
has no volumes and service-account-token automount is false. Capacity requests
before migration: nodes 0/1/2/3 memory 98/79/62/76%; duplicate reader64Mi fits,
reader placed socrat-2. Overcommitted limits/eviction risk remain.

Exact old resources backed up privately in
`~/.config/homelab/rustfs-foundation/reader-relocation/resources-before.json`
(mode0600, directory0700). After functional checks and exact Argo tracking ownership
verification, ONLY old rustfs gateway Deployment/Service/isolation NetworkPolicy
were deleted. Storage Deployment spec and UID compare exactly unchanged; retained
PVC remains Bound. Old Secrets/journals/fixtures preserved for rollback.

Actual new reader mounted-key canonical DNS/SigV4 manifest+artifact read passed:
45 bytes, SHA256 `973952a7d502a67bc652d5b67f104d0d6c1756bb4edb713e682e40f1b68e34f0`.
Canonical S3 DNS resolved10.43.34.112. Verified-TLS Authentik discovery returned200
(no trailing slash; trailing-slash request returned404, not an egress failure).
Local HTTP unauthenticated GET/HEAD/PUT, forged owner headers, double-leading slash
and traversal targets returned401. Local RustFS suite29 passed; Helm lint/render
and diff checks passed. These do not substitute for human authenticated downloads.

**New observed public-isolation blocker; no exception added:** k3s1.36.5+k3s1
node metadata reports Flannel VXLAN. Reader Pod10.42.0.7 and Service10.43.7.71:8080
are reachable from real VPS edge hostNetwork pod on socrat-2; route to reader
reports `dev cni0 src10.42.0.1`. Both produce401, proving reachability ONLY, not
network isolation or exact post-NAT source. Home Traefik likewise reaches reader.
An own unprivileged unrelated identity probe on socrat-2 was denied reader Pod
and Service (ConnectionRefused), but reached RustFS Service10.43.34.112:9000:
HTTP GET /health returned200, source socket10.42.0.9. Earlier probe10.42.0.8 also
connected. This contradicts intended unrelated-pod S3 denial despite exact
combined namespace/pod ingress selectors. No packet capture, host privilege,
network exception or policy broadening used. Probes removed. Parent review and
bounded CNI/NAT enforcement investigation are required before public activation;
no speculative CIDR fix is authorized. CNI binary/controller version and post-NAT
source at S3 were not inspected, so no precise root-cause claim is made.

DNS remains unapplied because secure sudo/become access is missing. TLS/SNI,
both-entrance authenticated checks, human owner/platform/outsider OIDC/STS,
logout/revocation and bounded authenticated slow-peer/hash tests remain gates.
This is a successful PRIVATE relocation, NOT public acceptance or SPI activation.

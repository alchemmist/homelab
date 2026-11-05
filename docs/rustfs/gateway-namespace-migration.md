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

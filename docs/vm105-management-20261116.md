# Rancher and Argo application-controller →VM105 —16Nov2026

## Current / accepted

Explicit owner authorization: Rancher and Argo CD application-controller, to
relieve0/1 RAM. Both now single Ready/restart0 on **socrat-5**. Argo application
`argo-cd` and `rancher`: Synced/Healthy, latest operations Succeeded. Argo server,
repo-server, Redis, ApplicationSet and notifications remain on0. Rancher webhooks
remain distributed0/3. Grafana, independent monitoring, VPN/node2 unchanged.

Argo chart10.11.6/version/resources unchanged: only controller-specific
nodeSelector overrides global0. StatefulSet name/ordinal/UID retained. Its local
volumes are ephemeral caches; authoritative Applications, Secrets and settings
remain in the existing Kubernetes API, not a copied filesystem. Controller5
really reconciled the Rancher Application/source/rollouts below, not merely
passed readiness. No blanket sync/prune, forced production Pod deletion, image
override, credentials reset, user impersonation or owner login performed.

Rancher server/chart remain **2.15.2**; original Deployment UID and FULL container
specification retained. No PVC/runtime database to copy: authoritative identity,
roles, cluster/project objects remain in the original Kubernetes API. A fresh
probe on5 used the exact old1 image digest and verified discovery against the
normal image CA with scoped issuer alias before production changes.

## Native issuer transport and source ownership

Upstream Rancher chart has no Pod hostAliases support. Vendor exact2.15.2 in
`charts/rancher`; all upstream file hashes in `UPSTREAM-SHA256.json`. Only optional
hostAliases extension/default added. Empty default rendering byte-identical to
original chart; upstream kubeVersion <1.37 preserved, rendered with actual1.36.5.
Application first source now local Git chart, other sources/public entry intact.
No bootstrap hooks, permissions, ingress/TLS settings or CA env changed.

Rancher Pod-only `auth.socrat.alchemmist.xyz →10.43.218.222` preserves issuer,
SNI/TLS/callback and PKCE; no global DNS/routes/security-policy changes. Review
alias on Traefik Service recreation. Existing
`SSL_CERT_FILE=/var/lib/ca-certificates/ca-bundle.pem` preserved. No insecure TLS
flag, custom CA replacement or IdP AuthConfig change.

Old Ansible placement role used upstream `helm upgrade --reuse-values`, which
would ignore the extension; replaced by require/refresh existing Git-owned
Rancher Application, then rollout/placement verification. No silent fallback
installation and no old imperative maxUnavailable/nodeSelector patch. Defaults
and values template agree with final5. Canonical source is Argo Git values.

## Incident / recovery —not zero-gap acceptance

At approximately14:12–14:22MSK, production Rancher had reached5 before the root
Application/source change propagated. The first Pod was still rendered from the
upstream chart, which ignored hostAliases. It was Ready, but a real in-Pod IdP
request timed out; **native login during this interval was impaired**. It was
not accepted on `/ping` alone. No claim that users were unaffected or that all
login attempts were audited.

Once the local chart applied, the original required anti-affinity plus one
eligible node and maxUnavailable0 blocked same-node replacement. Changing only
incoming Pod anti-affinity to preferred was insufficient: the old running Pod's
required anti-affinity also blocks incoming Pods. Native rollout timed out;
this failure was not hidden or treated as successful migration.

Recovery source commits21e8988f,70246fec/mergefd3dd71a: retain one replica and
maxSurge1/maxUnavailable0, prefer rather than require Rancher Pod anti-affinity;
briefly return the reviewed Deployment to original1 to drain the legacy rule.
Two UID-tested placement-only patches applied already-published desired source
while the old Argo sync was waiting for health. No operation/history fabricated,
no forced Pod deletion, no force/prune or speculative auth bypass. Normal
Deployment controller replacement restored native discovery200 on1; Argo
Succeeded/Synced/Healthy. Final source e0adf383 moved preferred-affinity Pod to5
normally. This is still one server, not HA. Existing distributed sites' required
anti-affinity was not changed.

The original upstream pre-upgrade hook ran successfully (read-only RKE1 resource
check); no schema migration or cleanup hook was introduced. Same-node preferred
anti-affinity now permits ordinary maxSurge1 replacement on future upgrades.

## Final acceptance

- Both final Pods on5, exactly1 Ready/restart0 each; owning object UIDs retained.
  FULL specs equal pre-move except Argo nodeSelector and Rancher reviewed
  affinity/hostAliases. Full container specs/versions/resources unchanged.
- Both Applications Synced/Healthy, operations Succeeded. Services UID/FULL specs
  and namespace NetworkPolicy UID/specs unchanged.
- **41 static Secrets** exact UID/data; **58 native user/role/binding/cluster/
  project objects** same UIDs and full nonmetadata/nonstatus bodies and counts.
  FULL native genericoidc AuthConfig JSON unchanged, not just clientID.
- Rancher's native `serving-cert` UID/private key preserved. Dynamic listener
  naturally reissued **tls.crt only** to update Pod-IP SANs. CA/other Secrets
  unchanged; new leaf verifies against original certificate trust. This is not
  a public TLS replacement or signing-key rotation.
- Actual final Rancher5 discovery200 with default TLS verification.
- Three native `/v1-oidc/genericoidc` requests:302, absolute HTTPS Authentik
  destination, existing `/verify-auth` callback, code flow, PKCE S256.
- Fresh browser reached normal Authentik username form: no page errors or failed
  requests. Public `/ping`200; anonymous `/v3`401. No human callback/token exchange
  claimed; owner can finish native login normally, no credentials borrowed.
- Five new regression tests plus three updated placement tests pass. Tests
  reconstruct every original chart file/hash and compare default render bytes.
  Old node1 recovery assertions deliberately updated to authorized current5,
  not weakened to permit broken TLS or a changed version.
- Exact-image preflight Pod removed by ordinary delete; no diagnostics remain.

Private receipts/snapshots/headers/browser result, outside Git:
`~/Library/Application Support/homelab/management-move-20261116/` (0700/0600).
This contains privileged snapshots; never publish raw files or redirect state.

## RAM / limits

Baseline13:59MSK: controller0 **1428Mi**, Rancher1 **1313Mi**, combined2741Mi
(~2.68GiB) consumers relocated, not a guaranteed net host reduction. At14:31MSK:
controller5 **927Mi**, Rancher5 **1331Mi**. Nodes0 **18457Mi (58%)**,1 **7817Mi
(51%)**,5 **7197Mi (18%)**, compared to baseline18983/8744/~4.6GiB. Other processes
and caches fluctuate; current host net reductions526/927Mi must not be advertised
as2741Mi proven savings. Need a sustained representative comparison. Argo cache
warming changes its working set. No memory limits or cache contents deliberately
trimmed to manufacture a result.

Still dependent on non-HA relay0 for1↔5 traffic and on5 for the single moved
controllers. Management UI availability is not management HA. Full VM restore,
independent cold boot/backup acceptance remain separate maintenance work.

Rollback: first commit reviewed Rancher placement1 (scoped alias/CA retained),
let normal rollout settle; controller-specific selector0 separately for Argo.
Keep only the intended component change. Native Kubernetes identity data remains
authoritative; do not restore stale snapshots over live API data. No old app
stateful volumes or source5 data touched by this management batch.

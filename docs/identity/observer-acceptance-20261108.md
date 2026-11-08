# Native observer accepted — 2026-11-08

**Completed for the effective four-service profile and the initial human cutover.**
This supersedes the blocked [November 7 checkpoint](observer-activation-20261107.md).
Harbor is deliberately unsupported/gated; its separate revocation follow-up is
[#134](https://github.com/alchemmist/homelab/issues/134), not an unreported success.

## Human result

Danila's immutable IdP subject was checked before any write. The only directory
changes were **add `homelab-observer`**, then **remove `authentik Read-only`**.
The separately approved `netbird-internal-admins` membership was retained. Exact
post-change group readback and unchanged password-change metadata were checked.
No password/MFA writes, login as the human, native user creation, per-person
Rancher binding, SQL account edit, owner/robot reset or NetBird change was performed.

Danila uses each application's **native SSO**; an existing session can require
sign-out/sign-in to receive the new claims. Native services handle local JIT and
roles. First use by the real human was not impersonated or claimed as tested.
Future ordinary onboarding needs only the same IdP group add, not a repeat of
this initial-person correction script or any personal app/RBAC provisioning.

| Service | Accepted authorization |
| --- | --- |
| Rancher / Kubernetes | Custom native group reader in `local`, including future namespaces. Workload/node/namespace reads allowed; Secrets, ConfigMaps, logs, exec/attach/port-forward/proxy, mutations, grants, escalation and impersonation denied. |
| Grafana | Native Viewer, not org/server admin; dashboard writes and user administration denied. All allowed Viewer groups are explicit; missing groups cannot fall back to Viewer. |
| Wiki | Native Reader; editor/admin REST and MCP writes denied. Public documentation remains public. |
| Argo CD | Native `role:readonly`; sync denied. Both rendered and actual live Secret data were checked masked, not merely hidden by the UI. No admitted-group claim means zero visible applications, not an anonymous default-reader grant. |
| Harbor | No observer admission or project Guest grant. Not reopened by this cutover. |

Existing owner/editor/native grants are additive and were not downgraded. The
observer group is not a deny overlay for an already privileged account.

## Real acceptance, not configuration-only receipts

A separate synthetic subject, its own password/MFA and genuine native SSO were
used. The same native identity survived removal/re-add. It was never Danila.

- **23** Rancher SelfSubjectAccessReview checks passed. Actual reads and negative
  Secrets/ConfigMaps/RBAC calls were exercised as well.
- A legacy self-owned Rancher API key could read nodes but not Secrets. After
  group removal, while the key still authenticated, node reads returned **403**;
  the old browser did too. Its later expiration was not misreported as that proof.
  Extension token/kubeconfig APIs remain denied, but legacy `/v3/tokens` can mint
  self credentials: possession does not freeze the observer authorization.
- Native Grafana administration/dashboard write, Wiki admin/editor/write and
  Argo sync calls all returned **403** (six independent negative checks).
- A Reader-created Wiki MCP key, even without its optional read-only flag, could
  list pages but its update tool returned **403: user/token cannot edit pages**.
  The old key returned **401** and the old browser had no authenticated user
  after membership removal. No wiki page was changed by the probe.
- Fresh native login was denied in all four apps after removal, using the test
  subject's existing IdP session but no service cookies. Old Grafana session was
  eventually **401** after refresh; refreshed Argo claims lacked groups and its
  application list was empty. OIDC snapshots were not described as instant logout.
- At `09:35:03Z` the test membership was removed. The scheduled native worker
  completed its cache removal at `09:35:13Z`, logging **one cache update, zero users
  created, zero roles modified**. No operator cache patch was used for this round.
- Re-admission was executed by the same worker code and least-privilege service
  account: one cache update, unchanged native UID, no personal user/role creation.
  Native SSO/Reader access and the MCP read/deny test worked again.
- Harbor's old synthetic session had **zero projects** and newly issued registry
  JWTs had **no actions** after its owned Guest grants were closed. Previously
  issued signed JWTs retain their original lifetime; do not promise retroactivity.

## Fixes exposed by the live run

The first worker version stopped on an unrelated historical orphan Rancher cache.
It now preserves/skips unrelated cache-less legacy identities, while a mismatched
cache carrying the observer grant still stops safely. Regression coverage includes
this case. The exact existing LAN control-plane Endpoint is allowed on 6443 in
addition to the pinned WireGuard Endpoints; there is no LAN-wide exception.

Grafana's Viewer fallback was replaced with explicit reviewed group expressions,
`groups` scope is explicit, and browser token rotation is one minute. Existing
owner/editor mappings, local recovery, eight-hour maximum lifetime and machine
credentials are preserved. This remains native OAuth refresh authorization, not
a universal one-minute revocation promise across applications.

The initial human cutover completed both group operations, then its first receipt
writer stopped when trying to reuse an exclusive progress filename. The uncertain
marker was **not retried**: directory readback proved both intended operations had
completed, with unrelated groups/password metadata intact. Source now uses separate
per-step receipts. An explicit readback-only finalization resolved the marker with
**zero repeated remote writes**, and a full two-step driver regression covers it.

## Operations and monitoring

`observer-membership` only reconciles the one native Rancher observer cache entry.
It cannot provision users, change roles/workloads, exec or read Kubernetes Secrets.
Its IdP machine credential has user/group **view** permissions only. Unknown or
incomplete identity state stops without speculative grants. Wiki's guard reads
current reader admission without rewriting accounts or stored pages/keys.

Prometheus loaded the last-success alert with healthy evaluation; the live
`kube_cronjob_status_last_successful_time` metric was observed. The rule warns on
missing success after three minutes for two minutes, avoiding reliance on a
15-minute per-Job alert for short-lived Jobs. A missing-worker rule is also declared.
Monitor this path: unavailable reconciliation can delay Rancher revocation, so the
minute schedule is a healthy-operation cadence, not an unconditional SLA.

The synthetic account was removed from observer and disabled in the IdP. Its two
owned Rancher session tokens were deleted with UID/RV preconditions, its own
Rancher/Wiki probe keys were removed, and the worker cleared its native observer
cache. No real human/machine credential was included in cleanup.

At runtime closeout all four nodes were Ready and the four application deployments
were Synced/Healthy. Scoped local CI: **89 tests + 208 subtests passed**; Helm lint
passed. These are scoped checks, not a claim about the repository-wide suite,
branch protection or independent human approval. Work was explicitly on `main`;
unrelated local monitoring changes were preserved and not staged.

Private evidence is retained in `/var/lib/homelab-observer-rollout/20261107-final`
and `/var/lib/homelab-observer-initial-person`, including the live acceptance,
automatic cache round-trip, cleanup and final group receipts. Credential values
remain private, not in this document, issues or Git.


## Active dependency incident: observer reconciliation intermittent,20:02–20:24UTC

Historical acceptance is not current bounded-revocation evidence. Last successful
worker19:52:12, then failures at20:00/20:01;20:09 success followed20:10 failure.
Prometheus20:16 reported pending, last success about236s ago (20:12:12), so a single
success can clear the alert temporarily without repairing its dependency.

Read-only diagnosis confirmed a DNS/public-entry failure, not revoked credentials:
- Authentik read-only machine Secret is byte-identical in cattle-system and wiki;
  no token value emitted. Same credential reads users9/groups21 withHTTP200.
- Hostname-origin API calls intermittently raiseURLError(reason=TimeoutError).
  Full groups page21/11577bytes and users9/14360bytes also complete in0.28–0.39s;
  no evidence of a deterministic oversized page or expired token.
- Verified-TLS per-process comparison with original Host/SNI to cluster Traefik
  10.43.218.222:443 returned groupsHTTP200 in0.329s; ordinary public-origin request
  immediately afterward timed out in5.104s. No TLS validation disabled, credentials
  rotated, group/role changed or DNS/routes modified.
- Passive /proc socket metadata of the ACTUAL running CronJob (no exec/load inside
  its100mCPU container) at20:20:09–12 showed SYN_SENT to109.120.141.97:443 with
  retransmissions. KUBERNETES_SERVICE_HOST is10.43.0.1, so this was not the
  Kubernetes cache API; worker has no auth hostname /etc/hosts override.
- CoreDNS replicas disagree: socrat-2 pod10.42.0.26 consistently returns
  auth.socrat.alchemmist.xyz→109.120.141.97; socrat-0 pod10.42.2.225 consistently
  returns109.173.40.247. ClusterDNS VIP10.43.0.10 alternates between these views.
  VPS CoreDNS really inherits provider resolvers46.254.22.138/46.254.23.138, both
  returning the VPS answer. Independent GoogleDoH returns HOME answer. Do NOT
  label provider poisoning/stale cache: our independently rendered authoritative
  failover zones legitimately differ under a partial network partition.
- Live VPS /usr/local/libexec/public-dns-refresh probes VPS127.0.0.1, not end-user
  reachability. Last5min showed ten `updated home=False vps=True` results. Thus VPS
  authority still advertises its locally healthy but home/mobile-inaccessible
  public entry; home authority selects HOME. Source scripts/public_dns_zone.py
  and public_authoritative_dns role explain this split. DNS failover cannot
  infer client-specific reachability from local loopback health.

Cause chain: inconsistent authoritative/upstream DNS views→random CoreDNS answer→
worker attempts affected VPS public443→5s connect timeout→no complete membership
snapshot→safe exit before cache reconciliation→critical freshness alert recurs.
The worker and Wiki internal membership dependency should use a narrow consistent
INTERNAL Authentik ingress resolution, preserving public hostname/Host/SNI/TLS and
all credential/RBAC/CAS protections. A scoped cluster DNS override for auth hostname
is a proposed fix; not applied without fresh owner approval/preimage/backup and
acceptance. Do not change global/Mac DNS, flush DNS/firewalls, restart nodes, relax
revocation freshness or issue a new token to mask this. Public authoritative
failover redesign is a separate larger change requiring fleet preflight/receipts.


### Scoped internal DNS repair accepted20:46UTC

Owner explicitly approved the narrow internal Authentik DNS fix. Added only
`authentik-internal.server` in `kube-system/coredns-custom`, full exact UID/RV/data
CAS and private preimages. All existing keys including Rancher preserved.
Initial mapping toTraefikService10.43.218.222 passed Wiki HTTPS but failed actual
restricted worker acceptance (fast connect refusal). Credential-free TLS probes
inside the existing worker network namespace, without executing in its CPU cgroup
or changing routes, confirmed Service443 and10.250.0.1:443 refused while private
HA VIP192.168.0.250:443 succeeded with full certificate verification.

No NetworkPolicy broadened. After successful scoped machine APIHTTP200 via private
VIP, replaced ONLY our exact previous key using its accepted preimage receipt and
a fresh CAS approval. **Final target is private HA VIP192.168.0.250, not ServiceIP.**
Public Host/SNI/issuer and TLS verification unchanged; no tokens, human membership,
RBAC, public DNS, upstream resolvers, Mac settings or VPN profiles modified.
No node/K3s/CoreDNS/pod restart or manually forced CronJob used. Normal projection
and reload propagated the record; all three DNS views (VIP and two replicas)
returned exactly192.168.0.250.

Runtime proof: three consecutive natural successes20:44:12,20:45:12,20:46:11UTC.
Prometheus freshness18.061s and no pending/firing series for the membership alert.
Private final state `socrat-0:/var/lib/homelab-observer-rollout/observer-internal-dns-vip-20261108/`
contains before/plan/after/write response, full runtime observations, three-job
acceptance and alert readback. Initial failed ServiceIP attempt retained separately
as historical pending acceptance, not represented as success. Rollback must remove
only exact owned key after fresh CAS; do not restore whole old ConfigMap.

Reviewed source/runbook: `scripts/observer-internal-dns.py`,
`deploy/identity/authentik-internal-dns.md`. Targeted tests75passed+195subtests.
This repairs internal membership reconciliation dependency, NOT public VPN access
or authoritative DNS partial-partition failover generally. Those incidents remain.

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

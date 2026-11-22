# Argo CD: short tokens, silent refresh and verified backend TLS

Rollout 2026-11-01; **accepted on both trusted public edges**. This replaces the earlier rolled-back
experiment. Authentik/MFA, owner admission, roles and recovery remain native.

## Cause and policy

Argo CD v3.5.6 previously requested only openid/profile/email/groups. Authentik
2026.8.5 issues a refresh token only with `offline_access`; configured eight-hour
refresh validity and an allowed grant alone were insufficient. The five-minute
ID token expired, forcing a visible authorize roundtrip despite a live IdP session.

Current intended settings:

- Authentik `homelab-argocd`: default offline-access mapping added, confidential
  authorization-code/refresh grants unchanged; access/ID tokens **five minutes**,
  refresh validity **eight hours**. Secret, signing key and subject mode unchanged.
- Argo `oidc.config`: request `offline_access`, `refreshTokenThreshold: 60s`.
- Argo `users.session.duration: 8h`: bounded session-refresh cache policy, not an
  eight-hour bearer token or a promise of immediate global session revocation.
  Pinned native code preserves `OidcTokenCache.SessionStart` during renewal and
  bounds remaining cache TTL against that original start. No eight-hour wall-clock
  acceptance test was performed; already-issued JWT validity is still five minutes.
- Existing browser sessions need a fresh Argo SSO authorization once to obtain a
  refresh token. The next existing-session expiry may therefore still redirect.
  Reauthentication after the app-session limit is expected; IdP MFA/session policy
  is separate and has not been weakened or extended.

## Why backend TLS is necessary

Pinned upstream v3.5.6 `server/server.go` passes `!server.Insecure` into
`httputil.SetTokenCookie` for gateway renewal. With HTTP behind the ingress,
renewed cookies lost Secure although the original callback set it correctly.
That experimental refresh was rolled back instead of weakening the Secure test.

Native Argo server now uses `server.insecure: false` and the **existing** trusted
`argocd-server-tls` certificate. Service annotations select HTTPS and
`argocd-argocd-verified-tls@kubernetescrd`; ingress backend port is 443.
`deploy/argocd/server-transport.yaml` fixes SNI to the public certificate hostname
and explicitly sets `insecureSkipVerify: false`. Both controllers must resolve it.
No skip-verify, new CA, copied private key, DNS or WireGuard change is needed.

## VPS ingress prerequisite and ownership

`charts/traefik-edge` adds a KubernetesCRD provider to the pinned Traefik 3.7.13:

- namespace **argocd only**;
- selector `homelab.alchemmist.xyz/edge-transport=argocd` (also on the transport);
- cross-namespace, ExternalName and CRD cluster-scope lookups disabled;
- one namespaced Role/RoleBinding: read-only ten Traefik CRD kinds and ConfigMaps.
  Services/Secrets/EndpointSlices were already readable there by the original
  Ingress provider. No additional namespace/cluster-wide Secret access was granted.
  Native CRD informers require all ten kinds even though only the labelled
  transport is selected; this does not give write privileges.

The home controller already supports CRDs. The VPS provider was missing them.
The upgrade's manifest guard allowed only eight provider flags and two new RBAC
objects; image, listeners, VPN routes, certificates and existing objects stayed
otherwise unchanged. The shared edge uses a single Recreate replica: connections
on that edge can be interrupted by rollout; this is not a zero-downtime/HA claim.

**Important:** `argocd/traefik-edge` is now self-managed with automated selfHeal.
The first live Helm change was reverted by it, causing temporary VPS Argo 404s.
The controller's active sync could also complete after skip-reconcile was set.
Only this application's reconciliation/automatic sync was paused for the migration;
all other applications remained managed. After publication and hard refresh to
observe the new revision, the original automated `{prune:false,selfHeal:true}`
policy was restored and the pause removed. Several edge rollouts were needed,
not the single originally anticipated. Both public paths recovered. Do not fight
selfHeal with repeated imperative patches: publish source first or pause this
specific application, wait for any active operation to finish, and then cut over.

## Reproduction

Sources:

- `charts/traefik-edge/{values.yaml,templates/deployment.yaml,templates/crd-rbac.yaml}`;
- `deploy/platform/argo-cd/values.yaml` — active self-managed multi-source values;
- `deploy/argocd/{values.yaml,server-transport.yaml}` — matching bootstrap;
- `ansible/playbooks/argocd.yml` and `roles/argocd_oidc/files/configure.py`;
- `tests/test_traefik_edge_crd.py`, `tests/test_argocd_refresh.py`;
- `scripts/identity-argocd-refresh-smoke.py`.

The active `argo-cd` Application reads **deploy/platform/argo-cd/values.yaml**,
not bootstrap deploy/argocd/values.yaml. Its selfHeal also reverted a first live
scope/threshold patch: idle refresh passed on a just-issued session, but preemptive
refresh failed after the threshold disappeared; a later VPS fixture had no refresh
token. Those runs are failures, not acceptance. Both values files now agree
semantically (unit contract), with identical extraObjects to manage the transport
through GitOps/Helm too. No replacement image or chart-version upgrade was needed.
Wait for the self-managed application to observe the published revision and for
live scopes/threshold/TLS mode to converge before starting acceptance fixtures.

The Argo playbook fails before changing TLS if the VPS CRD prerequisite is absent.
It applies the transport before the pinned Helm release. Service annotations must
be on the **Service**, not merely the Ingress. The live rollout patched only Argo
server/config/ingress/provider fields; other Argo workloads were not upgraded.

## Acceptance

`python3 scripts/identity-argocd-refresh-smoke.py --run [--public-edge IP]` requires
Playwright/Chromium and owner SSH; it is a **live fixture mutation test**. Use both
trusted edges 109.173.40.247 and 176.98.185.59 with verified public TLS/SNI.

The test creates a unique observer and UUID/user-specific temporary app admission
binding, not owner/operator membership. It performs native password, real TOTP and
consent, denies inspector access and confirms server-side create-app denial. It
waits past the actual five-minute token expiry with no app traffic, then requires
an authenticated API response and a newer same-subject **Secure** cookie without
browser IdP navigation. It subsequently polls to require a second, **preemptive**
renewal before expiry, again retaining Secure and read-only access. Tokens/seeds
stay in memory; no traces, real owner factors or credential screenshots are saved.
Cleanup always attempts deletion of both the exact binding and fixture user.

A first VPS attempt encountered an ingress 404 during the selfHeal conflict and
cleaned up; it is not counted as a pass. Owner personal acceptance is separate. Public health probes for Argo, Authentik,
Harbor and LiteLLM passed on both edges; a public Grafana TLS probe was not accepted
(Grafana is private/WireGuard-only). TLS verification was not bypassed and this is
not a claim of a full private-service or repository-wide acceptance run.

## Protected snapshots and recovery

Current pre-rollout objects, app sync policy, provider and edge Helm values/manifest
are in `/home/alchemmist/.cache/homelab-authentik/argocd-refresh-20261101T230303Z/`.
Files may include credentials; do not print, commit or restore whole objects over
concurrent changes. Historical rollback snapshots from 22:07/22:18 are separate.

Prefer a **refresh-policy-only rollback while retaining verified HTTPS**. Merely
removing offline_access does not revoke existing refresh grants or erase native
session caches. Do not revert the server to insecure HTTP while such sessions
can still renew: that would reintroduce the Secure regression. Full transport
rollback requires a reviewed provider/app-session invalidation plan (Argo only,
not unrelated users/services), then Argo HTTP/service/ingress restoration, and only
then removal of VPS CRD support. Source changes must precede restoring selfHeal.
Built-in admin recovery and machine/API credentials remain in place.


### Recovery transport note

Native local admin login remains available; no password recovery drill was run.
Backend port-forward diagnostics now require HTTPS with the public SNI hostname,
not plain HTTP or skip-verify. For example, after forwarding server port 443 to a
local 8080, a non-authenticated diagnostic is:

```sh
curl --connect-to argocd.socrat.alchemmist.xyz:443:127.0.0.1:8080 \
  https://argocd.socrat.alchemmist.xyz/api/version
```

Do not put recovery passwords, cookies, callback codes or API tokens in examples,
logs or shell history. Internal TLS is not protection against a compromised edge
root; that workload/credential trust boundary still exists.


## Final acceptance evidence (2026-11-01)

After the active GitOps source converged to `5d350c81efc6c03c90cf9cf802cfedd03708b21c`,
two fresh independent fixture runs passed, one pinned to each edge:

- native password + TOTP enrollment + consent; callback HTTP303;
- observer inspector denied404 and create-application permission denied;
- actual five-minute expiry after idle: API authenticated, newer same-subject
  cookie, **Secure retained**, no browser IdP navigation;
- second renewal under active polling: occurred **before** expiry, Secure retained,
  no browser IdP navigation; read-only permission retained;
- zero browser JS errors, both exact fixtures/bindings deleted; subsequent API
  check found no temporary users or temporary user-specific admission bindings;
- both `argo-cd` and `traefik-edge` applications Synced/Healthy with original
  automatic selfHeal policy restored; live CRD flags/scopes/threshold persisted;
- anonymous protected Argo API returned401 on both edges, not an interactive
  redirect. Client secret, provider subject/issuer/flows and token lifetimes
  compared unchanged; only provider property_mappings differed (offline scope).

Offline checks: 3 Argo contracts, 2 edge contracts, 17 Authentik branding/title,
10 ingress-neighbor, 14 identity and 7 LiteLLM identity checks passed (53 total);
Helm lint, two playbook syntax checks and scoped redacted secret scan passed.
This is focused acceptance, **not** a repository-wide CI/deploy or personal owner
recovery test. No eight-hour wait was simulated or claimed. Several real five-
minute renewal periods were exercised across the two independent sessions.

Source publication used an isolated worktree with narrow staging; concurrent
Nature/monitoring/DNS/router/other changes in the original worktree were retained,
not included in these commits. No force-push or history rewrite was used.

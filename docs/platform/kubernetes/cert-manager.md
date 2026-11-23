# cert-manager deployment notes

Owner release: `deploy/argocd/apps/cert-manager.yaml` (Argo Application,
project default, selfHeal, **prune: false**). Chart: `charts/cert-manager`,
vendored verbatim from `https://charts.jetstack.io` so Argo does not
helm-pull on refresh; the only local additions are the vendoring header in
`Chart.yaml`. Values: `deploy/platform/cert-manager/values.yaml` — immutable
digest pins for controller/cainjector/webhook/startupapicheck, node placement
(socrat-0 + socrat-3), anti-affinity, 2 replicas each and the
`--acme-http01-solver-nameservers` flag. PRUNE IS OFF BY POLICY: when an
upgrade legitimately removes rendered resources, they must be deleted
manually after sync (see the v1.21.3 tokenrequest RBAC below).

## Upgrade to v1.21.3 — 23 Nov 2026

Vendored chart re-pinned from v1.16.2 to upstream **v1.21.3** (repo
`jetstack/cert-manager`, chart version == appVersion). Upstream since 1.16.2
reorganised its templates; vendoring is a wholesale copy of the new
`templates/`, `values.yaml`, `values.schema.json` and `README.md`. Structural
upstream rename: the old single `templates/crds.yaml` became six
`templates/crd-*.yaml` gated by the same `.Values.crds.enabled`, and
`networkpolicy-egress.yaml` merged into `networkpolicy-webhooks.yaml`
(networkPolicy remains disabled in values, so no policy is rendered).
Image digests moved to v1.21.3 amd64 (`9b262e94…` controller, `165691f6…`
cainjector, `fc2845cc…` webhook, `6b9e17ad…` startupapicheck).

Cross-version breaking changes were checked against the cluster before
rollout: no Certificate uses `renewal.policy: Disabled` (v1.21 known
crash-loop trigger), no Issuer uses Vault/Route53 `serviceAccountRef`, no
Direct tooling creates Challenge/Order resources, and our values never set
the removed `prometheus.servicemonitor.targetPort`/`path` keys (schema uses
`additionalProperties: false`). The 1.18 defaults (`rotationPolicy: Always`,
`revisionHistoryLimit: 1`) were noted; the existing ACME-issued certificates
do not set these fields explicitly.

With `prune: false` the sync correctly refused to delete the now-removed
default tokenrequest `Role`/`RoleBinding`
(`cert-manager-tokenrequest`, `cert-manager-cert-manager-tokenrequest` in ns
`cert-manager`); they were deleted manually after sync, after which the app
reached Synced/Healthy. All three Deployments rolled 2/2 on the new digests.

Live verification: controller startup banner `v1.21.3` (go1.26.10);
transient `ACME client for issuer not initialised` requeues during the first
minutes, then zero error lines; ClusterIssuer `letsencrypt-http01` remained
Ready/ACMEAccountRegistered; all 69 Certificates Ready; a scratch
selfsigned Certificate `cm-1-21-3-issuance-probe` reached Ready in <6s,
issued a 1h cert verified with openssl, and was deleted together with its
Secret.

## Interaction with the Ansible k3s HA role

The `k3s_ha_dependencies` role (see `k3s-ha.md`) preserves replica,
placement and rolling-update settings in the *existing* Helm release and
uses the same chart version. Since the Argo Application took ownership of
this deployment, re-running that role must not replay an old chart version
or values that Git does not have; review any role run against the vendored
chart in Git before applying.

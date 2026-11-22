# Wiki runtime/theme upgrade — 2026-11-07

## Deployed artifacts

- Upstream source: `alchemmist/hugo-docs@f52cf2a6c61faeaf9734053c14b63f7d5e1ad276`.
- Latest published upstream tag remains **v0.4.1**; this is a deliberately pinned
  main revision nine commits later, not an invented v0.4.2 release.
- Final image: `harbor.socrat.alchemmist.xyz/homelab/wiki-runtime:upstream-f52cf2a-socrat-20261106`.
- Registry-verified digest: `sha256:dc5b15b391cd94fad3db51dc7fa917e138d77ea345e27518371073538c5a78d9`.
- GitOps maintenance commit `fb59e63`, upgrade/resume commit **`cc8ac0e`**.
- Argo CD `wiki-runtime`: observed **Synced / Healthy** on the upgrade revision.
  One ready replacement pod on socrat-0, zero restarts at acceptance.

## Compatibility caught before deployment

Upstream native OIDC requests `openid profile email`; our accepted provider uses
an explicit `groups` scope. Blindly replacing the old image could lose the claim.
`deploy/wiki-runtime/upstream/Dockerfile` preserves `openid profile email groups`
with an exact source SHA-256/text guard. No issuer, client secret, identity mapping,
MFA, native role or signing-key change. Do not apply the historical 0.4.1 full
OIDC overlay on top. Other upstream changes include current theme/editor styles,
typography/sidebar and Git subprocess lifecycle fixes.

## Controlled backup and rollout

A temporary Git commit set the **single writer to zero**; Argo applied that state.
The actual data claim was discovered from the running Deployment, not assumed
from the retained old socrat-3 claim. Current claim remains
`wiki-runtime-data-socrat-0`; its UID, binding and node placement were preserved.
Only after every pod mounting that claim was gone was the complete volume archived
under root-private `/var/lib/homelab-wiki-upgrades/` on socrat-0. Archive listing and
SQLite integrity passed; native account/link fingerprints and four Secret
UID/data fingerprints were retained privately. No password hashes, identities,
keys, sessions or receipt contents are in this repository.

The archive is approximately 231MB. It is a local protected backup, **not** an
independently tested off-node DR restore. No old PVC or historical backup was deleted.
Writer confirmed stopped before backup at 08:11:06Z; new ready runtime acceptance
completed at 08:12:45Z. This was planned maintenance, not zero downtime; these
observations do not measure the exact public outage duration.

The next Git commit pinned the final digest and restored one writer. Rendered
production manifests differed from the original only in the container image;
Secret references, branding, storage, ingress, origin and contentPrefix remained
unchanged. No manual Helm upgrade, node/database restart, unrelated Argo sync or
prune, data restore, importer or credential regeneration was performed.

The vendored chart now permits replicaCount **0 or 1 only**, guarded by schema.
Zero is explicit coordinated offline maintenance; it is not a normal operating
state. A source change to two writers must fail validation.

## Acceptance

- Fresh disposable-volume container acceptance passed on base and final images:
  bootstrap, public read, account theme isolation, MCP discovery/read/read-only/
  revocation, publication and restart persistence.
- Nine OIDC regressions passed on both; final image also asserts groups scope.
- Existing homelab wiki runtime/bootstrap/migration tests:11; placement tests:2.
- Helm lint/template passed; final rendered delta reviewed; schema rejects2 writers.
- Actual running image/digest, preserved groups scope, one ready pod and Argo health
  checked. Current PVC unchanged. All four used Secret UIDs/data unchanged.
  Audited native users/OIDC-link table fingerprints unchanged.
- Public HTTPS: home, health, updated onboarding and new SSH/deploy/SRE/bot notes200;
  retired Syncthing/structure notes404; anonymous MCP401.
- OIDC login redirects through the native login route to an authorization request
  with `openid profile email groups` and PKCE S256. Owner fallback form200.
- Nine public fingerprinted CSS/JS assets downloaded and content hashes verified.
  Runtime rebuilds the accepted publication with the new template at startup.
- Existing MCP bearer read, revision-guarded **real** deployment-guide improvement,
  immediate readback and public publication succeeded. No synthetic page or alert.

A fresh interactive real-user password/MFA/browser acceptance was **not** repeated;
redirect/scopes, local regressions and preserved identities are not that proof.
Physical browser rendering was not inspected because the existing Playwright
profile was busy; it was not killed or taken over. No blanket compatibility claim.

## Rollback boundaries

Previous image remains available:
`sha256:64d27d6f320ab7440be82578d1d73193278e6b12f77127776b715c2e98b17515`.
A rollback is an explicit new Git pin, retaining the current PVC, account policy,
Secrets and one writer. Do not restore the pre-upgrade archive over newly accepted
content. Freeze/backup/reconcile accepted writes first if a data restore becomes
necessary. Do not remove OIDC configuration to make a rollback easier.

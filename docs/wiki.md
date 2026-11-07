# Socrat Wiki deployment

Public documentation lives in `wiki/content/` and is served at <https://wiki.socrat.alchemmist.xyz/>. Operational documentation in `docs/` is not site content. Socrat configuration requests no indexing; `noindex` is not access control. Never publish credentials, user records or recovery material.

## Architecture and deployment status

The reusable theme, visual editor, backend, runtime image, Helm chart and their tests now belong to [hugo-docs](https://github.com/alchemmist/hugo-docs). Homelab owns Socrat content, branding, instance values, secret references and the Argo CD Application. Hugo still renders the site. Do not restore the removed homelab engine, charts or wiki image-publication workflows.

The production wiki runs pinned upstream `hugo-docs` commit `f52cf2a6c61faeaf9734053c14b63f7d5e1ad276` (2026-11-07 rollout), nine commits after tagged v0.4.1, with the existing Socrat Authentik groups scope preserved. This is not a new upstream release tag. See [the upgrade receipt](wiki-upgrade-20261107.md) and `deploy/wiki-runtime/upstream/README.md`. The final data copy was made with both writers stopped, and `wiki-editor-data` is retained for recovery. Public HTTPS routes to the runtime. The historical private gateway routes are currently missing their Wiki virtual hosts and fail certificate validation; do not bypass TLS or treat them as accepted. A local administrator has been created; HTTPS login/logout was verified through the public address `109.173.40.247` and private address `10.250.0.1`.

`deploy/argocd/apps/wiki-runtime.yaml` is the Argo CD Application. It renders `deploy/wiki-runtime/chart` with `deploy/wiki-runtime/values.yaml` on `main` into namespace `wiki`. The active runtime includes upstream native OIDC plus a guarded one-line groups-scope preservation layer, a narrowly vendored chart and an immutable private Harbor digest. The old v0.4.1 OIDC overlay is historical rollback provenance, not layered onto the current runtime. See `deploy/wiki-runtime/oidc/README.md` for provenance and rollout details. Background Git synchronization and ownership of the public ingress are declared by those values. The legacy wiki and wiki-editor bundles and deployments have been removed; the old data claim remains retained. See [the migration runbook](wiki-runtime-migration.md). Rancher can still run its own Fleet controllers while multi-cluster-management stays enabled; that is not a second wiki deployer. Do not add a Fleet GitRepo for this application.

The declared architecture uses one Argo CD Application consuming the vendored OIDC-capable chart and immutable runtime image. GitHub Actions in hugo-docs builds and tests release artifacts; Argo CD deploys the selected artifacts from this repository. There is no separate homelab static reader image or publication branch in this architecture. Argo CD is the release manager; do not run competing Helm upgrades. Deleting the Application can remove its resources because of the resources finalizer and is not a rollback procedure.

The release name is `wiki-runtime` in namespace `wiki`; its service is `wiki-runtime-wiki.wiki.svc.cluster.local:8080`. The runtime uses a single writer and the new `wiki-runtime-data` PVC. Never attach both old and new writers to the same volume. Keep the old `wiki-editor-data` PVC intact throughout migration and the rollback window. Preserve `contentPrefix: wiki/content` so existing history and queued changes retain their paths.

`deploy/wiki-runtime/values.yaml` carries the English interface configuration and Socrat logo through `siteConfig` and `staticFiles`. The blog’s CourierCyr fonts are instance-owned `staticBinaryFiles`, configured under `params.content.typography`; the shared upstream image does not contain these font binaries. Bootstrap and Git SSH credentials belong in Kubernetes Secrets. The original upstream image/chart are public. The current OIDC derivative is private in Harbor and uses the scoped `wiki-harbor-pull` Secret. The bootstrap secret creates the first local administrator; it is not a permanent shared login. Configure remote Git only after the old synchronization worker has stopped and its pending state has been inspected.

Folder expansion choices and sidebar scroll position are restored before page rendering and preserved when the editor tree finishes loading.

## Bootstrap and recovery

`ansible/playbooks/wiki.yml` invokes `scripts/bootstrap-wiki-runtime.py`. The helper prepares the namespace, new PVC, bootstrap and Git credentials. It does not create a Fleet identity or apply a GitRepo. It neither reads nor copies registry credentials. Use this playbook only after reviewing its declarations. Existing bootstrap credentials are preserved rather than rotated on reruns. Production bootstrap and routing cutover have completed. Argo CD reconciles the Application from `deploy/argocd/apps/wiki-runtime.yaml`.

For a clean installation without legacy Git credentials, the playbook supports `-e wiki_runtime_skip_legacy_git=true`. Verify the remaining prerequisites before applying. Existing registry secrets for legacy private images are left untouched. For the existing Socrat installation, follow the migration runbook and restore the accepted data before activating the runtime; namespace and PVC creation alone do not migrate content.

## Access and publication

Anonymous users can read the public wiki. Authentik native OIDC authorizes browser sign-in; existing owner and Tim identities are linked by reviewed issuer/subject mappings. Tim keeps his existing editor role; other observers default to reader. Local passwords and old local sessions are owner-only. The owner fallback form is `/login?local=1`, username `admin`, with the unchanged current password. A saved initial credential was stale and was not reset. Reader, editor and administrator roles apply across the wiki. There is no trusted-WG-header bypass. The backend checks permissions and CSRF on requests; hiding controls is not authorization. The interface uses English; the Markdown content remains Russian. Login is available at `/login`. Account settings and administrator user management are full pages at `/admin`; existing accounts and passwords persist across upgrades.

The editor’s Monospace button applies inline code typography without changing the text color or background. Linked monospace text preserves its appearance and remains clickable. Formatting is stored as Markdown code spans; code blocks retain their separate styling.

The browser stages content and structural changes together across pages. Publication validates revisions, applies the complete patch, renders with Hugo and atomically exposes the accepted result. A conflict or failed build must preserve the browser draft and leave the previous publication available. Git synchronization happens afterward; interactive publication does not wait for GitHub Actions or Argo CD.

Persisted local data is authoritative. GitHub can lag accepted publications, so a remote clone is not a complete backup. Preserve the entire volume, including local Git history, publication state/outbox, account database and uploads. Stop every writer before an offline backup. The canonical generic backup utility is `scripts/wiki-data.py` in hugo-docs; homelab retains `scripts/migrate-wiki-runtime.py` for the migration workflow. Follow the migration runbook for export, verification, restore and rollback.

## Operations and acceptance

Before switching routes, verify the isolated runtime, restored content, local administrator, reader/editor/admin permissions, immediate publication after reload, restart recovery and eventual Git synchronization. Use a new PVC and preserve the old release. Switch public ingress and optional private gateway to the same runtime only after acceptance. Keep the existing TLS secret `wiki-tls`; ensure the production hostname has only one active ingress owner.

The optional WG gateway switch is `wiki_editor_runtime_enabled`, default `true`, matching the active runtime routing. [Network instructions](wiki-editor-network.md) cover the exact-host split DNS and client lifecycle. Setting it to `false` restores legacy routing only as part of a coordinated rollback with the old deployment available.

The Socrat homepage links to the wiki through its chart-managed index ConfigMap. Configure monitoring with `python3 scripts/configure-wiki-monitor.py --activate --publish`; it requests the Kuma password interactively, reuses the exact-URL monitor, and adds it to the existing Socrat apps group without replacing other monitors. It uses the supported API and does not restart Kuma or edit its database.

Check HTTPS, public reading, authenticated editing, unknown-path responses, Russian search, local font delivery and mobile navigation after cutover. Monitor disk usage, publication errors, account access and Git backlog. Rollback after accepted writes requires preserving and reconciling those writes before reopening the old application; reverting routes alone is insufficient.

## Agent access

MCP is enabled with `config.mcp.enabled: true` at `https://wiki.socrat.alchemmist.xyz/mcp`. Each user creates a personal access token in `/admin`; browser sessions and bootstrap credentials are not MCP credentials. Use a read-only token for readers and a write-scoped token for editing. Effective permissions also follow the account role, and revocation takes effect on the next request. Do not store tokens in Git or shared agent configuration. See the [upstream MCP guide](https://github.com/alchemmist/hugo-docs/blob/v0.4.1/docs/mcp.md).

Authenticated users can choose Light or Dark under `/admin` → Account → Theme. This preference belongs to their account and persists across sessions; anonymous readers always receive the light theme. No shared deployment setting changes individual preferences.

## Identity rollout evidence

A real temporary observer completed password, TOTP, consent and OIDC/PKCE; the app
reported reader and rejected a write with 403. Fixture accounts were removed.
Both public edges return health 200, OIDC login redirect and the owner fallback form.
Existing MCP tools still list pages using their original bearer credential. Original
user IDs/password hashes were checked unchanged against the encrypted offline-consistent
volume backup. Access logs are disabled to avoid recording callback codes/state.
See `deploy/identity/migration-evidence/wiki-oidc-20261101.json`.

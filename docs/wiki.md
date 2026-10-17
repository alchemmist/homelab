# Socrat Wiki deployment

Public documentation lives in `wiki/content/` and is served at <https://wiki.alchemmist.xyz/>. Operational documentation in `docs/` is not site content. Socrat configuration requests no indexing; `noindex` is not access control. Never publish credentials, user records or recovery material.

## Prepared architecture and deployment status

The reusable theme, visual editor, backend, runtime image, Helm chart and their tests now belong to [hugo-docs](https://github.com/alchemmist/hugo-docs). Homelab owns Socrat content, branding, instance values, secret references and Fleet configuration. Hugo still renders the site. Do not restore the removed homelab engine, charts or wiki image-publication workflows.

This repository prepares a migration; it does not establish that production has switched. `deploy/fleet/wiki-runtime.yaml` declares the new GitRepo, watching `deploy/wiki-runtime` on `main`. The bundle is paused, ingress and Git synchronization are disabled, and the image digest must be pinned after the shared release is published and accepted. Applying or activating these manifests is a separate cutover step. See [the migration runbook](wiki-runtime-migration.md).

The target is one Fleet bundle consuming the upstream chart and immutable runtime image. GitHub Actions in hugo-docs builds and tests release artifacts; Fleet deploys the selected artifacts. There is no separate homelab static reader image or publication branch in this architecture. Fleet is the release manager; do not run competing Helm upgrades. Deleting a Fleet GitRepo can uninstall its resources and is not a rollback procedure.

The release name is `wiki-runtime` in namespace `wiki`; its service is `wiki-runtime-wiki.wiki.svc.cluster.local:8080`. The target uses a single writer and the new `wiki-runtime-data` PVC. Never attach both old and new writers to the same volume. Keep the old `wiki-editor-data` PVC intact throughout migration and the rollback window. Preserve `contentPrefix: wiki/content` so existing history and queued changes retain their paths.

`deploy/wiki-runtime/values.yaml` carries the Russian Hugo configuration and Socrat logo through `siteConfig` and `staticFiles`. Bootstrap and Git SSH credentials belong in Kubernetes Secrets. The upstream image and chart are public and require no registry credentials. The bootstrap secret creates the first local administrator; it is not a permanent shared login. Configure remote Git only after the old synchronization worker has stopped and its pending state has been inspected.

## Bootstrap preparation

`ansible/playbooks/wiki.yml` invokes `scripts/bootstrap-wiki-runtime.py` and applies the new GitRepo declaration. The helper prepares the namespace, scoped Fleet identity, new PVC, bootstrap and Git credentials. It neither reads nor copies registry credentials. The bundle remains paused. Existing bootstrap credentials are preserved rather than rotated on reruns. No production bootstrap or cutover has been performed as part of preparing these files.

For a clean installation without legacy Git credentials, the playbook supports `-e wiki_runtime_skip_legacy_git=true`. Verify the remaining prerequisites before applying. Existing registry secrets for legacy private images are left untouched. For the existing Socrat installation, follow the migration runbook and restore the accepted data before activating the runtime; namespace and PVC creation alone do not migrate content.

## Access and publication

After cutover, anonymous users can read the public wiki. Local accounts authorize editing from either the internet or WireGuard. Reader, editor and administrator roles apply across the wiki. There is no OIDC and no trusted-WG-header bypass. The backend checks permissions and CSRF on requests; hiding controls is not authorization. Login is available at `/login`.

The browser stages content and structural changes together across pages. Publication validates revisions, applies the complete patch, renders with Hugo and atomically exposes the accepted result. A conflict or failed build must preserve the browser draft and leave the previous publication available. Git synchronization happens afterward; interactive publication does not wait for GitHub Actions or Fleet.

Persisted local data is authoritative. GitHub can lag accepted publications, so a remote clone is not a complete backup. Preserve the entire volume, including local Git history, publication state/outbox, account database and uploads. Stop every writer before an offline backup. The canonical generic backup utility is `scripts/wiki-data.py` in hugo-docs; homelab retains `scripts/migrate-wiki-runtime.py` for the migration workflow. Follow the migration runbook for export, verification, restore and rollback.

## Operations and acceptance

Before switching routes, verify the isolated runtime, restored content, local administrator, reader/editor/admin permissions, immediate publication after reload, restart recovery and eventual Git synchronization. Use a new PVC and preserve the old release. Switch public ingress and optional private gateway to the same runtime only after acceptance. Keep the existing TLS secret `wiki-tls`; ensure the production hostname has only one active ingress owner.

The optional WG gateway switch is `wiki_editor_runtime_enabled`, default `false`. Set it to `true` only during the coordinated cutover. [Network instructions](wiki-editor-network.md) cover the exact-host split DNS and client lifecycle. The legacy default protects the running installation while migration is staged; it is not the target authorization model.

The Socrat homepage links to the wiki through its chart-managed index ConfigMap. Configure monitoring with `python3 scripts/configure-wiki-monitor.py --activate --publish`; it requests the Kuma password interactively, reuses the exact-URL monitor, and adds it to the existing Socrat apps group without replacing other monitors. It uses the supported API and does not restart Kuma or edit its database.

Check HTTPS, public reading, authenticated editing, unknown-path responses, Russian search, local font delivery and mobile navigation after cutover. Monitor disk usage, publication errors, account access and Git backlog. Rollback after accepted writes requires preserving and reconciling those writes before reopening the old application; reverting routes alone is insufficient.

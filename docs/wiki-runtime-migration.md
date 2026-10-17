# Migrating Socrat Wiki to the shared runtime

The production routing and data migration to `hugo-docs` v0.2.0 completed on 2026-10-18. The final volume copy was performed with both old and new writers stopped. The new runtime serves public ingress and both WG virtual hosts; the old PVC is retained. A local administrator exists, and HTTPS login/logout was verified through `109.173.40.247` and `10.250.0.1`. The procedures below document the rehearsal, cutover and recovery process. Legacy bundle retirement remains a separate cleanup step. No OIDC is required or configured. Public reading remains available; local accounts replace the WireGuard-only editing bypass.

## Data and ownership

The existing installation stores accepted content and Git objects in `/data/repository` and publication snapshots, the active pointer, and Git synchronization state in `/data/live`. Remote Git can lag an accepted publication. A GitHub clone alone is not a backup. Preserve the entire data volume, including any account database, SQLite sidecar files, uploads, and additional runtime state. Back up configuration, branding, secret references and the actual secrets separately in the existing protected backup system; never commit credentials to this repository.

The existing content prefix is `wiki/content`. Keep that prefix in the new runtime configuration. Changing it in place would invalidate queued patches and their Git paths. Preserve page URLs, aliases, front matter, and local Git history. The old template and branding live in the old image/source tree and must be copied into the new site's configuration independently of the data volume.

The migration utility requires Python 3.11+ and Git. It performs offline file copying, checksums and Git-object validation. It neither changes Kubernetes resources nor pushes Git. Its backup format is a directory with `manifest.json` and `data/`; internal links are made relative so restored volumes can move. Existing absolute `/data/...` links are supported. Links to other absolute paths and escaping relative links are rejected. Only use trusted operator-produced backups.

## Offline rehearsal

1. Select a shared runtime release by immutable image digest and chart version. Verify architecture support and its data-migration compatibility before using it with production data.
2. Disable editing, stop the Git synchronization worker and every other data writer, then take a filesystem/PVC snapshot or copy from the stopped volume. Suspending a Fleet reconciliation alone does not stop a process. Draining the Git queue is preferred, but pending records may be preserved if the new runtime supports their schema.
3. Export from the offline volume copy. `--offline` is an operator assertion, not a distributed lock. Do not copy a running SQLite database or let the old writer resume while its files are being copied.

```sh
python3 scripts/migrate-wiki-runtime.py export \
  --source /secure/wiki-old-data \
  --bundle /secure/wiki-backup-2026-10-17 \
  --offline
python3 scripts/migrate-wiki-runtime.py verify \
  --bundle /secure/wiki-backup-2026-10-17
python3 scripts/migrate-wiki-runtime.py restore \
  --bundle /secure/wiki-backup-2026-10-17 \
  --destination /secure/wiki-rehearsal-data
```

The restore destination must not exist. For a mounted empty PVC, restore into a new child directory and configure the runtime paths/subPath accordingly, or copy the validated restored directory onto the empty stopped volume with an operator-controlled transfer. Never restore over an active volume. Protect the backup directory and transport as credentials: future backups contain password hashes, sessions and private uploads. The tool makes its staging directory private but is not an encryption or remote-backup system.

The tool rejects dirty repositories, a HEAD different from the active accepted publication, missing publication/base commits, damaged checksums, missing state and external symlinks. Resolve these failures before migrating; do not delete queued state or reset Git to bypass them. Checksums detect accidental corruption, not malicious replacement of both manifest and data.

4. Start an isolated copy with remote Git synchronization disabled and an isolated hostname. Do not run a second Git publisher against the production branch during rehearsal. Confirm that any automatic migration affects only the copy.
5. Bootstrap a local administrator using the new runtime's one-time bootstrap procedure. No existing WG identity becomes an administrator automatically. Confirm that subsequent bootstrap attempts cannot take over an initialized installation.
6. Validate public reader, authenticated reader, editor and administrator permissions through both UI and direct API. Test login, logout, disabled accounts, password reset, CSRF, anonymous upload access and search. Public access must never trust the former `X-Socrat-*` headers.
7. Rehearse content editing across pages, create/move/reorder/rename/delete in one publication, rich-content round trips, immediate reload, drafts after failed publication, and restart. Verify pre-existing links and uploaded media. Check Git outbox recovery using a disposable remote, including a conflicting external commit.
8. Compare all old page URLs, titles and representative rendered content against the copy. Confirm fonts, subpath-aware assets, custom branding and installed plugins. Take and restore a second backup using the new runtime to verify its data layout.

## Production cutover

Use a new Helm release/resource naming scope and a **new PVC**. The old PVC `wiki-editor-data` must remain intact. The current `wiki` and `wiki-editor` Fleet installations must not be repointed to a shared writable volume. Only one runtime process may write the new volume; do not scale it to multiple writers.

After rehearsal acceptance, schedule a short edit freeze and repeat the offline backup from the final production state. Restore onto the new PVC and repeat the startup, publication and administrator checks. Keep public routes on the old readers until the new runtime is ready. Keep remote Git sync disabled until the old worker has stopped permanently and the preserved queue has been checked.

Manage the shared runtime with one declarative Fleet bundle consuming the versioned chart and immutable image. GitHub Actions builds and tests shared artifacts; Fleet deploys them. Socrat-specific configuration, content, branding and secret references remain in homelab. Record release identifiers, last accepted commit, outstanding queue entries, backup location and old resource names in the change record.

Switch both the public ingress and private WireGuard route to the new application. Confirm HTTPS, anonymous public reading and internet-accessible authenticated editing before enabling writes. Remove the legacy WG header authorization bypass. Verify a new accepted publication immediately after reload and its eventual remote Git synchronization.

Retire the old two bundles and wiki-specific image/publish CI only after acceptance. Fleet deletion may uninstall managed resources, so first verify resource ownership and prevent deletion of the retained PVC or shared ingress resources. Do not let old workflows redeploy the previous implementation after cutover.

## Rollback

Before any new write is accepted, restore the old routes and writer using its untouched PVC and pinned old image. Stop the new writer first. After the new runtime accepts writes, an ingress rollback alone loses visibility of those changes: freeze editing, stop writers, export the new data and reconcile the accepted content/history into a compatible old copy before reopening editing. Do not start the old binary on a database already migrated by the new version unless that downgrade is explicitly supported.

Retain the original volume and protected final backup until the rollback window closes. Monitor publication errors, authentication failures, restart recovery, disk usage and Git backlog throughout this period.

## Tool checks

```sh
python3 -m unittest discover -s tests -p test_wiki_runtime_migration.py -v
```

Tests use disposable local repositories and cover history/outbox/account/upload preservation, corruption detection, refusing overwrite, rejected escaping links, dirty content and missing Git objects. They never contact or modify the cluster.

## Declarative deployment

`deploy/wiki-runtime/fleet.yaml` and `values.yaml` define the active bundle. Its GitRepo declaration is `deploy/fleet/wiki-runtime.yaml`. The chart `0.2.0` and image `ghcr.io/alchemmist/hugo-docs-wiki:0.2.0` are public; the image is pinned to `sha256:fe86f6679d33380bfaecb92f8b6ded2b4d33c1947968a7cb2e9a1a74e526b6b4`. No registry credentials are required. The declarations include background Git synchronization and the runtime-owned public ingress; check Fleet reconciliation when assessing their rollout.

Deployment invariants and checks:

- Publish and accept the shared chart/runtime and pin its immutable image digest in values. `staticFiles` carries an exact copy of `wiki/static/images/socrat.svg`; `siteConfig` carries the Russian site configuration. A custom image is not required. Do not reuse the old editor image or copy the legacy `wiki/assets/wiki-editor.js`, `wiki/assets/wiki-editor.css`, or editor layout overrides: they shadow the new theme editor. Retain the packaged vendored module tree.
- Create and restore the **new** `wiki-runtime-data` claim and `wiki-runtime-bootstrap` Secret (`token` key) in namespace `wiki`. Check volume ownership for UID/GID 1000. The skeleton never claims `wiki-editor-data`.
- The installed Fleet v0.16.2 supports the OCI `helm.repo` field. The public chart is pulled anonymously; keep registry credentials used by the legacy images untouched. [Fleet chart-source reference](https://fleet.rancher.io/reference/ref-fleet-yaml#_chart_source).
- Accept the isolated application and administrator login before changing `paused`, enabling ingress or attaching the bundle to a GitRepo. Do not enable a duplicate ingress for the production hostname while the old route remains active.
- For cutover, configure Git repository `git@github.com:alchemmist/homelab.git`, branch `main`, and a new combined SSH Secret containing `id_ed25519` and `known_hosts`. The old installation uses separate secret/configmap mounts, so its secret cannot be referenced unchanged. Stop its sync worker first.
- Retain existing TLS secret `wiki-tls`, configure the private WG route to the same service, and then retire the legacy authorization bypass and old bundles according to the runbook.


### Private gateway cutover

The existing Ansible role `wiki_editor_access` manages the `syncthing` Helm release in namespace `syncthing`, which runs the private nginx entry points on `socrat-0` and `socrat-1`. Its wiki vhosts use `wiki-editor-private-tls` in that namespace. The certificate and WireGuard allowlist remain unchanged.

The role switch `wiki_editor_runtime_enabled` defaults to `true`, matching the completed cutover. It routes both wiki vhosts to one upstream, `http://wiki-runtime-wiki.wiki.svc.cluster.local:8080`, removes their separate `editorUpstream`, and removes the `editorAuthSecret` mount when no other vhost requires it. Consequently nginx no longer injects the legacy editor secret or WG peer headers for wiki API requests. The runtime still performs all account authorization.

Before applying, confirm the new service is healthy, the shared image is accepted, the old writer has stopped, and public routes are ready to switch. Render/review the entire Syncthing gateway release because it also serves other applications. Preserve all unrelated virtual hosts and keep the old secret objects until rollback is no longer needed. Both production wiki virtual hosts have been switched; future gateway changes must preserve other applications.

Rollback before new writes uses `wiki_editor_runtime_enabled=false` and the retained old deployment; rollback after accepted writes first requires the data reconciliation described above.

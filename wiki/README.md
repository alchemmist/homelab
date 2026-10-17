# Socrat Wiki content

Public Russian documentation for Socrat at <https://wiki.alchemmist.xyz/>. This directory contains instance content and branding. The Hugo theme, browser editor, runtime backend, container, chart and their tests live in [hugo-docs](https://github.com/alchemmist/hugo-docs). Hugo still renders the site.

## Content

Notes belong in `content/`. Folder `_index.md` files contain navigation title and weight; the root `_index.md` is the home page. Prefer Hugo `relref` links to notes. Keep page URLs and aliases stable when reorganizing content. Do not publish private operational documentation, credentials or personal configuration. `noindex` is not access control.

The accepted runtime data volume is authoritative during operation. Git synchronization can lag publication. Do not edit the runtime's managed working tree concurrently with its writer. Use the visual editor or the upstream documented import/Git synchronization workflow for content updates.

## Runtime and development

Use the upstream hugo-docs starter and its documented Makefile targets for local development, static previews, runtime launches and checks. This directory no longer ships a separate npm application, Dockerfile or Makefile. Runtime documentation is maintained in the upstream repository; Socrat deployment values live in `deploy/wiki-runtime/values.yaml` at the homelab root.

The production wiki uses the upstream v0.2.0 runtime with one writer and the migrated `wiki-runtime-data` volume; the old PVC is retained for recovery. `deploy/fleet/wiki-runtime.yaml` declares the GitRepo. The bundle is active, with the immutable image digest, public ingress and background Git synchronization declared in deployment values. Public and both WG routes now reach the shared runtime. Legacy bundle retirement is a separate cleanup step.

Public reading remains available and local accounts sign in at `/login` to edit. Reader, editor and administrator roles apply across the wiki. OIDC is not used. WG routing is optional and does not bypass account authorization. The editor stages changes across pages and publishes content and tree operations atomically; remote Git and CI are outside the immediate publication path.

See [deployment operations](../docs/wiki.md), [network setup](../docs/wiki-editor-network.md) and [the migration runbook](../docs/wiki-runtime-migration.md). Back up the entire runtime volume, not just GitHub. The canonical generic backup tool is upstream `scripts/wiki-data.py`; the homelab migration helper remains `scripts/migrate-wiki-runtime.py`.

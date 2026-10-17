# Socrat Wiki deployment

Public documentation lives only in `wiki/content/`. The theme is pinned to `github.com/alchemmist/hugo-docs@v0.1.0`, with Russian navigation and local search. Internal `docs/` is never copied into the site build. The public site requests no indexing; it does not require login.

Run `make -C wiki check` before publishing. `make -C wiki dev` starts the local preview. `make -C wiki image SOURCE_SHA=<commit>` builds the nginx gateway image with a bundled build artifact. Never publish tokens, personal VPN subscriptions, user records or recovery credentials. Document only verified behavior.

The `Socrat wiki` GitHub Actions workflow checks relevant pull requests. For `main`, it builds `ghcr.io/alchemmist/socrat-wiki:<source-sha>`, publishes a digest-pinned bundle to `wiki-publish`, and verifies the source SHA at `https://wiki.alchemmist.xyz/deployment-version.json`. The publication job uses `GITHUB_TOKEN` with `packages:write` and `contents:write`; GitHub receives no SSH key or kubeconfig. Publication is serialized. Newer relevant source changes prevent stale promotion; unrelated main commits do not invalidate unchanged wiki sources.

The publication branch contains only `bundle/fleet.yaml` and rendered resources. Do not edit it manually. Fleet polls every minute and manages only namespace `wiki` on the local cluster. Image publication and successful public rollout are separate checks. A verification failure can indicate DNS, certificate, registry or Fleet problems despite a successfully published image.

Bootstrap from `ansible/` with `ansible-playbook playbooks/wiki.yml --ask-become-pass`. It creates the namespace and a deployment identity in the actual Fleet agent namespace, with permissions scoped to wiki. It copies `blog/ghcr-pull` without printing credentials. The repository is public; if that changes, pass `-e wiki_git_secret=<existing-secret-name>` referencing a read-only repository credential in `fleet-local`.

The bundle sets `createNamespace: false`; do not grant cluster-wide namespace creation. The chart requires an immutable digest and runs nginx as UID 101 with a read-only root filesystem, two replicas across eligible nodes, and no database or PVC in the nginx deployment. Fleet is the sole release manager: do not add wiki to the generic apps.yml loop or run competing Helm upgrades.

DNS must point `wiki.alchemmist.xyz` at the public ingress. Existing issuer `letsencrypt-http01` issues `wiki/wiki-tls`. Verify Fleet readiness, both Deployment replicas, TLS, health/version endpoints, unknown-path 404 behavior and the robots header. Test desktop/mobile navigation and Russian search. Five consecutive public version reads do not replace Kubernetes replica readiness checks.

Roll back by reverting the relevant source commit on main and using the same pipeline. A failed build does not advance publication. Atomic Helm updates retain the preceding release on failed readiness. Deleting the Fleet GitRepo can remove its application; do not use deletion as rollback.

The Socrat homepage links to the wiki through its chart-managed index ConfigMap. Configure monitoring with `python3 scripts/configure-wiki-monitor.py --activate --publish`; it requests the Kuma password interactively, reuses the exact-URL monitor, and adds it to the existing Socrat apps group without replacing other monitors. It uses the supported API and does not restart Kuma or edit its database.

## Live publication

Public nginx forwards GET and HEAD requests to `wiki-editor:8080/site/`; `/api` and `/api/` remain unavailable through the public ingress. Authentication headers and cookies are stripped from the rendering upstream. HTML and assets use `Cache-Control: no-store`. `/healthz` checks the nginx process, `/deployment-version.json` identifies its immutable image, and `/version.json` identifies the content served by the live renderer. Do not use the deployment version as proof that an edit is published.

The editor packages Hugo 0.167.0, the vendored theme and compiled browser assets in `/opt/wiki`. It builds without runtime Go or theme downloads. `LIVE_MODE=true`, `LIVE_TEMPLATE_DIR=/opt/wiki` and `LIVE_STATE_DIR=/data/live` enable local publication. `/data` is a retained 5 GiB `local-path` PVC shared by the content state and Git worktree. The single editor replica uses Recreate and remains unready until its live site is usable. Nginx pods are explicitly admitted by the editor NetworkPolicy; the private gateway authentication is still mandatory for edit APIs.

Accepted edits publish a local rendered generation before Git synchronization completes. Git and CI provide history and image updates, not the interactive publication path. Image updates must retain persisted accepted content and render it with the new template. A node loss can interrupt the single local-path writer; do not delete its PVC as a rollout fix. Back up `/data` in addition to Git because pending synchronization may contain newer accepted edits.

Both wiki workflows include template and frontend changes, but content-only changes run only the static validation workflow and do not restart the editor. Only the editor image contains the live template. Build it from the repository root with `docker build -f wiki-editor/Dockerfile .`; its Dockerfile-specific allowlist excludes operational documentation, credentials and unrelated repository files from the build context.

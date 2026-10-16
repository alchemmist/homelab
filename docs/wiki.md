# Socrat Wiki deployment

Public documentation lives only in `wiki/content/`. The theme is pinned to `github.com/alchemmist/hugo-docs@v0.1.0`, with Russian navigation and local search. Internal `docs/` is never copied into the site build. The public site requests no indexing; it does not require login.

Run `make -C wiki check` before publishing. `make -C wiki dev` starts the local preview. `make -C wiki image SOURCE_SHA=<commit>` builds the standalone image. Never publish tokens, personal VPN subscriptions, user records or recovery credentials. Document only verified behavior.

The `Socrat wiki` GitHub Actions workflow checks relevant pull requests. For `main`, it builds `ghcr.io/alchemmist/socrat-wiki:<source-sha>`, publishes a digest-pinned bundle to `wiki-publish`, and verifies the source SHA at `https://wiki.alchemmist.xyz/version.json`. The publication job uses `GITHUB_TOKEN` with `packages:write` and `contents:write`; GitHub receives no SSH key or kubeconfig. Publication is serialized. Newer relevant source changes prevent stale promotion; unrelated main commits do not invalidate unchanged wiki sources.

The publication branch contains only `bundle/fleet.yaml` and rendered resources. Do not edit it manually. Fleet polls every minute and manages only namespace `wiki` on the local cluster. Image publication and successful public rollout are separate checks. A verification failure can indicate DNS, certificate, registry or Fleet problems despite a successfully published image.

Bootstrap from `ansible/` with `ansible-playbook playbooks/wiki.yml --ask-become-pass`. It creates the namespace and a deployment identity in the actual Fleet agent namespace, with permissions scoped to wiki. It copies `blog/ghcr-pull` without printing credentials. The repository is public; if that changes, pass `-e wiki_git_secret=<existing-secret-name>` referencing a read-only repository credential in `fleet-local`.

The bundle sets `createNamespace: false`; do not grant cluster-wide namespace creation. The chart requires an immutable digest and runs nginx as UID 101 with a read-only root filesystem, two replicas across eligible nodes, and no database or PVC. Fleet is the sole release manager: do not add wiki to the generic apps.yml loop or run competing Helm upgrades.

DNS must point `wiki.alchemmist.xyz` at the public ingress. Existing issuer `letsencrypt-http01` issues `wiki/wiki-tls`. Verify Fleet readiness, both Deployment replicas, TLS, health/version endpoints, unknown-path 404 behavior and the robots header. Test desktop/mobile navigation and Russian search. Five consecutive public version reads do not replace Kubernetes replica readiness checks.

Roll back by reverting the relevant source commit on main and using the same pipeline. A failed build does not advance publication. Atomic Helm updates retain the preceding release on failed readiness. Deleting the Fleet GitRepo can remove its application; do not use deletion as rollback.

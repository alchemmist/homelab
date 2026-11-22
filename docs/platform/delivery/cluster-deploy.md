# Deploying to the Socrat cluster

Updated **November 7, 2026**. Workloads are managed by Argo CD via root and
`deploy/argocd/apps`. Below is the build/image release contract for connected
services; not all images have been moved from GHCR to Harbor. The first blog
pilot is history, not a limitation of the current GitOps to a single
application.

**Fleet GitOps removal.** The repository no longer has a Fleet `GitRepo` and
`deploy/**/fleet.yaml`. Application delivery is Argo CD only
(`deploy/argocd/apps`). This is not a removal of the Fleet controllers from
the cluster: Rancher v2.15.2 re-enables Feature Fleet while
multi-cluster-management is enabled. The `cattle-fleet-*` budgets, the
`gitjob`/`helmops` placement and the descriptions of the excluded Fleet
dashboards are therefore kept. Do not restore a GitRepo and do not consider
multi-cluster-management disabled. GHCR images are a separate registry
migration, not a reason to keep a Fleet bundle.

The first-pilot journal and registry: `docs/platform/harbor/harbor.md`.

## What is the truth

The **desired** image version lives in Git, `alchemmist/homelab`, branch
`main`. The live version is proven by the Argo revision, the workload
image/imageID and functional acceptance. Argo applies it only on an allowed
sync; enabled=false, hooks or drift can stop the process. CI calls no Argo API
and does no Sync.

Manual edits in the Argo CD UI, `kubectl set image`, `helm upgrade` and Helm
parameters on an Application are not persisted. The next sync returns the
object to the manifest from Git. The blog has `selfHeal: true`.

The expected chain:

1. The service repository builds and verifies the artifact.
2. CI pushes an immutable image to Harbor. The image tag is the full git SHA
   of the service's commit, not `latest`.
3. The same job, in one step, calls `alchemmist/deploy-to-socrat@v1` and
   passes the digest returned by `docker/build-push-action`.
4. The Action commits to `homelab` `main` only that application's image fields.
5. Argo CD sees the commit on the next repository poll and syncs the
   Application. The usual poll interval is about three minutes. A GitHub
   webhook is not configured.

The image:

```text
harbor.socrat.alchemmist.xyz/homelab/<app>:<git-sha>
```

The pod gets `repository@sha256:...` if `image.digest` is non-empty. The tag
in values remains as a record of which service commit built this digest. Blog
template: `charts/blog/templates/deployment.yaml`.

## What not to do

- Do not patch an Application from CI and do not write the digest into Helm
  parameters. An empty list must be explicit in the manifest: `parameters: []`.
  If the field is absent, `kubectl apply` does not erase the old list, and the
  parameter overrides the Git file.
- Do not call `argocd app sync`, `helm upgrade`, `helm uninstall`,
  `kubectl set image` from CI.
- Do not add a second GitHub Actions job for the version commit. There is one
  entry point: the `Deploy to Socrat` step inside the job that already built
  and pushed the image.
- Do not create your own AppProject or ApplicationSet. All Applications live
  in the built-in `default` project. Argo's `spec.project` field is mandatory;
  `default` is created together with Argo CD and we do not describe it with a
  separate manifest.
- Do not hand-commit an image version bypassing the action, except for an
  emergency rollback.

## How to use the action

Repository: `alchemmist/deploy-to-socrat`, tag `v1`. It is a composite action,
not a separate workflow.

```yaml
- name: Deploy to Socrat
  uses: alchemmist/deploy-to-socrat@v1
  with:
    token: ${{ secrets.HOMELAB_DEPLOY_KEY }}
    image_version: ${{ steps.image.outputs.digest }}
```

The Application name is taken from the repository name. If they differ, pass
`app`. The name is lowercase letters, digits and hyphens, no longer than 41
characters.

`image_version`:

- `sha256:` and 64 hex. The action writes this into `image.digest` and sets
  `image.tag` equal to the calling commit's full SHA. This is how a release
  should be done.
- An ordinary image tag. The action writes it to `image.tag` and clears
  `image.digest`. That is a fallback, not the main path.

Files it changes:

- the required `deploy/<app>/values.yaml`;
- `charts/<app>/values.yaml`, if the file already exists.

In both, the root `image` key must already contain `tag` and `digest` strings.
The action does not create files and does not add keys. Only these files enter
the commit. The commit author is `socrat-releaser`. Message:
`chore(<app>): deploy <image_version>` plus a `Source: <repo>@<sha>` line.

If by commit time `GITHUB_SHA` is no longer the branch tip, the action exits
successfully and pushes nothing. An older build must not revert a newer commit.
If the values are already these, there is no commit either.

Before committing, the action runs `git pull --rebase origin main` so two
releases in a row do not overwrite each other's version commit.

A live invocation example: `.github/workflows/deploy.yaml` in `alchemmist/blog`,
job `publish-and-deploy`.

## The key and its rights

`token` is the private write deploy key `socrat-releaser` on the
`alchemmist/homelab` repository. In GitHub it is stored as the secret
`HOMELAB_DEPLOY_KEY` in each repository that calls the action. Currently that
is `blog` and `deploy-to-socrat` itself.

The key can push anything to `homelab`. The “only image fields” restriction is
in the action's code, not in the key's rights. Anyone able to change the
workflows of a repository with this secret can take the key and push any file
to `homelab`.

`main` in `homelab` is not closed by a ruleset. A deploy key cannot be added
to a ruleset bypass, so a closed branch would also cut off the robot. While
only the owner pushes to the repository, this is an accepted gap. When other
people appear with the right to change workflows, the key must be replaced by
a GitHub App that can be put into the bypass, and the private key kept only in
the action's repository.

The Argo CD token is not needed for a release. The old secret
`ARGOCD_AUTH_TOKEN` in the blog repository is unrelated to this path.

Harbor: the push account in CI secrets (`HARBOR_USERNAME`, `HARBOR_PASSWORD`).
Pull in the namespace — the Secret `kubernetes.io/dockerconfigjson` and
`imagePullSecrets`. For the blog that is `blog-harbor-pull`.


## The tile icon and external Helm repositories

Snapshot of **November 3, 2026**. The icon on an Application tile is the type
of the first source, not what is inside the chart. For `cats`,
`format-quorum`, `blog` and `authentik` the first source is the git
`alchemmist/homelab` (`charts/<app>`), hence Git. For `cert-manager` and
`harbor` the first source is an external Helm chart (`chart:`), with the git
values connected second (`ref: values`), hence Helm.

`authentik` no longer downloads `charts.goauthentik.io`. The `2026.8.6` chart
lives in `charts/authentik`; the Application reads
`deploy/platform/authentik/values.yaml`. The conditional PostgreSQL and
`authentik-remote-cluster` subcharts are not part of the vendored copy: both
are disabled in this cluster, and `helm dependency build` timed out on them.
The live Postgres is a separate StatefulSet, not a subchart.

`ComparisonError` / `failed to generate manifest for source 1 of 2` /
`context deadline exceeded` on the remaining external Helm applications is
not a pod crash. The repo-server does not manage `helm pull` within 90
seconds, in particular with `helm.goharbor.io`. On a cache miss the manifest
is re-downloaded. Until the pull succeeds, the sync stays `Unknown`; already
running pods are not stopped.

## Release annotations on Grafana charts

The `argo-cd-argocd-notifications-controller` subscribes to all Applications
except `root`. The `on-deployed` condition in
`deploy/platform/argo-cd/values.yaml`: sync `Succeeded`, health `Healthy`, the
operation finished less than 10 minutes ago. `oncePer: app.status.sync.revision`
prevents a repeat mark on the same commit. An application without
`operationState` is skipped by the condition.

A trigger sends `POST /api/annotations` to the Service
`kube-prometheus-stack-grafana` in `cattle-monitoring-system`. Body:
`"<app> deployed <revision>"`, tags `deploy` and the application name. The
Grafana service-account token `argocd-deploys` (Editor role) is stored only
in the Secret `argocd/argocd-notifications-secret`, key `grafana-api-key`.
Helm does not create this Secret.

On Overview, Services, Nodes, Metrics and LLM the `deploy` variable is a
dropdown of Application names. The dash `-` matches no tag, so the lines are
hidden. Choosing a service keeps the annotations that carry both tags: `deploy`
and that service's name. There is no “show all” switch on the dashboard. There
is no layer on the Traffic light. There is no separate posting into each
dashboard.

## A local API account for the agent

The current client is the official Argo CD Labs MCP from the project
settings, with `MCP_READ_ONLY=true`: diagnostics, not imperative deployment.
Installation and private credential storage are described in the
[official MCP runbook](../agent-access/official-mcp.md).
Do not run the credential helper to display the token and do not revive the
old user wrapper from the historical instructions.

The canonical `deploy/platform/argo-cd/values.yaml` keeps `accounts.mcp:
apiKey`, `g, mcp, role:readonly` and the existing server-side grant
`p, mcp, applications, sync, */*, allow`. This is the difference between the
credential's capabilities and the client's read-only mode, not permission to
use sync in routine diagnostics. This refactoring changes no RBAC, widens no
grant, and does not pass off the client restriction as a server-side ban. The
common default is `role:unassigned`, not `role:readonly`.

The historical November 7 snapshot described a temporary direct ConfigMap edit
while the chart failed to download. That is not the current maintenance method
and not a fallback on an Application error. Account/RBAC maintenance goes
through the canonical Git source; native OIDC and the existing credentials are
preserved. The accepted Argo acceptance after the move is described in the
[management handoff](https://github.com/alchemmist/homelab/blob/2fd1179442b3c7b05c9049dfa4bbaa47bfbc3790/docs/vm105-management-20261116.md).

## How Argo CD is arranged

Argo CD is placed separately: application-controller on `socrat-5`, the other
components on `socrat-0`. UI: `https://argocd.socrat.alchemmist.xyz`, native
Authentik OIDC. Canonical values: `deploy/platform/argo-cd/values.yaml`; the
old path is a compatibility symlink. `ansible/playbooks/argocd.yml` permits
only an explicit empty-cluster bootstrap and refuses when workloads already
exist. Current contract: [context](../system-overview.md); acceptance:
[management handoff](https://github.com/alchemmist/homelab/blob/2fd1179442b3c7b05c9049dfa4bbaa47bfbc3790/docs/vm105-management-20261116.md).

The base scheme and NetBird:

| Name | From | What it does |
| --- | --- | --- |
| `root` | `deploy/argocd/root.yaml`, applied once | Watches the `deploy/argocd/apps` catalog and maintains the Applications there. `prune: true`, `selfHeal: true`. Itself is not in the catalog. |
| `netbird` | `deploy/argocd/apps/netbird.yaml` | Chart `charts/netbird`, values `deploy/netbird/values.yaml`. The whole NetBird Kubernetes stack, including management/dashboard, edge, relays, STUN and machine agents; `prune: false`, `selfHeal: true`. PVCs/own namespaces are protected with `Prune=false,Delete=false`; secrets remain private bootstrap dependencies. |
| `blog` | `deploy/argocd/apps/blog.yaml` | Chart `charts/blog`, values `deploy/blog/values.yaml`, namespace `blog`. `prune: false`, `selfHeal: true`, `CreateNamespace=true`. |

`root` is the ordinary app-of-apps scheme without an ApplicationSet. Delete
the `blog` Application — `root` will create it again from Git. Delete the file
from `deploy/argocd/apps` — `root` will delete the Application too. The blog
has the finalizer `resources-finalizer.argocd.argoproj.io`, so deleting the
Application also removes its resources. `root` has no finalizer: deleting
`root` itself does not erase the child Applications. `root` can be restored
only by re-running `kubectl apply -f deploy/argocd/root.yaml`.

Pods are restored by the Deployment's ReplicaSet, not `root`. `root` restores
Applications. Old zero-pod ReplicaSets are the Deployment's history
(`revisionHistoryLimit` defaults to 10). Live replicas exist only for the
current one.

Harbor is a single instance, on socrat-0. A socrat-0 outage breaks push and
uncached pulls. Already running containers are not stopped by that. On a cold
node the blog layer took about 13 minutes. While the image downloads, the
Application can be `Synced` but not yet `Healthy`.

## The strict order for a new service

Do one service at a time. Do not copy the CI step while Git lacks the
Application and values.

1. A chart in `charts/<app>`. In the Deployment template a single image: if
   `image.digest` is set, use `repository@digest`, otherwise `repository:tag`.
2. `deploy/<app>/values.yaml` with root `image.repository`, `image.tag`,
   `image.digest`. Before the first release the digest is empty; the tag is an
   image that can already be rolled out. The same keys in
   `charts/<app>/values.yaml` if the file exists. The Application must read
   `deploy/<app>/values.yaml` via `helm.valueFiles`.
3. In the namespace — a pull Secret from the project's Harbor robot, with a
   reference in `imagePullSecrets`.
4. The Application manifest in `deploy/argocd/apps/<app>.yaml`: `project:
   default`, `parameters: []`, `targetRevision: main`, auto-sync, `prune:
   false`, `selfHeal: true`. Commit. `root` will create the Application
   itself. Do not create it manually in the UI.
5. Wait for `Synced`. The first render must match what already runs, or it is
   a deliberate first rollout.
6. In the service's CI, put the `HOMELAB_DEPLOY_KEY` secret with the same
   private key and add the step from the section above. Push the image to
`harbor.socrat.alchemmist.xyz/homelab/<app>`.
7. Check the `socrat-releaser` commit in `homelab`, then `Synced/Healthy` and
   live HTTP. On a cold node health may lag by the pull time.

The action supports one image per application and only the `image.tag` /
`image.digest` keys in those two paths. It will not update several images in
one chart, a different field name, or a different values directory.

## Rollback

A rollback is a new commit to `deploy/<app>/values.yaml` and the paired chart
values: the previous `repository`, `tag` and `digest`. Auto-sync picks it up.
A digest edit in the UI disappears on the next sync.

To return a specific already-pushed digest, take it from a previous
`chore(<app>): deploy ...` commit. Do not delete an image from Harbor while a
Deployment references it: the next pod restart would be unable to download it.

## How to verify a release arrived

1. The service's job is green, with the `Deploy to Socrat` step; there is no
   separate job.
2. In `homelab` there is a `socrat-releaser` commit with this digest.
3. `kubectl -n argocd get application <app>` shows `Synced` on this commit and
   then `Healthy`.
4. The Deployment image equals
   `harbor.socrat.alchemmist.xyz/homelab/<app>@sha256:...`.
5. `spec.source.helm.parameters` is empty.
6. The service's live HTTP responds.

If Git is already new and the cluster old, that is the poll wait, not a reason
to call Sync from CI. A forced refresh from the UI is acceptable when you need
to see the result immediately.

### NetBird: moving an existing service under Argo CD

User onboarding, topology, negative test results and open boundaries:
[the current NetBird runbook](../../network/netbird/README.md).

NetBird is no longer an exception: the Application is created by `root` from
the apps catalog, not a manual apply/UI. Details:
[netbird-argocd.md](../../network/netbird/infrastructure/netbird-argocd.md). The existing
upstream image versions are preserved by digest; the migration updates no
images and does not re-issue identities/secrets. Secret values and PVC
contents are not in Git. For a new node: inventory →
`ansible/scripts/netbird-gitops-nodes.py` → commit the inventory and
values → Argo CD → the usual Ansible machine enrollment/API grants. Ansible
creates no Kubernetes Deployment/PVC and does not compete with selfHeal.

### Release transport recovery — 2026-11-04

`deploy-to-socrat@v1` (56037a9) uses an isolated temporary 0600 deploy key, pinned official GitHub host keys, SSH-over-443, bounded retries and rebases the same commit when concurrent `main` updates cause either non-fast-forward or remote ref-lock rejection. It remains one composite step; no Argo API calls. Static shell tests plus eight image/component unit tests pass.

The GitHub Git Operations incident has cleared. Local SSH authentication and `git ls-remote` work again. End-to-end LMS run **41811725828** succeeded on the final retry: robot commit **76e9902** recorded `sha256:9890519389652cdd8c8436a76f81be6bc81131174a728144ab268c4150a80167`; live Deployment uses that GHCR digest and its rollout completed. Earlier failed attempts are not successful releases. LMS remains on GHCR intentionally during HA ownership work.


## Public entrances belong to the applications — 2026-11-07

**The separate Argo Application `public-web-entry` was removed from Git and
the cluster.** `charts/public-web-entry` was removed too. Do not restore that
aggregate layer when setting up a new service: the Ingress and the specific
protective proxy/config must belong to the same Application as the service.

| Argo Application | Public entrance / policy | Source |
| --- | --- | --- |
| `grafana` | Grafana, policy proxy and TV JS | `charts/grafana` + `deploy/platform/grafana/public-entry` |
| `rancher` | Rancher, policy proxy | `deploy/platform/rancher/public-entry` |
| `litellm` | `litellm.socrat…` alias | `deploy/platform/litellm/public-entry` |
| `searxng` | Search | `charts/searxng`, `publicEntry` |
| `open-webui` | `llm.socrat…` alias | `charts/open-webui`, `publicEntry` |
| `grafana-mcp` | bearer-only `/mcp` | `charts/grafana-mcp`, `publicEntry` |
| `syncthing` | both GUI entrances, policy proxy | `charts/syncthing`, `publicEntry` |
| `uptime-kuma` | admin entrance, policy proxy | `charts/uptime-kuma`, `publicEntry` |

For third-party Helm charts, `deploy/platform/<app>/public-entry` was added as
another `spec.sources` entry of the **existing** Application; these are not
new Applications. The main upstream chart/version/values are preserved. For
local charts the public templates are included directly in the chart. Traefik,
cert-manager and Authentik are shared platform components; the admission
allowlist/groups are still managed by the identity tooling
(`deploy/public-web/services.json`), not duplicated in the charts.

### The ownership transfer and verified boundaries

1. The old Application was first disconnected from auto-sync and its deletion
   finalizer removed **via Git**, so root would not start a cascade deletion.
2. All 22 resources were transferred to eight owners; the offline render
   before/after matched completely. The live tracking annotation on each
   resource points to the new owner.
3. The UIDs of all 22 resources and the 18 Certificate/TLS Secret objects are
   preserved. The 186 existing verified pods kept their UIDs/readiness/restart
   counts.
4. Then the old Application and the shared chart were deleted. The children
   kept `prune: false`, `selfHeal: true`; after the deletion root returned to
   `Synced / Healthy`.

The `public-web-` prefix in resource **names** is kept deliberately: it does
not imply the old Application's existence. The `identity` namespace of
Authentik-gated Ingresses also does not imply ownership by Authentik/the shared
public app. Look at the Argo tracking and the relevant Application's source;
do not rename/recreate TLS or Ingress for cosmetics alone.

A LiteLLM full sync attempted to run an existing DB migration hook. The Job
 stayed Pending due to the 512Mi request on socrat-0, before the container
 started. For the duration of the handoff its auto-sync was paused in Git, the
 operation stopped, Argo removed the pending Job; a separate resource-only sync
 transferred only the alias Ingress without hooks. The usual
 `prune: false / selfHeal: true` auto-sync has been restored; there are no
 active operations/Jobs at closing. The DB/identities were not migrated, the
 scheduling hook unchanged; its capacity at a future real release is a separate
 check.

The ownership table above accounts for the subsequent monitoring split
`8862770`. The initial transfer of 22 resources into eight apps was a separate
completed acceptance; it does not prove the final cleanup of the new
monitoring owners.
[The current map and read-only status](../../observability/monitoring/observability-current.md).

Migration acceptance: **134/134** public TLS/anonymous/forged-header/invalid-
token checks before and after, **88 profile tests**. Five old
`test_syncthing_scheduling.py` failures were reproduced on the original
`c612d71` (a DaemonSet expectation against the current Deployment); the full
repository suite was not declared green. New browser MFA/enrollment was not
verified by this ownership transfer.

Commits: disarm `41e10a2`, transfer `7ae691a`, temporary LiteLLM pause
`4e2c72e`, final deletion/auto-sync restore **`e7fe891`**. Details:
[operations migration](../../applications/public-web/public-web-migration.md),
[access and authorization](../../network/README.md). Do not restore the old
aggregate chart when rolling back one application; change only the source of
its current owner.


## Monitoring split into self-contained services — 2026-11-07

- `prometheus-stack`: Prometheus, Alertmanager, the operator, exporters and
  the shared recording/alert rules. The upstream chart remains
  `kube-prometheus-stack` 92.10.0, but Grafana inside it is **disabled**. The
  Helm releaseName stays `kube-prometheus-stack`, so the names, selectors,
  PVCs and addresses do not change.
- `grafana`: the local wrapper `charts/grafana`, the vendored upstream
  dependency Grafana chart **14.0.0** from the former stack (not a version
  update), the existing PVC/admin/OIDC Secrets, datasource provisioning and
  the public policy proxy. Native SSO, role/groups, refresh/session durations
  and anonymous=false are now declared in Git instead of depending on old
  live patches.
- `loki`, `tempo`: independent charts and their own ConfigMaps, the former
  runtime images, Service names, hostPath and mTLS. The shared leaf
  Certificate `otel-tls-backends` belongs to `monitoring-k3s` as shared PKI;
  the Secret/SANs were not re-issued for the split's sake. Loki retention
  rules live with Loki.
- `pyroscope`: the former Application `profiling`; data/Deployment/PVC
  preserved.
- `grafana-mcp`, `thanos`: already independent Applications and they stayed
  that way. `monitoring-k3s` / `monitoring-llm` are separate cluster/domain
  instrumentation; the existing collectors were not reinstalled or
  reconfigured by this split.

The old Applications `kube-prometheus-stack`, `otel-backends`, `profiling` and
the unused aggregate charts/paths were removed after disarm and verifying the
new ownership. The old names `kube-prometheus-stack-grafana`, `otel-loki`,
`otel-tempo`, release labels and `app.kubernetes.io/part-of: otel-backends`
are compatibility identities, not proof that the old Application exists. Do
not `helm uninstall` the old release and do not rename live PVCs for
aesthetics.

Before the Grafana rollout an agreed SQLite backup was made (private 0600,
outside Git). After the rollout the preservation of users/organizations/roles,
datasource identities, dashboard UIDs, native OAuth links and public sharing
was compared; DB contents and tokens were not printed. Grafana/Loki/Tempo
were restarted in a controlled way; versions and data directories did not
change. TLS/anonymous regression 134/134; the native OIDC redirect, verified
mTLS readiness, rejection without a client certificate, fresh Loki logs and
access to preserved Tempo traces are verified separately from the Argo state.
This is not a new browser-MFA/enrollment, backup/restore/HA, or
every-service telemetry acceptance.

The exact owners, safe handoff and check boundaries:
[monitoring-service-split.md](../../observability/monitoring/monitoring-service-split.md).
At that intermediate stage the guard refused when independent owners existed;
after the final split `monitoring.yml` / `monitoring_stack` is retired
**unconditionally**, before any mutations, including a run on a fresh
cluster. Edit the current Git sources, not the old
`deploy/monitoring/values.yaml` and not UI image/Helm overrides.


## The last Prometheus aggregate is also removed — 2026-11-07

The previous section describes an intermediate stage. **The Application
`prometheus-stack` was removed**; do not reunite Prometheus and Alertmanager
on the upstream chart boundary again. The current owners/sources:

| Application | Source | Composition |
| --- | --- | --- |
| `prometheus` | `charts/prometheus` | Prometheus, its configuration/storage, the shared recording/alert rules and cluster monitors |
| `alertmanager` | `charts/alertmanager` | Alertmanager, routing/config, its own SA/Service/monitor/rules |
| `prometheus-operator` | `charts/prometheus-operator` | The operator, the 10 shared CRDs, admission webhooks, its own rules |
| `node-exporter` | `charts/node-exporter` | The DaemonSet and its Service/monitor/rules |
| `kube-state-metrics` | `charts/kube-state-metrics` | K8s state export and the supporting RBAC/Service/monitor/rules |

All 77 resources have exactly one owner; the payload before/after matches
completely. The CRDs remain shared definitions without forced application
tracking; the new scope is the operator. The 8 existing runtime Pods were not
recreated and did not change node or restart counters. The 4 PVCs/bound
volumes and the UIDs/contents of the 3 target Secrets are preserved.
Prometheus keeps finding the same Alertmanager at the former Service.

The upstream kube-prometheus-stack92.10.0 is reused **only as a pinned source
of templates**: one verified immutable archive in `charts/_vendor`, each local
chart includes only its component. That is not an aggregate Application and
not shared mutable values. Each service has its own chart/values and its own
sync. The kube-prometheus-stack releaseName/resource names/labels are kept for
compatibility; do not rename PVCs/Services and do not `helm uninstall` the old
release.

The archive's SHA256, symlinks and the full disjoint/render-equivalence checks
live in the tests. Argo renders everything from Git offline, without
dependency downloads. The aggregate Ansible installer is finally retired: an
always-tag fail before any mutation, even on a fresh cluster.
Prerequisites/Secrets are restored separately per the runbook; do not bypass
the guard to bring back the old stack.

At the handoff: first disarm/no finalizers, then adopt, live checks, then the
deletion of the old Application/values. No global prune, no restart/WAL
repair/DB migration, no TLS or alert-credential rotation were performed.
Checks/boundaries and the ownership diagram:
[prometheus-service-split.md](../../observability/monitoring/prometheus-service-split.md).


The closing commits of the final split: `652e286` (disarm), `78a9336`
(adopt), `bcc93ca` (aggregate deletion), **`0bb4e31`** (final verification/
rollback safeguards). 104 tests + 24 subtests and 134/134 public checks
passed; at closing 49 Applications were Synced/Healthy, but the old WAL alert
was neither masked nor fixed. Detailed summary/boundaries:
[observability-current.md](../../observability/monitoring/observability-current.md#a-recorded-closeout-not-a-new-migration-command).

**Do not roll back an ownership transfer by simply deleting the new
Applications with active finalizers.** That can cascade-delete the already
transferred workloads. A reverse transfer needs the same disarm/handoff;
ordinary version changes roll back via the current owning chart. Private
audit receipts are not a verified DR.


## SPI full-service extraction — 9 November 2026

The application repo is now `alchemmist/spi-triage`, containing the actual backend,
English frontend, broker and one shared release image. Former `spi-queue-ui` is
the same renamed GitHub repository, not a separate active web publisher.
Existing Application `spi-triage` reads `deploy/spi-triage/values.yaml`; image fields
are root `image.repository/tag/digest` in it and `charts/spi-triage/values.yaml`.
CI uses the standard **same publish job** and deploy-to-socrat with `app: spi-triage`.
The empty frontend-only Argo/chart/deploy definitions were removed from Git.

This is a **stateful singleton**, not the blog's stateless release acceptance.
Protected environment `spi-triage-production` requires owner approval following
an actual bounded native SPI-only natural drain (including logical Wait owners,
paid/inflight/processing and n8n pending readback); never force idle or kill work.
Approval is not a drain proof. Owner explicitly waived the backup prerequisite
for this extraction; do not reconstruct it from earlier dated runbooks.

Current gate `bundleEnabled=false` keeps the legacy image/ConfigMap-backed runtime
and preserves all20SPI resource specs under the compatibility render proof.
`PUBLISH_ENABLED=false`; CI42585299451 built/tested the complete image but skipped
publishing. Activation, two namespace pull Secrets and live/browser proof remain
pending approved private cluster/Harbor reachability. On activation all three roles
use the same image digest with no ConfigMap shadowing. Do not manually seed image
versions, start a second backend/PVC, restore budgets or call the migration done.
See [authoritative SPI checkpoint](../../applications/spi/spi-incident-triage.md#current-source-extraction--9-november-2026).

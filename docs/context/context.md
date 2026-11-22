# Socrat: current operating context

[Unexpected loss of `socrat-1`, 21 November 2026](socrat-1-loss-20261121.md): do not extrapolate the results to the loss of `socrat-0` (NFS) or two nodes. The [second outage that day](socrat-1-loss-20261121-run2.md) tested a separate Alertmanager on node `0` without changing the PostgreSQL primary.

This guide reflects the migrations accepted on 16 November 2026. Git describes intent; each handoff records when the running system was last verified. This file does not authorize new production operations. Dated results are not continuous monitoring.

## Sources of truth

- Applications: `deploy/argocd/apps/`. Follow each Application to its values file.
- Ansible inventory: `ansible/inventory/hosts.yml`. Mesh registry: `wg_socrat_nodes` in `ansible/inventory/group_vars/Socrat/cluster.yml`.
- Shared issuer transport and its consumers: `deploy/contracts/infrastructure.json`. `ci/check_infrastructure_contracts.py` checks it offline by default; `--write` updates repository files only.
- Argo CD: `deploy/platform/argo-cd/values.yaml` is canonical; `deploy/argocd/values.yaml` is a compatibility symlink. Use `ansible/playbooks/argocd.yml` only for an explicitly authorized installation in an empty environment. The Git Application manages the existing release.
- See the [topic index](../README.md) for runbooks. The [archived chronology](context-history-20261116.md) is not a reference for current placement.

## Verified placement and data ownership

- `socrat-5` hosts the Argo application-controller and Rancher. Both are single replicas, not HA. The [management handoff](../vm105-management-20261116.md) verifies native SSO, UIDs, specs, users and roles and records an intervening sign-in incident.
- PostgreSQL: seven production databases in `pg-common` and `pg-critical`. Consult CNPG for current primary placement, not an old handoff. See the [runbook, CA and retained source volumes](../postgres-platform.md).
- [Redis Insight](../redisinsight.md) is a shared dashboard. Sign in through `redisinsight-readers` or `homelab-owner`; membership does not grant direct Redis access.
- LiteLLM uses [shared Redis over TLS](../redis-common.md) for coordination, not response caching. Its primary database remains in `pg-common`. Global limits are not guaranteed if Redis is lost.
- `socrat-0` hosts Argo CD components, RustFS and vLLM/GPU. Umami and LiteLLM use `pg-common-rw`, not standalone local PostgreSQL.
- Grafana and Grafana MCP passed acceptance after their cold move to `socrat-5`. The [Grafana handoff](../vm105-grafana-20261116.md) verifies image digests, identity and ACLs, native SSO and a real MCP → Grafana → Thanos request. Grafana uses the `grafana-socrat5` claim; the old claim on `socrat-1` is stale.
- `socrat-1` hosts the SPI GitHub broker. Check the respective Applications for other components.
- `socrat-5` hosts n8n, PR Agent, WebUI, Terminal, SearXNG, the Umami application, LMS, the LiteLLM application, the renderer, Monori frontend, blog/wiki workers and SPI queue UI. Blog and Home have distributed replicas; keep anti-affinity in place.
- Stateful workloads on `socrat-5`: Wishlist, Wiki runtime, Monori backend and sync, SPI worker, format-quorum and LiteLLM branding. See the [authoritative handoff](../vm105-stateful-20261116.md). New writes on `socrat-5` are authoritative. Old claims are stale recovery sources, not current copies. Rolling back after new writes requires a fresh reverse handoff.
- GitOps no longer declares SWE Mini for Monori. [Retirement scope and verification](../swe-mini.md): absence from Git does not prove removal from the cluster.
- [DeeperSeeker](../deeperseeker.md) runs on `socrat-5` in namespace `deeperseeker`. LiteLLM routes `o-deepseek` here. Sign-in uses Chrome at home; the token is in the dashboard. VPN identity: `svc-free-deepseek`.
- [OpenHands Canvas](../openhands.md) on `socrat-5` uses the upstream UI and Agent Server. A browser test verified shell results after closing the tab, and the native Stop-hook fixture passed. The full long-running PR loop has not passed acceptance. Owner-only oauth2-proxy/Authentik OIDC ingress is deployed. Targeted DNS was fixed; trusted TLS and SSO denial were verified from HOME and VPS. The owner's browser/MFA round trip remains unverified. No GitHub publisher is connected. PR #500 was closed externally as superseded, not marked Ready.
- Wiki: `deploy/wiki-runtime/values.yaml`, claim `wiki-runtime-socrat5`, path `/mnt/files/homelab/wiki-runtime/data`. The runtime volume is authoritative; Git sync may lag. Do not edit the managed tree concurrently with the writer.

## Safety constraints and outstanding risks

- Preserve accounts, roles, passwords, keys, sessions, history and native SSO/TLS/PKCE. Signing in on someone's behalf is not user acceptance. Do not bypass MFA.
- Use Git first and reconcile only the target. No blanket sync or prune, forced deletion, live image overrides, arbitrary schema upgrades or network restarts.
- Do not replay workflows, publish, run paid inference or sync bank data for a test. Keep secrets and private receipts outside Git; use mode `0700` for directories and `0600` for files. Do not print payloads.
- Leave VPN workloads on `socrat-2` alone. Do not change Mac VPN, DNS or routes, AllowedIPs, WireGuard identities, operator keys or permanent sudo access for convenience.
- The `socrat-0` relay between `socrat-1` and `socrat-5` is a non-HA mitigation. The underlying cause has not been established. Healthy applications do not prove VM recovery or HA.
- Historical Prometheus corruption is a separate issue. Do not clear the WAL. A VM cold boot and full independent restore require separate maintenance acceptance.
- Backups: the daily n8n job uses the current claim. The latest paired archive on `socrat-3` passed SHA verification; its SQLite database was independently restored and passed a read-only integrity check. One unpaired archive was not accepted. See the [coverage matrix](../backup-coverage-20261116.md) for datasets still outstanding. A retention policy is not a backup.
- Preserve the historical Wishlist OutOfSync state, SPI failure and limits on human callbacks and the production telemetry child. Do not mark them resolved without a test.

## Work in progress

The owner authorized sequential remediation of the [refactoring audit](../refactoring-audit-20261116.md) and a separate Grafana/Grafana MCP move to `socrat-5`. Implementation and acceptance evidence, not inclusion here, determine whether an item is complete.

The first published changes added the canonical Argo bootstrap guard, shared issuer contract and generator, mesh and fixed-relay drift checks without network restarts, separation of current state from history, and offline CI. Two earlier CI defects were fixed: stale SPI expected codes (Publish-only `STORAGE_TRANSIENT` was retained; the workflow did not change) and stale alert graphs. The append-only panel ID ledger preserves historical links. See [ownership and maintenance](../infrastructure-contracts.md). Recurring backups for other datasets, full wiki publication reconciliation and disaster recovery are not complete.

See the [implementation checkpoint](../infra-refactor-progress-20261116.md) for outstanding work. HTTP 200 confirmed that the public wiki still served stale text. The [proposed correction](../wiki-public-refactor-proposal-20261116.md) requires the normal native connection with write scope, unavailable during that session.

The owner deferred backups. The legacy Rancher installer now refuses to run. CI verifies that no plays or imports follow the refusal and that Argo bootstrap versions and values match the Git Application.

Subsequent repository-only changes inventoried three vendored trees against a Git baseline (not proof of upstream trust), retired the legacy LiteLLM installer and unified CLI and Ansible placement checks: both require the current ReplicaSet revision and ready Pods. Read-only checks of Rancher, Grafana and MCP on `socrat-5` passed; backups remained deferred.

The legacy `llm-vision.yml` and combined `monitoring-llm.yml` now refuse before GPU, Helm or identity actions. The gateway monitoring helper checks existing owners, credentials and ACLs read-only; it has no install or repair fallback. No backup, inference or production maintenance was performed.

Relay preflight now uses the mesh registry. CI compares the unit's /32 allowlist and sandbox against the canonical endpoints without changing or restarting the unit. An offline checker verifies Argo local sources, values and refs, selected current-document links and claims, and default RBAC. Historical receipts are excluded.

Operational continuation: Open Terminal/SearXNG/search bootstrap installers retired
before keys/Helm/imports. CI classifies literal Ansible Helm entrypoints without
certifying remaining review-required or VPN/GPU/backup-excluded paths. Vendor
baseline expanded to existing monitoring bundle and five dependency symlinks;
no chart/version/runtime changes or production/backup operations.

WebUI lifecycle/HTTPS/tool-guard and Terminal browser-cleanup entrypoints now
refuse before all remote tasks/imports; chart-owned protection remains unchanged.
Old-PVC backup/upgrade instructions are not a fallback. Within the literal Helm
gate only k3s/storage-nfs remain review-required; no maintenance was performed.

2026-11-16 LLM key activity short-range No data fixed (50de2fac): Requests by API
key used increase(counter[$__interval]); small pickers/pixel step made lookback5s,
insufficient counter samples. Live reproduction:5s empty,15s/1m populated. Replaced
ONLY panel1 lookback with fixed[1m], described rolling/extrapolated requests/minute,
not nonoverlapping buckets (do not sum adjacentpoints).30daytable unchanged; owner
live panels matchedGit before edit. Range queries5m/30m/1h/3h populated afterfix;
ArgoSyncedHealthy, GrafanaAPI serves exactfixedpanels. Regression test
 tests/test_llm_keys_window.py; no backend/collector mutation or missing→0 fallback.

17Nov owner architecture correction: `wg-socrat` is VPN-as-infrastructure only.
Application foreign egress must use a distinct native3x-ui service client and
its subscription with an official Pod VPN client, NOT a new SSH-to-NL tunnel.
[Reusable service-VPN runbook](../service-vpn-egress.md). N8N corrected in5b722c5c;
[finite acceptance and cleanup](../n8n/service-vpn-20261117.md). Venice's
pre-existing SSH-egress remains a separately recorded deviation, not a template.

Quality CI/refactoring integration scope: see [current quality runbook](../quality/README.md). Strict findings remain blocking in CI; operator permits a separate red-CI integration decision, not suppressions or source-green claims. No production operation is authorized by this scope.


## Storage runtime update —20 November 2026

Containerd on socrat-5 now runs from HDD `/mnt/files/homelab/runtime/containerd`
bound at its original `/var/lib/rancher/k3s/agent/containerd` path. OS/K3s server
state remain SSD; existing application claim identities unchanged. The55GiB stale
runtime preimage was removed after acceptance; SSD now has about78GiB available.
Two OpenHands archive claims also moved to HDD through original-path binds.
Day-2 owner: `ansible/playbooks/socrat-5-runtime-storage.yml`.

Dynamic `local-hdd`/`local-ssd` and HDD-first new node5 local-path provisioning are
accepted; `storage-tiers` is the sole Git owner. Only `nfs-shared` is cluster
default. Filesystem monitoring is live. Rancher observer API policy fixed and
Application Healthy. See [followup closeout](../storage-followup-20261120.md)
and [historical runtime receipt](../socrat5-runtime-hdd-complete-20261120.md).
Physical hypervisor capacity remains unverified. DeepSeek is an external
invalid-session blocker; respect its no-login/no-restart runbook window until
21 November2026 23:48 MSK. Do not extend the existing alert silence.

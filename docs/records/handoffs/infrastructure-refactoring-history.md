# Implementation history

The owner authorized sequential remediation of the [refactoring audit](refactoring-audit-20261116.md) and a separate Grafana/Grafana MCP move to `socrat-5`. Implementation and acceptance evidence, not inclusion here, determine whether an item is complete.

The first published changes added the canonical Argo bootstrap guard, shared issuer contract and generator, mesh and fixed-relay drift checks without network restarts, separation of current state from history, and offline CI. Two earlier CI defects were fixed: stale SPI expected codes (Publish-only `STORAGE_TRANSIENT` was retained; the workflow did not change) and stale alert graphs. The append-only panel ID ledger preserves historical links. See [ownership and maintenance](../../platform/infrastructure-contracts.md). Recurring backups for other datasets, full wiki publication reconciliation and disaster recovery are not complete.

See the [implementation checkpoint](infra-refactor-progress-20261116.md) for outstanding work. HTTP 200 confirmed that the public wiki still served stale text. The [proposed correction](../../research/wiki-public-refactor-proposal-20261116.md) requires the normal native connection with write scope, unavailable during that session.

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
[Reusable service-VPN runbook](../../network/service-vpn-egress.md). N8N corrected in5b722c5c;
[finite acceptance and cleanup](../../n8n/service-vpn-20261117.md). Venice's
pre-existing SSH-egress remains a separately recorded deviation, not a template.

Quality CI/refactoring integration scope: see [current quality runbook](../../quality/README.md). Strict findings remain blocking in CI; operator permits a separate red-CI integration decision, not suppressions or source-green claims. No production operation is authorized by this scope.


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
Application Healthy. See [followup closeout](storage-followup-20261120.md)
and [historical runtime receipt](socrat5-runtime-hdd-complete-20261120.md).
Physical hypervisor capacity remains unverified. DeepSeek is an external
invalid-session blocker; respect its no-login/no-restart runbook window until
21 November2026 23:48 MSK. Do not extend the existing alert silence.

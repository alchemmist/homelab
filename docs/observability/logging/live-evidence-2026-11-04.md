# Live logging metadata evidence — 2026-11-04

Acceptance: **NOT all covered; rollout remains blocked.** Local evidence only, no push or production configuration changes. Companion JSON records observation Unix time, exact source identities, counts and classifications. `unknown-sources-2026-11-04.tsv` is the exact nonverified container/host source list, not a proven missing-log list. No source can responsibly be declared missing rather than silent without independent emission expectations.

## Method and results

Live API inventory was reconciled with four successful bounded instant count queries (600s and 3600s, namespace and host selectors) using the existing coverage verifier's query, validator and assessment. Queries extract pod/container/unit structured metadata before aggregation; no log bodies, range streams, secret values or raw application output were requested or saved. Response cap 8 MiB, request timeout 20s. Credentials stayed inside a diagnostic curl pod mounting existing `otel-tls-grafana`; only secret key names ca.crt/tls.crt/tls.key were inspected. Service DNS TLS verification was enabled.

The explicitly authorized `logging-metadata-diagnostic-20261104` pod was created twice and deleted after each observation. Delete wait reported a timeout but a subsequent get with `--ignore-not-found` confirmed absence. No existing workload was changed. The pod had no service-account token and a 600s active deadline.

Inventory: 283 container definitions, 127 controllers, 1,138 installed/loaded system service identities across socrat-0 through socrat-3. Host union was freshly collected over SSH using systemctl list-unit-files and list-units; inactive/template units are included deliberately. User/session services and application file-only logs are not exhaustively inventoried. Controller existence does not verify its delivery.

Assessment: **0 canonical verified, 91 fresh emitting container/host sources, 1,330 unknown, 127 controller-existence rows**. Live legacy metadata proves some delivery, not deployment of the new severity contract. Both JSON and TSV retain hour-observed distinctions. Fresh records include all four hosts; that does not prove every host service is collected. There are no independently attested silent sources. Exact controllers are in the JSON; ownership reconciliation of controllers to pods remains a manual gate.

The two selectors overlap. Do not sum the raw metadata arrays as an ingestion rate. After deduplicating identical label sets with maximum count: 103 fresh groups / 37,374 records in 600s (**62.29 records/s**), and 141 groups / 218,802 records in 3600s (**60.78 records/s**). These are observed matching counts, not loss measurements or guaranteed complete ingestion rates; moving query evaluation times add uncertainty.

## Backend readiness and storage blockers

Existing `otel-loki` service is port 3100, native mTLS and reachable using service DNS. Running pod is on socrat-1; data hostPath is `/var/lib/private/homelab-otel-loki`, mounted at `/var/lib/otel`. Native metrics showed distributor cumulative received bytes 4,113,033,811, lines 7,273,632, stored chunks 2,444; compactor running=1. Live incoming stream retention was 336 hours, so repository severity rules are **not attested deployed**. Cumulative received bytes are neither compressed disk usage nor daily disk growth.

Read-only host df: filesystem 387,034,356 KiB total, 142,667,220 used, 224,633,632 available (39% used). This is shared host filesystem capacity, **not Loki allocation**. Actual Loki directory usage and growth remain **unknown**: unprivileged host du denied; sudo noninteractive unavailable; Loki image has no sh executable for bounded read-only du. No privilege escalation or extra host mount was attempted. Need owner-assisted two timestamped `du -sk` readings of only the Loki directory plus chunks/index/WAL split, representative bytes/rate sampling, and retention enforcement evidence. Disk headroom cannot be certified from df alone.

## Ownership and approved-deployment commands (NOT executed)

Repository owners: agent collection `deploy/monitoring/otel/agent.yaml` with `ansible/playbooks/otel-production-agents.yml`; backend Loki and cluster collector `deploy/monitoring/otel/{loki,cluster}.yaml` with `ansible/playbooks/otel-production-backends.yml`; Grafana provisioned dashboard chart `charts/monitoring-k3s`, operated by monitoring_k3s. Human on-call/approval owner remains unassigned and must accept storage/privacy/retention gates. Existing application DB, metrics and Thanos ownership/storage stay independent and must not be changed.

From ansible/, after explicit approval and review of check/diff output:

```sh
ansible-playbook -i inventory/hosts.yml playbooks/otel-production-backends.yml --check --diff --ask-become-pass
ansible-playbook -i inventory/hosts.yml playbooks/otel-production-agents.yml --check --diff --ask-become-pass
# Only after owner approves the exact diff, execute those same commands without --check --diff.
```

These playbooks may manage signals beyond logs: review full rendered diff and stop if metrics/Thanos/app DB changes appear; these are not authorization to execute a broad rollout. Dashboard should use its existing reviewed GitOps/chart release, not a new Helm release. No push/sync/apply was performed.

Remaining gates: exact unknown-source triage with emission expectations; explicit exclusion resolution; canonical service/severity live verification; independently measured loss/duplication; restart and rotation checks on approved disposable canaries; actual Loki disk/growth and retention enforcement; Grafana UI verification; human ownership and scoped rollout approval. Original broader inventory lives outside the repository; this durable report includes fresh identities instead of relying on that external file.

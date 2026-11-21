# Socrat PostgreSQL operations — 2026-11-20 cutover

All application writes use the cluster `-rw.postgres.svc.cluster.local` endpoint with verified TLS, never a pod or a fixed node. `pg-common` owns `umami`, `certification`, `lms`, `socrat`, `litellm`, `registry`, `n8n`, `grafana`; `pg-critical` owns `authentik`. Common normally starts on socrat-0 NVMe with an asynchronous socrat-5 HDD copy. Critical uses ANY 1 of two standbys across 0/1/5. Ask CNPG for `.status.currentPrimary` before any primary-only operation. LMS HA is hibernated, not a production source; its old dump schedule is suspended. Neither cluster has a recurring independent backup or PITR.

Acceptance receipts: Umami 27 table counts; Certification 3 table digests and advancing workflow heartbeats; LMS 11 table digests; Socrat Bot 17 table digests and sequence values (final transfer Job timed out after restore; contents independently compared); LiteLLM 91 table counts and sequences; Authentik 230 table counts and sequences, worker/server TLS and OIDC discovery (first rehearsal failed, retry succeeded); Harbor 49 table digests, sequences and separate robot push/pull. Application ACL audit: each of the seven runtime roles has CONNECT only on its own *application* database, excluding built-in/maintenance databases. This is not CPU, I/O or superuser isolation.

Browser acceptance: use a private window, open LMS, log in using your own MFA and verify a protected page. Discovery, HTTP redirects and existing sessions do not prove a new login. Do not share credentials or MFA codes.

## CA rotation

Inventory deployed volume refs before rotating. Sources are `postgres/pg-common-ca` and `postgres/pg-critical-ca`. Distribute ONLY the public `ca.crt` to the actual client ConfigMap/Secret: Umami and n8n/Certification use `pg-common-ca` ConfigMaps, Harbor uses the same ConfigMap name; LMS uses secret `lms-pg-common-ca`, Socrat Bot and LiteLLM use secret `pg-common-ca`; Authentik uses secret `pg-critical-ca`. Preserve their namespaces and object types; never propagate `ca.key`. Prefer staged overlap: trust old+new PEM first, restart/reload clients as required (Node reads NODE_EXTRA_CA_CERTS on startup; drain n8n), then rotate the server chain using the CNPG procedure for the installed version. Verify new connections by service DNS with strict hostname validation and wrong-CA rejection, app readiness and worker writes. Remove the old CA only after every client and standby has reconnected. Do not restart every consumer together or disable verification.

## Retention

Never prune all retained volumes. Keep source PVCs and Umami `/srv/umami/postgres` on socrat-0 for at least 14 full days after the corresponding cutover. For this batch do not review for disposal before **2026-12-05 UTC**. No automatic deletion. Compare the recorded PVC UID, PV name, mount/host, live consumers and Git references first. Decide explicitly whether a separate restorable copy is needed; no ongoing PITR. Deleting a retained source is not rollback; restoring the old DSN would discard subsequent writes. Do not delete working CA/DSN/robot/OIDC secrets, registry blobs or backup archives.

## Monitoring after cutover

LiteLLM and Umami keep separate TCP probe identities but both check `pg-common-rw:5432`; neither probe authenticates to its database. The active OTel scrape bundle (not just the ServiceMonitor) must use the new endpoint. The production LMS web rule stays enabled. Its experimental `lms-ha` readiness and dump rules apply only when that experiment is active. The production replication rules check the current primary of each tier. The former LMS dump tile now shows the common primary’s streaming standby count (expected 1; missing telemetry is unknown). Neither this count nor retained LMS dumps certify a backup.
## Live checks and troubleshooting

`kubectl get clusters.postgresql.cnpg.io -n postgres` reports instances and primary. Check `pg_stat_replication` on that primary; `pg-common` normally has one streaming async peer and `pg-critical` two streaming candidates in quorum mode. Cluster-local ingress policies in `charts/postgres-platform` allow same-cluster CNPG traffic, operator management, native metrics scraping and designated client workloads. The bot is hostNetwork: host-source exceptions are not per-process authorization. TLS and per-database grants remain necessary. Test new clients with a fresh connection, since an existing pool is not proof that a policy permits new connections.

The native otel-cluster Prometheus receiver scrapes primary-only services; `up{job="postgres-platform"}` must report two live targets. Six `socrat-postgres-platform` rules cover missing data, replica availability, delay/retained WAL, required sync observations and host root disks (0/1). Existing socrat-storage rules cover root and the HDD on node 5. Confirm rule health in Prometheus, not only a green Argo application. These are availability signals, not proof of backup integrity or a tested page to the operator.

Retention follow-up: [issue #216](https://github.com/alchemmist/homelab/issues/216). Hold is intentional; the issue is a review, not a deletion timer.

`pg-critical-async` is a single-instance CNPG replica cluster pinned to socrat-3. It follows `pg-critical-rw` over verified TLS, outside the two local quorum candidates. Expect three streaming peers on the source primary. The extra peer is neither a synchronous acknowledgement nor an independent backup.

## n8n cutover receipt — 2026-11-21

Production commit `efe90e16` switches n8n to `pg-common/n8n`. With the source stopped, verification matched 12 workflows, 15 encrypted credentials and 10,189 execution/history rows in each of `execution_entity` and `execution_data`. Workflow and encrypted credential content matched. Five ID sequences were advanced before startup. Import required `SET ON PARAMETER session_replication_role`; the temporary import role and Secret were removed. Do not grant that permission to the runtime role.

Acceptance: 7 active workflows, runtime connections over TLS 1.3, new executions in PostgreSQL, readiness HTTP 200 and Argo Synced/Healthy. The PVC remains mounted for non-database files. Its SQLite file is stale after cutover: do not revert the Helm switch as a rollback without reconciling subsequent writes. The SQLite-specific CronJob is suspended.

## Grafana cutover — 2026-11-21

`9d62ca67` selects `pg-common/grafana` via verify-full; `06470aec` narrows the network grant to the Grafana workload in the monitoring namespace. A cold-source SQLite transfer preserved all 87 application table counts (15,793 rows), using PostgreSQL-native schema/migration history and reseeding sequences. Production readback after provisioning: 59 dashboards, 8 folders, 859 permissions, 7 rules and 5 datasources. Resource, permissions, dashboard ACL and alert-rule digests matched; datasource provisioning rewrote ciphertext. Real Thanos and Loki reads via Grafana Viewer passed, runtime PG sessions used TLS 1.3, and the public health endpoint reported `database: ok`. No synthetic notification or interactive SSO login was used.

Keep `grafana-socrat5` for plugins/files; its SQLite file is stale, not a rollback for new writes. The startup guard now checks for imported PG data. For future maintenance, note that the identity-namespace public Grafana proxy is in an earlier Argo wave and its readiness depends on Grafana. When resuming from zero this can block the backend rollout; reconcile the exact committed backend Deployment before waiting on proxy readiness.

## Open WebUI cutover — 2026-11-21

`1cf4d2ed` starts Open WebUI on `pg-common/open_webui` after a cold SQLite transfer. PostgreSQL-native Alembic schema at `0bd252b206fb`; all 48 tables / 802 retained rows matched before startup. Only approved FK orphans excluded: 4 OAuth sessions without users and 14 file links without chats. Production readback: 6 users, 24 chats, 129 chat messages, 117 file links, 4 notes and 131/131 referenced files on `open-webui-socrat5`. Runtime PostgreSQL sessions from the app pod used TLS 1.3 with verify-full configured. `/health/db` and `/api/config` returned 200; anonymous chat access returned 401. No interactive user login or model generation was performed. Keep the PVC for uploads; its SQLite file is stale after cutover. Do not roll back onto that file without reconciling newer writes.

## Wishlist cutover — 2026-11-21

App `da985ad` and GitOps `4af380e3` run Wishlist on `pg-common/wishlist`, verify-full TLS, with the SQLite PVC retained but no longer authoritative. After quiescence, the importer checked integrity and every retained field across all 100 rows / six tables, added Unicode lookup keys, and reset identity sequences. Production public wishlist API returned 19 items and 69 photo references; inventory metrics read the new backend successfully. Synthetic competing reservations on a separate PostgreSQL test returned 200/409. Do not revert to stale SQLite after new writes.

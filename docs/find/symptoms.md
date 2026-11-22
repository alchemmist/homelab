# Find the next check by symptom

| Observation | Narrowest useful reference |
| --- | --- |
| pgAdmin opens a server but one database returns `permission denied for database` | [Check CONNECT on that database](../data/postgresql/pgadmin.md#access-as-of-22-november-2026), not the user's SSO membership. |
| `SocratRedisCommonWriterUnavailable` or `SocratRedisCommonRedundancyReduced` | [Verify coordination](../data/redis/redis-common.md#verifying-coordination). Writer failure and reduced redundancy are different conditions. |
| Redis Insight redirects but a reader cannot open the dashboard | [Check both group bindings and the gateway claim](../data/redis/redisinsight.md#access-checks-and-acceptance-limits). |
| The current PostgreSQL primary is not on its expected node | [Check the CNPG primary and durability contract](../data/postgresql/postgresql.md); use the [node-loss record](../records/incidents/socrat-1-loss-20261121.md) only for past failover evidence. |
| Authentik login succeeds but the application still denies access | [Identity gateway troubleshooting](../identity/identity-gateway-troubleshooting.md). |
| Grafana shows gaps in recent Thanos metrics | [Recent metrics diagnostics](../monitoring/observability-current.md#пропуски-свежих-метрик-в-thanos--19-ноября-2026). |

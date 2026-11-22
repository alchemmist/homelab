# redis-common: shared Redis and LiteLLM coordination

**As of 22 November 2026**, `redis-common` is a separate platform service in namespace `redis`, not an embedded Redis instance for LiteLLM, Harbor or Argo CD. Its first client is `llm/litellm`. There is one internal writer endpoint: **`redis-common-haproxy.redis.svc.cluster.local:6379`**. Use TLS and verify both the CA and server hostname. Do not pin clients to a pod, node or Sentinel port.

Shared read dashboard: [Redis Insight access, permissions and publication status](redisinsight.md).

## What each component stores

- **PostgreSQL `pg-common/litellm`** remains the proxy's primary database. Redis coordinates rate limits, spend tracking, configuration changes and key-revocation notifications across workers. Response caching and embedded Redis are disabled. Production had one pod and one worker at acceptance; scaling was not part of the migration.
- **Redis topology:** the primary and two asynchronous replicas run on separate nodes: `socrat-0`, `socrat-1` and `socrat-5`. Each node also runs Sentinel; electing a primary requires two votes out of three. Two HAProxy instances route clients to the elected server. The primary is not tied to a node.
- **Durability:** AOF `everysec`, local PVCs with `Retain`, and `noeviction`. Exhausting memory can cause writes to fail. Primary failover can lose recent writes. Neither replicas nor retained PVCs replace an independent backup.

## Verifying coordination

Start with `SocratRedisCommonWriterUnavailable`: a dedicated probe uses client DNS and TLS to write a key with a TTL and read it back. If it fails, check HAProxy routing, Sentinel quorum, TLS and ACL denials. `SocratRedisCommonRedundancyReduced` means fewer than three ready Redis/Sentinel pairs or missing data; it does not necessarily mean the writer is unavailable. Neither `Argo Healthy` nor a TCP connection proves that writes succeed.

During image acceptance, two isolated workers sharing a test key returned `200/429` at a limit of 1 RPM and `200/422` when the test budget was exceeded. After revocation the second worker returned `401` on the second check. Production checks confirmed connections as `litellm` and subscriptions to the configuration and revocation channels. **The spending budget is not a hard cap:** one request can exceed the remaining balance. When Redis was lost in the test environment, the second worker admitted a request over the RPM limit. Primary failover was tested there, not by shutting down a production node.

## Connecting clients and making changes

Each new client needs its own ACL user, key and channel prefixes, a Secret in its namespace and a narrowly scoped NetworkPolicy to the gateway. LiteLLM uses `litellm:*`; do not reuse its account. Give each client only its own credentials and the public CA certificate, never `redis-common-control` or the CA private key.

- The [Argo Application](../../../deploy/argocd/apps/redis-common.yaml) and [platform values](../../../deploy/platform/redis-common/values.yaml) define topology and service settings. The [active LiteLLM values](../../../deploy/platform/litellm/values.yaml) configure external Redis under `general_settings.coordination_redis`.
- See the [operations runbook](redis-platform.md) for grants, CA rotation, targeted rollback and production acceptance evidence. Rolling back the LiteLLM connection does not require deleting PVCs or rolling back PostgreSQL. Without Redis, treat rate limits as local to each worker.
